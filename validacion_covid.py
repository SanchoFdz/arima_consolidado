# -*- coding: utf-8 -*-
"""Vale la pena marcar los ciclos COVID? Se mide, no se supone.

El hoyo existe y es visible: nacionalmente el nuevo ingreso cae -7.0% en
2020-2021, el unico ciclo negativo de la serie. La pregunta operativa es otra:
si se le dice al modelo "estos dos ciclos son anomalos", pronostica mejor?

Se prueban las dos formas de decirselo:

  1. **Flag / dummy**: y ~ a + b*t + c*D_covid, y se proyecta con D = 0. Es la
     version literal de la idea. Solo aplica a un metodo que estime coeficientes,
     asi que se prueba sobre la tendencia lineal.
  2. **Limpieza del outlier**: se sustituye el valor de 2020 (y de 2021) por la
     interpolacion geometrica de sus vecinos sanos antes de ajustar. Esto si
     aplica a cualquier motor, incluido el ensemble que la app usa.

Protocolo identico al de `validacion.py`: origen movil sobre los mismos
segmentos reales. Se reporta tambien el regimen de uso real --- ventanas donde
COVID ya quedo estrictamente adentro y el objetivo es post-COVID --- porque un
backtest que predice 2021 esta prediciendo la pandemia, y ahi "limpiar" el
entrenamiento es competir contra una realidad que si tuvo pandemia.

Reproduce: python validacion_covid.py
"""
import warnings

import numpy as np
import pandas as pd

import metodos as mt
import pronostico as pr
import validacion as v

warnings.simplefilter("ignore")

COVID = (2020, 2021)


# --------------------------------------------------------- las dos versiones
def limpiar(y, anios, extrapolar_punta=True):
    """Sustituye los ciclos COVID por la interpolacion de sus vecinos sanos.

    Si el ciclo COVID es el ultimo punto de la ventana no hay vecino derecho.
    Con `extrapolar_punta` se reancla con la pendiente de los dos ultimos sanos;
    sin el, se deja como esta. La distincion importa: en el uso real de la app
    el ultimo punto es 2024-2025 y COVID siempre queda adentro, asi que la punta
    solo aparece en el backtest.
    """
    y = y.copy()
    sanos = [a for a in y.index if a not in anios]
    if len(sanos) < 3:
        return y
    for a in anios:
        if a not in y.index:
            continue
        izq = [s for s in sanos if s < a]
        der = [s for s in sanos if s > a]
        if izq and der:
            p, n = izq[-1], der[0]
            vp, vn = float(y.loc[p]), float(y.loc[n])
            if vp > 0 and vn > 0:
                y.loc[a] = vp * (vn / vp) ** ((a - p) / (n - p))
        elif extrapolar_punta and len(izq) >= 2:
            p1, p2 = izq[-2], izq[-1]
            pend = (float(y.loc[p2]) - float(y.loc[p1])) / (p2 - p1)
            y.loc[a] = max(float(y.loc[p2]) + pend * (a - p2), 0.0)
    return y


def con_limpieza(fn, anios, extrapolar_punta=True):
    return lambda y, h: fn(limpiar(y, anios, extrapolar_punta), h)


def lineal_dummy(y, h, anios=COVID, por_ciclo=False):
    """El flag literal. y ~ a + b*t + c*D, proyectado con D = 0."""
    t = np.arange(len(y), dtype=float)
    cols = [np.ones(len(y)), t]
    if por_ciclo:
        for a in anios:
            d = np.array([1.0 if x == a else 0.0 for x in y.index])
            if d.sum():
                cols.append(d)
    else:
        d = np.array([1.0 if x in anios else 0.0 for x in y.index])
        if 0 < d.sum() < len(y):
            cols.append(d)
    if len(cols) == 2:
        return mt.lineal(y, h)
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y.values.astype(float), rcond=None)
    return beta[0] + beta[1] * (len(y) - 1 + np.arange(1, h + 1))


METODOS = {
    "ensemble (el de la app)":     mt.ensemble,
    "ensemble + limpia 2020":      con_limpieza(mt.ensemble, (2020,)),
    "ensemble + limpia 2020-21":   con_limpieza(mt.ensemble, COVID),
    "theta":                       mt.theta,
    "theta + limpia 2020-21":      con_limpieza(mt.theta, COVID),
    "lineal":                      mt.lineal,
    "lineal + limpia 2020-21":     con_limpieza(mt.lineal, COVID),
    "lineal + dummy covid":        lineal_dummy,
    "lineal + dummy por ciclo":    lambda y, h: lineal_dummy(y, h, por_ciclo=True),
    "naive":                       mt.naive,
}


# ------------------------------------------------------- cuanto hoyo hay, de hecho
def magnitud(series):
    """Desviacion de cada ciclo contra la interpolacion de vecinos NO-covid.

    Para 2020 y 2021 los anclas son 2019 y 2022, que estan fuera del shock. Para
    los demas anios se usa la misma formula con t-1 y t+2, de modo que la columna
    sea comparable: dice que tan raro es un anio cualquiera con esta misma vara.
    """
    filas = []
    for nombre, y in series:
        y = y.astype(float)
        for anio in range(2015, 2023):
            prev = 2019 if anio in COVID else anio - 1
            nxt = 2022 if anio in COVID else anio + 2
            if not all(a in y.index for a in (prev, nxt, anio)) or prev >= anio:
                continue
            a_, b_ = float(y.loc[prev]), float(y.loc[nxt])
            if a_ <= 0 or b_ <= 0:
                continue
            cf = a_ * (b_ / a_) ** ((anio - prev) / (nxt - prev))
            filas.append({"segmento": nombre, "anio": anio,
                          "desvio_%": (float(y.loc[anio]) / cf - 1) * 100})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- el backtest
def evaluar(series, h_max=3, min_train=7, solo_interior=False):
    filas = []
    for nombre, y in series:
        y = y.astype(float)
        if len(y) < min_train + 1 or y.iloc[-3:].mean() < 30:
            continue
        for corte in range(min_train, len(y)):
            train, resto = y.iloc[:corte], y.iloc[corte:]
            # Regimen de uso real: COVID estrictamente adentro de la ventana.
            if solo_interior and int(train.index[-1]) < max(COVID) + 1:
                continue
            h = min(h_max, len(resto))
            esc = v.mase_escala(train)
            if not np.isfinite(esc):
                continue
            for met, fn in METODOS.items():
                try:
                    pred = np.asarray(fn(train, h), dtype=float)[:h]
                except Exception:
                    continue
                if not np.all(np.isfinite(pred)):
                    continue
                real = resto.values[:h]
                for i in range(h):
                    filas.append({
                        "segmento": nombre, "metodo": met, "h": i + 1,
                        "anio_predicho": int(train.index[-1]) + i + 1,
                        "ae": abs(pred[i] - real[i]), "escala": esc,
                        "ape": abs(pred[i] - real[i]) / real[i] * 100 if real[i] > 0 else np.nan,
                    })
    res = pd.DataFrame(filas)
    res["mase"] = res["ae"] / res["escala"]
    return res


def tabla(res, titulo):
    t = (res.groupby("metodo")
         .agg(MASE=("mase", "mean"), MASE_mediana=("mase", "median"),
              MAPE=("ape", "mean"))
         .sort_values("MASE").round(3))
    print(f"=== {titulo} ===")
    print(t.to_string())
    print()
    return t


# ------------------------- donde el COVID si pega: la escala del intervalo
def efecto_en_intervalos(series):
    """El ancho del intervalo es proporcional a mean|diff| de la serie.

    El salto de entrada al hoyo y el de salida son dos diferencias grandes, asi
    que inflan esa escala aunque el punto no se mueva. Eso no es un defecto que
    haya que corregir --- 2020 paso --- pero es la unica via por la que el COVID
    sigue tocando el numero que la app entrega.
    """
    rat = []
    for _, y in series:
        y = y.astype(float)
        d = np.abs(np.diff(y.values))
        anios_dif = list(y.index[1:])   # el salto a->b se etiqueta con b
        tocan = [i for i, a in enumerate(anios_dif) if a in (2020, 2021, 2022)]
        sin = np.delete(d, tocan)
        if len(sin) and sin.mean() > 0 and d.mean() > 0:
            rat.append(d.mean() / sin.mean())
    return np.array(rat)


# --------------------------- y donde no pega: el semaforo de confiabilidad
def efecto_en_semaforo(series):
    """El backtest incluye origenes que predicen 2020 y 2021. Eso castiga el
    MAPE de todos los segmentos por igual, asi que no reordena el semaforo."""
    def bt(y, excluir=()):
        aes, apes, escalas = [], [], []
        for corte in range(7, len(y)):
            train, resto = y.iloc[:corte], y.iloc[corte:]
            h = min(3, len(resto))
            esc = pr.volatilidad(train.values)
            if not np.isfinite(esc):
                continue
            try:
                pred = np.asarray(mt.ensemble(train, h), dtype=float)
            except Exception:
                continue
            for i in range(h):
                if int(train.index[-1]) + i + 1 in excluir:
                    continue
                real = float(resto.values[i])
                if not np.isfinite(pred[i]):
                    continue
                aes.append(abs(pred[i] - real))
                escalas.append(esc)
                if real > 0:
                    apes.append(abs(pred[i] - real) / real * 100)
        return (float(np.mean(np.array(aes) / np.array(escalas))) if aes else None,
                float(np.mean(apes)) if apes else None)

    filas = []
    for nombre, y in series:
        y = y.astype(float)
        m1, p1 = bt(y)
        m2, p2 = bt(y, excluir=COVID)
        nz, rec = int((y > 0).sum()), float(y.iloc[-3:].mean())
        filas.append({"segmento": nombre, "mape_con": p1, "mape_sin": p2,
                      "con": pr._confiabilidad(p1, nz, rec, m1),
                      "sin": pr._confiabilidad(p2, nz, rec, m2)})
    return pd.DataFrame(filas)


if __name__ == "__main__":
    df = pd.read_parquet("datos/panel_ni.parquet")
    series = [(n, y) for n, y in v.construir_series(df)
              if len(y) >= 8 and y.astype(float).iloc[-3:].mean() >= 30]
    print(f"Segmentos: {len(series)}\n")

    print("################ 1. QUE TAN GRANDE ES EL HOYO ################\n")
    mag = magnitud(series)
    print("Desvio contra la interpolacion de los vecinos sanos, por ciclo:")
    resumen = (mag.groupby("anio")["desvio_%"]
               .agg(n="size", mediana="median", media="mean",
                    p10=lambda s: s.quantile(.10), p90=lambda s: s.quantile(.90),
                    pct_negativos=lambda s: (s < 0).mean() * 100)
               .round(1))
    print(resumen.to_string())
    print("\n2020-2021 es el unico ciclo con desvio mediano de dos digitos y con "
          "8 de cada 10 segmentos por debajo de su propia interpolacion.")
    print("2021-2022 ya es recuperacion parcial: la mitad de ese hoyo, y un "
          "tercio de los segmentos ya esta arriba.\n")

    print("################ 2. SIRVE MARCARLOS? ################\n")
    todo = evaluar(series)
    tabla(todo, "TODOS LOS ORIGENES "
                f"({len(todo) // len(METODOS):,} predicciones por metodo)")

    interior = evaluar(series, solo_interior=True)
    tabla(interior, "REGIMEN DE USO REAL: COVID ADENTRO DE LA VENTANA, OBJETIVO POST-COVID "
                    f"({len(interior) // len(METODOS):,} predicciones por metodo)")

    base = interior[interior.metodo == "ensemble (el de la app)"].groupby("segmento")["mase"].mean()
    print("Contra el ensemble actual, segmento por segmento (regimen de uso real):")
    for m in METODOS:
        if m == "ensemble (el de la app)":
            continue
        alt = interior[interior.metodo == m].groupby("segmento")["mase"].mean()
        c = pd.concat([base.rename("b"), alt.rename("a")], axis=1).dropna()
        print(f"  {m:28s} le gana en {(c.a < c.b).mean() * 100:5.1f}% de {len(c)} segmentos")

    print("\n################ 3. DONDE SI PEGA EL COVID ################\n")
    rat = efecto_en_intervalos(series)
    print("Escala del error (mean|diff|), que es lo que fija el ancho del intervalo.")
    print(f"  ratio con-COVID / sin-COVID: mediana {np.median(rat):.3f}  "
          f"media {rat.mean():.3f}  p90 {np.quantile(rat, .9):.3f}")
    print(f"  intervalos >10% mas anchos por COVID: {(rat > 1.10).mean() * 100:.0f}% de segmentos")
    print(f"  intervalos >25% mas anchos por COVID: {(rat > 1.25).mean() * 100:.0f}% de segmentos")

    sem = efecto_en_semaforo(series)
    print("\nSemaforo de confiabilidad, backtest con vs. sin objetivos 2020-2021:")
    print(f"  MAPE medio: con {sem.mape_con.mean():.2f}%   sin {sem.mape_sin.mean():.2f}%")
    cambian = sem[sem["con"] != sem["sin"]]
    print(f"  segmentos que cambian de color: {len(cambian)} de {len(sem)} "
          f"({len(cambian) / len(sem) * 100:.0f}%), y en las dos direcciones:")
    print(pd.crosstab(sem["con"], sem["sin"]).to_string())
