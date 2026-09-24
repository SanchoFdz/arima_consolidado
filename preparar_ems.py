# -*- coding: utf-8 -*-
"""Panel de media superior (bachillerato) desde el formato 911, 2014-2015 a 2024-2025.

Mismo esquema que el panel ANUIES para que la app lo trate igual: una fila por
(corte geografico x sostenimiento x subnivel x modalidad x ciclo), con nuevo
ingreso y matricula. No usa ANUIES para nada; la fuente es el 911 de la SEP:

  * 2014-2015 a 2020-2021: RDS de ../Formatos 911/EMS, via ems/extraer_rds.R
    (pyreadr no los abre). Hace falta Rscript.
  * 2021-2022 a 2024-2025: los CSV de ../data/Educacion Media Superior 911.

Tres decisiones de homologacion, las tres medidas sobre el panel crudo:

 1. NI es el primer ingreso a 1er grado: MS130/MS149 (2014-18), V346/V414
    (2018-21), NVO_ING_1 (2021+). NO es NVO_ING de los CSV nuevos, que es
    alumnos menos repetidores de TODOS los grados (~92% de la matricula).
    Nacional: 1.95M (2014) -> 2.07M (2018) -> 1.89M (2020, COVID) -> 2.04M (2024).
 2. Subnivel en dos, no en tres. En 2018-2019 profesional tecnico salta de
    28k a 146k de NI y tecnologico cae lo mismo: es CONALEP (profesional
    tecnico bachiller) cambiando de casilla, no mercado. Tecnologico + PT si
    es continuo (756k -> 760k).
 3. MIXTA va dentro de ESCOLARIZADA, porque es lo que hacen los CSV 2021+:
    1,456 de las 1,464 escuelas MIXTA de 2020-2021 aparecen como ESCOLARIZADA
    en 2021-2022. Queda NO ESCOLARIZADA sola, con un quiebre de cobertura en
    2018-2019 (la matricula pasa de 185k a 369k al integrarse la virtual a los
    archivos principales); en NI el efecto es menor (75k -> 82k). Ver AVISO_NE.

Geografia por clave INEGI, no por nombre. Los nombres salen del crosswalk del
panel ANUIES cuando el municipio existe ahi (asi Estado/Municipio se escriben
igual en los dos paneles) y de CONAPO para el resto: EMS llega a ~2,260
municipios y superior a ~830. Chiapas no esta en el agregado ANUIES; aqui si.

Salida: datos/panel_ems.parquet
"""
import re
import subprocess
import unicodedata
from pathlib import Path

import pandas as pd

from preparar_datos import mapa_zonas, normalizar

RAIZ = Path(__file__).resolve().parent
RDS = RAIZ.parent / "Formatos 911" / "EMS"
CSVS = RAIZ.parent / "data" / "Educacion Media Superior 911"
EXTRACTOR = RAIZ / "ems" / "extraer_rds.R"
INTERMEDIO = RAIZ / "ems" / "rds_2014_2021.csv"
SALIDA = RAIZ / "datos" / "panel_ems.parquet"

METRICAS = ["Matricula", "NI"]
DIMENSIONES = ["Estado", "Municipio", "Zona_Metropolitana", "Nielsen_Region",
               "Nielsen_Area", "Sostenimiento", "Subnivel", "Modalidad"]

GENERAL = "Bachillerato general"
TECNOLOGICO = "Tecnologico y profesional tecnico"
SUBNIVEL = {"BACHILLERATO GENERAL": GENERAL,
            "BACHILLERATO TECNOLOGICO": TECNOLOGICO,
            "PROFESIONAL TECNICO": TECNOLOGICO,
            "PROFESIONAL TECNICO BACHILLER": TECNOLOGICO}
MODALIDAD = {"ESCOLARIZADA": "ESCOLARIZADA", "MIXTA": "ESCOLARIZADA",
             "NO ESCOLARIZADA": "NO ESCOLARIZADA"}
SOSTENIMIENTO = {"PRIVADO": "Particular", "PUBLICO": "Publico"}

# Chiapas no esta en el crosswalk porque no esta en el agregado ANUIES. Nielsen
# lo pone en Sureste, Area VI, con el resto del sur.
NIELSEN_FALTANTE = {"CHIAPAS": ("SURESTE", "Area_VI")}


def _ascii(texto):
    s = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def leer_rds():
    """Tabla larga 2014-2021. Se cachea en ems/ porque los RDS pesan 3 GB."""
    if not INTERMEDIO.exists():
        subprocess.run(["Rscript", str(EXTRACTOR), str(RDS), str(INTERMEDIO)], check=True)
    return pd.read_csv(INTERMEDIO)


def _leer_csv(ruta):
    # Cuatro archivos, tres formatos: latin1 con coma (21-22, 22-23), utf-8 con
    # coma (23-24) y utf-8 con BOM y pipe (24-25).
    cabeza = ruta.read_bytes()[:4000]
    sep = "|" if b"|" in cabeza.split(b"\n")[0] else ","
    for enc in ("utf-8-sig", "latin1"):
        try:
            return pd.read_csv(ruta, sep=sep, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"no se pudo leer {ruta}")


def leer_csvs():
    partes = []
    for ruta in sorted(CSVS.glob("*/*.csv")):
        a, b = re.search(r"(20\d\d)\D(20\d\d)", ruta.name).groups()
        d = _leer_csv(ruta)
        partes.append(pd.DataFrame({
            "ciclo": f"{a}-{b}",
            "cve_ent": pd.to_numeric(d["ENTIDAD"]).astype(int),
            "cve_mun": pd.to_numeric(d["CV_MUN"]).astype(int),
            "control": d["CONTROL"].map(_ascii),
            "modalidad": d["MODALIDAD"].map(_ascii),
            "subnivel": d["SUBNIVEL"].map(_ascii),
            "NI": pd.to_numeric(d["NVO_ING_1"], errors="coerce").fillna(0),
            "Matricula": pd.to_numeric(d["ALUMNOS"], errors="coerce").fillna(0),
        }))
    return pd.concat(partes, ignore_index=True)


def catalogo_geo():
    """clave_mun -> Estado, Municipio, Zona_Metropolitana, Nielsen_*."""
    cw = pd.read_parquet(RAIZ / "datos" / "crosswalk_geo.parquet")
    cw = cw.dropna(subset=["clave_mun"]).assign(clave_mun=lambda d: d["clave_mun"].astype(int))
    conapo = (pd.read_parquet(RAIZ / "datos" / "externos_municipio.parquet",
                              columns=["clave_mun", "cve_ent", "municipio"])
              .drop_duplicates("clave_mun"))

    estado_de = dict(zip(cw["cve_ent"].astype(int), cw["Estado"]))
    estado_de.setdefault(7, "CHIAPAS")
    nielsen = {e: (r, a) for e, r, a in
               cw[["Estado", "Nielsen_Region", "Nielsen_Area"]].drop_duplicates().itertuples(index=False)}
    nielsen.update(NIELSEN_FALTANTE)

    cat = conapo.assign(Estado=conapo["cve_ent"].astype(int).map(estado_de),
                        Municipio=conapo["municipio"].str.upper())
    # Nombre ANUIES donde lo hay, para que un mismo municipio se llame igual en
    # los dos paneles (p.ej. "PLAYA DEL CARMEN", que CONAPO llama Solidaridad).
    nombre_anuies = dict(zip(cw["clave_mun"], cw["Municipio"]))
    cat["Municipio"] = [nombre_anuies.get(k, m) for k, m in zip(cat["clave_mun"], cat["Municipio"])]

    zonas = mapa_zonas()
    zm_anuies = dict(zip(cw["clave_mun"], cw["Zona_Metropolitana"]))
    cat["Zona_Metropolitana"] = [
        zm_anuies.get(k) or zonas.get((normalizar(e), normalizar(m)), "Fuera de zona metropolitana")
        for k, e, m in zip(cat["clave_mun"], cat["Estado"], cat["Municipio"])]
    cat["Nielsen_Region"] = cat["Estado"].map(lambda e: nielsen[e][0])
    cat["Nielsen_Area"] = cat["Estado"].map(lambda e: nielsen[e][1])
    return cat.drop(columns=["cve_ent", "municipio"])


def construir():
    crudo = pd.concat([leer_rds(), leer_csvs()], ignore_index=True)
    crudo["clave_mun"] = crudo["cve_ent"] * 1000 + crudo["cve_mun"]
    crudo["Sostenimiento"] = crudo["control"].map(SOSTENIMIENTO)
    crudo["Subnivel"] = crudo["subnivel"].map(SUBNIVEL)
    crudo["Modalidad"] = crudo["modalidad"].map(MODALIDAD)
    for c, origen in (("Sostenimiento", "control"), ("Subnivel", "subnivel"),
                      ("Modalidad", "modalidad")):
        raros = crudo.loc[crudo[c].isna(), origen].unique()
        if len(raros):
            raise ValueError(f"{c}: valores sin homologar {raros}")

    geo = catalogo_geo()
    panel = crudo.merge(geo, on="clave_mun", how="left")
    sin = panel["Estado"].isna() | panel["Municipio"].isna()
    if sin.any():
        # Claves de municipio que CONAPO no tiene (municipios creados despues, o
        # capturas con clave 0). Se quedan en su estado como "NO ESPECIFICADO"
        # para que el total nacional y estatal cuadre con el 911.
        faltan = panel.loc[sin, "clave_mun"].unique()
        print(f"aviso: {len(faltan)} claves de municipio sin catalogo "
              f"({panel.loc[sin, 'NI'].sum():,.0f} de NI): {sorted(faltan)[:10]}")
        estado_de = geo.assign(ent=geo["clave_mun"] // 1000).drop_duplicates("ent")
        ent = panel.loc[sin, "cve_ent"]
        for col in ("Estado", "Nielsen_Region", "Nielsen_Area"):
            panel.loc[sin, col] = ent.map(dict(zip(estado_de["ent"], estado_de[col]))).values
        panel.loc[sin, "Municipio"] = "NO ESPECIFICADO"
        panel.loc[sin, "Zona_Metropolitana"] = "Fuera de zona metropolitana"

    panel["anio"] = panel["ciclo"].str[:4].astype(int)
    panel = (panel.groupby(DIMENSIONES + ["ciclo", "anio"], observed=True)[METRICAS]
                  .sum().reset_index())
    return panel


def main():
    panel = construir()
    for c in DIMENSIONES + ["ciclo"]:
        panel[c] = panel[c].astype("category")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(SALIDA, index=False)
    print(f"filas: {len(panel):,}  municipios: {panel[['Estado', 'Municipio']].drop_duplicates().shape[0]:,}")
    print(panel.pivot_table(index="ciclo", columns="Sostenimiento", values="NI",
                            aggfunc="sum", observed=True).astype(int))
    print(f"guardado en {SALIDA}")


if __name__ == "__main__":
    main()
