# -*- coding: utf-8 -*-
"""ETL de las fuentes externas que alimentan la proyeccion.

El extrapolador del repo solo ve su propia serie: 11 observaciones anuales de NI.
Lo que no puede saber es que el tamano de la cohorte que alimenta esa serie ya
esta escrito -- CONAPO lo proyecta hasta 2040 -- ni que el nivel anterior
(media superior) es el insumo casi mecanico del nuevo ingreso de superior un
ciclo despues. Este modulo trae esas cuatro fuentes al panel:

  1. CONAPO, proyecciones municipales por grandes grupos de edad, 1990-2040.
     `pobproy_ggrupos.csv`. De aqui sale la poblacion 12-29 ("edad educativa")
     y la poblacion total de cada municipio, con valores FUTUROS, que es lo
     que vuelve util un driver: no hay que proyectarlo.

  2. SEP, serie historica y prospectiva por entidad, 1990-1991 a 2030-2031.
     `serie_historica_entidades_sep (2).xlsm`, hoja MATRICULA. Renglon 500000
     es media superior: el nivel anterior. Tambien trae prospectiva propia de
     la SEP hasta 2030-31, asi que sirve como driver adelantado.

  3. La misma fuente, hoja ESCUELAS: numero de escuelas de superior por entidad
     (normal 700000 + licenciatura 800000 + posgrado 900000). Es el lado de la
     oferta -- capacidad instalada, no demanda.

  4. CONEVAL, Indice de Rezago Social municipal, censos 2000-2005-2010-2015-2020.
     `../data/Indice de Rezago Social/IRS_entidades_mpios_*.xlsx`. No es una
     serie anual: son cinco cortes. Entra como nivel estructural y como
     tendencia lenta, nunca como serie a extrapolar.

Salida: cuatro parquets en datos/ (ver SALIDAS al final) mas el crosswalk que
conecta los cortes geograficos del panel con las claves INEGI de las fuentes.

    python externos.py
"""
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
SERIES = RAIZ / "series_historicas"
DATOS = RAIZ / "datos"
PANEL = DATOS / "panel_ni.parquet"

CONAPO = SERIES / "pobproy_ggrupos.csv"
SEP = SERIES / "serie_historica_entidades_sep (2).xlsm"
IRS_DIR = RAIZ.parent / "data" / "Indice de Rezago Social"

MUN = DATOS / "externos_municipio.parquet"
ENT = DATOS / "externos_entidad.parquet"
IRS = DATOS / "irs_municipio.parquet"
CROSSWALK = DATOS / "crosswalk_geo.parquet"
SALIDAS = (MUN, ENT, IRS, CROSSWALK)

ANIOS_IRS = (2000, 2005, 2010, 2015, 2020)

# El panel usa nombres cortos de estado; CONAPO y CONEVAL usan los oficiales.
ALIAS_ESTADO = {
    "COAHUILA DE ZARAGOZA": "COAHUILA",
    "MICHOACAN DE OCAMPO": "MICHOACAN",
    "VERACRUZ DE IGNACIO DE LA LLAVE": "VERACRUZ",
}

# Renglones de la serie SEP que nos interesan.
REN_MEDIA_SUPERIOR = 500000
REN_SUPERIOR = (700000, 800000, 900000)  # normal + licenciatura + posgrado

# Municipios del panel cuyo nombre no coincide con CONAPO. Solo variantes de
# nombre: Eldorado y Juan Jose Rios (Sinaloa) son municipios creados en 2022 y
# no existen en la base CONAPO 1990-2040, asi que se quedan sin datos externos
# en vez de cargarse contra el municipio del que se separaron -- mapearlos
# duplicaria su poblacion al sumar una region.
ALIAS_MUNICIPIO = {
    ("GUANAJUATO", "SAN JOSE DE ITURBIDE"): ("GUANAJUATO", "SAN JOSE ITURBIDE"),
    ("OAXACA", "HEROICA CIUDAD DE JUCHITAN DE ZARAGOZA"): ("OAXACA", "JUCHITAN DE ZARAGOZA"),
    ("QUINTANA ROO", "PLAYA DEL CARMEN"): ("QUINTANA ROO", "SOLIDARIDAD"),
}


def normalizar(texto):
    s = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _estado(nombre):
    n = normalizar(nombre)
    return ALIAS_ESTADO.get(n, n)


# ------------------------------------------------------------------ 1. CONAPO
def cargar_conapo():
    """Poblacion municipal 1990-2040, sumada sobre sexo.

    POB_012_29 es el grupo que CONAPO publica a nivel municipal y el unico que
    cubre la edad de matriculacion en superior (18-24 vive dentro). No hay
    desglose mas fino en esta fuente, y usar el grupo ancho es preferible a
    inventar una reparticion.
    """
    cols = ["CLAVE", "CLAVE_ENT", "NOM_ENT", "NOM_MUN", "ANO",
            "POB_012_29", "POB_TOTAL"]
    d = pd.read_csv(CONAPO, usecols=cols)
    d = (d.groupby(["CLAVE", "CLAVE_ENT", "NOM_ENT", "NOM_MUN", "ANO"],
                   as_index=False)[["POB_012_29", "POB_TOTAL"]].sum())
    d.columns = ["clave_mun", "cve_ent", "estado", "municipio", "anio",
                 "pob_12_29", "pob_total"]
    d["estado_norm"] = d["estado"].map(_estado)
    d["municipio_norm"] = d["municipio"].map(normalizar)
    d["clave_mun"] = d["clave_mun"].astype(int)
    d["cve_ent"] = d["cve_ent"].astype(int)
    return d


# --------------------------------------------------------------------- 2 y 3.
def _hoja_sep(hoja):
    d = pd.read_excel(SEP, sheet_name=hoja, header=None)
    ciclos = [str(v) for v in d.iloc[2, 5:].tolist()]
    anios = [int(c.split("-")[0]) for c in ciclos]
    cuerpo = d.iloc[4:, [1, 2] + list(range(5, 5 + len(anios)))].copy()
    cuerpo.columns = ["cve_ent", "renglon"] + anios
    cuerpo = cuerpo.dropna(subset=["cve_ent", "renglon"])
    cuerpo["cve_ent"] = pd.to_numeric(cuerpo["cve_ent"], errors="coerce")
    cuerpo["renglon"] = pd.to_numeric(cuerpo["renglon"], errors="coerce")
    cuerpo = cuerpo.dropna(subset=["cve_ent", "renglon"])
    # La entidad 33 es el total nacional de la propia SEP; se recalcula sumando.
    cuerpo = cuerpo[cuerpo["cve_ent"].between(1, 32)]
    cuerpo["cve_ent"] = cuerpo["cve_ent"].astype(int)
    cuerpo["renglon"] = cuerpo["renglon"].astype(int)
    largo = cuerpo.melt(id_vars=["cve_ent", "renglon"], var_name="anio",
                        value_name="valor")
    largo["valor"] = pd.to_numeric(largo["valor"], errors="coerce")
    largo["anio"] = largo["anio"].astype(int)
    return largo


def cargar_sep():
    """Nivel anterior (media superior) y capacidad instalada por entidad.

    Las columnas de la fuente llegan a 2030-2031 porque la SEP publica su propia
    prospectiva. Eso es justo lo que hace usable un driver: el valor futuro no
    hay que inventarlo.
    """
    mat = _hoja_sep("MATRICULA")
    esc = _hoja_sep("ESCUELAS")

    def agrega(largo, renglones, nombre):
        sel = largo[largo["renglon"].isin(np.atleast_1d(renglones))]
        return (sel.groupby(["cve_ent", "anio"], as_index=False)["valor"].sum()
                   .rename(columns={"valor": nombre}))

    piezas = [
        agrega(mat, REN_MEDIA_SUPERIOR, "ms_matricula"),
        agrega(mat, REN_SUPERIOR, "sup_matricula"),
        agrega(esc, REN_SUPERIOR, "escuelas_sup"),
        agrega(esc, REN_MEDIA_SUPERIOR, "ms_escuelas"),
    ]
    out = piezas[0]
    for p in piezas[1:]:
        out = out.merge(p, on=["cve_ent", "anio"], how="outer")
    return out.sort_values(["cve_ent", "anio"]).reset_index(drop=True)


# ---------------------------------------------------------------------- 4. IRS
def cargar_irs():
    """IRS municipal de los cinco censos, en formato largo.

    Las 11 columnas de indicadores son porcentajes con el mismo significado en
    los cinco cortes; se conservan las dos que tienen lectura educativa directa.
    El indice y el grado los recalcula CONEVAL por componentes principales en
    cada censo, asi que los niveles son comparables solo de forma aproximada:
    por eso el ajuste del modulo `rezago` usa el indice como NIVEL estructural
    y el porcentaje de educacion basica incompleta para la tendencia.
    """
    piezas = []
    for anio in ANIOS_IRS:
        ruta = IRS_DIR / f"IRS_entidades_mpios_{anio}.xlsx"
        d = pd.read_excel(ruta, sheet_name="Municipios", header=None, skiprows=6)
        d = d.iloc[:, [2, 4, 7, 5, 16, 17, 18]].copy()
        d.columns = ["clave_mun", "pob_censo", "basica_incompleta", "analfabeta",
                     "irs", "grado_rezago", "lugar_nacional"]
        d = d.dropna(subset=["clave_mun"])
        d["clave_mun"] = pd.to_numeric(d["clave_mun"], errors="coerce")
        d = d.dropna(subset=["clave_mun"])
        d["clave_mun"] = d["clave_mun"].astype(int)
        for c in ["pob_censo", "basica_incompleta", "analfabeta", "irs", "lugar_nacional"]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d["grado_rezago"] = d["grado_rezago"].astype(str).str.strip()
        d["anio"] = anio
        piezas.append(d)
    return pd.concat(piezas, ignore_index=True).sort_values(["clave_mun", "anio"])


# ----------------------------------------------------------------- crosswalk
def construir_crosswalk(conapo):
    """Conecta cada corte geografico del panel con claves INEGI.

    Se saca del propio panel, que ya trae la asignacion a zona metropolitana y
    a region/area Nielsen. Asi cualquier corte de la app -- nacional, region,
    ZM, estado, municipio -- se traduce a un conjunto de municipios (para las
    fuentes municipales) y a un conjunto de entidades (para las estatales).
    """
    panel = pd.read_parquet(PANEL, columns=[
        "Estado", "Municipio", "Zona_Metropolitana", "Nielsen_Region", "Nielsen_Area"])
    geo = panel.astype(str).drop_duplicates().reset_index(drop=True)
    geo["estado_norm"] = geo["Estado"].map(_estado)
    geo["municipio_norm"] = geo["Municipio"].map(normalizar)
    pares = [ALIAS_MUNICIPIO.get(k, k)
             for k in zip(geo["estado_norm"], geo["municipio_norm"])]
    geo["estado_norm"], geo["municipio_norm"] = zip(*pares)

    ref = (conapo[["clave_mun", "cve_ent", "estado_norm", "municipio_norm"]]
           .drop_duplicates(subset=["estado_norm", "municipio_norm"]))
    out = geo.merge(ref, on=["estado_norm", "municipio_norm"], how="left")

    sin = out["clave_mun"].isna().sum()
    if sin:
        print(f"  aviso: {sin} de {len(out)} municipios del panel sin clave INEGI")
        print("  " + ", ".join(
            f"{r.Estado}/{r.Municipio}" for r in out[out["clave_mun"].isna()]
            .head(8).itertuples()))
    return out


def main():
    DATOS.mkdir(parents=True, exist_ok=True)

    print("CONAPO: proyecciones municipales...")
    conapo = cargar_conapo()
    conapo.to_parquet(MUN, index=False)
    print(f"  {conapo['clave_mun'].nunique():,} municipios x "
          f"{conapo['anio'].min()}-{conapo['anio'].max()}")

    print("SEP: serie historica por entidad...")
    sep = cargar_sep()
    sep.to_parquet(ENT, index=False)
    print(f"  32 entidades x {sep['anio'].min()}-{sep['anio'].max()} "
          f"(incluye prospectiva SEP)")

    print("CONEVAL: indice de rezago social...")
    irs = cargar_irs()
    irs.to_parquet(IRS, index=False)
    print(f"  {irs['clave_mun'].nunique():,} municipios x {len(ANIOS_IRS)} censos")

    print("Crosswalk geografico desde el panel...")
    cw = construir_crosswalk(conapo)
    cw.to_parquet(CROSSWALK, index=False)
    print(f"  {len(cw):,} combinaciones geograficas, "
          f"{cw['clave_mun'].notna().mean() * 100:.1f}% con clave")

    for s in SALIDAS:
        print(f"guardado {s.relative_to(RAIZ)}  ({s.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
