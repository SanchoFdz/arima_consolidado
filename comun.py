# -*- coding: utf-8 -*-
"""Catalogos y helpers compartidos entre las paginas de la app."""
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
PANEL = RAIZ / "datos" / "panel_ni.parquet"
CONCORDANCIA = RAIZ / "datos" / "concordancia_areas.parquet"

METRICAS = {
    "Nuevo ingreso (NI)": "NI",
    "Matricula total": "Matricula",
    "Egresados": "Egresados",
    "Solicitudes de nuevo ingreso": "Sols_NI",
}

# Los cortes por disciplina NO usan las columnas crudas del panel. ANUIES cambio
# de catalogo en 2017-2018 y `Subarea`/`Area_especifica` traen los dos catalogos
# revueltos: 10 de 38 subareas existen solo hasta 2016 y 16 solo desde 2017, asi
# que cualquier serie a ese nivel tiene 3 u 8 ciclos, no 11. En vez de eso se usa
# la concordancia de `concordancia.py`: 69 grupos comparables, cada uno un
# conjunto de categorias viejas + nuevas cuyo agregado si es continuo en el cruce
# 2016-2017. El campo se reconstruye sumando grupos, y eso arregla de paso el
# nivel area, que estaba roto para dos areas porque el catalogo nuevo movio
# programas entre ellas (computacion saltaba +66%, ingenieria caia -19%; con los
# grupos quedan en +5.0% y +0.8%).
DISCIPLINA = {
    "Campo de conocimiento": "Campo",
    "Carrera o grupo de carreras": "Grupo_comparable",
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


def _campo_de_cada_grupo(conc):
    """Campo de cada grupo: el area del catalogo NUEVO donde esta su mayor NI.

    Se toma el catalogo nuevo porque es el vigente, y se traducen sus nombres a
    los del catalogo 2014 para que el campo siga llamandose como la gente lo
    conoce. Ojo con una consecuencia: un grupo se va completo al campo donde
    pesa mas, asi que la composicion de un campo no es identica a la del area
    ANUIES. Es el precio de que la serie sea comparable, y es el correcto:
    un grupo partido entre dos campos habria que repartirlo con proporciones
    inventadas, que es justo lo que la concordancia no hace.
    """
    from preparar_datos import AREA_A_2014

    nuevo = conc[conc["catalogo"].isin(["nuevo", "ambos"])].copy()
    nuevo["campo"] = nuevo["Area"].replace(AREA_A_2014)
    dominante = (nuevo.groupby(["grupo", "campo"], observed=True)["ni_nuevo"].sum()
                 .reset_index().sort_values("ni_nuevo", ascending=False)
                 .drop_duplicates("grupo"))
    return dict(zip(dominante["grupo"], dominante["campo"]))


@st.cache_data(show_spinner=False)
def cargar():
    if not PANEL.exists():
        st.error("Falta el panel de datos. Corre primero: python preparar_datos.py")
        st.stop()
    df = pd.read_parquet(PANEL)

    if not CONCORDANCIA.exists():
        st.error("Falta la concordancia de catalogos. Corre: python concordancia.py")
        st.stop()
    conc = pd.read_parquet(CONCORDANCIA)
    grupo = dict(zip(conc["Area_especifica"], conc["grupo"]))
    campo = _campo_de_cada_grupo(conc)

    ae = df["Area_especifica"].astype(str)
    df["Grupo_comparable"] = ae.map(grupo).astype("category")
    df["Campo"] = df["Grupo_comparable"].astype(str).map(campo).astype("category")
    return df


@st.cache_data(show_spinner=False)
def opciones(df, columna):
    return sorted(str(v) for v in df[columna].dropna().unique())


def aplicar_filtros(df, filtros):
    mascara = pd.Series(True, index=df.index)
    for col, valores in filtros.items():
        if valores:
            mascara &= df[col].astype(str).isin(valores)
    return df[mascara]
