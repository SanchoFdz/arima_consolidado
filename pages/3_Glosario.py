# -*- coding: utf-8 -*-
"""Glosario: que municipios integran cada zona metropolitana y que estados cada
region Nielsen.

Es solo eso. No hay controles ni modelo: los dos cortes geograficos que la app
ofrece son agregados cuya definicion no se ve en pantalla, y el numero de una ZM
no se puede discutir sin saber que municipios entraron. Aqui esta la definicion,
y nada mas.
"""
import pandas as pd
import streamlit as st

from comun import SIN_ZM, cargar
from preparar_datos import normalizar
from zonas import ZONAS, pares_zona

st.set_page_config(page_title="Glosario", page_icon="📖", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 2.6rem; max-width: 1240px;}
  h1 {font-size: 2.05rem !important; font-weight: 650 !important;
      letter-spacing: -0.021em; color: #0b0b0b; margin-bottom: .15rem;}
  h3 {font-size: 1.02rem !important; font-weight: 600 !important;
      letter-spacing: -0.008em; color: #0b0b0b;}
  .sub {color: #52514e; font-size: .88rem; line-height: 1.5; margin-bottom: 1.6rem;}
  [data-testid="stMetric"] {background: #fafaf8; border: 1px solid #ececea;
      border-radius: 10px; padding: .85rem 1rem;}
  [data-testid="stMetricLabel"] p {font-size: .76rem !important; color: #52514e;
      text-transform: uppercase; letter-spacing: .045em; font-weight: 550;}
  [data-testid="stMetricValue"] {font-size: 1.62rem; font-weight: 620;
      letter-spacing: -0.018em;}
  hr {margin: 1.4rem 0; border-color: #ececea;}
</style>
""", unsafe_allow_html=True)

st.title("Glosario")
st.markdown(
    '<div class="sub">Que hay exactamente detras de cada corte geografico: los '
    'municipios de cada zona metropolitana y los estados de cada region Nielsen.</div>',
    unsafe_allow_html=True)

df = cargar()


def plural(n, singular, plural_):
    return f"{n} {singular if n == 1 else plural_}"


@st.cache_data(show_spinner=False)
def municipios_con_oferta(df):
    """Claves (estado, municipio) normalizadas que aparecen en el panel ANUIES."""
    pares = df[["Estado", "Municipio"]].astype(str).drop_duplicates()
    return {(normalizar(e), normalizar(m)) for e, m in pares.itertuples(index=False)}


@st.cache_data(show_spinner=False)
def tabla_zonas(df):
    con_oferta = municipios_con_oferta(df)
    ni = (df[df["ciclo"].astype(str) == df["ciclo"].astype(str).max()]
          .groupby("Zona_Metropolitana", observed=True)["NI"].sum())
    filas = []
    for zona, estado, municipio in pares_zona():
        filas.append({
            "Zona metropolitana": zona,
            "Estado": estado,
            "Municipio": municipio,
            "Tiene oferta de educacion superior":
                (normalizar(estado), normalizar(municipio)) in con_oferta,
        })
    detalle = pd.DataFrame(filas)
    resumen = (detalle.groupby("Zona metropolitana")
               .agg(Estados=("Estado", lambda s: " · ".join(sorted(set(s)))),
                    Municipios=("Municipio", "size"),
                    Con_oferta=("Tiene oferta de educacion superior", "sum"))
               .reset_index())
    col_ni = f"NI {df['ciclo'].astype(str).max()}"
    resumen[col_ni] = resumen["Zona metropolitana"].map(ni).fillna(0).astype(int)
    resumen = resumen.rename(columns={"Con_oferta": "Con oferta"})
    return detalle, resumen.sort_values(col_ni, ascending=False)


@st.cache_data(show_spinner=False)
def tabla_nielsen(df):
    pares = (df[["Nielsen_Region", "Nielsen_Area", "Estado"]].astype(str)
             .drop_duplicates())
    ni = df.groupby("Nielsen_Region", observed=True)["NI"].sum()
    t = (pares.groupby(["Nielsen_Region", "Nielsen_Area"])["Estado"]
         .agg(Estados=lambda s: " · ".join(sorted(s)), Cuantos="size")
         .reset_index()
         .rename(columns={"Nielsen_Region": "Region Nielsen",
                          "Nielsen_Area": "Area Nielsen",
                          "Cuantos": "Estados (n)"}))
    col_ni = f"NI acumulado {int(df['anio'].min())}-{int(df['anio'].max()) + 1}"
    t[col_ni] = t["Region Nielsen"].map(ni).fillna(0).astype(int)
    return t.sort_values(col_ni, ascending=False)


detalle_zm, resumen_zm = tabla_zonas(df)
COL_NI_ZM = next(c for c in resumen_zm.columns if c.startswith("NI "))
nielsen = tabla_nielsen(df)

zm, nl = st.tabs(["Zonas metropolitanas", "Regiones Nielsen"])

# ------------------------------------------------------- zonas metropolitanas
with zm:
    st.markdown(
        '<div class="sub">Delimitacion <b>Metropolis de Mexico 2020</b> '
        '(SEDATU · CONAPO · INEGI). Es la lista oficial completa: se usa entera, '
        'tenga o no cada municipio una IES. El joven que vive en un municipio sin '
        'universidad se matricula en el de al lado, asi que recortar la zona a los '
        'municipios con oferta inflaria la tasa de captacion.</div>',
        unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Zonas", len(ZONAS))
    c2.metric("Municipios que las integran", len(detalle_zm))
    c3.metric("Con oferta en la base",
              int(detalle_zm["Tiene oferta de educacion superior"].sum()),
              f"{len(detalle_zm) - int(detalle_zm['Tiene oferta de educacion superior'].sum())} "
              "sin IES aportan cero", delta_color="off")

    st.subheader("Resumen")
    st.dataframe(resumen_zm, use_container_width=True, hide_index=True)

    st.subheader("Municipios de cada zona")
    busca = st.text_input("Buscar municipio o zona", placeholder="p. ej. Tizayuca, Toluca…")
    vista = detalle_zm
    if busca:
        b = normalizar(busca)
        vista = detalle_zm[
            detalle_zm["Municipio"].map(lambda v: b in normalizar(v))
            | detalle_zm["Zona metropolitana"].map(lambda v: b in normalizar(v))
            | detalle_zm["Estado"].map(lambda v: b in normalizar(v))]
        if vista.empty:
            st.caption("Sin coincidencias. Ese municipio no pertenece a ninguna "
                       f"de las {len(ZONAS)} zonas: en la app cae en «{SIN_ZM}».")

    for zona in resumen_zm["Zona metropolitana"]:
        bloque = vista[vista["Zona metropolitana"] == zona]
        if bloque.empty:
            continue
        r = resumen_zm[resumen_zm["Zona metropolitana"] == zona].iloc[0]
        with st.expander(f"**{zona}** — {plural(r['Municipios'], 'municipio', 'municipios')}"
                         f" · {r['Estados']} · {COL_NI_ZM}: {r[COL_NI_ZM]:,}",
                         expanded=bool(busca)):
            for estado, g in bloque.groupby("Estado"):
                nombres = [m if oferta else f"{m} ○" for m, oferta in
                           zip(g["Municipio"], g["Tiene oferta de educacion superior"])]
                st.markdown(f"**{estado}** ({len(g)}) — " + ", ".join(sorted(nombres)))
            if not bloque["Tiene oferta de educacion superior"].all():
                st.caption("○ = municipio de la delimitacion sin oferta de educacion "
                           "superior en la base ANUIES. Cuenta para la poblacion del "
                           "corte, aporta cero al nuevo ingreso.")

    st.download_button(
        "Descargar el catalogo de zonas (CSV)",
        detalle_zm.to_csv(index=False).encode("utf-8-sig"),
        file_name="zonas_metropolitanas_municipios.csv", mime="text/csv")

# ------------------------------------------------------------ regiones nielsen
with nl:
    st.markdown(
        '<div class="sub">Las regiones Nielsen son agrupaciones de estados '
        'completos: ningun estado se parte entre dos regiones, y cada region '
        'corresponde a exactamente un area. Vienen asignadas en la fuente ANUIES '
        'agregada, no se calculan aqui.</div>',
        unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    c1.metric("Regiones", nielsen["Region Nielsen"].nunique())
    c2.metric("Estados cubiertos", int(nielsen["Estados (n)"].sum()))

    st.dataframe(nielsen, use_container_width=True, hide_index=True,
                 column_config={"Estados": st.column_config.TextColumn(width="large")})

    for _, r in nielsen.iterrows():
        st.markdown(f"**{r['Region Nielsen']}** · {r['Area Nielsen']} "
                    f"({plural(r['Estados (n)'], 'estado', 'estados')}) — {r['Estados']}")

    faltan = {
        "AGUASCALIENTES", "BAJA CALIFORNIA", "BAJA CALIFORNIA SUR", "CAMPECHE",
        "CHIAPAS", "CHIHUAHUA", "CIUDAD DE MÉXICO", "COAHUILA", "COLIMA",
        "DURANGO", "GUANAJUATO", "GUERRERO", "HIDALGO", "JALISCO", "MICHOACÁN",
        "MORELOS", "MÉXICO", "NAYARIT", "NUEVO LEÓN", "OAXACA", "PUEBLA",
        "QUERÉTARO", "QUINTANA ROO", "SAN LUIS POTOSÍ", "SINALOA", "SONORA",
        "TABASCO", "TAMAULIPAS", "TLAXCALA", "VERACRUZ", "YUCATÁN", "ZACATECAS",
    } - set(df["Estado"].astype(str).unique())
    if faltan:
        st.info(
            f"**{', '.join(sorted(faltan))}** no aparece en el agregado ANUIES que "
            "alimenta la app, asi que no esta en ninguna region: los 31 estados de "
            "arriba son todo lo que hay. Cualquier total llamado «nacional» excluye "
            "ese estado.")

    st.download_button(
        "Descargar el catalogo Nielsen (CSV)",
        nielsen.to_csv(index=False).encode("utf-8-sig"),
        file_name="regiones_nielsen_estados.csv", mime="text/csv")
