# -*- coding: utf-8 -*-
"""El cambio de catalogo ANUIES de 2017, y como no proyectar encima de el.

ANUIES cambio de catalogo de areas en el ciclo 2017-2018. `preparar_datos.py`
homologa el nivel AREA mapeando nombre viejo a nombre nuevo, y con eso la serie
por area deja de romperse. Pero solo el nivel area: `Subarea` y
`Area_especifica` siguen cargando los dos catalogos revueltos, y ahi el cambio
no fue de nombres sino de estructura.

Lo que eso produce en pantalla, si nadie lo atrapa: seleccionas la subarea
"CIENCIAS DE LA COMPUTACION" --- que existe solo hasta 2016 --- y la app dibuja
tres ciclos con datos, ocho ceros, y encima te proyecta el cero. O seleccionas
"DESARROLLO DE SOFTWARE", que existe solo desde 2017, y la serie arranca con
tres ceros que el extrapolador lee como crecimiento explosivo.

Por que no se homologa y ya: se intento reconstruir la correspondencia con los
propios datos, rastreando programas reclasificados por escuela + sede + nivel +
modalidad. Donde hay volumen el metodo se valida solo (DERECHO -> DERECHO 99.2%,
MEDICINA -> MEDICINA GENERAL 73%, SALUD MULTIDISCIPLINARIOS -> MEDICINA DE
ESPECIALIDAD 99.6%). Pero en la rama de computo los casos inequivocos suman 423
alumnos de nuevo ingreso: esas carreras casi siempre se ofrecen junto a otras en
la misma escuela, asi que no hay pareja limpia que rastrear. Una concordancia
inventada a nivel hoja seria peor que un corte visible, porque quedaria dentro
del numero.

Ademas el cambio movio programas ENTRE areas, no solo dentro: las TIC pasaron de
INGENIERIA a CIENCIAS NATURALES, EXACTAS Y DE LA COMPUTACION. Por eso en 2017
computo salta +66% y ingenieria cae -19%, aunque las dos esten "homologadas" por
nombre. Sumadas, las dos areas si son comparables (-3.2% en el mismo corte), y
eso es lo que dice `NOTA_AREA`.

Asi que este modulo no arregla el catalogo. Hace que el catalogo no pueda
mentirte: recorta la serie a los ciclos donde la categoria existe de verdad, y
avisa cuando lo que estas viendo tiene un quiebre de catalogo debajo.
"""
import numpy as np

CICLO_CAMBIO = 2017

# Areas cuyo nivel-area quedo con quiebre porque el catalogo nuevo movio
# programas entre ellas. Verificado sobre el panel: sumadas dan una serie
# continua, separadas no.
AREAS_CON_TRASVASE = {
    "CIENCIAS NATURALES, EXACTAS Y DE LA COMPUTACIÓN",
    "INGENIERÍA, MANUFACTURA Y CONSTRUCCIÓN",
}

NOTA_AREA = (
    "Estas dos áreas no son comparables por separado a lo largo de los 11 ciclos: "
    "en 2017-2018 ANUIES movió las carreras de tecnologías de la información de "
    "**Ingeniería** a **Ciencias naturales, exactas y de la computación**. Por eso "
    "computación salta +66% y ingeniería cae -19% justo en ese ciclo, sin que "
    "cambiara la matrícula real. Seleccionando **las dos áreas juntas** la serie sí "
    "es comparable (-3.2% en ese mismo cruce)."
)


def recortar(serie):
    """Deja la serie en los ciclos donde la categoria existe, y explica el recorte.

    Devuelve (serie, aviso). Los ceros que se quitan son los de las puntas: una
    categoria que arranca en 2017 no tenia cero alumnos en 2014, no existia en el
    catalogo. Los ceros de en medio se respetan, porque ahi si son informacion.
    """
    if serie.empty or (serie > 0).sum() == 0:
        return serie, None
    vivos = serie[serie > 0].index
    ini, fin = int(min(vivos)), int(max(vivos))
    if ini == int(serie.index.min()) and fin == int(serie.index.max()):
        return serie, None

    recortada = serie.loc[ini:fin]
    perdidos = len(serie) - len(recortada)
    if ini >= CICLO_CAMBIO:
        aviso = (f"Esta categoría solo existe en el catálogo ANUIES vigente desde "
                 f"2017-2018: la serie arranca en {ini}-{ini + 1} y son "
                 f"{len(recortada)} ciclos, no 11. Los {perdidos} ciclos anteriores "
                 f"no son ceros, es que la categoría no existía — bajo el catálogo "
                 f"anterior esa matrícula estaba repartida en otras categorías.")
    elif fin < serie.index.max():
        aviso = (f"Esta categoría desapareció del catálogo ANUIES en 2017-2018: "
                 f"la serie termina en {fin}-{fin + 1} y son {len(recortada)} "
                 f"ciclos. No es que la matrícula se haya ido a cero; se reclasificó "
                 f"en las categorías del catálogo nuevo.")
    else:
        aviso = (f"La serie se recortó a {ini}-{ini + 1} … {fin}-{fin + 1}: "
                 f"fuera de ese rango la categoría no reporta alumnos.")
    return recortada, aviso


def quiebre_de_catalogo(serie, factor=2.5, factor_leve=1.5):
    """Detecta un salto anomalo en 2016->2017, que es donde cambio el catalogo.

    La prueba es contra la propia serie: se compara el cambio de ese cruce con la
    mediana de los cambios de los demas cruces. Es el mismo criterio con el que
    `concordancia.py` acepta o rechaza un grupo comparable, y aqui se aplica a la
    serie del corte que de verdad esta en pantalla --- que puede ser un grupo
    cruzado con una zona chica y una modalidad, donde la continuidad del grupo
    nacional ya no garantiza nada.

    Dos niveles, porque hay dos cosas distintas que decir. Arriba de `factor`, lo
    que se esta viendo es catalogo y no mercado. Entre `factor_leve` y `factor`,
    el corte es de los que la concordancia marca fragiles: pasa el criterio, pero
    pasa porque su propia serie es tan ruidosa que el criterio no tiene poder
    para rechazarlo. Eso ultimo no es un error, es una advertencia de confianza.

    Devuelve (severidad, texto) o None. severidad: "alto" o "leve".
    """
    if CICLO_CAMBIO not in serie.index or (CICLO_CAMBIO - 1) not in serie.index:
        return None
    y = serie.astype(float)
    if len(y) < 5 or (y <= 0).any():
        return None
    cambios = y.pct_change().dropna().abs()
    salto = abs(float(y.loc[CICLO_CAMBIO] / y.loc[CICLO_CAMBIO - 1] - 1))
    resto = cambios.drop(index=CICLO_CAMBIO, errors="ignore")
    tipico = float(np.median(resto)) if len(resto) else np.nan
    if not np.isfinite(tipico) or tipico <= 0 or salto < factor_leve * tipico:
        return None
    direccion = "sube" if y.loc[CICLO_CAMBIO] > y.loc[CICLO_CAMBIO - 1] else "baja"
    medida = (f"{direccion} {salto * 100:.0f}% entre 2016-2017 y 2017-2018, contra un "
              f"cambio típico de {tipico * 100:.0f}% en los demás ciclos")

    if salto >= factor * tipico:
        return "alto", (
            f"Este corte {medida}. Ese es el ciclo en que ANUIES cambió de catálogo "
            f"de áreas, y un salto de ese tamaño ahí es reclasificación, no mercado. "
            f"No uses esta serie para proyectar sin revisarla.")
    return "leve", (
        f"Serie ruidosa en el cruce del cambio de catálogo: {medida}. Pasa el "
        f"criterio de comparabilidad, pero lo pasa porque su propia volatilidad es "
        f"alta, no porque el cruce esté limpio. Toma la proyección con reserva.")


def nota_trasvase(areas):
    """Aviso cuando se selecciona una sola de las dos areas que intercambiaron TIC."""
    sel = set(map(str, areas or []))
    return NOTA_AREA if len(sel & AREAS_CON_TRASVASE) == 1 else None
