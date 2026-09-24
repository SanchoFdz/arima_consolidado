# -*- coding: utf-8 -*-
"""Convierte el agregado ANUIES ancho (2014-2025) en una tabla larga lista para ARIMA.

Hace tres cosas:
 1. Homologa el area de conocimiento a la taxonomia 2014 (ANUIES cambio de catalogo
    en el ciclo 2017-2018; sin homologar, la serie se rompe a la mitad).
 2. Asigna Zona Metropolitana segun la delimitacion Metropolis de Mexico 2020.
 3. Separa sostenimiento: Particular contra Publico, a partir de `Tipo_inst`.
 4. Deja una fila por (corte geografico x sostenimiento x nivel x modalidad x area x ciclo).

Salida: datos/panel_ni.parquet
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

from zonas import pares_zona

RAIZ = Path(__file__).resolve().parent
FUENTE = RAIZ.parent / "data" / "Anuies_agregado_2014_2025.xlsx"
SALIDA = RAIZ / "datos" / "panel_ni.parquet"

METRICAS = ["Matricula", "NI", "Egresados", "Sols_NI"]

# Catalogo nuevo (2017-2018 en adelante) -> catalogo 2014.
AREA_A_2014 = {
    "ADMINISTRACIÓN Y NEGOCIOS": "CIENCIAS SOCIALES, ADMINISTRACIÓN Y DERECHO",
    "CIENCIAS SOCIALES Y DERECHO": "CIENCIAS SOCIALES, ADMINISTRACIÓN Y DERECHO",
    "CIENCIAS DE LA SALUD": "SALUD",
    "CIENCIAS NATURALES, MATEMÁTICAS Y ESTADÍSTICA": "CIENCIAS NATURALES, EXACTAS Y DE LA COMPUTACIÓN",
    "TECNOLOGÍAS DE LA INFORMACIÓN Y LA COMUNICACIÓN": "CIENCIAS NATURALES, EXACTAS Y DE LA COMPUTACIÓN",
}

DIMENSIONES = [
    "Estado", "Municipio", "Zona_Metropolitana", "Nielsen_Region", "Nielsen_Area",
    "Sostenimiento", "Tipo_inst", "Nivel_educativo", "Modalidad", "Area_2014", "Subarea", "Area_especifica",
]


# ANUIES no trae una columna de sostenimiento: trae el tipo de institucion, y de
# los 12 tipos solo PARTICULAR es privado. Los otros 11 (UPES, TecNM, normales,
# politecnicas, interculturales, centros CONACYT...) son publicos.
PARTICULAR = "PARTICULAR"
PREFIJO_TIPO = "TIPO DE INSTITUCIÓN:"


def sostenimiento(tipo_inst):
    return tipo_inst.map(lambda t: "Particular" if t == PARTICULAR else "Publico")


def normalizar(texto):
    s = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def mapa_zonas():
    return {(normalizar(e), normalizar(m)): z for z, e, m in pares_zona()}


def cargar_ancho():
    df = pd.read_excel(FUENTE)
    df["Area_2014"] = df["Area"].replace(AREA_A_2014)
    df["Tipo_inst"] = df["Tipo_inst"].str.replace(PREFIJO_TIPO, "", regex=False).str.strip()
    df["Sostenimiento"] = sostenimiento(df["Tipo_inst"])
    clave = list(zip(df["Estado"].map(normalizar), df["Municipio"].map(normalizar)))
    zonas = mapa_zonas()
    df["Zona_Metropolitana"] = [zonas.get(k, "Fuera de zona metropolitana") for k in clave]
    return df


def a_largo(df):
    patron = re.compile(r"^(\d{4})_(\d{4})_(" + "|".join(METRICAS) + r")$")
    columnas = {c: patron.match(c).groups() for c in df.columns if patron.match(c)}

    bloques = []
    for ciclo in sorted({f"{a}-{b}" for a, b, _ in columnas.values()}):
        ini, fin = ciclo.split("-")
        cols = {f"{ini}_{fin}_{m}": m for m in METRICAS if f"{ini}_{fin}_{m}" in df.columns}
        bloque = df[DIMENSIONES + list(cols)].rename(columns=cols)
        bloque["ciclo"] = ciclo
        bloque["anio"] = int(ini)
        bloques.append(bloque)

    largo = pd.concat(bloques, ignore_index=True)
    for m in METRICAS:
        largo[m] = pd.to_numeric(largo[m], errors="coerce").fillna(0)

    # Colapsa las filas que comparten exactamente la misma combinacion de dimensiones
    # (varias escuelas/sedes del mismo municipio-carrera) para aligerar el panel.
    largo = (largo.groupby(DIMENSIONES + ["ciclo", "anio"], dropna=False, observed=True)[METRICAS]
                  .sum().reset_index())
    return largo


def main():
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    ancho = cargar_ancho()
    largo = a_largo(ancho)
    for c in DIMENSIONES + ["ciclo"]:
        largo[c] = largo[c].astype("category")
    largo.to_parquet(SALIDA, index=False)

    print(f"filas: {len(largo):,}  ciclos: {largo['ciclo'].nunique()}")
    print(f"NI total por ciclo:\n{largo.groupby('ciclo', observed=True)['NI'].sum().astype(int)}")
    print(f"guardado en {SALIDA}")


if __name__ == "__main__":
    main()
