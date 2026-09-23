# -*- coding: utf-8 -*-
"""Sirven los datos externos? Backtest de origen movil, driver contra nada.

Mismo protocolo que validacion.py --- origen movil, MASE contra el naive del
propio train --- pero ahora la competencia no es entre metodos de extrapolacion
sino entre extrapolar a secas y extrapolar la TASA DE CAPTACION anclada a un
driver externo. El punto de esto es que la decision de usar demografia no se
tome porque suena bien.

    python validacion_externos.py

Un cuidado metodologico que vale decir en voz alta: el ajuste por rezago usa la
trayectoria de educacion basica incompleta anclada en el censo 2020, asi que en
los origenes mas viejos del backtest mira un poco hacia adelante. El efecto es
de ~0.5% anual, asi que no cambia el orden de la tabla, pero la columna con
ajuste es por eso ligeramente optimista.
"""
import warnings

import numpy as np
import pandas as pd

import drivers
import metodos
import pronostico
import rezago

warnings.simplefilter("ignore")

MIN_TRAIN = 7
H_MAX = 3
MIN_NIVEL = 30


def construir_segmentos(df, metrica="NI"):
    """Segmentos con geografia identificable: sin ella no hay driver que armar."""
    g = lambda sub: sub.groupby("anio", observed=True)[metrica].sum().sort_index()
    segs = [("NACIONAL", g(df), {})]

    for col, pref in [("Estado", "EDO"), ("Zona_Metropolitana", "ZM"),
                      ("Nielsen_Region", "NIELSEN"), ("Nielsen_Area", "AREA_N")]:
        for v in df[col].dropna().unique():
            if v == "Fuera de zona metropolitana":
                continue
            segs.append((f"{pref}:{v}", g(df[df[col] == v]), {col: [v]}))

    # Cortes que cruzan geografia con segmento: el uso real de la app.
    for niv in ["LICENCIATURA UNIVERSITARIA Y TECNOLÓGICA", "MAESTRÍA", "TSU"]:
        sub_n = df[df["Nivel_educativo"] == niv]
        segs.append((f"NAC|{niv[:12]}", g(sub_n), {}))
        for v in df["Estado"].dropna().unique():
            segs.append((f"EDO:{v}|{niv[:12]}", g(sub_n[sub_n["Estado"] == v]),
                         {"Estado": [v]}))
    for mod, etq in [(["ESCOLARIZADA"], "PRESENCIAL"),
                     (["NO ESCOLARIZADA", "MIXTA"], "ONLINE")]:
        sub_m = df[df["Modalidad"].isin(mod)]
        segs.append((f"NAC|{etq}", g(sub_m), {}))
        for v in df["Zona_Metropolitana"].dropna().unique():
            if v == "Fuera de zona metropolitana":
                continue
            segs.append((f"ZM:{v}|{etq}", g(sub_m[sub_m["Zona_Metropolitana"] == v]),
                         {"Zona_Metropolitana": [v]}))
    return segs


def competidores(filtros, ext):
    """Diccionario metodo -> funcion(serie, h). Uno por driver disponible."""
    base = metodos.ensemble
    comp = {"sin_driver": base}

    claves, _ = ext.claves(filtros)
    for nombre, spec in drivers.DRIVERS.items():
        if spec is None:
            continue
        serie, _ = ext.serie(filtros, nombre)
        if serie is None:
            continue
        etq = spec[0] + ("_lag1" if spec[1] else "")
        comp[etq] = (lambda d: lambda y, h: metodos.razon(y, h, d, base))(serie)

    # Lo que la app hace de verdad: elegir por segmento entre anclar a la
    # demografia y no anclar, con backtest sobre los origenes VIEJOS, y
    # proyectar con la que gano. Es la unica fila de la tabla que corresponde a
    # un usuario apretando un boton, asi que es la que decide si esto sirve.
    pob, _ = ext.serie(filtros, "Poblacion 12-29 anios (CONAPO)")
    if pob is not None:
        def auto(y, h, d=pob):
            razon = lambda s, k: metodos.razon(s, k, d, base)
            tope = len(y) - 1
            m_a, _ = pronostico._backtest(y, razon, max_origen=tope)
            m_b, _ = pronostico._backtest(y, base, max_origen=tope)
            usa = bool(m_a and m_b and m_a < m_b)
            return razon(y, h) if usa else base(y, h)
        comp["auto_por_segmento"] = auto

    if pob is not None and claves:
        def con_rezago(y, h, d=pob, claves=tuple(claves)):
            anios = [int(y.index[-1]) + i for i in range(1, h + 1)]
            punto = metodos.razon(y, h, d, base)
            fac, _ = rezago.ajuste(claves, anios)
            return punto if fac is None else punto * fac.reindex(anios).values
        comp["pob_12_29_+rezago"] = con_rezago
    return comp


def evaluar(segmentos, ext):
    filas = []
    for i, (nombre, y, filtros) in enumerate(segmentos, 1):
        y = y.astype(float)
        if len(y) < MIN_TRAIN + 1 or y.iloc[-3:].mean() < MIN_NIVEL:
            continue
        comp = competidores(filtros, ext)
        if len(comp) < 2:
            continue
        for corte in range(MIN_TRAIN, len(y)):
            train, resto = y.iloc[:corte], y.iloc[corte:]
            h = min(H_MAX, len(resto))
            d = np.abs(np.diff(train.values))
            esc = d.mean() if len(d) and d.mean() > 0 else np.nan
            if not np.isfinite(esc):
                continue
            for met, fn in comp.items():
                try:
                    pred = np.asarray(fn(train, h), dtype=float)[:h]
                except Exception:
                    continue
                if not np.all(np.isfinite(pred)):
                    continue
                real = resto.values[:h]
                for k in range(h):
                    filas.append({
                        "segmento": nombre, "metodo": met, "origen": corte,
                        "h": k + 1, "ae": abs(pred[k] - real[k]),
                        "ape": (abs(pred[k] - real[k]) / real[k] * 100
                                if real[k] > 0 else np.nan),
                        "escala": esc})
        if i % 25 == 0:
            print(f"  {i}/{len(segmentos)} segmentos...")
    return pd.DataFrame(filas)


if __name__ == "__main__":
    df = pd.read_parquet("datos/panel_ni.parquet")
    ext = drivers.externos()
    segs = construir_segmentos(df)
    print(f"Segmentos candidatos: {len(segs)}")

    res = evaluar(segs, ext)
    res["mase"] = res["ae"] / res["escala"]

    # Solo segmentos donde TODOS los competidores corrieron, para comparar peras
    # con peras: si un driver falla en un segmento dificil y los demas no, su
    # promedio saldria bonito por ausencia.
    n_met = res["metodo"].nunique()
    completos = (res.groupby("segmento")["metodo"].nunique() == n_met)
    res = res[res["segmento"].isin(completos[completos].index)]
    print(f"\nSegmentos comparables: {res['segmento'].nunique()} | "
          f"predicciones: {len(res):,}\n")

    tabla = (res.groupby("metodo")
             .agg(MASE=("mase", "mean"), MASE_mediana=("mase", "median"),
                  MAPE=("ape", "mean"))
             .sort_values("MASE").round(3))
    por_h = res.pivot_table(index="metodo", columns="h", values="mase", aggfunc="mean")
    tabla["MASE_h3"] = por_h[3].round(3)
    por_seg = res.groupby(["segmento", "metodo"])["mase"].mean().reset_index()
    gana = por_seg.loc[por_seg.groupby("segmento")["mase"].idxmin(), "metodo"].value_counts()
    tabla["gana_segmentos"] = gana
    tabla["gana_segmentos"] = tabla["gana_segmentos"].fillna(0).astype(int)

    print("=== DRIVER CONTRA NADA (MASE, menor es mejor) ===")
    print(tabla.to_string())

    base = res[res["metodo"] == "sin_driver"].groupby("segmento")["mase"].mean()
    print("\n=== EN QUE FRACCION DE SEGMENTOS CADA DRIVER LE GANA A NO USARLO ===")
    for met in tabla.index:
        if met == "sin_driver":
            continue
        otro = res[res["metodo"] == met].groupby("segmento")["mase"].mean()
        comun = base.index.intersection(otro.index)
        print(f"  {met:22s} {(otro[comun] < base[comun]).mean() * 100:5.1f}%  "
              f"({len(comun)} segmentos)")

    print("\n=== POR TIPO DE CORTE (MASE medio) ===")
    res["tipo"] = res["segmento"].str.split(":").str[0].str.split("|").str[0]
    print(res.pivot_table(index="tipo", columns="metodo", values="mase",
                          aggfunc="mean").round(3).to_string())

    res.to_parquet("datos/validacion_externos.parquet", index=False)
    print("\nguardado datos/validacion_externos.parquet")
