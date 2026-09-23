# -*- coding: utf-8 -*-
"""Competencia de metodos: el ARIMA vs. benchmarks triviales.

La prueba honesta de si un modelo sirve no es su AIC, es si le gana a metodos
tontos fuera de muestra. Backtest de origen movil sobre muchos segmentos reales.
"""
import warnings

import numpy as np
import pandas as pd

import modelo as m

warnings.simplefilter("ignore")


def naive(y, h):
    return np.repeat(float(y.iloc[-1]), h)


def drift(y, h):
    """Ultimo valor + pendiente promedio. Es literalmente ARIMA(0,1,0) con deriva."""
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


def arima(y, h, margen=m.MARGEN_AICC):
    r = m.proyectar(y, h, margen=margen)
    return naive(y, h) if r is None else r.proyeccion["pronostico"].values


def arima_log(y, h):
    if (y <= 0).any():
        return arima(y, h)
    r = m.proyectar(np.log(y), h)
    return naive(y, h) if r is None else np.exp(r.proyeccion["pronostico"].values)


def holt_amortiguado(y, h):
    """Holt con tendencia amortiguada: el referente en series anuales cortas
    (gana sistematicamente las M-competitions en este regimen)."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    esc = float(np.mean(np.abs(y))) or 1.0
    fit = ExponentialSmoothing(y.values / esc, trend="add", damped_trend=True,
                               initialization_method="estimated").fit()
    return fit.forecast(h) * esc


def theta(y, h):
    """Metodo Theta (ganador de la M3): tendencia lineal a media pendiente + SES."""
    from statsmodels.tsa.holtwinters import SimpleExpSmoothing
    x = np.arange(len(y))
    b, a = np.polyfit(x, y.values.astype(float), 1)
    futuro = len(y) - 1 + np.arange(1, h + 1)
    esc = float(np.mean(np.abs(y))) or 1.0
    ses = SimpleExpSmoothing(y.values / esc, initialization_method="estimated").fit()
    return 0.5 * (a + b * futuro) + 0.5 * (ses.forecast(h) * esc)


def ensemble(y, h):
    """Mediana de metodos simples. Combinar casi siempre le gana a elegir uno."""
    preds = np.vstack([naive(y, h), drift(y, h), lineal(y, h), media_movil(y, h)])
    return np.median(preds, axis=0)


def ensemble_amplio(y, h):
    preds = [naive(y, h), drift(y, h), lineal(y, h), media_movil(y, h)]
    for fn in (holt_amortiguado, theta, arima):
        try:
            preds.append(np.asarray(fn(y, h), dtype=float))
        except Exception:
            pass
    return np.median(np.vstack(preds), axis=0)


# La competencia corre con TODOS los metodos, incluidos los que la app ya no
# ofrece en su selector. Theta y Holt amortiguado salieron de `metodos.MOTORES_UI`
# porque empatan con el ensemble y elegirlos en pantalla seria cambiar de motor
# por ruido; aqui tienen que seguir compitiendo, porque son precisamente los dos
# rivales que hacen que "el ensemble gana" signifique algo. Estas
# implementaciones son las de este modulo, no las de metodos.py, asi que la
# competencia es independiente de lo que la interfaz exponga por definicion.
METODOS = {
    "holt_amortiguado": holt_amortiguado,
    "theta": theta,
    "ensemble": ensemble,
    "ensemble_amplio": ensemble_amplio,
    "naive": naive,
    "drift": drift,
    "lineal": lineal,
    "cagr": cagr,
    "media_movil_3": media_movil,
    "arima": arima,
    "arima_margen0": lambda y, h: arima(y, h, margen=0.0),
    "arima_log": arima_log,
}


def mase_escala(y_train):
    """Denominador MASE: error medio del naive un paso adelante en el train."""
    d = np.abs(np.diff(np.asarray(y_train, dtype=float)))
    return d.mean() if len(d) and d.mean() > 0 else np.nan


def evaluar(series, horizonte_max=3, min_train=7):
    filas = []
    for nombre, y in series:
        y = y.astype(float)
        if len(y) < min_train + 1 or y.iloc[-3:].mean() < 30:
            continue
        for corte in range(min_train, len(y)):
            train, resto = y.iloc[:corte], y.iloc[corte:]
            h = min(horizonte_max, len(resto))
            esc = mase_escala(train)
            if not np.isfinite(esc):
                continue
            for met, fn in METODOS.items():
                try:
                    pred = np.asarray(fn(train, h), dtype=float)[:h]
                except Exception:
                    continue
                real = resto.values[:h]
                if not np.all(np.isfinite(pred)):
                    continue
                for i in range(h):
                    filas.append({"segmento": nombre, "metodo": met, "origen": corte,
                                  "h": i + 1, "ae": abs(pred[i] - real[i]),
                                  "ape": abs(pred[i] - real[i]) / real[i] * 100 if real[i] > 0 else np.nan,
                                  "escala": esc})
    return pd.DataFrame(filas)


def construir_series(df, metrica="NI"):
    """Segmentos realistas: los cortes que la gente de finanzas realmente pide."""
    series = []
    g = lambda sub: sub.groupby("anio", observed=True)[metrica].sum().sort_index()

    series.append(("NACIONAL", g(df)))
    for col, pref in [("Zona_Metropolitana", "ZM"), ("Estado", "EDO"),
                      ("Nielsen_Region", "NIELSEN"), ("Area_2014", "AREA"),
                      ("Nivel_educativo", "NIVEL"), ("Modalidad", "MOD")]:
        for v in df[col].dropna().unique():
            if v == "Fuera de zona metropolitana":
                continue
            series.append((f"{pref}:{v}", g(df[df[col] == v])))

    # Cruces nivel x modalidad y ZM x nivel: lo que mas se va a usar en la practica.
    for niv in df["Nivel_educativo"].dropna().unique():
        for mod in ["ESCOLARIZADA", "NO ESCOLARIZADA"]:
            series.append((f"X:{niv}|{mod}",
                           g(df[(df["Nivel_educativo"] == niv) & (df["Modalidad"] == mod)])))
    for z in df["Zona_Metropolitana"].dropna().unique():
        if z == "Fuera de zona metropolitana":
            continue
        for niv in ["LICENCIATURA UNIVERSITARIA Y TECNOLÓGICA", "MAESTRÍA"]:
            series.append((f"ZMxN:{z}|{niv[:12]}",
                           g(df[(df["Zona_Metropolitana"] == z) & (df["Nivel_educativo"] == niv)])))
    return series


if __name__ == "__main__":
    df = pd.read_parquet("datos/panel_ni.parquet")
    series = construir_series(df)
    print(f"Series candidatas: {len(series)}")
    res = evaluar(series)
    res["mase"] = res["ae"] / res["escala"]

    print(f"Series evaluadas: {res['segmento'].nunique()} | observaciones: {len(res):,}\n")

    tabla = (res.groupby("metodo")
                .agg(MASE=("mase", "mean"), MASE_mediana=("mase", "median"),
                     MAPE=("ape", "mean"), MAPE_mediana=("ape", "median"))
                .sort_values("MASE").round(3))
    print("=== GLOBAL (menor es mejor; MASE<1 = mejor que naive) ===")
    print(tabla.to_string())

    print("\n=== POR HORIZONTE (MASE medio) ===")
    print(res.pivot_table(index="metodo", columns="h", values="mase", aggfunc="mean")
             .round(3).sort_values(1).to_string())

    # Cuantas veces cada metodo es el mejor en su segmento
    por_seg = res.groupby(["segmento", "metodo"])["mase"].mean().reset_index()
    ganadores = por_seg.loc[por_seg.groupby("segmento")["mase"].idxmin(), "metodo"].value_counts()
    print("\n=== VECES QUE CADA METODO GANA SU SEGMENTO ===")
    print(ganadores.to_string())

    print("\n=== MASE MEDIO POR ORIGEN (que anio se predijo) ===")
    # origen = numero de observaciones de entrenamiento; el anio predicho es 2014+origen
    piv = res.copy()
    piv["anio_predicho"] = 2014 + piv["origen"] + piv["h"] - 1
    print(piv.pivot_table(index="metodo", columns="anio_predicho", values="mase",
                          aggfunc="mean").round(2).to_string())

    print("\n=== EXCLUYENDO 2020 y 2021 (shock COVID) ===")
    sin = piv[~piv["anio_predicho"].isin([2020, 2021])]
    print(sin.groupby("metodo")["mase"].mean().sort_values().round(3).to_string())

    res.to_parquet("datos/validacion.parquet", index=False)
