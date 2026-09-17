# -*- coding: utf-8 -*-
"""Un intervalo al 80% deberia contener el valor real el 80% de las veces.
Si cubre mucho menos, el intervalo miente y no sirve para escenarios financieros.
"""
import warnings
import numpy as np
import pandas as pd
import modelo as m
from validacion import construir_series

warnings.simplefilter("ignore")

df = pd.read_parquet("datos/panel_ni.parquet")
filas = []
for nombre, y in construir_series(df):
    y = y.astype(float)
    if len(y) < 8 or y.iloc[-3:].mean() < 30:
        continue
    for corte in range(7, len(y)):
        train, resto = y.iloc[:corte], y.iloc[corte:]
        h = min(3, len(resto))
        for nivel in (0.80, 0.95):
            r = m.proyectar(train, h, alpha=1 - nivel)
            if r is None:
                continue
            for i in range(h):
                real = resto.values[i]
                p = r.proyeccion.iloc[i]
                filas.append({"nivel": nivel, "h": i + 1,
                              "dentro": p["inferior"] <= real <= p["superior"],
                              "ancho_rel": (p["superior"] - p["inferior"]) / real if real > 0 else np.nan})

res = pd.DataFrame(filas)
print(f"evaluaciones: {len(res):,}\n")
print("=== COBERTURA REAL DEL INTERVALO ===")
t = res.groupby(["nivel", "h"]).agg(cobertura=("dentro", "mean"),
                                    ancho_rel=("ancho_rel", "median"), n=("dentro", "size"))
t["cobertura"] = (t["cobertura"] * 100).round(1)
t["objetivo"] = (t.index.get_level_values("nivel") * 100).round(0)
print(t.round(3).to_string())
print("\n=== GLOBAL ===")
print((res.groupby("nivel")["dentro"].mean() * 100).round(1).to_string())
