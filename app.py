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
import comun
from comun import (AYUDA_MODALIDAD, CORTES, METRICAS, MODALIDAD_ONLINE, SIN_ZM,
                   aplicar_filtros, cargar, etiqueta_modalidades,
                   normalizar_modalidades, opciones, opciones_modalidad)

st.set_page_config(page_title="Tendencias de Nuevo Ingreso", page_icon="📈", layout="wide")


@st.cache_data(show_spinner="Calculando proyeccion...")
def serie_y_modelo(df, filtros, metrica, horizonte, nivel, motor):
    """Serie del corte, su recorte, y la proyeccion si la serie da para una.

    Se devuelve tambien la serie SIN recortar, con sus ceros de punta. Ese es el
    eje completo 2014-2015 … 2024-2025 y la vista historica lo necesita: sin el
    no hay forma de dibujar "aqui no habia dato" a escala, solo de dibujar dos
    puntos sueltos como si fueran toda la historia del corte.
    """
    sub = aplicar_filtros(df, filtros)
    completa = sub.groupby("anio", observed=True)[metrica].sum().sort_index()
    if completa.empty:
        return completa, completa, None, None
    # Dos quiebres distintos producen ceros de punta que no son ceros de mercado:
    # el cambio de catalogo de areas de 2017-2018 y el desglose de modalidad de
    # 2023-2024. Se recortan antes de proyectar, porque el extrapolador no sabe
    # distinguir un cero de "no existia". Ver taxonomia.py.
    serie, aviso_recorte = tax.recortar(completa)
    return completa, serie, pr.proyectar(serie, horizonte, nivel, motor), aviso_recorte


@st.cache_data(show_spinner=False)
def serie_del_padre(df, filtros, mods_padre, metrica):
    """Serie continua de la que salio un corte de modalidad nueva.

    Mismo corte en todo lo demas --- geografia, nivel, disciplina ---, cambiando
    solo el filtro de Modalidad. `mods_padre = None` significa quitarlo: el
    padre es el total de todas las modalidades del corte.
    """
    otros = {k: v for k, v in filtros.items() if k != "Modalidad"}
    if mods_padre:
        otros["Modalidad"] = list(mods_padre)
    sub = aplicar_filtros(df, otros)
    return sub.groupby("anio", observed=True)[metrica].sum().sort_index()


@st.cache_data(show_spinner=False)
def derivada_por_share(hijo, padre, horizonte, nivel, motor, etiqueta_padre):
    return pr.derivar_por_share(hijo, padre, horizonte, nivel, motor, etiqueta_padre)


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


def tabla_historica(serie, metrica_nombre, derivada=None):
    """La misma tabla, para un corte que no se puede proyectar directo.

    Antes esta rama no producia tabla ninguna: la app soltaba un `st.line_chart`
    y paraba, asi que un corte de MIXTA no tenia ni tabla ni descarga. Las filas
    historicas existen igual, y si hay derivada se anexa marcada como tal --- la
    columna `tipo` dice "derivado", nunca "proyeccion", para que quien abra el
    CSV sin haber visto la pantalla no la confunda con una proyeccion directa.
    """
    partes = [pd.DataFrame({
        "ciclo": [f"{a}-{a + 1}" for a in serie.index],
        "tipo": "historico",
        metrica_nombre: serie.values.astype(float),
        "inferior": float("nan"),
        "superior": float("nan"),
    })]
    if derivada is not None:
        partes.append(pd.DataFrame({
            "ciclo": derivada.proyeccion["ciclo"],
            "tipo": "derivado",
            metrica_nombre: derivada.proyeccion["pronostico"].round(0),
            "inferior": derivada.proyeccion["inferior"].round(0),
            "superior": derivada.proyeccion["superior"].round(0),
        }))
    salida = pd.concat(partes, ignore_index=True)
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
# Serie padre y tramo no reportado, solo para la vista historica. El gris de la
# serie padre es mas oscuro que GRIS_TENUE (que es el de la retícula) porque
# tiene que leerse como un trazo de datos, no como parte del fondo; y mas claro
# que TINTA_SUAVE porque es contexto detras del azul, no un segundo protagonista.
GRIS_PADRE = "#b8b7b2"
ZONA_SIN_DATO = "rgba(11, 11, 10, 0.045)"


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
    #
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


def grafica_historica(serie, anios_eje, etiqueta, metrica_nombre, padre=None,
                      etiqueta_padre=None, derivada=None, confianza=80):
    """Hermana de `grafica()` para los cortes que no se pueden proyectar directo.

    Misma paleta, misma tipografia, mismos ejes, mismas etiquetas directas. Es
    deliberadamente una funcion hermana y no un `st.line_chart`: lo que cambia
    es que no hay proyeccion propia que dibujar, no que el corte merezca una
    pantalla de segunda. Antes esta rama perdia titulo, metricas, tabla,
    descarga y todo el diseño por no tener seis observaciones.

    Tres decisiones de lectura:

      * **El eje va completo**, 2014-2015 a 2024-2025, aunque la serie tenga dos
        puntos. Recortarlo a los dos ciclos con dato dibuja un segmento que
        ocupa toda la pantalla y sugiere una historia larga que no existe.
      * **El tramo sin dato es una zona gris rotulada**, no una linea en cero ni
        un hueco mudo. Una linea en cero afirma que habia cero alumnos, que es
        falso; un hueco deja al lector suponiendo cual de las dos cosas es.
      * **El padre va detras en gris**, por los 11 ciclos. Es lo que contesta de
        donde salio la serie corta y que proporcion ocupa, que es justo la
        lectura que la modalidad nueva necesita.
    """
    hist_x = [f"{a}-{a + 1}" for a in anios_eje]
    proy_x = list(derivada.proyeccion["ciclo"]) if derivada is not None else []
    eje = hist_x + proy_x

    vivos = [int(a) for a in serie.index]
    i_ini = anios_eje.index(vivos[0])
    prop_x = [f"{a}-{a + 1}" for a in vivos]

    fig = go.Figure()

    # Zona sin dato: solo si de verdad falta tramo por la izquierda.
    if i_ini > 0:
        fig.add_vrect(
            x0=-0.5, x1=i_ini - 0.5, fillcolor=ZONA_SIN_DATO,
            line_width=0, layer="below",
            annotation_text="<b>No reportado por separado</b><br>"
                            f"{hist_x[0]} a {hist_x[i_ini - 1]}",
            annotation_position="top left",
            annotation=dict(font=dict(size=11, color=TINTA_SUAVE), yshift=8))

    # Serie padre: el contexto, detras y en gris.
    if padre is not None and not padre.empty:
        padre_x = [f"{a}-{a + 1}" for a in padre.index]
        fig.add_trace(go.Scatter(
            x=padre_x, y=padre.values, mode="lines", name=etiqueta_padre or "Agregado",
            line=dict(color=GRIS_PADRE, width=2),
            hovertemplate="%{x}<br><b>%{y:,.0f}</b> " + (etiqueta_padre or "agregado")
                          + "<extra></extra>"))

    # Derivada, si la hay: mismo lenguaje que la proyeccion directa (punteado y
    # banda), pero rotulada "derivado" en todas partes.
    if derivada is not None:
        puente_x = [prop_x[-1]] + proy_x
        puente_y = [float(serie.iloc[-1])] + list(derivada.proyeccion["pronostico"])
        inf = [float(serie.iloc[-1])] + list(derivada.proyeccion["inferior"])
        sup = [float(serie.iloc[-1])] + list(derivada.proyeccion["superior"])
        fig.add_vrect(
            x0=len(hist_x) - 1, x1=len(eje) - 0.5, fillcolor=ZONA_FUTURA,
            line_width=0, layer="below",
            annotation_text=f"<b>Derivado</b> {proy_x[0]} a {proy_x[-1]}",
            annotation_position="top right",
            annotation=dict(font=dict(size=11, color=TINTA_SUAVE), yshift=8))
        fig.add_trace(go.Scatter(
            x=puente_x + puente_x[::-1], y=sup + inf[::-1], mode="lines",
            fill="toself", fillcolor=AZUL_TENUE, line=dict(width=0),
            hoverinfo="skip", showlegend=False, name="Intervalo"))
        fig.add_trace(go.Scatter(
            x=puente_x, y=puente_y, mode="lines", name="Derivado",
            line=dict(color=AZUL, width=2, dash="dot"),
            hovertemplate="%{x}<br><b>%{y:,.0f}</b> derivado<extra></extra>"))

    fig.add_trace(go.Scatter(
        x=prop_x, y=serie.values, mode="lines", name="Observado",
        line=dict(color=AZUL, width=2), marker=dict(color=AZUL, size=7),
        hovertemplate="%{x}<br><b>%{y:,.0f}</b> observado<extra></extra>"))

    # Con dos observaciones la linea es un segmento: sin marcadores no se
    # distingue de una anotacion.
    fig.add_trace(go.Scatter(
        x=prop_x, y=serie.values, mode="markers", showlegend=False,
        hoverinfo="skip",
        marker=dict(color=AZUL, size=9, line=dict(color=SURFACE, width=2))))

    valores = list(serie.values) + (list(padre.values) if padre is not None else [])
    if derivada is not None:
        valores += list(derivada.proyeccion["superior"])
    tope, piso = max(valores), min(valores + [0.0])

    anotaciones = [
        dict(x=prop_x[-1], y=float(serie.iloc[-1]),
             text=f"<b>{formato_corto(float(serie.iloc[-1]))}</b>",
             showarrow=False, yshift=18, xshift=-14,
             font=dict(size=12, color=AZUL)),
    ]
    if padre is not None and not padre.empty:
        # A un tercio del eje, donde la serie corta todavia no existe: ahi el
        # gris esta solo y la etiqueta no pisa nada.
        i = max(len(padre) // 3, 0)
        anotaciones.append(dict(
            x=f"{int(padre.index[i])}-{int(padre.index[i]) + 1}",
            y=float(padre.iloc[i]),
            text=f"<b>{etiqueta_padre}</b><br>"
                 "<span style='font-size:10px'>serie de referencia, 11 ciclos</span>",
            showarrow=False, yshift=20,
            font=dict(size=11, color=TINTA_SUAVE), align="left"))
    if derivada is not None:
        anotaciones.append(dict(
            x=proy_x[-1], y=float(derivada.proyeccion["pronostico"].iloc[-1]),
            text=f"<b>{formato_corto(float(derivada.proyeccion['pronostico'].iloc[-1]))}</b>"
                 f"<br><span style='font-size:10px'>derivado · banda {confianza}%</span>",
            showarrow=False, yshift=-26, font=dict(size=12, color=AZUL)))

    fig.update_xaxes(categoryorder="array", categoryarray=eje,
                     range=[-0.5, len(eje) - 0.5],
                     showgrid=False, showline=True, linecolor=GRIS_TENUE,
                     ticks="outside", tickcolor=GRIS_TENUE, ticklen=4,
                     tickfont=dict(size=11, color=TINTA_SUAVE), tickangle=-45)
    fig.update_yaxes(showgrid=True, gridcolor=GRIS_TENUE, gridwidth=1,
                     zeroline=False, showline=False,
                     range=[piso, tope * 1.12],
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


def cta_sin_proyeccion(mods_base, mods_padre, etiqueta_padre, n_ciclos):
    """Que hacer en vez de quedarse mirando una serie de dos puntos.

    Va donde en la proyeccion directa va la banda "Proyección": es el lugar de
    la pantalla al que se va el ojo a buscar el numero, y decir ahi "no hay" sin
    decir "pide esto otro" es dejar el trabajo a medias.
    """
    sel = set(mods_base or [])
    falta = f"Son {n_ciclos} ciclos y el mínimo para proyectar son {pr.MIN_OBS}"
    if sel == {"MIXTA"}:
        return (f"**Para proyectar esta matrícula, pide «{MODALIDAD_ONLINE}»** en el "
                f"filtro de Modalidad —o marca NO ESCOLARIZADA y MIXTA, que es lo "
                f"mismo—. {falta}, porque ANUIES desglosó MIXTA hasta 2023-2024. "
                f"Online sí tiene los 11 ciclos y es la única serie de modalidad "
                f"comparable: 437,882 → 475,083 → 540,301 a nivel nacional.")
    if mods_padre is None and etiqueta_padre:
        return (f"**Para proyectar, quita el filtro de Modalidad** y trabaja sobre "
                f"{etiqueta_padre.lower()}. {falta}: esta modalidad se reporta por "
                f"separado desde 2023-2024 y no hay serie previa que extrapolar.")
    return (f"**No hay proyección para este corte.** {falta}. Amplía el corte "
            f"—menos filtros, o un nivel geográfico más grueso— y vuelve a pedirla.")


def vista_historica(df, filtros, mods_base, serie, serie_completa, metrica,
                    metrica_nombre, segmento, horizonte, nivel, motor, confianza,
                    nombre_archivo):
    """Vista de primera clase para un corte sin proyeccion directa.

    Lo que habia antes era `st.warning` + `st.line_chart` + `st.stop()`: se
    perdian titulo, metricas, tabla, descarga y toda la identidad visual, y la
    pantalla terminaba diciendo menos de lo que los datos dan. Aqui se conserva
    todo lo que si se puede calcular y se quita lo que no --- CAGR sobre dos
    puntos, MAPE, MASE y semaforo de confiabilidad no existen para este corte, y
    ponerlos en "n/d" es llenar la pantalla de tarjetas vacias.
    """
    padre_spec = tax.padre_de_modalidades(mods_base)
    mods_padre, etiqueta_padre, padre = None, None, None
    if padre_spec:
        mods_padre, etiqueta_padre = padre_spec
        padre = serie_del_padre(df, filtros, tuple(mods_padre or ()), metrica)
        if padre.empty or padre.sum() == 0:
            padre, etiqueta_padre = None, None

    derivada, motivo = None, None
    if padre is not None:
        derivada, motivo = derivada_por_share(serie, padre, horizonte, nivel,
                                              motor, etiqueta_padre)

    # -------------------------------------------------------------- metricas
    ultimo_anio = int(serie.index[-1])
    cols = st.columns(3 if padre is not None else 2)
    cols[0].metric(f"{metrica_nombre} {ultimo_anio}-{ultimo_anio + 1}",
                   f"{int(serie.iloc[-1]):,}")
    if len(serie) >= 2:
        var = (float(serie.iloc[-1]) / float(serie.iloc[-2]) - 1) * 100
        cols[1].metric("Variación vs ciclo anterior", f"{var:+.1f}%",
                       help=f"Contra {int(serie.index[-2])}-{int(serie.index[-2]) + 1}. "
                            "Es la única variación que existe: no hay serie previa "
                            "con la que construir un CAGR.")
    else:
        cols[1].metric("Ciclos con dato", f"{len(serie)}")
    if padre is not None:
        share = float(serie.iloc[-1]) / float(padre.loc[ultimo_anio])
        # Dos decimales por debajo de 1%: DUAL es 196 de 1,670,298, y redondeado
        # a una decima sale "0.0%", que se lee como "no hay" y no como "es chico".
        cols[2].metric(f"Participación en {etiqueta_padre.split(' (')[0].lower()}",
                       f"{share * 100:.1f}%" if share >= 0.01 else f"{share * 100:.2f}%",
                       help=f"{etiqueta_padre}: {int(padre.loc[ultimo_anio]):,} en "
                            f"{ultimo_anio}-{ultimo_anio + 1}.")

    st.plotly_chart(
        grafica_historica(serie, [int(a) for a in serie_completa.index], segmento,
                          metrica_nombre, padre, etiqueta_padre, derivada, confianza),
        use_container_width=True)

    st.info(cta_sin_proyeccion(mods_base, mods_padre, etiqueta_padre, len(serie)))

    # ------------------------------------------------------- proyeccion derivada
    if derivada is not None:
        st.markdown("---")
        st.subheader("Proyección derivada por participación")
        st.caption(
            f"No es una proyección de este corte: es la proyección de "
            f"**{etiqueta_padre}** —serie continua de 11 ciclos, motor y calibración "
            f"ya validados— repartida por la participación observada de este corte "
            f"dentro de ella. Por eso no lleva semáforo de confiabilidad ni MAPE: no "
            f"tiene backtest propio, y el del padre no es el suyo.")
        u = derivada.proyeccion.iloc[-1]
        e1, e2, e3 = st.columns(3)
        e1.metric(f"Derivado {u['ciclo']}", f"{int(u['pronostico']):,}",
                  help="Punto del padre por la participación fija.")
        e2.metric(f"Banda {confianza}%",
                  f"{int(u['inferior']):,} – {int(u['superior']):,}",
                  help="El intervalo del padre, ensanchado por la incertidumbre del "
                       "reparto. Es la envolvente externa: empareja el peor caso del "
                       "padre con el peor caso de la participación.")
        e3.metric("Participación usada", f"{derivada.share * 100:.1f}%",
                  f"banda {derivada.banda_share[0] * 100:.1f}–"
                  f"{derivada.banda_share[1] * 100:.1f}%",
                  delta_color="off",
                  help="Promedio de los ciclos observados: "
                       + ", ".join(f"{int(a)}-{int(a) + 1} {s * 100:.1f}%"
                                   for a, s in derivada.shares_observados.items())
                       + ". Fija, no extrapolada: con dos observaciones, la "
                         "tendencia del share es la pendiente del ruido.")
    elif motivo:
        st.caption(f"**Sin proyección derivada.** {motivo}")

    # --------------------------------------------------- tabla y descargas
    salida = tabla_historica(serie, metrica_nombre, derivada)
    st.markdown("---")
    izq, der = st.columns([3, 2])
    with izq:
        st.subheader("Serie completa")
        st.dataframe(salida, use_container_width=True, hide_index=True)
    with der:
        st.subheader("Qué trae la descarga")
        st.write(f"**{len(serie)} ciclos históricos**"
                 + (f" y {len(derivada.proyeccion)} derivados de {etiqueta_padre}."
                    if derivada is not None else ", sin proyección."))
        st.caption(
            "Las filas derivadas van marcadas `derivado` en la columna `tipo`, nunca "
            "`proyeccion`: quien abra el archivo sin haber visto esta pantalla tiene "
            "que poder distinguirlas.")
        st.download_button(
            "Descargar CSV", salida.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"historico_{metrica}_{nombre_archivo}.csv",
            mime="text/csv", use_container_width=True)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as xls:
            salida.to_excel(xls, index=False, sheet_name="historico")
            ficha = {
                "segmento": segmento,
                "metrica": metrica_nombre,
                "ciclos_con_datos": len(serie),
                "proyeccion_directa": "no (serie mas corta que "
                                      f"{pr.MIN_OBS} ciclos)",
                "serie_padre": etiqueta_padre,
                "tipo_de_proyeccion": "derivada por participación"
                                      if derivada is not None else "ninguna",
            }
            if derivada is not None:
                ficha.update({
                    "participacion_usada_%": round(derivada.share * 100, 2),
                    "participacion_banda_min_%": round(derivada.banda_share[0] * 100, 2),
                    "participacion_banda_max_%": round(derivada.banda_share[1] * 100, 2),
                    "dispersion_share_%": round(derivada.dispersion * 100, 1),
                    "motor_del_padre": derivada.padre.motor,
                    "nivel_intervalo_%": confianza,
                    "CAGR_proyectado_del_padre_%": (round(derivada.cagr_padre, 2)
                                                    if derivada.cagr_padre is not None
                                                    else None),
                })
            elif motivo:
                ficha["motivo_sin_derivada"] = motivo
            pd.DataFrame({"campo": list(ficha), "valor": list(ficha.values())}
                         ).to_excel(xls, index=False, sheet_name="ficha")
        st.download_button(
            "Descargar Excel", buffer.getvalue(),
            file_name=f"historico_{metrica}_{nombre_archivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)


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

# Mismo problema que MOTORES_UI (ver abajo), del lado de los datos: si Cloud
# sigue sirviendo `comun` viejo desde sys.modules, `cargar` puede devolver de
# cache un panel anterior a la columna Sostenimiento. Se limpia y se relee.
if "Sostenimiento" not in df.columns:
    st.cache_data.clear()
    df = cargar()

# getattr por la misma razon que MOTORES_UI: nombre nuevo en un modulo importado.
AYUDA_SOSTENIMIENTO = getattr(comun, "AYUDA_SOSTENIMIENTO",
                              "Vacio = particulares y publicas sumadas.")

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

sostenimientos = st.sidebar.multiselect(
    "Sostenimiento", opciones(df, "Sostenimiento"), help=AYUDA_SOSTENIMIENTO)
if sostenimientos:
    filtros["Sostenimiento"] = sostenimientos

modalidades = st.sidebar.multiselect(
    "Modalidad", opciones_modalidad(df), help=AYUDA_MODALIDAD)
# Al filtro se le mandan siempre las modalidades BASE, no lo que se marco. Asi
# elegir el atajo compuesto y marcar las dos casillas producen literalmente el
# mismo `filtros`, o sea la misma clave de cache y el mismo numero: no son dos
# caminos que "dan lo mismo", son el mismo camino.
mods_base = normalizar_modalidades(modalidades)
if mods_base:
    filtros["Modalidad"] = mods_base

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
# MOTORES_UI, no MOTORES: Theta y Holt amortiguado siguen midiendose en
# validacion.py y calibrandose en calibrar.py, pero no se ofrecen aqui porque
# empatan con el ensemble (1.225 y 1.325 de MASE contra 1.216) y elegirlos seria
# cambiar de motor por ruido. Ver el comentario de `metodos.MOTORES_UI`.
# `getattr` y no `metodos.MOTORES_UI` directo. Streamlit Cloud vuelve a ejecutar
# el script de la pagina en cada rerun, pero el modulo importado puede seguir
# viniendo de sys.modules con el codigo de antes del deploy. Cuando un push
# AGREGA un nombre nuevo a metodos.py, esa ventana deja la pagina tirada con
# AttributeError hasta que alguien reinicia la app a mano --- que es exactamente
# lo que paso al publicar MOTORES_UI. El fallback deriva el mismo subconjunto de
# MOTORES, que ya existia antes, asi que la pagina levanta con o sin reinicio.
MOTORES_UI = getattr(metodos, "MOTORES_UI", None) or tuple(
    n for n in metodos.MOTORES if n not in ("Theta", "Holt amortiguado"))

motor = st.sidebar.selectbox(
    "Metodo", list(MOTORES_UI), index=0,
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

serie_completa, serie, res, aviso_recorte = serie_y_modelo(
    df, filtros, metrica, horizonte, confianza / 100, motor)
if aviso_recorte:
    st.info(aviso_recorte)

if serie.empty or serie.sum() == 0:
    st.warning("No hay datos para esta combinacion de filtros.")
    st.stop()

# El corte mas fino primero: si filtraste una carrera, eso es lo que estas
# viendo, y ponerle de titulo el campo entero hace creer que es otra cosa.
# Se arma antes de bifurcar porque la vista sin proyeccion tambien lleva titulo:
# antes se calculaba despues del `st.stop()` y por eso esa rama no tenia ninguno.
etiqueta_mod = etiqueta_modalidades(modalidades)
segmento = " · ".join([etiqueta_geo] +
                      ([", ".join(niveles)] if niveles else []) +
                      ([", ".join(sostenimientos)] if sostenimientos else []) +
                      ([etiqueta_mod] if etiqueta_mod else []) +
                      ([", ".join(grupos)] if grupos else
                       [", ".join(campos)] if campos else []))
nombre_archivo = etiqueta_geo[:30].replace(" ", "_")

# Aviso de seleccion, no de datos: NO ESCOLARIZADA sin MIXTA no es comparable en
# los 11 ciclos aunque su serie se vea perfectamente proyectable, porque el -40%
# de 2023-2024 es el desglose de MIXTA. Gemelo de `nota_trasvase` para las areas.
nota_mod = tax.nota_modalidad(mods_base)
if nota_mod:
    st.warning(nota_mod)

if res is None:
    vista_historica(df, filtros, mods_base, serie, serie_completa, metrica,
                    metrica_nombre, segmento, horizonte, confianza / 100, motor,
                    confianza, nombre_archivo)
    st.stop()

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

# Red de seguridad sobre la serie que de verdad esta en pantalla. Se miran los
# dos cruces conocidos: 2016->2017 (catalogo de areas) y 2022->2023 (desglose de
# modalidad). Los grupos comparables son continuos por construccion, pero un
# cruce (grupo x zona chica x modalidad) puede seguir teniendo un salto raro en
# cualquiera de los dos. Si lo tiene, se dice.
for severidad, texto in tax.quiebres(serie):
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
                       file_name=f"tendencia_{metrica}_{nombre_archivo}.csv",
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
                       file_name=f"tendencia_{metrica}_{nombre_archivo}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
