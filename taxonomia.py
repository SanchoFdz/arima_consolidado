# -*- coding: utf-8 -*-
"""Los dos quiebres de la fuente ANUIES, y como no proyectar encima de ellos.

Son dos, y conviene no confundirlos porque piden avisos distintos:

  * **Quiebre de CATALOGO** (ciclo 2017-2018). Cambio el catalogo de areas. Es
     un problema de disciplina: afecta `Subarea` y `Area_especifica`, y de
     rebote al nivel area porque el catalogo nuevo movio programas entre areas.
     Todo el resto de este docstring va de este.
  * **Quiebre de REPORTE** (ciclo 2023-2024). ANUIES empezo a desglosar MIXTA
     (y DUAL) como modalidades propias. Es un problema de modalidad, no de
     areas: no se reclasifico ninguna carrera, se partio en dos una columna que
     antes venia junta. Verificado sobre el panel: NO ESCOLARIZADA sola pasa de
     356,200 a 184,576 de nuevo ingreso nacional entre 2022-2023 y 2023-2024
     (-48.2%) mientras NO ESCOLARIZADA + MIXTA pasa de 356,200 a 379,985
     (+6.7%), luego a 432,140 (+13.7%) y a 477,639 (+10.5%). No se fue un solo
     alumno: MIXTA es el 51.4% del online ese ciclo, 51.3% el siguiente y 47.0%
     en 2025-2026. Ver `NOTA_MODALIDAD`.

Hasta antes de esto el modulo trataba cualquier serie que arrancara en o
despues de 2017 como artefacto del catalogo de areas, y a una serie de MIXTA
—que arranca en 2023— le estampaba un texto factualmente falso sobre el
catalogo de 2017-2018. De ahi que los ciclos de quiebre esten nombrados y que
cada uno traiga su propio texto.

---

El cambio de catalogo ANUIES de 2017, y como no proyectar encima de el.

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

CICLO_CAMBIO = 2017      # cambio de catalogo de areas
CICLO_MODALIDAD = 2023   # ANUIES empieza a desglosar MIXTA y DUAL

# Areas cuyo nivel-area quedo con quiebre porque el catalogo nuevo movio
# programas entre ellas. Verificado sobre el panel: sumadas dan una serie
# continua, separadas no.
AREAS_CON_TRASVASE = {
    "CIENCIAS NATURALES, EXACTAS Y DE LA COMPUTACIÓN",
    "INGENIERÍA, MANUFACTURA Y CONSTRUCCIÓN",
}

NOTA_AREA = (
    "Estas dos áreas no son comparables por separado a lo largo de toda la serie: "
    "en 2017-2018 ANUIES movió las carreras de tecnologías de la información de "
    "**Ingeniería** a **Ciencias naturales, exactas y de la computación**. Por eso "
    "computación salta +80% y ingeniería cae -18% justo en ese ciclo, sin que "
    "cambiara la matrícula real. Seleccionando **las dos áreas juntas** la serie sí "
    "es comparable (-2.0% en ese mismo cruce)."
)

# --------------------------------------------------------------- modalidad
# El equivalente exacto de AREAS_CON_TRASVASE, un ciclo distinto y otra columna:
# estas dos modalidades por separado no son comparables en toda la serie, y
# sumadas si. Vive aqui y no en comun.py porque es un hecho de la fuente, no una
# preferencia de la interfaz, y porque asi lo pueden importar los scripts de
# validacion sin arrastrar streamlit.
MODALIDADES_ONLINE = ["NO ESCOLARIZADA", "MIXTA"]

# Modalidades que solo existen desde CICLO_MODALIDAD. Cualquier serie suya tiene
# pocos ciclos, no la serie completa, y eso no es un hueco de mercado.
MODALIDADES_NUEVAS = {"MIXTA", "DUAL"}

NOTA_MODALIDAD = (
    "**NO ESCOLARIZADA sola no es comparable a lo largo de toda la serie.** En el "
    "ciclo 2023-2024 ANUIES empezó a reportar **MIXTA** como modalidad propia y esa "
    "matrícula salió casi toda de aquí: nacionalmente NO ESCOLARIZADA pasa de "
    "356,200 a 184,576 de nuevo ingreso (**-48.2%**) sin que se fuera un solo "
    "alumno, y al ciclo siguiente rebota +13.9%. Ese -48% es reclasificación, no "
    "mercado, y una proyección montada sobre él arrastra el escalón. "
    "**Marca también MIXTA** —o elige la opción *Online (no escolarizada + "
    "mixta)*, que es exactamente esa suma—: 356,200 → 379,985 → 432,140 → 477,639, "
    "es decir +6.7%, +13.7% y +10.5%, que sí es la serie de modalidad comparable "
    "en toda la serie."
)

# Textos del detector de quiebres, uno por ciclo. Separados de la logica porque
# lo que cambia entre un quiebre y otro es la explicacion, no la prueba.
QUIEBRES = {
    CICLO_CAMBIO: {
        "cruce": "2016-2017 y 2017-2018",
        "alto": ("Ese es el ciclo en que ANUIES cambió de catálogo de áreas, y un "
                 "salto de ese tamaño ahí es reclasificación, no mercado. No uses "
                 "esta serie para proyectar sin revisarla."),
        "leve": ("Pasa el criterio de comparabilidad entre los dos catálogos de "
                 "áreas, pero lo pasa porque su propia volatilidad es alta, no "
                 "porque el cruce esté limpio. Toma la proyección con reserva."),
    },
    CICLO_MODALIDAD: {
        "cruce": "2022-2023 y 2023-2024",
        "alto": ("Ese es el ciclo en que ANUIES empezó a reportar MIXTA (y DUAL) "
                 "por separado, y esa matrícula salió casi toda de NO ESCOLARIZADA: "
                 "nacionalmente la serie de NO ESCOLARIZADA sola cae -48.2% ahí sin "
                 "perder un alumno. Si este corte incluye NO ESCOLARIZADA sin "
                 "MIXTA, el salto es reclasificación: súmalas. Si no la incluye, "
                 "revisa la serie antes de proyectarla."),
        "leve": ("Es el cruce en que ANUIES separó MIXTA de NO ESCOLARIZADA, así "
                 "que conviene descartar que el movimiento sea de reporte antes de "
                 "leerlo como mercado. Toma la proyección con reserva."),
    },
}


def recortar(serie):
    """Deja la serie en los ciclos donde la categoria existe, y explica el recorte.

    Devuelve (serie, aviso). Los ceros que se quitan son los de las puntas: una
    categoria que arranca en 2017 no tenia cero alumnos en 2014, no existia en el
    catalogo. Los ceros de en medio se respetan, porque ahi si son informacion.

    El aviso se elige por el ciclo EXACTO en que arranca o termina la serie, no
    por un ">= 2017". La version anterior estampaba el texto del catalogo de
    areas a cualquier serie que empezara en 2017 o despues, asi que a MIXTA y a
    DUAL —que arrancan en 2023-2024, por el desglose de modalidad— les decia que
    eran categorias del catalogo nuevo de areas. Falso y desorientador: no hay
    ninguna carrera reclasificada detras, hay una columna que se partio en dos.
    Fuera de los dos ciclos conocidos el aviso es descriptivo y no atribuye causa,
    que es lo unico honesto que se puede decir de un hueco cualquiera.
    """
    if serie.empty or (serie > 0).sum() == 0:
        return serie, None
    vivos = serie[serie > 0].index
    ini, fin = int(min(vivos)), int(max(vivos))
    if ini == int(serie.index.min()) and fin == int(serie.index.max()):
        return serie, None

    recortada = serie.loc[ini:fin]
    perdidos = len(serie) - len(recortada)
    arranca_tarde = ini > int(serie.index.min())
    termina_antes = fin < int(serie.index.max())

    if arranca_tarde and ini == CICLO_MODALIDAD:
        aviso = (f"Esta modalidad no existía como categoría propia antes de "
                 f"{CICLO_MODALIDAD}-{CICLO_MODALIDAD + 1}: la serie arranca ahí y "
                 f"son {len(recortada)} ciclos, no {len(serie)}. No es un cambio del catálogo "
                 f"de áreas, es que ANUIES empezó a desglosar **MIXTA** y **DUAL** "
                 f"ese ciclo; antes esa matrícula venía dentro de otra modalidad "
                 f"—la de MIXTA, dentro de NO ESCOLARIZADA—. Los "
                 f"{perdidos} ciclos anteriores no son ceros de mercado.")
    elif arranca_tarde and ini == CICLO_CAMBIO:
        aviso = (f"Esta categoría solo existe en el catálogo ANUIES vigente desde "
                 f"{CICLO_CAMBIO}-{CICLO_CAMBIO + 1}: la serie arranca ahí y son "
                 f"{len(recortada)} ciclos, no {len(serie)}. Los {perdidos} ciclos anteriores "
                 f"no son ceros, es que la categoría no existía — bajo el catálogo "
                 f"anterior esa matrícula estaba repartida en otras categorías.")
    elif termina_antes and fin == CICLO_CAMBIO - 1:
        aviso = (f"Esta categoría desapareció del catálogo ANUIES en "
                 f"{CICLO_CAMBIO}-{CICLO_CAMBIO + 1}: la serie termina en "
                 f"{fin}-{fin + 1} y son {len(recortada)} ciclos. No es que la "
                 f"matrícula se haya ido a cero; se reclasificó en las categorías "
                 f"del catálogo nuevo.")
    else:
        aviso = (f"La serie se recortó a {ini}-{ini + 1} … {fin}-{fin + 1} "
                 f"({len(recortada)} ciclos de {len(serie)}): fuera de ese rango el "
                 f"corte no reporta alumnos. No coincide con ninguno de los dos "
                 f"quiebres conocidos de la fuente, así que puede ser oferta que "
                 f"abrió o cerró de verdad.")
    return recortada, aviso


def _quiebre_en(serie, ciclo, factor, factor_leve):
    """Prueba de quiebre en un cruce concreto. Devuelve (severidad, texto) o None.

    La prueba es contra la propia serie: se compara el cambio de ese cruce con la
    mediana de los cambios de los demas cruces. Es el mismo criterio con el que
    `concordancia.py` acepta o rechaza un grupo comparable, y aqui se aplica a la
    serie del corte que de verdad esta en pantalla --- que puede ser un grupo
    cruzado con una zona chica y una modalidad, donde la continuidad del grupo
    nacional ya no garantiza nada.

    Dos niveles, porque hay dos cosas distintas que decir. Arriba de `factor`, lo
    que se esta viendo es estructura de la fuente y no mercado. Entre
    `factor_leve` y `factor`, el corte es de los que la concordancia marca
    fragiles: pasa el criterio, pero pasa porque su propia serie es tan ruidosa
    que el criterio no tiene poder para rechazarlo. Eso ultimo no es un error, es
    una advertencia de confianza.
    """
    if ciclo not in serie.index or (ciclo - 1) not in serie.index:
        return None
    y = serie.astype(float)
    if len(y) < 5 or (y <= 0).any():
        return None
    cambios = y.pct_change().dropna().abs()
    salto = abs(float(y.loc[ciclo] / y.loc[ciclo - 1] - 1))
    resto = cambios.drop(index=ciclo, errors="ignore")
    tipico = float(np.median(resto)) if len(resto) else np.nan
    if not np.isfinite(tipico) or tipico <= 0 or salto < factor_leve * tipico:
        return None

    textos = QUIEBRES[ciclo]
    direccion = "sube" if y.loc[ciclo] > y.loc[ciclo - 1] else "baja"
    medida = (f"{direccion} {salto * 100:.0f}% entre {textos['cruce']}, contra un "
              f"cambio típico de {tipico * 100:.0f}% en los demás ciclos")
    if salto >= factor * tipico:
        return "alto", f"Este corte {medida}. {textos['alto']}"
    return "leve", f"Serie ruidosa en el cruce {textos['cruce']}: {medida}. {textos['leve']}"


def quiebres(serie, factor=2.5, factor_leve=1.5):
    """Red de seguridad sobre la serie que esta en pantalla. Lista de (severidad, texto).

    Se evaluan los DOS cruces conocidos, no solo el del catalogo de areas. El de
    2022->2023 no estaba cubierto y es exactamente el mismo tipo de red: un corte
    filtrado por NO ESCOLARIZADA sin MIXTA cae -40% ahi por reclasificacion pura,
    y hasta ahora la app lo proyectaba sin decir nada. La prueba es la misma y es
    barata, asi que no hay razon para mirar solo un cruce.

    Se devuelve lista y no el peor de los dos porque un corte puede tener los dos
    quiebres —un grupo comparable fragil cruzado con NO ESCOLARIZADA— y son dos
    cosas distintas que arreglar.
    """
    salida = []
    for ciclo in QUIEBRES:
        hallazgo = _quiebre_en(serie, ciclo, factor, factor_leve)
        if hallazgo:
            salida.append(hallazgo)
    return salida


def nota_trasvase(areas):
    """Aviso cuando se selecciona una sola de las dos areas que intercambiaron TIC."""
    sel = set(map(str, areas or []))
    return NOTA_AREA if len(sel & AREAS_CON_TRASVASE) == 1 else None


def nota_modalidad(modalidades):
    """Aviso cuando se pide NO ESCOLARIZADA sin MIXTA. Gemelo de `nota_trasvase`.

    Recibe modalidades BASE ya normalizadas (`comun.normalizar_modalidades`), de
    modo que elegir el atajo "Online (no escolarizada + mixta)" —que se expande a
    las dos— no dispara el aviso, igual que no lo dispara marcar las dos casillas.

    A diferencia de `quiebres`, esto no mira los datos: mira la seleccion. Es
    deterministico y se dispara tambien en cortes chicos donde la prueba
    estadistica no tendria potencia para detectar nada.
    """
    sel = set(map(str, modalidades or []))
    if "NO ESCOLARIZADA" in sel and "MIXTA" not in sel:
        return NOTA_MODALIDAD
    return None


def padre_de_modalidades(modalidades):
    """De que serie continua salio un corte de modalidad nueva.

    MIXTA y DUAL arrancan en 2023-2024 y no hay forma de proyectarlas directo:
    son 2 observaciones. Pero si hay una serie continua que las contiene, y es la
    referencia con la que se leen —y, si el volumen aguanta, con la que se
    derivan, ver `pronostico.derivar_por_share`—.

    Devuelve `(modalidades_del_padre, etiqueta)` o None si el corte no es una
    modalidad de reporte nuevo. `modalidades_del_padre = None` significa "sin
    filtro de modalidad", o sea el total del corte.

      * MIXTA -> Online (NO ESCOLARIZADA + MIXTA). Es de donde salio: el desglose
        de 2023-2024 partio esa columna en dos, asi que la suma es continua.
      * DUAL (sola o con MIXTA) -> el total de todas las modalidades. DUAL son
        115 y 196 alumnos nacionales; de donde salieron exactamente no esta
        documentado en la fuente y no se va a inventar, asi que el padre honesto
        es el agregado que con seguridad la contiene.
      * Cualquier seleccion que incluya ESCOLARIZADA o NO ESCOLARIZADA no tiene
        padre: esas series ya cubren todos los ciclos por si mismas.
    """
    sel = set(map(str, modalidades or []))
    if not sel or not sel <= MODALIDADES_NUEVAS:
        return None
    if sel == {"MIXTA"}:
        return list(MODALIDADES_ONLINE), "Online (no escolarizada + mixta)"
    return None, "Todas las modalidades"
