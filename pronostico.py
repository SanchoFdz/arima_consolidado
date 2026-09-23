# -*- coding: utf-8 -*-
"""API unica de proyeccion que usa la app.

Dos diferencias de fondo con la version anterior, ambas producto de medir en vez
de suponer (ver validacion.py y calibrar.py):

  1. El motor por defecto es un ensemble de metodos simples, no ARIMA. En un
     backtest sobre 110 segmentos el ARIMA quedo por debajo del naive; el
     ensemble le gana por ~15%. Con 11 observaciones anuales no hay estructura
     que un ARIMA pueda identificar: el 83% de los segmentos colapsaba a
     ARIMA(0,1,0), que es "ultimo valor" o "ultimo valor + pendiente promedio".

  2. Los intervalos salen de los errores observados en backtest, no de la formula
     del modelo. Los analiticos del ARIMA sub-cubrian (80% nominal, 73.7% real);
     los calibrados dan 79.5% real.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import metodos

RAIZ = Path(__file__).resolve().parent
CALIBRACION = RAIZ / "datos" / "calibracion.json"

MOTOR_DEFAULT = "Ensemble (recomendado)"
MIN_OBS = 6
NIVELES = (0.50, 0.80, 0.95)

# ------------------------------------------------- umbrales de la derivada
# Volumen minimo de la subcategoria en su ultimo ciclo observado. 1,000 alumnos
# es 10x el umbral con el que este mismo modulo ya llama "volumen bajo" a un
# segmento (ver los avisos de `proyectar`), y el factor 10 no es decorativo: en
# una derivada se componen DOS incertidumbres, la del padre y la del reparto,
# asi que el piso tiene que ser mas alto que el de una proyeccion directa.
MIN_NI_DERIVADA = 1000

# Dispersion maxima tolerada del share, medida como rango observado sobre share
# medio. El 15% separa limpio los casos del panel: con las 2 observaciones que
# hay de MIXTA, Licenciatura da 1.6% (49.1% -> 49.9%), Maestria 2.1% (24.6% ->
# 24.1%) y Tecnico Superior 7.2%, mientras Doctorado da 31% (47.6% -> 34.8%) y
# Especialidad 30% (63.3% -> 46.7%). Los dos ultimos son justo los niveles sin
# volumen, donde el share se mueve 13 y 17 puntos de un ciclo al otro: repartir
# la proyeccion del padre con un numero asi es inventarse la mitad del
# resultado. Se rechazan.
DISPERSION_MAX_SHARE = 0.15

# Piso de la banda del share, en terminos relativos. Con 2 observaciones el
# rango observado es una cota INFERIOR de la dispersion real --- dos puntos que
# coinciden son evidencia de estabilidad, no prueba ---, asi que la banda nunca
# cierra por debajo de +-5% del share. Sin este piso, MIXTA nacional (44.9% y
# 45.0%) saldria con una banda de +-0.1 puntos, o sea afirmando que el reparto
# de 2027 se conoce con tres cifras significativas desde dos observaciones.
PISO_BANDA_SHARE = 0.05

MIN_OBS_SHARE = 2


@dataclass
class Resultado:
    motor: str
    historico: pd.Series
    proyeccion: pd.DataFrame
    mase_backtest: float | None
    mape_backtest: float | None
    cagr_historico: float | None
    cagr_proyectado: float | None
    cobertura_real: float | None
    confiabilidad: str
    avisos: list = field(default_factory=list)


@dataclass
class Derivada:
    """Proyeccion de una subcategoria obtenida repartiendo la de su padre.

    NO es un `Resultado` y no lo hereda, a proposito: no tiene backtest propio,
    no tiene MAPE ni MASE propios y no le corresponde un semaforo de
    confiabilidad. Los campos que existen son los que se pueden calcular de
    verdad. Que el tipo sea distinto es lo que impide que la interfaz la
    presente por accidente como una proyeccion directa.
    """
    etiqueta_padre: str
    padre: "Resultado"
    proyeccion: pd.DataFrame
    share: float
    shares_observados: pd.Series
    banda_share: tuple
    dispersion: float
    cagr_padre: float | None


def cargar_calibracion():
    if not CALIBRACION.exists():
        return {}
    return json.loads(CALIBRACION.read_text())


def volatilidad(y):
    """Error medio del naive un paso: la escala natural de la serie."""
    d = np.abs(np.diff(np.asarray(y, dtype=float)))
    return float(d.mean()) if len(d) and d.mean() > 0 else np.nan


def _factor(calib, motor, nivel, h):
    tabla = calib.get(motor, {}).get("factores", {}).get(str(nivel), {})
    if not tabla:
        return None
    if str(h) in tabla:
        return tabla[str(h)]
    h_ref = max(int(k) for k in tabla)
    return tabla[str(h_ref)] * np.sqrt(h / h_ref)


def _cagr(inicio, fin, periodos):
    if not inicio or inicio <= 0 or not fin or fin <= 0 or periodos <= 0:
        return None
    return ((fin / inicio) ** (1 / periodos) - 1) * 100


def _backtest(y, motor_fn, h_max=3, min_train=7):
    """Error de origen movil. MASE<1 significa mejor que repetir el ultimo valor."""
    aes, apes, escalas = [], [], []
    for corte in range(min_train, len(y)):
        train, resto = y.iloc[:corte], y.iloc[corte:]
        h = min(h_max, len(resto))
        esc = volatilidad(train.values)
        if not np.isfinite(esc):
            continue
        try:
            pred = np.asarray(motor_fn(train, h), dtype=float)
        except Exception:
            continue
        for i in range(h):
            real = float(resto.values[i])
            if not np.isfinite(pred[i]):
                continue
            aes.append(abs(pred[i] - real))
            escalas.append(esc)
            if real > 0:
                apes.append(abs(pred[i] - real) / real * 100)
    mase = float(np.mean(np.array(aes) / np.array(escalas))) if aes else None
    mape = float(np.mean(apes)) if apes else None
    return mase, mape


def _confiabilidad(mape, n_no_cero, nivel_reciente, mase=None):
    """Semaforo del segmento. El MASE manda sobre el MAPE.

    Un segmento puede tener MAPE chico y aun asi no ganarle a repetir el ultimo
    valor: pasa en series planas, donde el error porcentual es bajo porque el
    nivel casi no se mueve. Llamarle "alta confiabilidad" a eso y al mismo tiempo
    avisar que el metodo no le gana al naive es decir dos cosas contrarias en la
    misma pantalla, asi que con MASE > 1 el semaforo no sube de media.
    """
    if mape is None or n_no_cero < 8 or nivel_reciente < 100:
        return "baja"
    if mase is not None and mase > 1:
        return "media" if mape <= 15 else "baja"
    if mape <= 8:
        return "alta"
    if mape <= 15:
        return "media"
    return "baja"


def proyectar(serie: pd.Series, horizonte: int = 3, nivel: float = 0.80,
              motor: str = MOTOR_DEFAULT) -> Resultado | None:
    y = serie.astype(float).sort_index()
    if len(y) < MIN_OBS or y.sum() == 0:
        return None

    motor_fn = metodos.MOTORES.get(motor)
    if motor_fn is None:
        return None

    try:
        punto = np.asarray(motor_fn(y, horizonte), dtype=float)
    except Exception:
        return None
    if not np.all(np.isfinite(punto)):
        return None
    punto = np.clip(punto, 0, None)

    calib = cargar_calibracion()
    vol = volatilidad(y.values)
    inferior, superior = [], []
    for i in range(horizonte):
        f = _factor(calib, motor, nivel, i + 1)
        margen = f * vol if (f is not None and np.isfinite(vol)) else np.nan
        inferior.append(max(punto[i] - margen, 0) if np.isfinite(margen) else np.nan)
        superior.append(punto[i] + margen if np.isfinite(margen) else np.nan)

    anios = [int(y.index[-1]) + i for i in range(1, horizonte + 1)]
    proyeccion = pd.DataFrame({
        "anio": anios,
        "ciclo": [f"{a}-{a + 1}" for a in anios],
        "pronostico": punto,
        "inferior": inferior,
        "superior": superior,
    })

    mase, mape = _backtest(y, motor_fn)
    no_cero = int((y > 0).sum())
    reciente = float(y.iloc[-3:].mean())

    avisos = []
    if no_cero < 8:
        avisos.append(f"Solo {no_cero} de {len(y)} ciclos con datos: la proyeccion es fragil.")
    if reciente < 100:
        avisos.append("Segmento de volumen bajo (<100 alumnos): el intervalo domina al punto.")
    if mase is not None and mase > 1:
        avisos.append(
            f"En backtest este segmento no le gana a repetir el ultimo valor "
            f"(MASE {mase:.2f}). Trata la proyeccion como referencia, no como insumo directo.")

    return Resultado(
        motor=motor,
        historico=y,
        proyeccion=proyeccion,
        mase_backtest=mase,
        mape_backtest=mape,
        cagr_historico=_cagr(float(y.iloc[0]), float(y.iloc[-1]), len(y) - 1),
        cagr_proyectado=_cagr(float(y.iloc[-1]), float(punto[-1]), horizonte),
        cobertura_real=calib.get(motor, {}).get("cobertura_real", {}).get(str(nivel)),
        confiabilidad=_confiabilidad(mape, no_cero, reciente, mase),
        avisos=avisos,
    )


def derivar_por_share(hijo: pd.Series, padre: pd.Series, horizonte: int = 3,
                      nivel: float = 0.80, motor: str = MOTOR_DEFAULT,
                      etiqueta_padre: str = "el agregado"):
    """Proyecta al padre y reparte por la participacion observada del hijo.

    El caso que la motiva: MIXTA existe desde 2023-2024 y son 2 observaciones.
    `proyectar` la rechaza y hace bien --- `MIN_OBS = 6` no se baja, y meterle 2
    puntos al ensemble seria pedirle a `drift` y a `lineal` que extrapolen una
    recta entre dos numeros ---. Pero el agregado del que salio, Online (no
    escolarizada + mixta), si tiene los 11 ciclos y es el motor y la calibracion
    ya validados. Proyectarlo a el y repartir es lo unico que se puede decir del
    hijo sin inventar nada.

    El share va FIJO, el promedio de las observaciones disponibles. No se
    extrapola su tendencia: con 2 puntos, "la tendencia del share" es una recta
    entre dos numeros que a 3 ciclos manda el reparto de MIXTA de 45% a 47% o a
    43% segun de que lado caiga el ruido, y eso no es informacion, es la
    pendiente del error de medicion.

    El intervalo hereda el del padre y se ensancha por la incertidumbre del
    reparto: `inferior = inferior_padre x share_min` y `superior =
    superior_padre x share_max`. Es la envolvente externa, no una convolucion:
    empareja el peor caso del padre con el peor caso del share como si fueran
    simultaneos. Sobre-cubre, y con 2 observaciones de share sobre-cubrir es el
    lado correcto en el que equivocarse.

    Devuelve `(Derivada, None)` si aplica y `(None, motivo)` si no, porque el
    motivo es lo que la pantalla tiene que decir en vez de la derivada.
    """
    hijo = hijo.astype(float).sort_index()
    padre = padre.astype(float).sort_index()

    comunes = [a for a in hijo.index
               if a in padre.index and padre.loc[a] > 0 and hijo.loc[a] > 0]
    if len(comunes) < MIN_OBS_SHARE:
        return None, (f"No hay ni {MIN_OBS_SHARE} ciclos en que este corte y "
                      f"{etiqueta_padre} reporten alumnos a la vez, así que no hay "
                      f"participación que repartir.")

    shares = pd.Series([hijo.loc[a] / padre.loc[a] for a in comunes],
                       index=comunes, dtype=float)
    share = float(shares.mean())
    rango = float(shares.max() - shares.min())
    dispersion = rango / share if share > 0 else np.inf
    ultimo = float(hijo.loc[comunes[-1]])

    if ultimo < MIN_NI_DERIVADA:
        return None, (f"El corte cierra en {ultimo:,.0f} alumnos y el mínimo para "
                      f"derivar es {MIN_NI_DERIVADA:,}. Debajo de ahí la derivada "
                      f"compone dos incertidumbres sobre una base que el propio "
                      f"motor ya consideraría de volumen bajo.")
    if dispersion > DISPERSION_MAX_SHARE:
        return None, (f"La participación dentro de {etiqueta_padre} se mueve "
                      f"{dispersion * 100:.0f}% entre los ciclos observados "
                      f"({' y '.join(f'{s * 100:.1f}%' for s in shares)}), muy arriba "
                      f"del {DISPERSION_MAX_SHARE * 100:.0f}% que se tolera. Con un "
                      f"reparto que baila así, la derivada diría más sobre el "
                      f"supuesto de reparto que sobre el mercado.")

    res_padre = proyectar(padre, horizonte, nivel, motor)
    if res_padre is None:
        return None, (f"{etiqueta_padre} tampoco es proyectable, así que no hay de "
                      f"dónde derivar.")

    amplitud = max(rango, PISO_BANDA_SHARE * share)
    share_min, share_max = max(share - amplitud, 0.0), share + amplitud

    punto = res_padre.proyeccion["pronostico"].to_numpy() * share
    inferior = np.clip(res_padre.proyeccion["inferior"].to_numpy() * share_min, 0, None)
    superior = res_padre.proyeccion["superior"].to_numpy() * share_max

    proyeccion = pd.DataFrame({
        "anio": res_padre.proyeccion["anio"],
        "ciclo": res_padre.proyeccion["ciclo"],
        "pronostico": punto,
        "inferior": inferior,
        "superior": superior,
    })
    return Derivada(
        etiqueta_padre=etiqueta_padre,
        padre=res_padre,
        proyeccion=proyeccion,
        share=share,
        shares_observados=shares,
        banda_share=(share_min, share_max),
        dispersion=dispersion,
        cagr_padre=res_padre.cagr_proyectado,
    ), None
