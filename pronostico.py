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
