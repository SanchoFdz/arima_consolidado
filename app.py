# -*- coding: utf-8 -*-
"""Tendencias de Nuevo Ingreso — front para el equipo de finanzas.

Se elige un corte (geografico + nivel + modalidad + area) y la app devuelve la
serie historica 2014-2025 y la proyeccion lista para pegar en un modelo.
"""
from io import BytesIO
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import contexto as ctx
import metodos
import taxonomia as tax
import pronostico as pr
from comun import (CORTES, METRICAS, SIN_ZM, aplicar_filtros, cargar,
                   etiqueta_modalidades, opciones)

st.set_page_config(page_title="Tendencias de Nuevo Ingreso", page_icon="📈", layout="wide")


@st.cache_data(show_spinner="Calculando proyeccion...")
def serie_y_modelo(df, filtros, metrica, horizonte, nivel, motor):
    sub = aplicar_filtros(df, filtros)
    serie = sub.groupby("anio", observed=True)[metrica].sum().sort_index()
    if serie.empty:
        return serie, None, None
    # El catalogo ANUIES cambio en 2017-2018 y las subareas y areas especificas
    # no estan homologadas: una categoria que solo existe en uno de los dos
    # catalogos trae ceros en las puntas que no son ceros de mercado. Se recortan
    # antes de proyectar, porque el extrapolador no sabe distinguirlos.
    serie, aviso_catalogo = tax.recortar(serie)
    return serie, pr.proyectar(serie, horizonte, nivel, motor), aviso_catalogo


def tabla_salida(res, metrica_nombre):
    hist = pd.DataFrame({
        "ciclo": [f"{a}-{a + 1}" for a in res.historico.index],
        "tipo": "historico",
        metrica_nombre: res.historico.values,
        # float("nan") y no None: con None la columna queda de tipo object y el
        # concat con la parte proyectada (float) tiene que adivinar el dtype.
        # pandas ya avisa que va a dejar de adivinarlo.
        "inferior": float("nan"),
        "superior": float("nan"),
    })
    proy = pd.DataFrame({
        "ciclo": res.proyeccion["ciclo"],
        "tipo": "proyeccion",
        metrica_nombre: res.proyeccion["pronostico"].round(0),
        "inferior": res.proyeccion["inferior"].round(0),
        "superior": res.proyeccion["superior"].round(0),
    })
    salida = pd.concat([hist, proy], ignore_index=True)
    salida["var_%"] = (salida[metrica_nombre].pct_change() * 100).round(2)
    return salida


# Paleta: un solo hue (azul slot 1) validado contra la superficie clara. Observado
# y proyectado son la MISMA serie en dos estados, asi que comparten color y se
# distinguen por trazo y por etiqueta directa, no por un segundo hue.
SURFACE = "#ffffff"
AZUL = "#2a78d6"
AZUL_TENUE = "rgba(42, 120, 214, 0.10)"
TINTA = "#0b0b0b"
TINTA_SUAVE = "#52514e"
GRIS_TENUE = "#e8e8e5"
ZONA_FUTURA = "rgba(11, 11, 10, 0.028)"


def formato_corto(v):
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M".replace(".00M", "M")
    if v >= 10_000:
        return f"{v / 1_000:.0f}k"
    return f"{v:,.0f}"


def grafica(res, etiqueta, metrica_nombre, confianza):
    hist_x = [f"{a}-{a + 1}" for a in res.historico.index]
    proy_x = list(res.proyeccion["ciclo"])
    eje = hist_x + proy_x

    # La proyeccion arranca del ultimo punto observado para que no quede un hueco.
    puente_x = [hist_x[-1]] + proy_x
    puente_y = [float(res.historico.iloc[-1])] + list(res.proyeccion["pronostico"])
    inf = [float(res.historico.iloc[-1])] + list(res.proyeccion["inferior"])
    sup = [float(res.historico.iloc[-1])] + list(res.proyeccion["superior"])

    fig = go.Figure()

    # Region futura: un lavado apenas perceptible que separa lo medido de lo inferido.
    fig.add_vrect(
        x0=len(hist_x) - 1, x1=len(eje) - 0.5, fillcolor=ZONA_FUTURA,
        line_width=0, layer="below",
        annotation_text=f"<b>Proyección</b> {proy_x[0]} a {proy_x[-1]}",
        annotation_position="top",
        annotation=dict(font=dict(size=11, color=TINTA_SUAVE), yshift=8))

    fig.add_trace(go.Scatter(
        x=puente_x + puente_x[::-1], y=sup + inf[::-1], mode="lines",
        fill="toself", fillcolor=AZUL_TENUE, line=dict(width=0),
        hoverinfo="skip", showlegend=False, name="Intervalo"))

    fig.add_trace(go.Scatter(
        x=hist_x, y=res.historico.values, mode="lines", name="Observado",
        line=dict(color=AZUL, width=2, shape="linear"),
        hovertemplate="%{x}<br><b>%{y:,.0f}</b> observado<extra></extra>"))

    fig.add_trace(go.Scatter(
        x=puente_x, y=puente_y, mode="lines", name="Proyectado",
        line=dict(color=AZUL, width=2, dash="dot"),
        hovertemplate="%{x}<br><b>%{y:,.0f}</b> proyectado<extra></extra>"))

    # Marcadores solo en los dos puntos que se leen: el ultimo dato real y el
    # final de la proyeccion. Anillo del color de fondo para que no se peguen.
    for x, y in [(hist_x[-1], float(res.historico.iloc[-1])),
                 (proy_x[-1], float(res.proyeccion["pronostico"].iloc[-1]))]:
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(color=AZUL, size=9, line=dict(color=SURFACE, width=2))))

    # Etiquetas directas: nombran cada area en el grafico, en vez de una caja de
    # leyenda que obliga a emparejar colores.
    tope = max(list(res.historico.values) + sup)
    piso = min(list(res.historico.values) + inf)
    holgura = (tope - piso) or 1

    # Se agregan una por una: pasarlas juntas a update_layout las fusiona con la
    # anotacion que add_vrect ya dejo puesta, y la primera se pierde.
    anotaciones = [
        dict(x=hist_x[len(hist_x) // 3], y=res.historico.iloc[len(hist_x) // 3],
             text="<b>Observado</b><br>2014-2015 a 2024-2025", showarrow=False,
             yshift=-34, font=dict(size=11, color=TINTA_SUAVE), align="center"),
        # Anclada por dentro del borde superior de la banda, a media anchura: asi
        # queda siempre dentro del area de trazo aunque el limite inferior llegue a
        # cero, y lejos de los valores etiquetados a la derecha.
        dict(x=proy_x[len(proy_x) // 2],
             y=float(res.proyeccion["superior"].iloc[len(proy_x) // 2]),
             text=f"<b>Intervalo {confianza}%</b>", showarrow=False,
             yshift=-15, font=dict(size=11, color=TINTA_SUAVE)),
        dict(x=hist_x[-1], y=float(res.historico.iloc[-1]),
             text=f"<b>{formato_corto(float(res.historico.iloc[-1]))}</b>",
             showarrow=False, yshift=18, xshift=-18,
             font=dict(size=12, color=TINTA)),
        dict(x=proy_x[-1], y=float(res.proyeccion["pronostico"].iloc[-1]),
             text=f"<b>{formato_corto(float(res.proyeccion['pronostico'].iloc[-1]))}</b>"
                  "<br><span style='font-size:10px'>proyectado</span>",
             showarrow=False, yshift=-24, font=dict(size=12, color=AZUL)),
    ]

    fig.update_xaxes(categoryorder="array", categoryarray=eje,
                     showgrid=False, showline=True, linecolor=GRIS_TENUE,
                     ticks="outside", tickcolor=GRIS_TENUE, ticklen=4,
                     tickfont=dict(size=11, color=TINTA_SUAVE), tickangle=-45)
    fig.update_yaxes(showgrid=True, gridcolor=GRIS_TENUE, gridwidth=1,
                     zeroline=False, showline=False,
                     tickfont=dict(size=11, color=TINTA_SUAVE),
                     tickformat="~s", nticks=7)

    fig.update_layout(
        height=470, margin=dict(l=10, r=30, t=92, b=90),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        title=dict(text=f"<b>{metrica_nombre}</b><br>"
                        f"<span style='font-size:13px;color:{TINTA_SUAVE}'>{etiqueta}</span>",
                   font=dict(size=17, color=TINTA), x=0, xanchor="left", y=0.96),
        showlegend=False, hovermode="x unified",
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRIS_TENUE,
                        font=dict(color=TINTA, size=12)),
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif"),
    )
    for a in anotaciones:
        fig.add_annotation(**a)
    return fig



@st.cache_data(show_spinner=False)
def contexto_externo(filtros, serie, anios, cagr_proyectado):
    return ctx.lectura(filtros, serie, anios, cagr_proyectado)


def bloque_contexto(c):
    """Contra que corre la proyeccion. Se lee, no se configura.

    Los datos externos no entran al numero --- se probo y no mejoro el error, ver
    el docstring de contexto.py --- pero si dicen lo que el numero supone. La
    divergencia va primero porque es lo unico que puede cambiar una decision:
    una proyeccion que crece mientras la cohorte cae es un supuesto de ganancia
    de participacion, y conviene que sea a proposito.
    """
    if c is None:
        return
    st.markdown("---")
    st.subheader("Contra qué corre esta proyección")

    if c.get("divergencia"):
        st.warning(c["divergencia"])

    d1, d2, d3 = st.columns(3)
    d1.metric(f"Población 12-29 del corte, {c['anio_fin']}",
              formato_corto(c["pob_fin"]),
              f"{c['cagr_pob_%']:+.2f}% anual" if c["cagr_pob_%"] is not None else None,
              help=f"CONAPO, proyecciones municipales. Suma de {c['municipios']} "
                   "municipios del corte, incluidos los que no tienen oferta: el "
                   "joven que vive donde no hay universidad se matricula en la de "
                   "al lado.")
    d2.metric("Tasa de captación", f"{c['tasa_captacion_x1000']:.1f} por mil",
              help="Nuevo ingreso del corte por cada 1,000 jóvenes de 12 a 29 años "
                   "que viven en él.")
    if c.get("cambio_2040_%") is not None:
        d3.metric("Cohorte joven a 2040", f"{c['cambio_2040_%']:+.1f}%",
                  help="Cambio de la población de 12 a 29 años del corte entre hoy "
                       "y 2040, según CONAPO. La proyección del panel no lo "
                       "incorpora: su horizonte llega a 5 ciclos.")

    for linea in (ctx.linea_demografia(c), ctx.linea_rezago(c)):
        if linea:
            st.caption(linea)


# ------------------------------------------------------------------ sidebar
df = cargar()

st.sidebar.header("Corte")
corte = st.sidebar.selectbox("Nivel geografico", list(CORTES))
col_geo = CORTES[corte]
filtros = {}
etiqueta_geo = "Nacional"

if col_geo:
    if col_geo == "Municipio":
        estado = st.sidebar.selectbox("Estado", opciones(df, "Estado"))
        filtros["Estado"] = [estado]
        muns = opciones(df[df["Estado"].astype(str) == estado], "Municipio")
        municipio = st.sidebar.selectbox("Municipio", muns)
        filtros["Municipio"] = [municipio]
        etiqueta_geo = f"{municipio}, {estado}"
    else:
        vals = opciones(df, col_geo)
        if col_geo == "Zona_Metropolitana":
            vals = [v for v in vals if v != SIN_ZM]
        elegido = st.sidebar.selectbox(corte, vals)
        filtros[col_geo] = [elegido]
        etiqueta_geo = elegido

st.sidebar.header("Segmento")
niveles = st.sidebar.multiselect("Nivel educativo", opciones(df, "Nivel_educativo"),
                                 help="Vacio = todos los niveles sumados")
if niveles:
    filtros["Nivel_educativo"] = niveles

modalidades = st.sidebar.multiselect(
    "Modalidad", opciones(df, "Modalidad"),
    help="Vacio = todas las modalidades sumadas. Se pueden combinar varias: "
         "marcar NO ESCOLARIZADA y MIXTA a la vez es lo que antes era el preset "
         "'Online'.")
if modalidades:
    filtros["Modalidad"] = modalidades

# Disciplina: dos niveles, los dos con serie continua de 11 ciclos. No son las
# columnas crudas del panel, son los grupos comparables de concordancia.py.
campos = st.sidebar.multiselect("Campo de conocimiento", opciones(df, "Campo"),
                                help="Vacio = todos los campos sumados")
if campos:
    filtros["Campo"] = campos
disponibles = opciones(aplicar_filtros(df, {"Campo": campos}) if campos else df,
                       "Grupo_comparable")
grupos = st.sidebar.multiselect(
    "Carrera o grupo de carreras", disponibles,
    help="69 grupos comparables entre los dos catalogos ANUIES. Cada uno junta "
         "las categorias viejas y nuevas que se corresponden, porque el catalogo "
         "cambio en 2017-2018: 'Desarrollo de software' no existia antes de 2017 "
         "y 'Ciencias de la computacion' desaparecio ese ano. Agrupadas, la serie "
         "cubre los 11 ciclos.")
if grupos:
    filtros["Grupo_comparable"] = grupos

st.sidebar.header("Modelo")
metrica_nombre = st.sidebar.selectbox("Metrica a proyectar", list(METRICAS))
metrica = METRICAS[metrica_nombre]
horizonte = st.sidebar.slider("Ciclos a proyectar", 1, 5, 3)
confianza = st.sidebar.select_slider("Confianza del intervalo", [50, 80, 95], value=80)
motor = st.sidebar.selectbox(
    "Metodo", list(metodos.MOTORES), index=0,
    help="El ensemble gana el backtest sobre 110 segmentos. El ARIMA esta "
         "disponible para comparar, pero ahi quedo por debajo del naive: con 11 "
         "observaciones anuales no tiene estructura que identificar.")

# --------------------------------------------------------------------- main
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
  [data-testid="stSidebar"] {background: #fafaf8; border-right: 1px solid #ececea;}
  [data-testid="stSidebar"] h2 {font-size: .78rem !important; font-weight: 600;
      text-transform: uppercase; letter-spacing: .07em; color: #52514e;
      margin-top: 1.1rem;}
  .stDownloadButton button {border-radius: 8px; font-weight: 550;}
  hr {margin: 1.4rem 0; border-color: #ececea;}
</style>
""", unsafe_allow_html=True)

st.title("Tendencias de Nuevo Ingreso")
st.markdown(
    '<div class="sub">Agregado ANUIES, ciclos 2014-2015 a 2024-2025 &nbsp;·&nbsp; '
    'carreras agrupadas para ser comparables entre los dos catálogos ANUIES &nbsp;·&nbsp; '
    'zonas metropolitanas según Metrópolis de México 2020</div>',
    unsafe_allow_html=True)

serie, res, aviso_catalogo = serie_y_modelo(df, filtros, metrica, horizonte,
                                            confianza / 100, motor)
if aviso_catalogo:
    st.info(aviso_catalogo)

if serie.empty or serie.sum() == 0:
    st.warning("No hay datos para esta combinacion de filtros.")
    st.stop()
if res is None:
    st.warning("La serie es demasiado corta o dispersa para proyectarla.")
    st.line_chart(serie)
    st.stop()

# El corte mas fino primero: si filtraste una carrera, eso es lo que estas
# viendo, y ponerle de titulo el campo entero hace creer que es otra cosa.
etiqueta_mod = etiqueta_modalidades(modalidades)
segmento = " · ".join([etiqueta_geo] +
                      ([", ".join(niveles)] if niveles else []) +
                      ([etiqueta_mod] if etiqueta_mod else []) +
                      ([", ".join(grupos)] if grupos else
                       [", ".join(campos)] if campos else []))

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{metrica_nombre} 2024-2025", f"{int(serie.iloc[-1]):,}")
ultimo = res.proyeccion.iloc[-1]
c2.metric(f"Proyectado {ultimo['ciclo']}", f"{int(ultimo['pronostico']):,}",
          f"{res.cagr_proyectado:+.2f}% anual" if res.cagr_proyectado is not None else None)
c3.metric("CAGR historico", f"{res.cagr_historico:+.2f}%" if res.cagr_historico is not None else "n/d")
SEMAFORO = {"alta": "🟢 Alta", "media": "🟡 Media", "baja": "🔴 Baja"}
c4.metric("Confiabilidad", SEMAFORO[res.confiabilidad],
          f"error {res.mape_backtest:.1f}%" if res.mape_backtest is not None else None,
          help="Error promedio al predecir ciclos ya conocidos, con origen movil. "
               "Alta: hasta 8%. Media: hasta 15%. Baja: arriba de 15% o serie muy rala.")

for aviso in res.avisos:
    st.warning(aviso)

# Red de seguridad: los grupos comparables son continuos por construccion, pero
# un cruce (grupo x zona chica x modalidad) puede seguir teniendo un salto raro
# en 2017. Si lo tiene, se dice.
quiebre = tax.quiebre_de_catalogo(serie)
if quiebre:
    severidad, texto = quiebre
    (st.warning if severidad == "alto" else st.info)(texto)

st.plotly_chart(grafica(res, segmento, metrica_nombre, confianza), use_container_width=True)

contexto = contexto_externo(filtros, serie, list(res.proyeccion["anio"]),
                            res.cagr_proyectado)
bloque_contexto(contexto)

salida = tabla_salida(res, metrica_nombre)
st.markdown("---")
izq, der = st.columns([3, 2])
with izq:
    st.subheader("Serie completa")
    st.dataframe(salida, use_container_width=True, hide_index=True)
with der:
    st.subheader("Modelo")
    linea = f"**{res.motor}** · intervalo al {confianza}%"
    if res.cobertura_real is not None:
        linea += f" (cobertura real medida: {res.cobertura_real * 100:.0f}%)"
    st.write(linea)
    if res.mase_backtest is not None:
        st.write(f"MASE {res.mase_backtest:.2f} — "
                 + ("mejor" if res.mase_backtest < 1 else "peor")
                 + " que repetir el ultimo valor")
    st.caption(
        "El intervalo no sale de la formula del modelo: sale de los errores que este "
        "metodo cometio en backtest sobre 110 segmentos reales. Para un escenario "
        "conservador usa el limite inferior; para el base, el punto.")
    st.download_button("Descargar CSV", salida.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"tendencia_{metrica}_{etiqueta_geo[:30].replace(' ', '_')}.csv",
                       mime="text/csv", use_container_width=True)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as xls:
        salida.to_excel(xls, index=False, sheet_name="proyeccion")
        pd.DataFrame({"campo": ["segmento", "metrica", "metodo", "confiabilidad",
                                "MAPE_backtest_%", "MASE_backtest", "nivel_intervalo_%",
                                "cobertura_real_%", "CAGR_historico_%", "CAGR_proyectado_%"],
                      "valor": [segmento, metrica_nombre, res.motor, res.confiabilidad,
                                res.mape_backtest, res.mase_backtest, confianza,
                                (res.cobertura_real * 100) if res.cobertura_real else None,
                                res.cagr_historico, res.cagr_proyectado]}
                     ).to_excel(xls, index=False, sheet_name="ficha")
        if contexto:
            campos = {
                "municipios_del_corte": contexto["municipios"],
                f"poblacion_12_29_{contexto['anio_base']}": contexto["pob_base"],
                f"poblacion_12_29_{contexto['anio_fin']}": contexto["pob_fin"],
                "CAGR_poblacion_12_29_%": contexto["cagr_pob_%"],
                "poblacion_12_29_2040": contexto.get("pob_2040"),
                "cambio_cohorte_a_2040_%": contexto.get("cambio_2040_%"),
                "tasa_captacion_x1000": contexto["tasa_captacion_x1000"],
                "brecha_proyeccion_vs_demografia_pp": contexto.get("brecha_pp"),
            }
            if contexto.get("rezago"):
                r = contexto["rezago"]
                campos.update({
                    "rezago_grado_2020": r["grado_rezago"],
                    "rezago_basica_incompleta_%": r["basica_incompleta"],
                    "rezago_basica_incompleta_2000_%": r["basica_incompleta_2000"],
                })
            pd.DataFrame({"campo": list(campos), "valor": list(campos.values())}
                         ).to_excel(xls, index=False, sheet_name="contexto")
    st.download_button("Descargar Excel", buffer.getvalue(),
                       file_name=f"tendencia_{metrica}_{etiqueta_geo[:30].replace(' ', '_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
