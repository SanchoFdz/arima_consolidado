# -*- coding: utf-8 -*-
"""Que escalador del error transfiere mejor entre segmentos."""
import warnings
import numpy as np
import pandas as pd
import metodos
from validacion import construir_series, mase_escala

warnings.simplefilter("ignore")

df = pd.read_parquet("datos/panel_ni.parquet")
series = construir_series(df)
filas = []
for nombre, y in series:
    y = y.astype(float)
    if len(y) < 8 or y.iloc[-3:].mean() < 30:
        continue
    for corte in range(7, len(y)):
        train, resto = y.iloc[:corte], y.iloc[corte:]
        h = min(3, len(resto))
        vol = mase_escala(train.values)
        nivel = float(train.iloc[-1])
        if not np.isfinite(vol) or vol <= 0 or nivel <= 0:
            continue
        pred = np.asarray(metodos.ensemble(train, h), dtype=float)
        for i in range(h):
            e = abs(pred[i] - resto.values[i])
            filas.append({"segmento": nombre, "h": i + 1,
                          "por_volatilidad": e / vol,
                          "por_nivel": e / nivel,
                          "hibrido": e / np.sqrt(vol * nivel)})

d = pd.DataFrame(filas)
rng = np.random.default_rng(7)
segs = d["segmento"].unique()

print("Estabilidad del cuantil 0.8 entre submuestras aleatorias de segmentos")
print("(menor dispersion = el factor transfiere mejor a segmentos no vistos)\n")
for col in ["por_volatilidad", "por_nivel", "hibrido"]:
    qs = []
    for _ in range(200):
        elegidos = rng.choice(segs, size=len(segs) // 2, replace=False)
        sub = d[d["segmento"].isin(elegidos) & (d["h"] == 1)]
        qs.append(np.quantile(sub[col], 0.8))
    qs = np.array(qs)
    print(f"  {col:16s} q80 = {qs.mean():.3f}  ±{qs.std():.3f}  "
          f"(variacion relativa {qs.std() / qs.mean() * 100:.1f}%)")

print("\nCobertura que da el q80 global aplicado a cada segmento por separado:")
for col in ["por_volatilidad", "por_nivel", "hibrido"]:
    q = np.quantile(d.loc[d["h"] == 1, col], 0.8)
    cob = d[d["h"] == 1].groupby("segmento")[col].apply(lambda s: (s <= q).mean())
    print(f"  {col:16s} mediana {cob.median() * 100:.0f}%  |  "
          f"segmentos con cobertura <50%: {(cob < 0.5).mean() * 100:.0f}%")
