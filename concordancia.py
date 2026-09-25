# -*- coding: utf-8 -*-
"""Concordancia entre el catalogo ANUIES anterior y el CINE-F 2013 (vigente desde 2017-2018).

ANUIES cambio de catalogo de areas de conocimiento en el ciclo 2017-2018. En el
panel quedaron los dos catalogos revueltos: de 171 areas especificas, 53 solo
existen hasta 2016, 84 solo desde 2017 y 34 en ambas eras. Los cortes por
subarea y area especifica quedan inproyectables (3 u 8 ciclos en vez de 11).

Este modulo NO intenta un mapeo 1:1 ni reparte matricula con proporciones
inventadas. Construye GRUPOS COMPARABLES: conjuntos de areas especificas
(viejas + nuevas) cuyo agregado si forma una serie continua de 11 ciclos. Cada
area especifica pertenece a exactamente un grupo, nunca se parte.

Tres fuentes de evidencia:

 1. FLUJO. Dentro de cada escuela-sede-nivel-modalidad se observan las areas
    especificas que desaparecen en 2016 y las que aparecen en 2017. Las
    marginales de esa tabla se ajustan por IPF (Sinkhorn) hacia un nucleo global
    de transicion, y el nucleo se reestima con los flujos acumulados: es un EM
    sobre un problema de inferencia ecologica. Los grupos escuela-sede con UNA
    sola categoria vieja y UNA sola nueva anclan la solucion porque ahi la
    reclasificacion es inequivoca.

 2. NOMBRE. Las areas especificas que conservan su nombre entre eras arrancan
    unidas (el catalogo nuevo renombro el Area y la Subarea pero no siempre el
    Area_especifica).

 3. CONTINUIDAD. El juez final. Un grupo se acepta si el cambio 2016->2017 de su
    serie nacional de NI no es anomalo frente a su propia volatilidad:

        |s[2017]/s[2016] - 1| <= 2.5 * mediana(|pct_change|) de los otros cruces

    Los grupos que no pasan se fusionan con el vecino de mayor flujo relativo
    hasta que pasen. Los que quedan aislados se marcan NO COMPARABLE, no se
    maquillan.

Salida: datos/concordancia_areas.parquet
Uso:    python concordancia.py               (grupos congelados, metricas al dia)
        python concordancia.py --reestimar   (reestima y reemplaza la particion)
API:    grupos_de(panel) agrega el panel por grupo comparable.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
FUENTE = RAIZ.parent / "data" / "Anuies_agregado_2014_2026.xlsx"
CACHE = RAIZ / "datos" / "flujo_reclasificacion.parquet"
SALIDA = RAIZ / "datos" / "concordancia_areas.parquet"
# Particion vigente, congelada. `construir` la usa en vez de reestimar; solo
# `python concordancia.py --reestimar` la reemplaza. Ver `grupos_congelados`.
GRUPOS = RAIZ / "datos" / "grupos_comparables.parquet"

# Ventana de estimacion, fija aunque la fuente traiga ciclos posteriores. El flujo
# compara lo que desaparece hasta 2016 contra lo que aparece "despues": cada ciclo
# nuevo mete ahi oferta que simplemente abrio ese anio, no reclasificacion. Con
# 2025-2026 adentro cambiaban 9 de 68 grupos (Biologia + Farmacia terminaban con
# los planes de ingenieria). Un ciclo que ya usa el catalogo nuevo no dice nada
# del quiebre de 2017, y todas sus areas especificas ya estan en esta ventana.
ANIOS = list(range(2014, 2025))
ULTIMO_VIEJO = 2016            # ultimo ciclo del catalogo anterior
COL_NI = [f"{a}_{a+1}_NI" for a in ANIOS]
CLAVE_OFERTA = ["Estado", "Municipio", "Escuela", "Sede", "Nivel_educativo", "Modalidad"]

# Umbrales del grafo semilla: una arista viejo->nuevo se acepta si concentra al
# menos T_ORIGEN del flujo que sale de la categoria vieja y al menos T_DESTINO
# del que entra a la nueva. Calibrados para maximizar el numero de grupos que
# pasan el criterio de continuidad (ver reporte).
T_ORIGEN = 0.25
T_DESTINO = 0.20
MIN_MASA = 500                 # NI minimo rastreado para confiar en una fila del flujo
TOLERANCIA = 2.5               # multiplo de la volatilidad propia que se admite
ITER_EM = 40
ITER_IPF = 60


# --------------------------------------------------------------------------- #
# 1. Lectura de la fuente cruda y estimacion del flujo de reclasificacion
# --------------------------------------------------------------------------- #
def cargar_crudo():
    cols = ["Area", "Subarea", "Area_especifica"] + CLAVE_OFERTA + COL_NI
    return pd.read_excel(FUENTE)[cols]


def catalogo(crudo):
    """Tabla (Area, Subarea, Area_especifica) con la era en que existe cada triple."""
    g = crudo.groupby(["Area", "Subarea", "Area_especifica"], dropna=False, observed=True)[COL_NI].sum()
    v = g[[c for c in COL_NI if int(c[:4]) <= ULTIMO_VIEJO]].sum(axis=1)
    n = g[[c for c in COL_NI if int(c[:4]) > ULTIMO_VIEJO]].sum(axis=1)
    era = np.where(n == 0, "viejo", np.where(v == 0, "nuevo", "ambos"))
    return g.reset_index().assign(era=era, ni_viejo=v.values, ni_nuevo=n.values)[
        ["Area", "Subarea", "Area_especifica", "era", "ni_viejo", "ni_nuevo"]]


def series_ae(crudo):
    """Serie anual nacional de NI por area especifica, mas su era."""
    s = crudo.groupby("Area_especifica", observed=True)[COL_NI].sum()
    s.columns = ANIOS
    v = s[[a for a in ANIOS if a <= ULTIMO_VIEJO]].sum(axis=1)
    n = s[[a for a in ANIOS if a > ULTIMO_VIEJO]].sum(axis=1)
    s["era"] = np.where(n == 0, "viejo", np.where(v == 0, "nuevo", "ambos"))
    return s


def estimar_flujo(crudo):
    """Matriz de flujo NI viejo -> categoria nueva, por EM sobre marginales locales.

    Devuelve un DataFrame largo (Area_especifica_viejo, Area_especifica_nuevo, ni).
    """
    d = crudo.copy()
    d["v"] = d[[c for c in COL_NI if int(c[:4]) <= ULTIMO_VIEJO]].sum(axis=1)
    d["n"] = d[[c for c in COL_NI if int(c[:4]) > ULTIMO_VIEJO]].sum(axis=1)
    d["oferta"] = d[CLAVE_OFERTA].astype(str).agg("|".join, axis=1)

    # Filas que solo tienen alumnos antes del corte: oferta que "desaparece".
    # Filas que solo los tienen despues: oferta que "aparece".
    baja = d[(d.v > 0) & (d.n == 0)]
    alta = d[(d.v == 0) & (d.n > 0)]
    vg = baja.groupby(["oferta", "Area_especifica"], observed=True)["v"].sum().reset_index()
    ng = alta.groupby(["oferta", "Area_especifica"], observed=True)["n"].sum().reset_index()

    comunes = set(vg.oferta) & set(ng.oferta)
    vg = vg[vg.oferta.isin(comunes)]
    ng = ng[ng.oferta.isin(comunes)]

    VIEJAS = sorted(vg.Area_especifica.unique())
    NUEVAS = sorted(ng.Area_especifica.unique())
    iv = {a: i for i, a in enumerate(VIEJAS)}
    inu = {a: i for i, a in enumerate(NUEVAS)}

    bloques = []
    porOferta = {k: v for k, v in ng.groupby("oferta", observed=True)}
    for oferta, a in vg.groupby("oferta", observed=True):
        b = porOferta[oferta]
        bloques.append((np.array([iv[x] for x in a.Area_especifica]), a.v.values.astype(float),
                        np.array([inu[x] for x in b.Area_especifica]), b.n.values.astype(float)))

    F = np.ones((len(VIEJAS), len(NUEVAS)))
    W = np.zeros_like(F)
    for _ in range(ITER_EM):
        W = np.zeros_like(F)
        for ii, vv, jj, nn in bloques:
            M = F[np.ix_(ii, jj)].copy()
            if M.sum() == 0:
                M = np.ones_like(M)
            r = vv / vv.sum()
            c = nn / nn.sum()
            for _ in range(ITER_IPF):           # IPF hacia las marginales locales
                rs = M.sum(1); rs[rs == 0] = 1; M *= (r / rs)[:, None]
                cs = M.sum(0); cs[cs == 0] = 1; M *= (c / cs)[None, :]
            W[np.ix_(ii, jj)] += M * vv.sum()
        Fn = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
        if np.abs(Fn - F / np.maximum(F.sum(1, keepdims=True), 1e-12)).max() < 1e-6:
            F = Fn
            break
        F = Fn

    filas = [(VIEJAS[i], NUEVAS[j], W[i, j])
             for i in range(len(VIEJAS)) for j in range(len(NUEVAS)) if W[i, j] > 0]
    return pd.DataFrame(filas, columns=["viejo", "nuevo", "ni"])


def _guardar_series(s, ruta):
    """Parquet exige nombres de columna homogeneos; los anios van como texto."""
    s.rename(columns={a: str(a) for a in ANIOS}).to_parquet(ruta)


def flujo(recalcular=False):
    """Flujo de reclasificacion, cacheado en datos/ porque leer el xlsx tarda minutos."""
    if CACHE.exists() and not recalcular:
        return pd.read_parquet(CACHE)
    crudo = cargar_crudo()
    f = estimar_flujo(crudo)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    f.to_parquet(CACHE, index=False)
    catalogo(crudo).to_parquet(CACHE.with_name("catalogo_areas.parquet"), index=False)
    _guardar_series(series_ae(crudo), CACHE.with_name("series_ae.parquet"))
    return f


def _auxiliares(recalcular=False):
    """Catalogo y series por area especifica, reconstruyendo el cache si falta."""
    cat = CACHE.with_name("catalogo_areas.parquet")
    ser = CACHE.with_name("series_ae.parquet")
    if recalcular or not (cat.exists() and ser.exists()):
        crudo = cargar_crudo()
        estimar_flujo(crudo).to_parquet(CACHE, index=False)
        catalogo(crudo).to_parquet(cat, index=False)
        _guardar_series(series_ae(crudo), ser)
    s = pd.read_parquet(ser)
    s.columns = [int(c) if str(c).isdigit() else c for c in s.columns]
    return pd.read_parquet(cat), s


# --------------------------------------------------------------------------- #
# 2. Criterio de continuidad
# --------------------------------------------------------------------------- #
def continuidad(serie):
    """(salto 2016->2017, volatilidad tipica, estado).

    estado: PASA, FALLA o SIN_TESTear (la serie tiene ceros: solo vive en una era).
    """
    s = np.asarray(serie, dtype=float)
    if s.min() <= 0:
        return np.nan, np.nan, "SIN_TEST"
    pct = s[1:] / s[:-1] - 1
    k = ULTIMO_VIEJO - ANIOS[0]                 # indice del cruce 2016->2017
    salto = pct[k]
    vol = float(np.median(np.abs(np.delete(pct, k))))
    return float(salto), vol, "PASA" if abs(salto) <= TOLERANCIA * vol else "FALLA"


# --------------------------------------------------------------------------- #
# 3. Construccion de los grupos comparables
# --------------------------------------------------------------------------- #
def grupos_congelados():
    """(grupos, evidencia, nombres) de la particion congelada, o None si no hay.

    La reestimacion es codiciosa y no es estable ante cambios chicos de datos:
    sumar Chiapas (2.3% del NI) movia 14 de los 68 grupos y subia los fragiles
    de 14 a 20, mientras la particion anterior seguia pasando completa la prueba
    de continuidad con Chiapas adentro (13 fragiles). La correspondencia entre
    catalogos es un hecho de los catalogos, no de que estado entra en la base, y
    un grupo que cambia de composicion en cada actualizacion deja de ser la
    misma serie para quien ya lo uso. Por eso se congela: cada corrida recalcula
    metricas y la prueba de continuidad sobre los datos vigentes, pero no la
    particion ni los nombres.
    """
    if not GRUPOS.exists():
        return None
    g = pd.read_parquet(GRUPOS)
    G = [list(x["Area_especifica"]) for _, x in g.groupby("grupo", sort=True)]
    evidencia = dict(zip(g["Area_especifica"], g["evidencia"]))
    nombres = {frozenset(x["Area_especifica"]): n for n, x in g.groupby("grupo")}
    return G, evidencia, nombres


_NOMBRES_FIJOS = {}


def construir(recalcular=False, reestimar=False):
    """Devuelve (grupos, series, catalogo, flujo, evidencia).

    Sin `reestimar`, los grupos y la evidencia salen de la particion congelada
    (`grupos_congelados`) si existe; series, catalogo y flujo siempre se leen de
    los datos vigentes.

    grupos: lista de listas de areas especificas.
    evidencia: dict area_especifica -> 'nombre' | 'flujo' | 'continuidad' | 'aislada'
    """
    f = flujo(recalcular)
    cat, ser = _auxiliares(recalcular)
    fijos = None if reestimar else grupos_congelados()
    if fijos is not None:
        G, evidencia, nombres = fijos
        faltan = set(ser.index) - {x for g in G for x in g}
        assert not faltan, f"areas sin grupo congelado, corre --reestimar: {sorted(faltan)}"
        _NOMBRES_FIJOS.clear()
        _NOMBRES_FIJOS.update(nombres)
        return G, ser, cat, f, evidencia
    _NOMBRES_FIJOS.clear()
    AE = list(ser.index)
    pos = {a: i for i, a in enumerate(AE)}
    S = ser[ANIOS].values.astype(float)

    VIEJAS = sorted(f.viejo.unique())
    NUEVAS = sorted(f.nuevo.unique())
    M = np.zeros((len(VIEJAS), len(NUEVAS)))
    iv = {a: i for i, a in enumerate(VIEJAS)}
    inu = {a: i for i, a in enumerate(NUEVAS)}
    for r in f.itertuples():
        M[iv[r.viejo], inu[r.nuevo]] = r.ni
    sale = M.sum(1)
    entra = M.sum(0)

    # Flujo simetrizado entre areas especificas y masa rastreada de cada una.
    L = np.zeros((len(AE), len(AE)))
    for a, i in iv.items():
        for b, j in inu.items():
            if M[i, j] > 0:
                L[pos[a], pos[b]] += M[i, j]
                L[pos[b], pos[a]] += M[i, j]
    masa = np.array([max(sale[iv[a]] if a in iv else 0.0, entra[inu[a]] if a in inu else 0.0)
                     for a in AE])

    def serie(grupo):
        return S[[pos[x] for x in grupo]].sum(0)

    # --- semilla: aristas de flujo significativas en los dos sentidos ---------
    # Las areas especificas que conservan el nombre entre eras ya estan unidas
    # porque son un solo nodo (la evidencia de nombre entra por ahi).
    padre = {a: a for a in AE}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    evidencia = {a: ("nombre" if ser.loc[a, "era"] == "ambos" else "aislada") for a in AE}
    for a, i in iv.items():
        if sale[i] < MIN_MASA:
            continue
        for b, j in inu.items():
            if M[i, j] <= 0 or entra[j] <= 0:
                continue
            if M[i, j] / sale[i] >= T_ORIGEN and M[i, j] / entra[j] >= T_DESTINO:
                padre[raiz(a)] = raiz(b)
                evidencia[a] = evidencia[b] = "flujo"

    comp = {}
    for a in AE:
        comp.setdefault(raiz(a), []).append(a)
    G = [sorted(v) for v in comp.values()]

    # --- fusion voraz de los grupos que no pasan -----------------------------
    aislados = set()
    for _ in range(1000):
        est = [continuidad(serie(g)) for g in G]
        malos = [k for k, e in enumerate(est) if e[2] != "PASA" and k not in aislados]
        if not malos:
            break
        malos.sort(key=lambda k: -serie(G[k]).sum())
        movio = False
        for k in malos:
            ik = [pos[x] for x in G[k]]
            cand = []
            for m in range(len(G)):
                if m == k:
                    continue
                im = [pos[x] for x in G[m]]
                fl = L[np.ix_(ik, im)].sum()
                if fl <= 0:
                    continue
                # flujo relativo al tamano del grupo mas chico: evita que todo
                # se fusione contra el grupo mas grande.
                sc = fl / max(min(masa[ik].sum(), masa[im].sum()), 1e-9)
                if est[m][2] != "PASA":
                    sc *= 50           # preferir no romper un grupo ya continuo
                cand.append((sc, m))
            if not cand:
                aislados.add(k)
                continue
            cand.sort(reverse=True)
            elegido = next((m for _, m in cand[:8] if continuidad(serie(G[k] + G[m]))[2] == "PASA"),
                           cand[0][1])
            a, b = min(k, elegido), max(k, elegido)
            for x in G[b]:
                if evidencia[x] == "aislada":
                    evidencia[x] = "continuidad"
            for x in G[a]:
                if evidencia[x] == "aislada":
                    evidencia[x] = "continuidad"
            G[a] = sorted(G[a] + G[b])
            G.pop(b)
            aislados = set()
            movio = True
            break
        if not movio:
            break

    # --- reubicacion: manda cada area al grupo con el que mas flujo comparte ---
    # La fusion voraz arrastra areas por continuidad, no por afinidad; esto las
    # devuelve a su grupo natural cuando el traslado no rompe ninguna serie.
    def afinidad(x, grupo):
        otros = [pos[y] for y in grupo if y != x]
        if not otros or masa[pos[x]] <= 0:
            return 0.0
        return L[pos[x], otros].sum() / masa[pos[x]]

    for _ in range(200):
        movio = False
        for k in range(len(G)):
            if len(G[k]) < 2:
                continue
            for x in G[k]:
                aqui = afinidad(x, G[k])
                mejor, sc = None, aqui
                for m in range(len(G)):
                    if m == k:
                        continue
                    a = afinidad(x, G[m] + [x])
                    if a > sc:
                        mejor, sc = m, a
                if mejor is None:
                    continue
                resto = [y for y in G[k] if y != x]
                if (continuidad(serie(resto))[2] == "PASA"
                        and continuidad(serie(G[mejor] + [x]))[2] == "PASA"):
                    G[k] = resto
                    G[mejor] = sorted(G[mejor] + [x])
                    evidencia[x] = "flujo"
                    movio = True
                    break
            if movio:
                break
        if not movio:
            break

    # --- pulido: separa las areas que solas ya forman una serie continua ------
    for _ in range(100):
        movio = False
        for k in range(len(G)):
            if len(G[k]) < 2:
                continue
            for x in sorted(G[k], key=lambda y: -S[pos[y]].sum()):
                resto = [y for y in G[k] if y != x]
                if (continuidad(serie([x]))[2] == "PASA"
                        and continuidad(serie(resto))[2] == "PASA"):
                    G[k] = resto
                    G.append([x])
                    if ser.loc[x, "era"] == "ambos":
                        evidencia[x] = "nombre"
                    movio = True
                    break
            if movio:
                break
        if not movio:
            break

    G.sort(key=lambda g: -serie(g).sum())

    # --- evidencia final por area especifica ---------------------------------
    # nombre     : el nombre sobrevivio al cambio de catalogo (vive en las dos eras)
    # flujo      : comparte flujo de reclasificacion medible con su grupo
    # continuidad: solo el criterio de continuidad la ubica; es la mas debil
    evidencia = {}
    for g in G:
        for x in g:
            otros = [pos[y] for y in g if y != x]
            comparte = (masa[pos[x]] > 0 and otros
                        and L[pos[x], otros].sum() / masa[pos[x]] >= 0.05)
            if ser.loc[x, "era"] == "ambos" and len(g) == 1:
                evidencia[x] = "nombre"
            elif comparte:
                evidencia[x] = "flujo"
            elif ser.loc[x, "era"] == "ambos":
                evidencia[x] = "nombre"
            else:
                evidencia[x] = "continuidad"
    return G, ser, cat, f, evidencia


def nombrar(grupo, ser):
    """Nombre del grupo en vocabulario del catalogo nuevo (el vigente)."""
    if frozenset(grupo) in _NOMBRES_FIJOS:
        return _NOMBRES_FIJOS[frozenset(grupo)]
    nuevas = [x for x in grupo if ser.loc[x, "era"] in ("nuevo", "ambos")]
    pool = nuevas or grupo
    cabeza = max(pool, key=lambda x: ser.loc[x, ANIOS[len(ANIOS) - 1]])
    if len(grupo) == 1 or cabeza.endswith("AFINES"):
        return cabeza
    return f"{cabeza} Y AFINES"


# --------------------------------------------------------------------------- #
# 4. Entregables
# --------------------------------------------------------------------------- #
def tabla_validacion(G, ser):
    filas = []
    for g in G:
        s = ser.loc[g, ANIOS].sum()
        salto, vol, est = continuidad(s.values)
        viejas = [x for x in g if ser.loc[x, "era"] == "viejo"]
        nuevas = [x for x in g if ser.loc[x, "era"] == "nuevo"]
        ambas = [x for x in g if ser.loc[x, "era"] == "ambos"]
        prev = s[[a for a in ANIOS if a <= ULTIMO_VIEJO]].mean()
        pnew = s[[a for a in ANIOS if a > ULTIMO_VIEJO]].mean()
        filas.append(dict(
            grupo=nombrar(g, ser), n_ae=len(g), n_viejas=len(viejas), n_nuevas=len(nuevas),
            n_ambas=len(ambas), ni_prom_viejo=round(prev), ni_prom_nuevo=round(pnew),
            salto_pct=round(salto * 100, 1) if salto == salto else np.nan,
            limite_pct=round(TOLERANCIA * vol * 100, 1) if vol == vol else np.nan,
            estado=est if est != "SIN_TEST" else "NO COMPARABLE",
            fragil=bool(est == "PASA" and abs(salto) > 1.5 * vol),
            viejas=" + ".join(sorted(viejas)), nuevas=" + ".join(sorted(nuevas + ambas))))
    return pd.DataFrame(filas)


def concordancia(recalcular=False, reestimar=False):
    """Tabla larga: una fila por triple del catalogo, con su grupo comparable."""
    G, ser, cat, f, evidencia = construir(recalcular, reestimar)
    grupo_de = {x: nombrar(g, ser) for g in G for x in g}
    estado = {}
    for g in G:
        est = continuidad(ser.loc[g, ANIOS].sum().values)[2]
        for x in g:
            estado[x] = est if est != "SIN_TEST" else "NO COMPARABLE"
    out = cat.copy()
    out["catalogo"] = out["era"]
    out["grupo"] = out.Area_especifica.map(grupo_de)
    out["evidencia"] = out.Area_especifica.map(evidencia)
    out["estado"] = out.Area_especifica.map(estado)
    return out[["catalogo", "Area", "Subarea", "Area_especifica", "grupo", "evidencia",
                "estado", "ni_viejo", "ni_nuevo"]].sort_values(["grupo", "catalogo", "Area_especifica"])


def grupos_de(panel, conc=None, dims=None, metricas=("Matricula", "NI", "Egresados", "Sols_NI")):
    """Agrega el panel por grupo comparable.

    El grupo es una particion de Area_especifica, asi que el cruce es por esa
    sola columna. Las columnas Subarea y Area_especifica se reemplazan por
    'grupo'; el resto de las dimensiones se conserva (o las que se pidan en
    dims). Las areas de grupos NO COMPARABLE se conservan con su etiqueta para
    que la app pueda excluirlas explicitamente.
    """
    if conc is None:
        conc = pd.read_parquet(SALIDA) if SALIDA.exists() else concordancia()
    mapa = conc.drop_duplicates("Area_especifica").set_index("Area_especifica")
    df = panel.copy()
    ae = df["Area_especifica"].astype(str)
    df["grupo"] = ae.map(mapa["grupo"]).fillna("SIN CLASIFICAR")
    df["estado_grupo"] = ae.map(mapa["estado"]).fillna("NO COMPARABLE")
    if dims is None:
        dims = [c for c in df.columns
                if c not in list(metricas) + ["Subarea", "Area_especifica", "Area_2014"]]
    mets = [m for m in metricas if m in df.columns]
    return df.groupby(dims, dropna=False, observed=True)[mets].sum().reset_index()


def main():
    import sys
    reestimar = "--reestimar" in sys.argv
    G, ser, cat, f, evidencia = construir(reestimar=reestimar)
    tab = tabla_validacion(G, ser)
    conc = concordancia(reestimar=reestimar)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    conc.to_parquet(SALIDA, index=False)
    if reestimar or not GRUPOS.exists():
        (conc.drop_duplicates("Area_especifica")[["Area_especifica", "grupo", "evidencia"]]
             .to_parquet(GRUPOS, index=False))
        print(f"particion {'reestimada' if reestimar else 'inicial'} congelada en {GRUPOS}")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 300)
    pd.set_option("display.max_colwidth", 70)

    ni_tot = ser[ANIOS].values.sum()
    pasa = tab[tab.estado == "PASA"]
    ni_pasa = sum(ser.loc[g, ANIOS].values.sum() for g in G
                  if continuidad(ser.loc[g, ANIOS].sum().values)[2] == "PASA")

    print("=" * 110)
    print("CONCORDANCIA DE AREAS ANUIES  (catalogo anterior <-> CINE-F 2013)")
    print("=" * 110)
    print(f"areas especificas       : {len(ser)}  "
          f"(viejas {int((ser.era=='viejo').sum())}, nuevas {int((ser.era=='nuevo').sum())}, "
          f"en ambas {int((ser.era=='ambos').sum())})")
    print(f"triples del catalogo    : {len(cat)}")
    print(f"grupos comparables      : {len(tab)}   pasan {len(pasa)}   "
          f"no comparables {int((tab.estado!='PASA').sum())}")
    print(f"NI en grupos que pasan  : {ni_pasa/ni_tot*100:.1f}%")
    print(f"grupos marginales       : {int(tab.fragil.sum())} (pasan pero el salto supera 1.5x su volatilidad)")
    print(f"\nguardado en {SALIDA}\n")

    print("-" * 110)
    print("VALIDACION POR GRUPO")
    print("-" * 110)
    for _, r in tab.iterrows():
        marca = r.estado + (" (fragil)" if r.fragil else "")
        print(f"\n[{r.n_ae} AE] {r.grupo}")
        print(f"    NI/anio  2014-2016 {r.ni_prom_viejo:>9,.0f}   2017-{ANIOS[-1]} {r.ni_prom_nuevo:>9,.0f}"
              f"   salto 2016->2017 {r.salto_pct:+.1f}%  limite {r.limite_pct:.1f}%   {marca}")
        if r.viejas:
            print(f"    viejas : {r.viejas[:260]}")
        if r.nuevas:
            print(f"    vigentes: {r.nuevas[:260]}")

    print("\n" + "-" * 110)
    print("RESUMEN")
    print("-" * 110)
    print(tab[["grupo", "n_ae", "n_viejas", "n_nuevas", "n_ambas", "ni_prom_viejo",
               "ni_prom_nuevo", "salto_pct", "limite_pct", "estado", "fragil"]].to_string(index=False))


if __name__ == "__main__":
    main()
