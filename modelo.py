# -*- coding: utf-8 -*-
"""Ajuste y proyeccion ARIMA sobre series anuales cortas (11 ciclos).

Con 11 observaciones no hay lugar para modelos grandes: la busqueda se limita a
ordenes con p+q<=2 y se selecciona por AICc, que penaliza parametros mas fuerte
que el AIC en muestras chicas. Se reporta ademas un backtest de un paso para que
quien use la proyeccion sepa que tan bien predijo el ultimo ciclo observado.
"""
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA

# p+q<=2: con 11 observaciones cualquier cosa mas grande sobreajusta.
PQ = [(p, q) for p in (0, 1, 2) for q in (0, 1, 2) if p + q <= 2]

MIN_OBS = 6

# Margen de AICc dentro del cual dos modelos se consideran indistinguibles
# (Burnham & Anderson). Con 11 observaciones el AICc casi siempre prefiere el
# paseo aleatorio plano; si un modelo con deriva cae dentro de este margen, se
# elige ese, porque una proyeccion plana no le sirve a nadie que modele ingresos.
MARGEN_AICC = 2.0


@dataclass
class Resultado:
    orden: tuple
    tendencia: str
    historico: pd.Series
    proyeccion: pd.DataFrame          # anio | pronostico | inferior | superior
    aicc: float
    mape_backtest: float | None
    cagr_historico: float | None
    cagr_proyectado: float | None
    nota: str = ""
    avisos: list = field(default_factory=list)


def _aicc(res, n):
    k = res.df_model + 1
    if n - k - 1 <= 0:
        return np.inf
    return res.aic + (2 * k * (k + 1)) / (n - k - 1)


def _orden_diferenciacion(y):
    """d=1 fijo, deliberadamente.

    Lo correcto seria decidirlo con KPSS como hace auto.arima, pero con 11
    observaciones la prueba no tiene potencia: practicamente nunca rechaza y deja
    pasar modelos con d=0. Un d=0 con tendencia ajusta una recta a toda la serie e
    ignora donde termino, asi que el primer anio proyectado puede salir 10% por
    debajo del ultimo dato real: inservible para un modelo financiero. Las series
    de matricula son niveles acumulados, es decir I(1), y d=1 ancla la proyeccion
    en el ultimo ciclo observado.
    """
    return 1


def _escala(y):
    """Factor de normalizacion. Sin el, series en millones hacen que el optimizador
    no converja: sigma2 queda inflado y el AICc castiga injustamente a la deriva."""
    m = float(np.mean(np.abs(y)))
    return m if m > 0 else 1.0


def _con_periodos(y):
    """Indice anual explicito: evita que statsmodels adivine y nos llene de warnings."""
    z = y.copy()
    z.index = pd.PeriodIndex([int(a) for a in y.index], freq="Y")
    return z


def _ajustar(y, orden, trend):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ARIMA(_con_periodos(y), order=orden, trend=trend,
                     enforce_stationarity=True,
                     enforce_invertibility=True).fit()


def _mejor_modelo(y, preferir_tendencia=True, margen=MARGEN_AICC):
    """y debe venir ya escalada."""
    d = _orden_diferenciacion(y)
    candidatos = []
    for p, q in PQ:
        orden = (p, d, q)
        # Con d=0 la deriva se pide como constante ('c'); con d=1 statsmodels exige
        # una tendencia lineal ('t'), que sobre la serie diferenciada es el drift.
        trends = ["c", "n"] if d == 0 else ["t", "n"]
        for trend in trends:
            try:
                res = _ajustar(y, orden, trend)
                valor = _aicc(res, len(y))
            except Exception:
                continue
            if np.isfinite(valor):
                candidatos.append((valor, orden, trend, res))

    if not candidatos:
        return None, np.inf, None, None

    # Red de seguridad: descarta modelos cuyo primer pronostico se despega del
    # ultimo dato observado mas que el mayor salto anual visto en la historia.
    salto_max = float(np.abs(np.diff(y)).max()) * 1.5 if len(y) > 1 else np.inf
    ultimo = float(y.iloc[-1])
    coherentes = []
    for valor, orden, trend, res in candidatos:
        try:
            primero = float(res.get_forecast(1).predicted_mean.iloc[0])
        except Exception:
            continue
        if np.isfinite(primero) and abs(primero - ultimo) <= salto_max:
            coherentes.append((valor, orden, trend, res))
    if coherentes:
        candidatos = coherentes

    candidatos.sort(key=lambda c: c[0])
    aicc, orden, trend, res = candidatos[0]

    if preferir_tendencia and trend == "n":
        con_deriva = [c for c in candidatos if c[2] != "n"]
        if con_deriva and con_deriva[0][0] <= aicc + margen:
            aicc, orden, trend, res = con_deriva[0]

    return res, aicc, orden, trend


def _backtest(y, orden, trend):
    """MAPE de un paso adelante sobre los ultimos 3 ciclos (origen movil).

    y viene escalada; el MAPE es invariante a la escala.
    """
    errores = []
    for corte in range(len(y) - 3, len(y)):
        if corte < MIN_OBS:
            continue
        try:
            res = _ajustar(y.iloc[:corte], orden, trend)
            pred = float(res.forecast(1).iloc[0])
        except Exception:
            continue
        real = float(y.iloc[corte])
        # Un ajuste degenerado en submuestra puede escupir valores absurdos; se
        # descartan en vez de contaminar el MAPE.
        if not np.isfinite(pred) or pred > 10 * float(y.max()):
            continue
        if real > 0:
            errores.append(abs(pred - real) / real)
    return float(np.mean(errores) * 100) if errores else None


def _cagr(inicio, fin, periodos):
    if inicio is None or inicio <= 0 or fin is None or fin <= 0 or periodos <= 0:
        return None
    return ((fin / inicio) ** (1 / periodos) - 1) * 100


def proyectar(serie: pd.Series, horizonte: int = 3, alpha: float = 0.20,
              preferir_tendencia: bool = True,
              margen: float = MARGEN_AICC) -> Resultado | None:
    """serie: indice = anio de inicio del ciclo, valores = NI (u otra metrica)."""
    y = serie.astype(float).sort_index()
    avisos = []

    if len(y) < MIN_OBS or y.sum() == 0:
        return None

    no_cero = (y > 0).sum()
    if no_cero < MIN_OBS:
        avisos.append(f"Solo {no_cero} de {len(y)} ciclos con matricula > 0: la proyeccion es fragil.")
    if y.iloc[-3:].mean() < 30:
        avisos.append("Serie de volumen muy bajo (<30 NI promedio reciente); el intervalo domina al punto.")

    esc = _escala(y)
    ye = y / esc

    modelo, aicc, orden, trend = _mejor_modelo(ye, preferir_tendencia, margen)
    if modelo is None:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pron = modelo.get_forecast(horizonte)
    media = pron.predicted_mean * esc
    ic = pron.conf_int(alpha=alpha) * esc

    anios = [int(y.index[-1]) + i for i in range(1, horizonte + 1)]
    proyeccion = pd.DataFrame({
        "anio": anios,
        "ciclo": [f"{a}-{a + 1}" for a in anios],
        "pronostico": np.clip(np.asarray(media, dtype=float), 0, None),
        "inferior": np.clip(np.asarray(ic.iloc[:, 0], dtype=float), 0, None),
        "superior": np.clip(np.asarray(ic.iloc[:, 1], dtype=float), 0, None),
    })

    if trend == "n":
        cagr_h = _cagr(float(y.iloc[0]), float(y.iloc[-1]), len(y) - 1)
        if cagr_h is not None and abs(cagr_h) >= 2:
            avisos.append(
                f"El modelo seleccionado no tiene deriva: proyecta plano pese a un "
                f"CAGR historico de {cagr_h:.1f}%. La serie es demasiado ruidosa para "
                f"que la tendencia sea estadisticamente distinguible del ruido.")

    return Resultado(
        orden=orden,
        tendencia=trend,
        historico=y,
        proyeccion=proyeccion,
        aicc=float(aicc),
        mape_backtest=_backtest(ye, orden, trend),
        cagr_historico=_cagr(float(y.iloc[0]), float(y.iloc[-1]), len(y) - 1),
        cagr_proyectado=_cagr(float(y.iloc[-1]), float(proyeccion["pronostico"].iloc[-1]), horizonte),
        nota=f"ARIMA{orden}" + (" con deriva" if trend in ("c", "t") else ""),
        avisos=avisos,
    )
