# -*- coding: utf-8 -*-
"""Calibra los intervalos con los errores reales del backtest.

Los intervalos analiticos del ARIMA sub-cubren (80% nominal daba 73.7% real)
porque ignoran la incertidumbre de estimacion y de seleccion de modelo. Aqui se
mide como se equivoca el metodo en la practica y se usan los cuantiles de ese
error, escalados por la volatilidad propia de cada serie (el error medio del
naive un paso, mismo denominador del MASE).

Por que ese escalador y no el nivel de la serie: se probaron ambos en
diag_escala.py. Escalar por volatilidad da un factor que varia solo 4.1% entre
submuestras de segmentos (vs 9.6% por nivel) y deja mal cubierto al 5% de los
segmentos (vs 13%).

La cobertura se reporta con splits repetidos: calibrar en la mitad de los
segmentos, medir en la otra, 200 veces. Un solo split da un numero con mucho
ruido; un intento previo de ajustar el cuantil sobre un unico grupo sobreajusto
y tiro la cobertura a 65%.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import metodos
from validacion import construir_series, mase_escala

warnings.simplefilter("ignore")

SALIDA = Path(__file__).resolve().parent / "datos" / "calibracion.json"
NIVELES = (0.50, 0.80, 0.95)
H_MAX = 5
MIN_TRAIN = 7
REPETICIONES = 200


def errores_escalados(series, motor):
    filas = []
    for nombre, y in series:
        y = y.astype(float)
        if len(y) < MIN_TRAIN + 1 or y.iloc[-3:].mean() < 30:
            continue
        for corte in range(MIN_TRAIN, len(y)):
            train, resto = y.iloc[:corte], y.iloc[corte:]
            h = min(H_MAX, len(resto))
            esc = mase_escala(train.values)
            if not np.isfinite(esc) or esc <= 0:
                continue
            try:
                pred = np.asarray(motor(train, h), dtype=float)
            except Exception:
                continue
            for i in range(h):
                filas.append({"segmento": nombre, "h": i + 1,
                              "err": abs(pred[i] - resto.values[i]) / esc})
    return pd.DataFrame(filas)


def factores(err, nivel):
    """Cuantil del error escalado por horizonte, extendido con raiz de h."""
    por_h = {}
    for h in range(1, H_MAX + 1):
        muestra = err.loc[err["h"] == h, "err"]
        if len(muestra) >= 30:
            por_h[h] = float(np.quantile(muestra, nivel))
    if not por_h:
        return {}
    h_ref = max(por_h)
    for h in range(h_ref + 1, H_MAX + 1):
        por_h[h] = por_h[h_ref] * np.sqrt(h / h_ref)
    return {str(h): round(v, 4) for h, v in sorted(por_h.items())}


def cobertura(err, tabla):
    dentro = total = 0
    for h_s, f in tabla.items():
        sub = err[err["h"] == int(h_s)]
        dentro += int((sub["err"] <= f).sum())
        total += len(sub)
    return dentro / total if total else np.nan


def calibrar_motor(series, nombre, motor, rng):
    err = errores_escalados(series, motor)
    segmentos = err["segmento"].unique()
    tabla = {str(n): factores(err, n) for n in NIVELES}

    resumen = {}
    for nivel in NIVELES:
        cobs = []
        for _ in range(REPETICIONES):
            cal = rng.choice(segmentos, size=len(segmentos) // 2, replace=False)
            t = factores(err[err["segmento"].isin(cal)], nivel)
            if t:
                cobs.append(cobertura(err[~err["segmento"].isin(cal)], t))
        resumen[str(nivel)] = round(float(np.mean(cobs)), 4)

    mase = float(err["err"].mean())
    print(f"\n--- {nombre} | MASE medio {mase:.3f} ---")
    print(pd.DataFrame(tabla).to_string())
    print("  cobertura fuera de muestra: " + " · ".join(
        f"{float(n) * 100:.0f}%->{c * 100:.1f}%" for n, c in resumen.items()))
    return {"factores": tabla, "cobertura_real": resumen, "mase_medio": round(mase, 4)}


def main():
    df = pd.read_parquet("datos/panel_ni.parquet")
    series = construir_series(df)
    rng = np.random.default_rng(7)

    salida = {}
    for nombre, motor in metodos.MOTORES.items():
        salida[nombre] = calibrar_motor(series, nombre, motor, rng)

    SALIDA.write_text(json.dumps(salida, indent=2, ensure_ascii=False))
    print(f"\nguardado en {SALIDA}")


if __name__ == "__main__":
    main()
