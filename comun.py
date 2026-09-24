# -*- coding: utf-8 -*-
"""Catalogos y helpers compartidos entre las paginas de la app."""
from pathlib import Path

import pandas as pd
import streamlit as st

from taxonomia import MODALIDADES_ONLINE

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

# Modalidad es multiselect, igual que el resto de los filtros de Segmento: las
# opciones son las modalidades base del panel (ESCOLARIZADA, NO ESCOLARIZADA,
# MIXTA y DUAL) y el usuario las combina como quiera.
#
# Y ADEMAS convive en la lista una opcion compuesta, "Online (no escolarizada +
# mixta)", que se expande a sus dos modalidades base. Esto se habia quitado al
# pasar a multiselect, con el argumento de que se arma marcando dos casillas y
# tener el mismo corte con dos nombres invita a reportar cifras que parecen de
# universos distintos. El argumento estaba equivocado y los numeros lo dicen:
#
#   NO ESCOLARIZADA sola   437,882 -> 261,678 -> 297,016   -40.2% / +13.5%
#   NO ESCOLARIZADA+MIXTA  437,882 -> 475,083 -> 540,301    +8.5% / +13.7%
#
# El -40.2% es el desglose de MIXTA en 2023-2024, no mercado (ver taxonomia.py).
# O sea que la suma no es un corte mas entre los 15 posibles: es la UNICA serie
# de modalidad comparable en los 11 ciclos que se puede pedir de este panel, y
# esconderla detras de "marca estas dos y no estas otras" es esconder el camino
# correcto. Se devuelve como atajo, no como modo: sigue siendo un multiselect y
# se puede combinar con lo que sea.
#
# El resto de los presets no vuelven al selector --- "Escolarizada (presencial)"
# y "Solo no escolarizada" si son un duplicado de marcar una casilla. Viven aqui
# para que `normalizar_modalidades` traduzca cualquier nombre viejo a sus
# modalidades base y nada que ya mande un preset se rompa.
MODALIDAD_ONLINE = "Online (no escolarizada + mixta)"

PRESETS_MODALIDAD = {
    "Todas": None,
    "Escolarizada (presencial)": ["ESCOLARIZADA"],
    MODALIDAD_ONLINE: list(MODALIDADES_ONLINE),
    "Solo no escolarizada": ["NO ESCOLARIZADA"],
    "Dual": ["DUAL"],
}

# Presets que SI se ofrecen en la interfaz, en el orden en que se ofrecen.
PRESETS_EN_SELECTOR = [MODALIDAD_ONLINE]

AYUDA_MODALIDAD = (
    "Vacio = todas las modalidades sumadas. Se pueden combinar varias. "
    f"**{MODALIDAD_ONLINE}** es un atajo: equivale exactamente a marcar esas dos "
    "casillas, y es la unica serie de modalidad comparable en los 11 ciclos "
    "porque ANUIES empezo a desglosar MIXTA hasta 2023-2024 (NO ESCOLARIZADA "
    "sola cae -40.2% ese ciclo por reclasificacion, no por mercado)."
)

AYUDA_SOSTENIMIENTO = (
    "Vacio = particulares y publicas sumadas. ANUIES no publica sostenimiento: "
    "se deriva del tipo de institucion, donde solo PARTICULAR es privado y los "
    "otros 11 tipos (UPES, TecNM, normales, politecnicas...) son publicos.")

SIN_ZM = "Fuera de zona metropolitana"


def normalizar_modalidades(valor):
    """Modalidades base a partir de un string suelto, una lista o None.

    Acepta indistintamente modalidades base ("MIXTA"), nombres de preset
    ("Online (no escolarizada + mixta)") y mezclas de ambos. "Todas" —y None—
    significan "sin filtro", asi que devuelven lista vacia. El resultado no
    tiene repetidos y conserva el orden en que se pidieron.
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        valor = [valor]
    salida = []
    for v in valor:
        if v is None:
            continue
        if v in PRESETS_MODALIDAD:
            base = PRESETS_MODALIDAD[v] or []   # "Todas" -> [] -> sin filtro
        else:
            base = [str(v)]
        for m in base:
            if m not in salida:
                salida.append(m)
    return salida


def etiqueta_modalidades(seleccion):
    """Etiqueta corta para titulos y fichas de exportacion.

    Si lo seleccionado coincide exacto con un preset se usa su nombre —para que
    no escolarizada + mixta siga leyendose "Online (no escolarizada + mixta)" en
    el titulo de la grafica—; si no, se listan las modalidades elegidas.
    """
    seleccion = normalizar_modalidades(seleccion)
    if not seleccion:
        return ""
    for nombre, mods in PRESETS_MODALIDAD.items():
        if mods and set(mods) == set(seleccion):
            return nombre
    return ", ".join(seleccion)


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


def cargar():
    """Panel con disciplina comparable. La cache va atada a la fecha del parquet.

    Sin eso, regenerar el panel con una columna nueva (Sostenimiento) no invalida
    `st.cache_data`, porque el codigo de la funcion no cambio, y la app sigue
    sirviendo el DataFrame viejo sin la columna.
    """
    if not PANEL.exists():
        st.error("Falta el panel de datos. Corre primero: python preparar_datos.py")
        st.stop()
    return _cargar(PANEL.stat().st_mtime)


@st.cache_data(show_spinner=False)
def _cargar(_version):
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


def opciones_modalidad(df):
    """Opciones del multiselect de Modalidad: el atajo compuesto y luego las base.

    El compuesto va primero a proposito. Es la respuesta correcta para la
    pregunta que mas se hace de esta columna --- "como va el online" --- y
    ponerlo debajo de las cuatro base lo convierte en una nota al pie de la
    unica serie que no tiene el escalon de 2023-2024.
    """
    return list(PRESETS_EN_SELECTOR) + opciones(df, "Modalidad")


def aplicar_filtros(df, filtros):
    """Filtra el panel. Cada filtro es un OR entre sus valores (isin).

    Un filtro puede llegar como lista (lo normal desde los multiselect) o como
    string suelto; las dos formas se aceptan. Para `Modalidad` ademas se
    expanden los nombres de preset a sus modalidades base, ver
    `normalizar_modalidades`.
    """
    mascara = pd.Series(True, index=df.index)
    for col, valores in filtros.items():
        if col == "Modalidad":
            valores = normalizar_modalidades(valores)
        elif isinstance(valores, str):
            valores = [valores]
        if valores:
            mascara &= df[col].astype(str).isin([str(v) for v in valores])
    return df[mascara]
