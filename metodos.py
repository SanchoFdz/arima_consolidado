# -*- coding: utf-8 -*-
"""Metodos de pronostico puntual.

Todos reciben una serie anual y un horizonte, y devuelven h valores. La eleccion
del motor por defecto (ensemble) no es estetica: sale de la competencia en
validacion.py, donde el ARIMA quedo por debajo del naive.
"""
import warnings

import numpy as np
import pandas as pd

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


# Registro COMPLETO de motores: todo lo que se mide, se calibra y se puede
# resolver por nombre. `calibrar.py` recorre este diccionario, y por eso
# `datos/calibracion.json` trae factores de los seis --- incluidos Theta y Holt,
# que son el registro de la medicion y no se tocan.
MOTORES = {
    "Ensemble (recomendado)": ensemble,
    "Theta": theta,
    "Holt amortiguado": holt_amortiguado,
    "ARIMA": arima,
    "Tendencia lineal": lineal,
    "Ultimo valor (naive)": naive,
}

# Lo que el selector de la app ofrece. Es un SUBCONJUNTO de MOTORES, no una
# lista aparte: `pronostico.proyectar` sigue resolviendo contra MOTORES, asi que
# cualquier nombre de aqui tiene garantizado su motor y sus factores calibrados.
#
# Theta y Holt amortiguado quedan fuera del selector y DENTRO de MOTORES a
# proposito. En la competencia de validacion.py sobre 110 segmentos (11,688
# predicciones) quedaron en 1.225 y 1.325 de MASE contra 1.216 del ensemble:
# ninguno de los dos mejora la eleccion por defecto, y ofrecerlos en pantalla
# invitaba a cambiar de motor por un empate estadistico. Pero son justo los dos
# competidores que sostienen por que el motor por defecto es el ensemble --- sin
# ellos la tabla del README se queda comparando el ensemble contra el naive y el
# ARIMA, que es la parte facil de ganar ---, asi que siguen existiendo,
# midiendose en cada corrida de validacion.py y calibrandose en calibrar.py.
# Quitarlos del codigo seria borrar la evidencia, no simplificar la interfaz.
#
# El ARIMA si se queda en el selector, aunque haya perdido: es el metodo con el
# que arranco el proyecto y el que la gente espera ver, y poder reproducir en
# pantalla que queda por debajo del naive vale mas que ahorrarse una opcion.
MOTORES_UI = (
    "Ensemble (recomendado)",
    "ARIMA",
    "Tendencia lineal",
    "Ultimo valor (naive)",
)


# --------------------------------------------------------------- con driver
def extender_driver(driver, anios):
    """Garantiza que el driver cubra los anos pedidos.

    CONAPO llega a 2040 y la SEP a 2030-31, asi que en la practica nunca hace
    falta; existe para que un horizonte largo no truene y para dejar registro
    de que esos anos son extrapolacion nuestra y no de la fuente.
    """
    faltan = [a for a in anios if a not in driver.index]
    if not faltan:
        return driver, []
    ult = driver.dropna()
    ventana = ult.iloc[-5:]
    g = (float(ventana.iloc[-1]) / float(ventana.iloc[0])) ** (1 / (len(ventana) - 1))
    base_anio, base_val = int(ult.index[-1]), float(ult.iloc[-1])
    extra = pd.Series({a: base_val * g ** (a - base_anio) for a in faltan})
    return pd.concat([driver, extra]).sort_index(), faltan


def razon(y, h, driver, base=None):
    """Proyecta la tasa y/driver y la reescala por el driver futuro conocido.

    NO es el motor de la app, y no por olvido: quedo en 1.226 de MASE contra
    1.214 de extrapolar a secas sobre 155 segmentos (validacion_externos.py).
    Vive aqui porque es el competidor de esa medicion, y porque si algun dia hay
    un driver municipal decente --- egresados de media superior por municipio ---
    esta es la forma de engancharlo.

    La idea era meter informacion externa sin gastar un grado de libertad: la
    demografia no se estima, se lee de CONAPO, y lo unico que se extrapola es la
    tasa de captacion, que viene limpia de crecimiento poblacional. Con un
    horizonte de 3 anos no alcanza: la cohorte se mueve menos de 0.5% al ano.

    Si la tasa proyectada es negativa se recorta a cero: la captacion no puede
    serlo, y la recta de un componente del ensemble si puede cruzar el eje.
    """
    base = base or ensemble
    anios_futuros = [int(y.index[-1]) + i for i in range(1, h + 1)]
    d, _ = extender_driver(driver, anios_futuros)

    comun = [a for a in y.index if a in d.index and d.loc[a] > 0]
    if len(comun) < 6:
        return base(y, h)

    tasa = pd.Series(y.loc[comun].values.astype(float) / d.loc[comun].values,
                     index=comun)
    tasa_futura = np.clip(np.asarray(base(tasa, h), dtype=float), 0, None)
    return tasa_futura * d.loc[anios_futuros].values
