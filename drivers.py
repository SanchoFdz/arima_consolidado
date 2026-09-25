# -*- coding: utf-8 -*-
"""Traduce un corte de la app en una serie-driver anual con valores futuros.

La idea del driver es la unica forma honesta de meter datos externos a una serie
de 11 puntos: en vez de estimar coeficientes que no alcanzan los grados de
libertad, se proyecta la TASA (NI entre driver) y se reescala por el valor
futuro del driver, que ya es conocido -- CONAPO publica poblacion municipal a
2040 y la SEP publica matricula de media superior a 2030-31. Cuesta cero
parametros extra y la tasa suele ser mas estable que el nivel, porque le quitas
encima el crecimiento demografico.

Consistencia geografica: todo driver se arma a nivel municipio y luego se suma
sobre los municipios del corte. Las fuentes estatales (SEP) se reparten entre
los municipios de su entidad con la participacion municipal en la poblacion
12-29. Para cortes Nacional y Estado el reparto es exacto por construccion; para
zona metropolitana y region Nielsen es un supuesto, y esta ahi porque la
alternativa -- sumar entidades completas para una ZM que cruza tres estados --
mide una cosa distinta de la que se proyecta.
"""
from pathlib import Path

import pandas as pd

from externos import ALIAS_MUNICIPIO, _estado, normalizar
from zonas import pares_zona

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"

COLS_GEO = ["Estado", "Municipio", "Zona_Metropolitana",
            "Nielsen_Region", "Nielsen_Area"]

# nombre visible -> (columna interna, rezago en anios, texto de la unidad)
DRIVERS = {
    "Ninguno (solo la serie historica)": None,
    "Poblacion 12-29 anios (CONAPO)": ("pob_12_29", 0, "jovenes 12-29"),
    "Poblacion total (CONAPO)": ("pob_total", 0, "habitantes"),
    "Matricula de media superior, ciclo anterior (SEP)": ("ms_matricula", 1, "alumnos de EMS"),
    "Escuelas de educacion superior (SEP)": ("escuelas_sup", 0, "escuelas"),
}

DRIVER_DEFAULT = "Poblacion 12-29 anios (CONAPO)"


def _cargar(nombre):
    ruta = DATOS / nombre
    if not ruta.exists():
        raise FileNotFoundError(
            f"Falta {ruta.name}. Corre primero: python externos.py")
    return pd.read_parquet(ruta)


class Externos:
    """Panel externo municipalizado, 1990-2040, con cache en memoria."""

    def __init__(self):
        mun = _cargar("externos_municipio.parquet")
        ent = _cargar("externos_entidad.parquet")
        self.crosswalk = _cargar("crosswalk_geo.parquet")

        # Participacion de cada municipio en la poblacion 12-29 de su entidad,
        # ano por ano: el reparto de las fuentes estatales.
        mun = mun.copy()
        mun["peso_ent"] = mun["pob_12_29"] / mun.groupby(["cve_ent", "anio"])[
            "pob_12_29"].transform("sum")

        panel = mun.merge(ent, on=["cve_ent", "anio"], how="left")
        for col in ["ms_matricula", "sup_matricula", "escuelas_sup", "ms_escuelas"]:
            panel[col] = panel[col] * panel["peso_ent"]
        self.panel = panel
        self._armar_universos(mun)

    def _armar_universos(self, mun):
        """Conjuntos de municipios por corte, sobre el universo completo del pais.

        Ojo con la diferencia: el panel educativo solo contiene los municipios
        que tienen oferta de educacion superior (829 de 2,475). Pero la demanda
        no vive solo ahi -- los jovenes de un municipio sin IES se matriculan en
        el de al lado. Asi que el driver de un estado, de una region o de una
        zona metropolitana se arma con TODOS sus municipios, no con los que
        tienen escuelas. Solo el corte por municipio se queda con el suyo.
        """
        ref = mun[["clave_mun", "estado_norm", "municipio_norm"]].drop_duplicates()
        self.universo_pais = set(ref["clave_mun"].astype(int))
        self.por_nombre = {(e, m): int(c) for c, e, m in ref.itertuples(index=False)}

        self.por_estado = {}
        for estado, grupo in ref.groupby("estado_norm"):
            self.por_estado[estado] = set(grupo["clave_mun"].astype(int))

        # Zona metropolitana: la delimitacion completa (149 municipios), no el
        # subconjunto con oferta.
        self.por_zona, faltan = {}, []
        for zona, estado, municipio in pares_zona():
            k = (_estado(estado), normalizar(municipio))
            k = ALIAS_MUNICIPIO.get(k, k)
            clave = self.por_nombre.get(k)
            if clave is None:
                faltan.append(f"{estado}/{municipio}")
                continue
            self.por_zona.setdefault(zona, set()).add(clave)
        self.zonas_incompletas = faltan

        # Region y area Nielsen son agrupaciones de estados (verificado sobre el
        # crosswalk: ningun estado aparece en dos regiones), asi que se expanden
        # a todos los municipios de esos estados.
        cw = self.crosswalk
        # "Nacional" son los estados que EXISTEN en el panel educativo, no los 32.
        # Hasta sep 2026 la fuente ANUIES no traia Chiapas, y contar su poblacion
        # en el denominador nacional inflaba el universo 4.8% y desinflaba la tasa
        # de captacion en la misma proporcion. Hoy estan los 32; la regla se queda
        # por si una fuente futura vuelve a llegar incompleta.
        estados_panel = {_estado(e) for e in self.crosswalk["Estado"].astype(str)}
        self.todos = set()
        for e in estados_panel:
            self.todos |= self.por_estado.get(e, set())
        self.estados_panel = sorted(estados_panel)
        self.estados_sin_panel = sorted(
            set(self.por_estado) - estados_panel)

        self.por_nielsen = {}
        for col in ["Nielsen_Region", "Nielsen_Area"]:
            for valor, grupo in cw.groupby(col, observed=True):
                estados = {_estado(e) for e in grupo["Estado"]}
                claves = set()
                for e in estados:
                    claves |= self.por_estado.get(e, set())
                self.por_nielsen[(col, str(valor))] = claves

    # ------------------------------------------------------------- geografia
    def claves(self, filtros):
        """Municipios (claves INEGI) que cubre el corte geografico elegido.

        Cada filtro geografico presente se expande a un conjunto de municipios y
        el corte es la interseccion de todos. Sin filtros geograficos, el pais.
        """
        conjuntos, sin_mapear = [], []

        if filtros.get("Municipio"):
            cw = self.crosswalk
            sel = cw[cw["Municipio"].astype(str).isin(
                [str(v) for v in filtros["Municipio"]])]
            if filtros.get("Estado"):
                sel = sel[sel["Estado"].astype(str).isin(
                    [str(v) for v in filtros["Estado"]])]
            conjuntos.append(set(sel["clave_mun"].dropna().astype(int)))
            sin_mapear += [str(r.Municipio) for r in
                           sel[sel["clave_mun"].isna()].itertuples()]
        elif filtros.get("Estado"):
            claves = set()
            for v in filtros["Estado"]:
                claves |= self.por_estado.get(_estado(v), set())
            conjuntos.append(claves)

        if filtros.get("Zona_Metropolitana"):
            claves = set()
            for v in filtros["Zona_Metropolitana"]:
                claves |= self.por_zona.get(str(v), set())
            conjuntos.append(claves)

        for col in ["Nielsen_Region", "Nielsen_Area"]:
            if filtros.get(col):
                claves = set()
                for v in filtros[col]:
                    claves |= self.por_nielsen.get((col, str(v)), set())
                conjuntos.append(claves)

        universo = self.todos
        for c in conjuntos:
            universo = universo & c
        return sorted(universo), sin_mapear

    # ---------------------------------------------------------------- driver
    def serie(self, filtros, driver):
        """Serie anual del driver para el corte, 1990-2040 (o 1991-2031 si va rezagada).

        Devuelve (serie, meta). La serie esta indexada por el ano de la serie
        educativa, ya con el rezago aplicado: si el driver es la matricula de
        media superior del ciclo anterior, el valor en 2024 es la matricula de
        EMS de 2023.
        """
        spec = DRIVERS.get(driver)
        if spec is None:
            return None, {}
        col, rezago, unidad = spec

        claves, sin_mapear = self.claves(filtros)
        if not claves:
            return None, {"aviso": "El corte no se pudo mapear a claves INEGI."}

        sub = self.panel[self.panel["clave_mun"].isin(claves)]
        serie = sub.groupby("anio")[col].sum(min_count=1).dropna().sort_index()
        if serie.empty or (serie <= 0).any():
            return None, {"aviso": f"Sin datos de {driver} para este corte."}

        if rezago:
            serie.index = serie.index + rezago

        meta = {
            "driver": driver,
            "columna": col,
            "unidad": unidad,
            "rezago": rezago,
            "municipios": len(claves),
            "sin_mapear": sin_mapear,
            "estatal": col in ("ms_matricula", "sup_matricula",
                               "escuelas_sup", "ms_escuelas"),
            "anio_min": int(serie.index.min()),
            "anio_max": int(serie.index.max()),
        }
        if sin_mapear:
            meta["aviso"] = ("Sin datos externos para " + ", ".join(sin_mapear[:3])
                             + ": son municipios creados despues de la base CONAPO.")
        return serie, meta


_instancia = None


def externos():
    """Singleton: el panel externo pesa ~1 MB y se arma una sola vez."""
    global _instancia
    if _instancia is None:
        _instancia = Externos()
    return _instancia
