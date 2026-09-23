# -*- coding: utf-8 -*-
"""Corre la proyeccion sobre todas las categorias de hasta tres dimensiones.

Pensado para que finanzas se lleve, en un solo archivo, la tendencia de cada zona
metropolitana (o estado, o area) sin tener que ir una por una. Con dos o tres
dimensiones el corte es el cruce: region Nielsen x campo de conocimiento, ZM x
nivel x modalidad, y asi.

El cruce solo genera las combinaciones que existen en los datos, no el producto
cartesiano: la mayoria de las celdas de un cruce de tres dimensiones estan
vacias, y pedirle una proyeccion a una serie de ceros no significa nada.
"""
from io import BytesIO
import pandas as pd
import streamlit as st

import contexto as ctx
import drivers
import metodos
import pronostico as pr
import taxonomia as tax
from comun import (CORTES, METRICAS, PRESETS_MODALIDAD, SIN_ZM,
                   aplicar_filtros, cargar, opciones)

st.set_page_config(page_title="Descarga masiva", page_icon="📦", layout="wide")
st.title("Descarga masiva de tendencias")
st.caption("Proyecta cada categoria —o cada cruce de hasta tres— y entrega todo en un Excel.")

df = cargar()

DIMENSIONES = {k: v for k, v in CORTES.items() if v} | {
    "Nivel educativo": "Nivel_educativo",
    "Modalidad": "Modalidad",
    # Disciplina: los grupos comparables, no las columnas crudas del catalogo.
    # Ver comun.py y concordancia.py.
    "Campo de conocimiento": "Campo",
    "Carrera o grupo de carreras": "Grupo_comparable",
}
NINGUNA = "— ninguna —"

# Tope duro. No es estetico: cada combinacion corre su propio backtest de origen
# movil, y arriba de esto la corrida deja de terminar en un tiempo razonable.
# Si se alcanza, se dice cuantas quedaron fuera; no se recorta en silencio.
MAX_COMBINACIONES = 1500

st.subheader("Desagregacion")
d1, d2, d3 = st.columns(3)
dim1_nombre = d1.selectbox("Desagregar por", list(DIMENSIONES))
restantes = [NINGUNA] + [k for k in DIMENSIONES if k != dim1_nombre]
dim2_nombre = d2.selectbox("Y por (opcional)", restantes)
restantes3 = [NINGUNA] + [k for k in DIMENSIONES
                          if k not in (dim1_nombre, dim2_nombre)]
dim3_nombre = d3.selectbox("Y una tercera (opcional)", restantes3,
                           disabled=dim2_nombre == NINGUNA)
if dim2_nombre == NINGUNA:
    dim3_nombre = NINGUNA

dim_nombres = [n for n in (dim1_nombre, dim2_nombre, dim3_nombre) if n != NINGUNA]
dims = [DIMENSIONES[n] for n in dim_nombres]

if "Campo" in dims and "Grupo_comparable" in dims:
    st.caption("Campo y carrera son niveles del mismo arbol: el cruce da un solo "
               "campo por carrera, no una matriz.")

st.subheader("Metrica y horizonte")
m1, m2, m3 = st.columns(3)
metrica_nombre = m1.selectbox("Metrica", list(METRICAS))
metrica = METRICAS[metrica_nombre]
horizonte = m2.slider("Ciclos a proyectar", 1, 5, 3)
motor = m3.selectbox("Metodo", list(metodos.MOTORES), index=0,
                     help="El ensemble gana el backtest; el ARIMA se deja para comparar.")

st.subheader("Filtros fijos (se aplican a todas las categorias)")
f1, f2, f3 = st.columns(3)
filtros = {}
niveles = f1.multiselect("Nivel educativo", opciones(df, "Nivel_educativo"))
if niveles and "Nivel_educativo" not in dims:
    filtros["Nivel_educativo"] = niveles
preset = f2.selectbox("Modalidad", list(PRESETS_MODALIDAD))
if PRESETS_MODALIDAD[preset] and "Modalidad" not in dims:
    filtros["Modalidad"] = PRESETS_MODALIDAD[preset]
campos = f3.multiselect("Campo de conocimiento", opciones(df, "Campo"))
if campos and not {"Campo", "Grupo_comparable"} & set(dims):
    filtros["Campo"] = campos

minimo = st.number_input(
    "Ignorar combinaciones con menos de N alumnos en el ultimo ciclo",
    min_value=0, value=50, step=10,
    help="Con dos o tres dimensiones el cruce se vuelve muy fino muy rapido. "
         "Este minimo es lo que separa un segmento proyectable de una serie de "
         "tres alumnos.")


def combinaciones(base, dims, metrica, minimo):
    """Una fila por combinacion observada, una columna por anio.

    Se arma con un solo groupby en vez de una mascara por categoria: con tres
    dimensiones las categorias son cientos y filtrar el panel entero una vez por
    cada una es lo que hace que la corrida no termine.
    """
    tabla = (base.groupby([base[d].astype(str) for d in dims] + ["anio"],
                          observed=True)[metrica].sum()
             .unstack("anio").fillna(0.0))
    tabla.index.names = dims
    ultimo = tabla.columns.max()
    return tabla[tabla[ultimo] >= minimo].sort_values(ultimo, ascending=False)


if st.button("Generar proyecciones", type="primary"):
    base = aplicar_filtros(df, filtros)
    if "Zona_Metropolitana" in dims:
        base = base[base["Zona_Metropolitana"].astype(str) != SIN_ZM]

    tabla = combinaciones(base, dims, metrica, minimo)
    if tabla.empty:
        st.warning("Ninguna combinacion cumplio el minimo.")
        st.stop()

    descartadas = 0
    if len(tabla) > MAX_COMBINACIONES:
        descartadas = len(tabla) - MAX_COMBINACIONES
        tabla = tabla.iloc[:MAX_COMBINACIONES]
        st.warning(
            f"El cruce da {len(tabla) + descartadas:,} combinaciones y el tope es "
            f"{MAX_COMBINACIONES:,}. Se corrieron las {MAX_COMBINACIONES:,} mas "
            f"grandes del ultimo ciclo y quedaron fuera **{descartadas:,}**. "
            "Sube el minimo de alumnos o quita una dimension para cubrirlas.")

    # Contexto externo: se resuelve mientras el cruce tenga alguna dimension
    # geografica. Con dos, `drivers.claves` intersecta los conjuntos de
    # municipios, que es lo correcto porque los cortes geograficos de la app o
    # estan anidados (estado dentro de region) o se cruzan limpio (una ZM y uno
    # de sus estados): la interseccion sigue siendo un conjunto de municipios y
    # CONAPO se suma sobre el sin ambiguedad.
    hay_geo = any(d in drivers.COLS_GEO for d in dims)

    filas, barra = [], st.progress(0.0, "Calculando proyecciones...")
    total = len(tabla)

    for i, (clave, valores) in enumerate(tabla.iterrows(), 1):
        clave = clave if isinstance(clave, tuple) else (clave,)
        etiqueta = " · ".join(clave)
        if i % 5 == 0 or i == total:
            barra.progress(i / total, f"Proyectando {etiqueta} ({i}/{total})")

        serie = valores.astype(float).sort_index()
        # Mismo recorte que en la pagina principal: una categoria que solo vive
        # en uno de los dos catalogos ANUIES no tiene 11 ciclos, tiene los que
        # tiene. Ver taxonomia.py.
        serie, aviso_catalogo = tax.recortar(serie)
        res = pr.proyectar(serie, horizonte, motor=motor)
        if res is None:
            continue

        fila = dict(zip(dim_nombres, clave))
        fila.update({
            f"{metrica}_2024-2025": int(serie.iloc[-1]),
            "metodo": res.motor,
            "confiabilidad": res.confiabilidad,
            "CAGR_historico_%": round(res.cagr_historico, 2) if res.cagr_historico is not None else None,
            "CAGR_proyectado_%": round(res.cagr_proyectado, 2) if res.cagr_proyectado is not None else None,
            "MAPE_backtest_%": round(res.mape_backtest, 2) if res.mape_backtest is not None else None,
            "MASE_backtest": round(res.mase_backtest, 2) if res.mase_backtest is not None else None,
        })
        for _, p in res.proyeccion.iterrows():
            fila[f"{p['ciclo']}"] = int(round(p["pronostico"]))
            fila[f"{p['ciclo']}_inf"] = int(round(p["inferior"]))
            fila[f"{p['ciclo']}_sup"] = int(round(p["superior"]))
        # Contexto externo del corte. No entra al pronostico (ver contexto.py),
        # pero en un Excel de 15 zonas es justo lo que permite ver cuales estan
        # proyectando crecimiento contra su propia demografia.
        if hay_geo:
            c = ctx.lectura(filtros | {d: [v] for d, v in zip(dims, clave)},
                            serie, list(res.proyeccion["anio"]), res.cagr_proyectado)
            if c:
                fila.update({
                    "poblacion_12_29": int(c["pob_base"]),
                    "CAGR_poblacion_%": (round(c["cagr_pob_%"], 2)
                                         if c["cagr_pob_%"] is not None else None),
                    "brecha_vs_demografia_pp": (round(c["brecha_pp"], 2)
                                                if c.get("brecha_pp") is not None else None),
                    "tasa_captacion_x1000": round(c["tasa_captacion_x1000"], 2),
                    "rezago_grado": (c["rezago"]["grado_rezago"]
                                     if c.get("rezago") else None),
                    "basica_incompleta_%": (round(c["rezago"]["basica_incompleta"], 1)
                                            if c.get("rezago") else None),
                })
        fila["ciclos_con_datos"] = len(serie)
        quiebre = tax.quiebre_de_catalogo(serie)
        fila["avisos"] = " | ".join(
            res.avisos + [a for a in (aviso_catalogo,
                                      quiebre[1] if quiebre else None) if a])
        filas.append(fila)

    barra.empty()
    if not filas:
        st.warning("Ninguna combinacion tenia serie suficiente para proyectar.")
        st.stop()

    salida = pd.DataFrame(filas)
    descartadas_serie = len(tabla) - len(salida)
    st.success(f"{len(salida):,} combinaciones proyectadas "
               f"sobre {' × '.join(dim_nombres)}.")
    if descartadas_serie:
        una = descartadas_serie == 1
        st.caption(f"{descartadas_serie:,} combinacion{'' if una else 'es'} "
                   f"cumpli{'o' if una else 'eron'} el minimo de alumnos pero su "
                   f"serie es demasiado corta o dispersa para proyectarla, y no "
                   f"{'esta' if una else 'estan'} en la tabla.")

    st.dataframe(salida, use_container_width=True, hide_index=True)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as xls:
        salida.to_excel(xls, index=False, sheet_name="proyecciones")
    nombre = "_x_".join(d[:18] for d in dims)
    st.download_button("Descargar Excel", buffer.getvalue(),
                       file_name=f"tendencia_{metrica}_por_{nombre}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
