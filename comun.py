# -*- coding: utf-8 -*-
"""Catalogos y helpers compartidos entre las paginas de la app."""
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
PANEL = RAIZ / "datos" / "panel_ni.parquet"

METRICAS = {
    "Nuevo ingreso (NI)": "NI",
    "Matricula total": "Matricula",
    "Egresados": "Egresados",
    "Solicitudes de nuevo ingreso": "Sols_NI",
}

CORTES = {
    "Nacional": None,
    "Region Nielsen": "Nielsen_Region",
    "Area Nielsen": "Nielsen_Area",
    "Zona metropolitana": "Zona_Metropolitana",
    "Estado": "Estado",
    "Municipio": "Municipio",
}

PRESETS_MODALIDAD = {
    "Todas": None,
    "Escolarizada (presencial)": ["ESCOLARIZADA"],
    "Online (no escolarizada + mixta)": ["NO ESCOLARIZADA", "MIXTA"],
    "Solo no escolarizada": ["NO ESCOLARIZADA"],
    "Dual": ["DUAL"],
}

SIN_ZM = "Fuera de zona metropolitana"


@st.cache_data(show_spinner=False)
def cargar():
    if not PANEL.exists():
        st.error("Falta el panel de datos. Corre primero: python preparar_datos.py")
        st.stop()
    return pd.read_parquet(PANEL)


@st.cache_data(show_spinner=False)
def opciones(df, columna):
    return sorted(str(v) for v in df[columna].dropna().unique())


def aplicar_filtros(df, filtros):
    mascara = pd.Series(True, index=df.index)
    for col, valores in filtros.items():
        if valores:
            mascara &= df[col].astype(str).isin(valores)
    return df[mascara]
