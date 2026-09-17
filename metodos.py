# -*- coding: utf-8 -*-
"""Metodos de pronostico puntual.

Todos reciben una serie anual y un horizonte, y devuelven h valores. La eleccion
del motor por defecto (ensemble) no es estetica: sale de la competencia en
validacion.py, donde el ARIMA quedo por debajo del naive.
"""
import warnings

import numpy as np

import modelo as m


def naive(y, h):
    return np.repeat(float(y.iloc[-1]), h)


def drift(y, h):
    """Ultimo valor + pendiente promedio. Equivale a ARIMA(0,1,0) con deriva."""
    pend = (float(y.iloc[-1]) - float(y.iloc[0])) / (len(y) - 1)
    return float(y.iloc[-1]) + pend * np.arange(1, h + 1)


def lineal(y, h):
    x = np.arange(len(y))
    b, a = np.polyfit(x, y.values.astype(float), 1)
    return a + b * (len(y) - 1 + np.arange(1, h + 1))


def cagr(y, h):
    ini, fin = float(y.iloc[0]), float(y.iloc[-1])
    if ini <= 0 or fin <= 0:
        return naive(y, h)
    g = (fin / ini) ** (1 / (len(y) - 1))
    return fin * g ** np.arange(1, h + 1)


def media_movil(y, h):
    return np.repeat(float(y.iloc[-3:].mean()), h)


def holt_amortiguado(y, h):
    """Holt con tendencia amortiguada: referente en series anuales cortas."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    esc = float(np.mean(np.abs(y))) or 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(y.values / esc, trend="add", damped_trend=True,
                                   initialization_method="estimated").fit()
        return np.asarray(fit.forecast(h)) * esc


def theta(y, h):
    """Metodo Theta (ganador de la M3): recta a media pendiente + suavizado."""
    from statsmodels.tsa.holtwinters import SimpleExpSmoothing
    x = np.arange(len(y))
    b, a = np.polyfit(x, y.values.astype(float), 1)
    futuro = len(y) - 1 + np.arange(1, h + 1)
    esc = float(np.mean(np.abs(y))) or 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ses = SimpleExpSmoothing(y.values / esc, initialization_method="estimated").fit()
        return 0.5 * (a + b * futuro) + 0.5 * (np.asarray(ses.forecast(h)) * esc)


def arima(y, h):
    r = m.proyectar(y, h)
    return naive(y, h) if r is None else r.proyeccion["pronostico"].values


def arima_log(y, h):
    if (y <= 0).any():
        return arima(y, h)
    r = m.proyectar(np.log(y), h)
    return naive(y, h) if r is None else np.exp(r.proyeccion["pronostico"].values)


COMPONENTES_ENSEMBLE = (naive, drift, lineal, media_movil)


def ensemble(y, h):
    """Mediana de cuatro metodos simples. Ganador de la competencia.

    La mediana, no la media: si un componente se desboca (la recta en una serie
    con quiebre), la mediana lo ignora en vez de promediarlo.
    """
    return np.median(np.vstack([fn(y, h) for fn in COMPONENTES_ENSEMBLE]), axis=0)


MOTORES = {
    "Ensemble (recomendado)": ensemble,
    "Theta": theta,
    "Holt amortiguado": holt_amortiguado,
    "ARIMA": arima,
    "Tendencia lineal": lineal,
    "Ultimo valor (naive)": naive,
}
