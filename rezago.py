# -*- coding: utf-8 -*-
"""El rezago social como correccion a la tasa de captacion proyectada.

El IRS no es una serie anual: son cinco censos (2000-2020). Y hay una trampa en
usarlo como serie, que se ve sola en los datos: CONEVAL reestima el indice por
componentes principales en cada censo y lo normaliza a media nacional CERO. La
media de los 2,469 municipios es exactamente 0.000 en los cinco cortes. O sea
que el indice mide posicion RELATIVA, no nivel absoluto: la Ciudad de Mexico
"empeora" de -1.91 a -1.31 entre 2000 y 2020 no porque su rezago haya crecido
--- ninguno de sus indicadores empeoro --- sino porque el resto del pais mejoro
mas rapido. Extrapolar ese indice en el tiempo mete el signo al reves.

Asi que el modulo parte los dos usos:

  * **Nivel estructural (transversal)**: ahi el indice si sirve, y mucho. El
    grado de rezago, el lugar nacional y la brecha entre la captacion observada
    del corte y la que su rezago haria esperar son diagnostico directo de
    mercado. `diagnostico()`.

  * **Correccion temporal**: se hace con `% de poblacion de 15 anos y mas con
    educacion basica incompleta`, que es un porcentaje con la misma definicion
    en los cinco censos --- baja de 72.3% a 45.8% de promedio municipal --- y
    que ademas es el indicador con mas senal transversal de los once
    (t = -6.3 contra la tasa de captacion). `ajuste()`.

Sobre la correccion: la proyeccion de la tasa de captacion YA extrapola la
tendencia historica, y esa tendencia ya contiene la mejoria educativa de los
ultimos once anos. Aplicarle encima el efecto completo del rezago proyectado
seria contar lo mismo dos veces. Lo que corrige `ajuste()` es solo el cambio de
RITMO: la educacion basica incompleta cae de forma proporcional, asi que su
caida en puntos se desacelera conforme baja el nivel, y la tasa de captacion
deberia crecer un poco menos rapido de lo que crecio. Por eso el ajuste es
chico y casi siempre negativo. Esa es la correccion honesta que se puede hacer
con cinco censos, no un pronostico de rezago.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
IRS = DATOS / "irs_municipio.parquet"
ELASTICIDAD = DATOS / "elasticidad_irs.json"

ANIOS_CENSO = (2000, 2005, 2010, 2015, 2020)
TOPE_AJUSTE = 0.06  # +/-6% acumulado sobre el punto del modelo
MIN_NI = 100        # municipios con menos NI que esto son ruido en la regresion
INDICADOR = "basica_incompleta"
MAX_MUN_BRECHA = 20  # arriba de esto la brecha de captacion deja de ser legible


def cargar_irs():
    if not IRS.exists():
        raise FileNotFoundError("Falta irs_municipio.parquet. Corre: python externos.py")
    return pd.read_parquet(IRS)


def perfil(claves):
    """Rezago del corte, censo por censo, ponderado por poblacion.

    Ponderar es lo correcto para un agregado: la captacion de una zona
    metropolitana la determinan sus municipios grandes, no el promedio simple
    entre la capital y un municipio de ocho mil habitantes.
    """
    d = cargar_irs()
    d = d[d["clave_mun"].isin(list(claves))]
    if d.empty:
        return None

    filas = []
    for anio, g in d.groupby("anio"):
        w = g["pob_censo"].fillna(0)
        if w.sum() <= 0:
            continue
        filas.append({
            "anio": int(anio),
            "irs": float(np.average(g["irs"].fillna(0), weights=w)),
            "basica_incompleta": float(np.average(g[INDICADOR].fillna(0), weights=w)),
            "analfabeta": float(np.average(g["analfabeta"].fillna(0), weights=w)),
            "pob_censo": float(w.sum()),
        })
    if not filas:
        return None
    perf = pd.DataFrame(filas).set_index("anio").sort_index()

    ultimo = d[d["anio"] == max(ANIOS_CENSO)]
    if not ultimo.empty:
        w = ultimo["pob_censo"].fillna(0)
        dominante = (ultimo.assign(w=w).groupby("grado_rezago")["w"].sum()
                     .sort_values(ascending=False))
        perf.attrs["grado"] = dominante.index[0] if len(dominante) else None
        perf.attrs["grado_share"] = (float(dominante.iloc[0] / w.sum())
                                     if w.sum() > 0 else None)
        perf.attrs["municipios"] = int(ultimo["clave_mun"].nunique())
        if w.sum() > 0:
            perf.attrs["lugar_nacional"] = float(
                np.average(ultimo["lugar_nacional"].fillna(np.nan), weights=w))
    return perf


def trayectoria_indicador(perf, anios):
    """Proyecta la educacion basica incompleta con caida proporcional constante.

    Log-lineal sobre los cinco censos, anclada en el nivel de 2020: el indicador
    no puede bajar de cero y su caida en puntos se desacelera sola conforme se
    acerca al piso. Una recta en niveles lo llevaria a negativo antes de 2060 y,
    peor para lo que aqui importa, supondria un ritmo de mejora constante.

    Devuelve (serie proyectada, ritmo anual en puntos durante el horizonte,
    ritmo anual en puntos durante la historia reciente).
    """
    y = perf[INDICADOR].dropna()
    y = y[y > 0]
    if len(y) < 3:
        return None
    t = y.index.values.astype(float)
    b, _ = np.polyfit(t, np.log(y.values), 1)          # caida proporcional/ano
    base_anio, base_val = int(y.index[-1]), float(y.iloc[-1])

    def nivel(anio):
        return base_val * np.exp(b * (anio - base_anio))

    proy = pd.Series({int(a): float(nivel(a)) for a in anios})

    # Ritmo en PUNTOS: es lo que la elasticidad convierte en efecto sobre la
    # tasa, y es lo que se desacelera.
    a0, a1 = min(anios) - 1, max(anios)
    ritmo_futuro = (nivel(a1) - nivel(a0)) / (a1 - a0)
    hist = (base_anio - 10, base_anio)                  # decada previa al ultimo censo
    ritmo_hist = (nivel(hist[1]) - nivel(hist[0])) / (hist[1] - hist[0])
    return proy, float(ritmo_futuro), float(ritmo_hist)


def estimar_elasticidad(panel=None, guardar=True):
    """Cuanto cambia la tasa de captacion por punto de rezago, en el corte transversal.

    Un municipio, una observacion: NI promedio de los tres ultimos ciclos entre
    poblacion 12-29 de 2020, contra los indicadores de rezago de 2020, en
    logaritmo --- el coeficiente se lee como cambio proporcional de la tasa por
    punto del indicador. Se guardan los tres candidatos para que la eleccion
    quede a la vista, pero el que se usa es `basica_incompleta`: es comparable
    entre censos y es el de mas senal.

    Ojo con lo que mide: una ASOCIACION. Un municipio con rezago alto capta
    menos, y no solo por el rezago --- tambien porque ahi no hay universidades.
    """
    from drivers import externos

    if panel is None:
        panel = pd.read_parquet(DATOS / "panel_ni.parquet",
                                columns=["Estado", "Municipio", "anio", "NI"])
    ext = externos()
    cw = ext.crosswalk[["Estado", "Municipio", "clave_mun"]].dropna().drop_duplicates()

    reciente = panel[panel["anio"] >= panel["anio"].max() - 2]
    # Primero suma el NI de cada municipio dentro del ciclo (el panel trae una
    # fila por nivel x modalidad x area), y solo despues promedia entre ciclos.
    ni = (reciente.astype({"Estado": str, "Municipio": str})
          .groupby(["Estado", "Municipio", "anio"], observed=True)["NI"].sum()
          .groupby(level=["Estado", "Municipio"]).mean().reset_index())
    ni = ni.merge(cw.astype({"Estado": str, "Municipio": str}),
                  on=["Estado", "Municipio"], how="inner")
    ni["clave_mun"] = ni["clave_mun"].astype(int)

    pob = ext.panel[ext.panel["anio"] == 2020][["clave_mun", "pob_12_29"]]
    irs = cargar_irs()
    irs = irs[irs["anio"] == 2020][["clave_mun", "irs", INDICADOR, "analfabeta"]]

    d = ni.merge(pob, on="clave_mun").merge(irs, on="clave_mun")
    d = d[(d["NI"] >= MIN_NI) & (d["pob_12_29"] > 0)].dropna(subset=[INDICADOR])
    d["tasa"] = d["NI"] / d["pob_12_29"]
    d = d[d["tasa"] > 0]
    ylog = np.log(d["tasa"].values)
    n = len(d)

    def regresion(col):
        x = d[col].values.astype(float)
        b, a = np.polyfit(x, ylog, 1)
        pred = a + b * x
        r2 = 1 - ((ylog - pred) ** 2).sum() / ((ylog - ylog.mean()) ** 2).sum()
        ee = float(np.sqrt((((ylog - pred) ** 2).sum() / (n - 2))
                           / ((x - x.mean()) ** 2).sum()))
        return {"pendiente": float(b), "intercepto": float(a), "error_estandar": ee,
                "t": float(b / ee) if ee else None, "r2": float(r2)}

    candidatos = {c: regresion(c) for c in ["irs", INDICADOR, "analfabeta"]}
    elegido = candidatos[INDICADOR]

    salida = {
        "indicador": INDICADOR,
        "elasticidad": elegido["pendiente"],
        "intercepto": elegido["intercepto"],
        "error_estandar": elegido["error_estandar"],
        "t": elegido["t"],
        "r2": elegido["r2"],
        "n_municipios": int(n),
        "anio_indicadores": 2020,
        "ciclos_ni": sorted(int(v) for v in reciente["anio"].unique()),
        "candidatos": candidatos,
        "nota": ("Asociacion transversal entre tasa de captacion y rezago, no efecto "
                 "causal. Solo se aplica al CAMBIO DE RITMO del rezago proyectado "
                 f"(el nivel ya esta en la tasa historica) y se acota a "
                 f"+/-{TOPE_AJUSTE * 100:.0f}%."),
    }
    if guardar:
        ELASTICIDAD.write_text(json.dumps(salida, indent=2, ensure_ascii=False))
    return salida


def cargar_elasticidad():
    if not ELASTICIDAD.exists():
        return None
    return json.loads(ELASTICIDAD.read_text())


def diagnostico(claves, tasa_observada=None):
    """Nivel estructural del corte, para leer junto a la proyeccion.

    Incluye la brecha de captacion: cuanto capta el corte contra lo que su nivel
    de rezago haria esperar, segun la regresion transversal. Un corte muy por
    debajo de su linea es mercado que su contexto socioeconomico ya permitiria.

    La brecha solo se calcula para cortes chicos (hasta MAX_MUN_BRECHA
    municipios). Dos razones, las dos de agregacion: la regresion es municipal,
    asi que la esperanza de un agregado es el promedio ponderado de las
    predicciones municipales y no la prediccion del promedio --- eso se corrige
    aqui ---; pero ademas, en un corte grande el denominador de la tasa incluye
    municipios sin una sola universidad, cuya demanda se matricula en la
    capital. Comparar eso contra una linea estimada sobre municipios CON oferta
    mide sobre todo la concentracion de la oferta, no la captacion. En un
    municipio o una zona metropolitana chica ese problema casi no existe.
    """
    perf = perfil(claves)
    if perf is None:
        return None
    elas = cargar_elasticidad()
    ult = perf.iloc[-1]
    out = {
        "irs": float(ult["irs"]),
        "grado_rezago": perf.attrs.get("grado"),
        "grado_share": perf.attrs.get("grado_share"),
        "basica_incompleta": float(ult[INDICADOR]),
        "basica_incompleta_2000": float(perf[INDICADOR].iloc[0]),
        "analfabeta": float(ult["analfabeta"]),
        "municipios": perf.attrs.get("municipios"),
        "serie": perf,
    }
    if (elas and tasa_observada and tasa_observada > 0
            and len(list(claves)) <= MAX_MUN_BRECHA):
        # Prediccion municipio por municipio, ponderada por poblacion 12-29:
        # exp() no conmuta con el promedio, asi que predecir sobre el indicador
        # promedio daria otro numero.
        from drivers import externos
        d = cargar_irs()
        d = d[(d["clave_mun"].isin(list(claves))) & (d["anio"] == max(ANIOS_CENSO))]
        ext = externos()
        pob = ext.panel[ext.panel["anio"] == 2020][["clave_mun", "pob_12_29"]]
        d = d.merge(pob, on="clave_mun", how="left").dropna(subset=[INDICADOR])
        w = d["pob_12_29"].fillna(0)
        if w.sum() > 0:
            esperadas = np.exp(elas["intercepto"]
                               + elas["elasticidad"] * d[INDICADOR].values)
            esperada = float(np.average(esperadas, weights=w))
            out["tasa_esperada"] = esperada
            out["brecha_%"] = (tasa_observada / esperada - 1) * 100
    return out


def ajuste(claves, anios):
    """Factor multiplicativo por ano proyectado, por el cambio de ritmo del rezago.

    factor[t] = exp(b * (ritmo_futuro - ritmo_historico) * (t - t0)), acotado.
    Sin indicador o sin elasticidad, devuelve None: mejor no ajustar que ajustar
    a ciegas.
    """
    elas = cargar_elasticidad()
    perf = perfil(claves)
    if elas is None or perf is None:
        return None, {"aviso": "Sin rezago o sin elasticidad estimada para este corte."}

    tray = trayectoria_indicador(perf, anios)
    if tray is None:
        return None, {"aviso": "Rezago insuficiente para una trayectoria."}
    proy, ritmo_futuro, ritmo_hist = tray

    b = elas["elasticidad"]
    delta_ritmo = ritmo_futuro - ritmo_hist
    t0 = min(anios) - 1
    crudo = {int(t): float(np.exp(b * delta_ritmo * (t - t0))) for t in anios}
    factores = pd.Series({t: float(np.clip(v, 1 - TOPE_AJUSTE, 1 + TOPE_AJUSTE))
                          for t, v in crudo.items()})

    meta = {
        "indicador": INDICADOR,
        "elasticidad": b,
        "nivel_actual": float(perf[INDICADOR].iloc[-1]),
        "nivel_proyectado": {int(t): float(v) for t, v in proy.items()},
        "ritmo_futuro": ritmo_futuro,
        "ritmo_historico": ritmo_hist,
        "grado_rezago": perf.attrs.get("grado"),
        "irs": float(perf["irs"].iloc[-1]),
        "efecto_total_%": (float(factores.iloc[-1]) - 1) * 100,
        "topado": any(abs(v - 1) > TOPE_AJUSTE for v in crudo.values()),
        "r2": elas["r2"],
        "t": elas["t"],
        "n_municipios": elas["n_municipios"],
    }
    return factores, meta


if __name__ == "__main__":
    info = estimar_elasticidad()
    print(json.dumps({k: v for k, v in info.items() if k != "candidatos"},
                     indent=2, ensure_ascii=False))
    print("\ncandidatos:")
    for c, r in info["candidatos"].items():
        print(f"  {c:20s} b={r['pendiente']:+.4f}  t={r['t']:+.2f}  R2={r['r2']:.3f}")
