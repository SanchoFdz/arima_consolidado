# -*- coding: utf-8 -*-
"""Corre la proyeccion sobre todas las categorias de una dimension a la vez.

Pensado para que finanzas se lleve, en un solo archivo, la tendencia de cada zona
metropolitana (o estado, o area) sin tener que ir una por una.
"""
from io import BytesIO
import pandas as pd
import streamlit as st

import metodos
import pronostico as pr
from comun import (CORTES, METRICAS, PRESETS_MODALIDAD, SIN_ZM,
                   aplicar_filtros, cargar, opciones)

st.set_page_config(page_title="Descarga masiva", page_icon="📦", layout="wide")
st.title("Descarga masiva de tendencias")
st.caption("Proyecta cada categoria de la dimension elegida y entrega todo en un Excel.")

df = cargar()

DIMENSIONES = {k: v for k, v in CORTES.items() if v} | {
    "Nivel educativo": "Nivel_educativo",
    "Modalidad": "Modalidad",
    "Area de conocimiento (2014)": "Area_2014",
}

col1, col2, col3 = st.columns(3)
dim_nombre = col1.selectbox("Desagregar por", list(DIMENSIONES))
dim = DIMENSIONES[dim_nombre]
metrica_nombre = col2.selectbox("Metrica", list(METRICAS))
metrica = METRICAS[metrica_nombre]
horizonte = col3.slider("Ciclos a proyectar", 1, 5, 3)

st.subheader("Filtros fijos (se aplican a todas las categorias)")
f1, f2, f3 = st.columns(3)
filtros = {}
niveles = f1.multiselect("Nivel educativo", opciones(df, "Nivel_educativo"))
if niveles and dim != "Nivel_educativo":
    filtros["Nivel_educativo"] = niveles
preset = f2.selectbox("Modalidad", list(PRESETS_MODALIDAD))
if PRESETS_MODALIDAD[preset] and dim != "Modalidad":
    filtros["Modalidad"] = PRESETS_MODALIDAD[preset]
areas = f3.multiselect("Area de conocimiento (2014)", opciones(df, "Area_2014"))
if areas and dim != "Area_2014":
    filtros["Area_2014"] = areas

g1, g2 = st.columns(2)
minimo = g1.number_input("Ignorar categorias con menos de N alumnos en el ultimo ciclo",
                         min_value=0, value=50, step=10)
motor = g2.selectbox("Metodo", list(metodos.MOTORES), index=0,
                     help="El ensemble gana el backtest; el ARIMA se deja para comparar.")

if st.button("Generar proyecciones", type="primary"):
    base = aplicar_filtros(df, filtros)
    if dim == "Zona_Metropolitana":
        base = base[base[dim].astype(str) != SIN_ZM]

    categorias = sorted(base[dim].dropna().astype(str).unique())
    filas, barra = [], st.progress(0.0, "Calculando proyecciones...")

    for i, cat in enumerate(categorias, 1):
        barra.progress(i / len(categorias), f"Proyectando {cat} ({i}/{len(categorias)})")
        serie = (base[base[dim].astype(str) == cat]
                 .groupby("anio", observed=True)[metrica].sum().sort_index())
        if serie.empty or serie.iloc[-1] < minimo:
            continue
        res = pr.proyectar(serie, horizonte, motor=motor)
        if res is None:
            continue

        fila = {dim_nombre: cat,
                f"{metrica}_2024-2025": int(serie.iloc[-1]),
                "metodo": res.motor,
                "confiabilidad": res.confiabilidad,
                "CAGR_historico_%": round(res.cagr_historico, 2) if res.cagr_historico is not None else None,
                "CAGR_proyectado_%": round(res.cagr_proyectado, 2) if res.cagr_proyectado is not None else None,
                "MAPE_backtest_%": round(res.mape_backtest, 2) if res.mape_backtest is not None else None,
                "MASE_backtest": round(res.mase_backtest, 2) if res.mase_backtest is not None else None}
        for _, p in res.proyeccion.iterrows():
            fila[f"{p['ciclo']}"] = int(round(p["pronostico"]))
            fila[f"{p['ciclo']}_inf"] = int(round(p["inferior"]))
            fila[f"{p['ciclo']}_sup"] = int(round(p["superior"]))
        fila["avisos"] = " | ".join(res.avisos)
        filas.append(fila)

    barra.empty()
    if not filas:
        st.warning("Ninguna categoria cumplio el minimo.")
        st.stop()

    salida = pd.DataFrame(filas)
    st.success(f"{len(salida)} categorias proyectadas.")
    st.dataframe(salida, use_container_width=True, hide_index=True)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as xls:
        salida.to_excel(xls, index=False, sheet_name="proyecciones")
    st.download_button("Descargar Excel", buffer.getvalue(),
                       file_name=f"tendencia_{metrica}_por_{dim}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
