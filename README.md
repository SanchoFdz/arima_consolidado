# Tendencias de Nuevo Ingreso

App de Streamlit para que el equipo de finanzas tome la tendencia proyectada de
nuevo ingreso (NI) de cualquier corte del mercado y la meta en sus modelos.

## Correr

```bash
pip install -r requirements.txt
streamlit run app.py
```

El panel ya procesado (`datos/panel_ni.parquet`) y los panels de datos externos
vienen en el repo, así que la app arranca sin más. Las fuentes en bruto no están
versionadas (la de ANUIES pesa 25 MB, la de CONAPO 23 MB). Para regenerarlas:

```bash
python preparar_datos.py   # necesita Anuies_agregado_2014_2025.xlsx en ../data/
python externos.py         # necesita series_historicas/ y ../data/Indice de Rezago Social/
python rezago.py           # reestima la elasticidad transversal del rezago
```

### Deploy en Streamlit Community Cloud

Apuntar a este repo, rama `main`, archivo principal `app.py`. No necesita
secretos ni variables de entorno. El tema claro viene en `.streamlit/config.toml`.

## Qué hace

- **Página principal**: eliges un corte y devuelve la serie 2014-2025, la
  proyección con intervalo, y la descarga en CSV/Excel. Debajo, la sección
  *"Contra qué corre esta proyección"*: demografía CONAPO del corte, tasa de
  captación y rezago social. Es lectura, no configuración — los datos externos
  no entran al número (ver más abajo).
- **Descarga masiva**: proyecta todas las categorías de una dimensión —o de un
  cruce de hasta tres— y entrega un solo Excel. Una dimensión da las 15 zonas
  metropolitanas; tres dan región Nielsen × campo de conocimiento × nivel. El
  cruce solo genera las combinaciones que existen en los datos, no el producto
  cartesiano, y trae el mismo contexto demográfico por fila siempre que alguna
  de las tres dimensiones sea geográfica.
- **Glosario**: qué municipios integran cada zona metropolitana y qué estados
  cada región Nielsen. Es solo la definición, sin controles ni modelo: el número
  de una ZM no se puede discutir sin saber qué municipios entraron.

Cortes disponibles:

| Dimensión | Valores |
|---|---|
| Geográfico | Nacional · Región Nielsen · Área Nielsen · **Zona metropolitana** · Estado · Municipio |
| Nivel educativo | TSU, Licenciatura, Normal, Especialidad, Maestría, Doctorado |
| Modalidad | **Online (no escolarizada + mixta)** · Escolarizada · No escolarizada · Mixta · Dual (multiselect: se combinan libremente) |
| Disciplina | Campo de conocimiento → Carrera o grupo de carreras (69 grupos comparables) |
| Métrica | NI · Matrícula · Egresados · Solicitudes |

**Modalidad es multiselect, y la primera opción es un agregador.** Las opciones
son las cuatro modalidades base del panel más *"Online (no escolarizada +
mixta)"*, que se expande a esas dos; se combinan libremente (una, dos o las que
sean) y vacío = todas sumadas. Elegir el agregador y marcar las dos casillas
producen literalmente el mismo filtro —`normalizar_modalidades` traduce el
compuesto a sus modalidades base antes de filtrar, así que es la misma clave de
caché y el mismo número—; verificado: 192,786 filas y 3,878,794 de NI en los dos
caminos, y el render completo de la página idéntico campo por campo.

El agregador **se había quitado** al pasar a multiselect, con el argumento de que
se arma marcando dos casillas y tener el mismo corte con dos nombres invita a
reportar cifras que parecen de universos diferentes. **El argumento estaba
equivocado** y se revirtió. Ver la sección de abajo: no es un atajo de
conveniencia, es la única serie de modalidad comparable en los 11 ciclos.

## Decisiones que conviene conocer antes de usar los números

**Taxonomía: los cortes por disciplina son grupos comparables, no el catálogo.**
ANUIES cambió de catálogo en el ciclo 2017-2018, y no fue un cambio de nombres:
fue de estructura. De 38 subáreas, 10 existen solo hasta 2016 y 16 solo desde
2017; de 171 áreas específicas, 53 y 84. "Ciencias de la computación" desaparece
ese año y aparecen "Desarrollo de software", "Informática", "Ciencias
computacionales", "Soporte y servicios…". Y el catálogo movió programas *entre*
áreas, así que ni el nivel área se salvaba con mapear nombres: en 2017
computación saltaba +66% e ingeniería caía -19% sin que cambiara la matrícula.

La app no expone esas columnas. Expone **69 grupos comparables** construidos por
`concordancia.py`: cada grupo junta las categorías viejas y nuevas que se
corresponden, de modo que su agregado sí es una serie continua de 11 ciclos. El
criterio de aceptación es explícito y es lo único que decide:

```
|s[2017]/s[2016] - 1|  <=  2.5 × mediana(|cambio anual|) de los otros 9 cruces
```

Los 69 grupos pasan, cubren las 171 áreas específicas y el 100% del NI, y no
quedaron categorías huérfanas. El **campo de conocimiento** se reconstruye
sumando grupos, y eso arregla de paso el nivel área: computación queda en +5.0%
e ingeniería en +0.8% en ese cruce.

| | catálogo crudo | grupos comparables |
|---|---|---|
| Series nacionales con 11 ciclos | 34 de 171 áreas específicas (20%) | **69 de 69 (100%)** |
| Series zona metropolitana × corte | 278 de 1,723 (16%) | **597 de 786 (76%)** |

Granularidad: 19 grupos son de una sola área específica (Derecho, Psicología,
Contabilidad, Arquitectura…), 26 de dos, 14 de tres; el más grueso tiene 10 y
concentra 11.1% del NI.

**Cómo se construyó la correspondencia.** Con los propios datos, no con criterio.
Cuando ANUIES reclasificó un programa, la fuente lo deja como dos filas en la
misma escuela + sede + nivel + modalidad: una con datos solo hasta 2016 y otra
solo desde 2017. Eso permite rastrear a dónde fue cada categoría. Dos intentos
previos fallaron y vale registrarlos: el reparto proporcional dentro de la
escuela rastreaba 63% del NI pero producía ruido (hacía que "ciencias de la
computación" se fuera 9.8% a Derecho y 6.1% a Nutrición, porque le daba crédito
a toda la oferta del plantel); restringirlo a escuelas con exactamente una
categoría vieja y una nueva daba flujos limpios pero cubría 8.4% del NI, y en la
rama de cómputo apenas 423 alumnos.

Lo que funcionó fue inferencia ecológica por EM: IPF (Sinkhorn) de las marginales
locales de cada escuela contra un núcleo global de transición, reestimado 40
veces. Los casos inequívocos son puntos fijos del IPF, así que anclan la
solución en vez de que el resto se reparta a ciegas. Cobertura: **63% del NI
viejo** con flujos ya no ruidosos. La validación cruzada contra los casos donde
la respuesta ya se conocía da correlación de shares **0.951** (n=3,414) y destino
modal coincidente en **43 de 48** áreas viejas (93% ponderado por NI): Derecho →
Derecho, Medicina → Medicina General, Salud multidisciplinarios → Medicina de
Especialidad. Eso es lo que sostiene el método donde el conteo directo no
alcanza — no su convergencia, que con solo marginales observadas no implica
identificabilidad.

**Dos cosas que salieron de ahí y cambian la lectura del mercado.** La primera:
*"Desarrollo de software" no viene de "Ciencias de la computación"*. El 50.7%
de su flujo viene de **Electrónica y automatización**, que estaba en Ingeniería.
Buena parte del famoso +66% de computación en 2017 es electrónica reclasificada,
no cómputo nuevo. La segunda: *Administración de empresas* —la categoría vieja
más grande, 145 mil de NI al año— se abre hacia **gastronomía, hospitalidad y
turismo**, categorías que el catálogo anterior no tenía. Los dos métodos de
emparejamiento lo detectan por separado.

**Lo que sigue débil, dicho aquí y en pantalla.** 16 grupos pasan el criterio con
un salto mayor a 1.5× su volatilidad: lo pasan porque su serie es tan ruidosa que
el criterio no tiene poder para rechazarlos. Los peores son `SERVICIOS DE
TRANSPORTE` (-50.5%) y `SEGURIDAD PÚBLICA` (-47.4%), que no son comparables en
ningún sentido útil. La app aplica el mismo criterio a la serie del corte que
tienes en pantalla —que puede ser un grupo cruzado con una zona chica, donde la
continuidad del grupo nacional ya no garantiza nada— y avisa en dos niveles:
reclasificación probable arriba de 2.5×, serie ruidosa entre 1.5× y 2.5×
(`taxonomia.py`). Tres áreas específicas descansan solo en continuidad, sin
evidencia de flujo: `Mecánica y profesiones afines al trabajo metálico`, `Planes
multidisciplinarios de Innovación en TIC` y `Tecnologías audiovisuales`. Y el
campo de un grupo es aquel donde pesa más su NI, así que la composición de un
campo no es idéntica a la del área ANUIES: partir un grupo entre dos campos
habría requerido proporciones inventadas, que es justo lo que la concordancia no
hace.

**El otro quiebre de la fuente: modalidad, 2023-2024.** No es el del catálogo y
conviene no confundirlos. En el ciclo 2023-2024 ANUIES empezó a reportar **MIXTA**
—y DUAL— como modalidades propias. No se reclasificó ninguna carrera: se partió
en dos una columna que antes venía junta, y esa matrícula salió casi toda de NO
ESCOLARIZADA. Nuevo ingreso nacional:

| | 2022-2023 | 2023-2024 | 2024-2025 | var 23 | var 24 |
|---|---|---|---|---|---|
| NO ESCOLARIZADA sola | 437,882 | 261,678 | 297,016 | **-40.2%** | +13.5% |
| **Online** (no esc. + mixta) | 437,882 | 475,083 | 540,301 | **+8.5%** | +13.7% |

El -40.2% no perdió un solo alumno. MIXTA es el **44.9%** del online en 2023-2024
y el **45.0%** en 2024-2025, y la suma de las dos es continua. Por eso el
agregador volvió al selector: con multiselect *sí* se arma marcando dos casillas,
pero esconder detrás de "marca estas dos y no estas otras" la **única serie de
modalidad comparable en los 11 ciclos** es esconder el camino correcto. El resto
de los presets viejos —"Escolarizada (presencial)", "Solo no escolarizada"— no
volvieron: ésos sí son un duplicado de marcar una casilla.

La app avisa en tres lugares (`taxonomia.py`):

- **Al seleccionar NO ESCOLARIZADA sin MIXTA**, con la cuenta hecha y qué hacer.
  Es determinista, mira la selección y no los datos, igual que `nota_trasvase`
  hace con las dos áreas que intercambiaron TIC.
- **Al detectar el salto en la serie que está en pantalla.** `quiebres()` evalúa
  los **dos** cruces conocidos, 2016→2017 y 2022→2023, con la misma prueba
  (el salto contra la mediana de los demás cruces). Antes sólo miraba el primero,
  así que un corte de NO ESCOLARIZADA se proyectaba sobre el escalón sin decir
  nada; hoy el nacional sale marcado "alto" (baja 40% contra un cambio típico de
  13%). Es red de seguridad para cruces finos, donde la nota de selección no
  alcanza.
- **Al recortar la serie de MIXTA o DUAL.** El recorte ya existía; el mensaje
  estaba mal. Cualquier serie que arrancara en 2017 o después recibía el texto
  del cambio de catálogo de áreas, así que a MIXTA —que arranca en 2023— le decía
  que era una categoría del catálogo nuevo. Falso: no hay ninguna carrera
  reclasificada detrás. Ahora el aviso se elige por el ciclo exacto de arranque, y
  fuera de los dos ciclos conocidos es descriptivo y no atribuye causa.

**Cuando no hay proyección posible, la pantalla no se apaga.** El motor pide 6
observaciones (`MIN_OBS`) y MIXTA tiene 2. Antes esa rama era un `st.warning` +
`st.line_chart` + `st.stop()`: se perdían el título, las métricas, la tabla, la
descarga y toda la identidad visual. Ahora hay una vista histórica hermana de la
gráfica principal —misma paleta, mismos ejes, mismas etiquetas directas—, con:

- El **eje completo** 2014-2015 → 2024-2025, para conservar la escala. El tramo
  sin dato es una **zona gris rotulada "no reportado por separado"**: una línea
  en cero afirmaría que había cero alumnos, y un hueco mudo dejaría al lector
  adivinando cuál de las dos cosas es.
- La **serie padre en gris detrás**, por los 11 ciclos. Para MIXTA es Online; para
  DUAL, el total de todas las modalidades (de dónde salieron sus 196 alumnos no
  está documentado en la fuente y no se inventa).
- Sólo las **métricas que existen**: último valor, variación contra el ciclo
  anterior y participación dentro del padre. Sin CAGR, sin MAPE/MASE y sin
  semáforo de confiabilidad, que para dos observaciones no significan nada.
- **Tabla y descarga CSV/Excel**, que también se perdían.

**Proyección indirecta por participación.** Donde el volumen aguanta, la vista
además deriva: proyecta al **padre** —serie continua, motor y calibración ya
validados— y lo reparte por la participación observada del hijo. El share va
**fijo** (promedio de las observaciones disponibles), nunca extrapolado: con dos
puntos, "la tendencia del share" es la pendiente del error de medición. El
intervalo hereda el del padre y se ensancha por la incertidumbre del reparto,
emparejando el peor caso de cada uno — sobre-cubre, que con dos observaciones es
el lado correcto en el que equivocarse.

Se aplica sólo si se cumplen los tres umbrales (`pronostico.py`), y **no se baja
`MIN_OBS` ni se fuerza al ensemble a correr con dos puntos**:

| Umbral | Valor | Por qué |
|---|---|---|
| Volumen del hijo, último ciclo | ≥ 1,000 | 10× el umbral con el que el propio motor ya llama "volumen bajo" a un segmento: aquí se componen dos incertidumbres |
| Dispersión del share (rango / media) | ≤ 15% | Separa limpio los casos reales |
| Padre proyectable | sí | Si el padre no da, no hay de dónde derivar |

Qué pasa cada nivel con MIXTA, que es para lo que se diseñó el umbral:

| Corte | Share 2023-24 → 2024-25 | Dispersión | Volumen | Resultado |
|---|---|---|---|---|
| Nacional | 44.9% → 45.0% | 0.2% | 243,285 | **deriva** |
| Licenciatura | 49.1% → 49.9% | 1.6% | 210,415 | **deriva** |
| Maestría | 24.6% → 24.1% | 2.1% | 22,324 | **deriva** |
| Técnico Superior | 45.7% → 49.1% | 7.2% | 988 | rechaza (volumen) |
| Doctorado | 47.6% → **34.8%** | 31% | 4,472 | rechaza (share) |
| Especialidad | 63.3% → **46.7%** | 30% | 5,086 | rechaza (share) |

El patrón es el que había que respetar: el share es estable donde hay volumen e
inestable donde no. Repartir la proyección del padre con un número que se mueve
13 o 17 puntos de un ciclo al otro sería inventarse la mitad del resultado, así
que Doctorado y Especialidad se rechazan con el motivo escrito en pantalla. Lo
que sí deriva se etiqueta **"derivado"** en todas partes —gráfica, tarjetas y la
columna `tipo` del CSV/Excel—, nunca "proyección", y **no lleva semáforo de
confiabilidad**: no tiene backtest propio y el del padre no es el suyo.

**Zonas metropolitanas.** Delimitación *Metrópolis de México 2020*: 15 zonas.
De los 149 municipios que las integran, 110 tienen oferta de educación superior
en la base; los otros 39 simplemente no tienen IES y aportan cero. La lista
completa —qué municipio cae en qué zona, y cuál de ellos no tiene IES— está en la
página **Glosario**, junto con los estados de cada región Nielsen.

**Regiones Nielsen.** Seis regiones (Valle, Centro, Norte, Sureste, Oeste,
Pacífico), una por área Nielsen, agrupando estados completos: ningún estado se
parte entre dos regiones. Vienen asignadas en la fuente ANUIES agregada, no se
calculan aquí. Cubren los 31 estados que la base trae — **Chiapas no aparece en
el agregado**, así que cualquier total llamado "nacional" lo excluye.

**El motor no es ARIMA, y eso está medido.** El proyecto empezó como un ARIMA.
Un backtest de origen móvil sobre 110 segmentos reales (11,688 predicciones) lo
dejó **por debajo del naive**:

| Método | MASE | MASE a 3 años | Gana su segmento |
|---|---|---|---|
| **ensemble** (mediana de naive, drift, lineal, media móvil 3) | **1.216** | 1.475 | 8 |
| theta | 1.225 | **1.435** | 13 |
| holt amortiguado | 1.325 | 1.623 | 12 |
| naive | 1.379 | 1.793 | 6 |
| lineal | 1.384 | 1.751 | 33 |
| **arima** | **1.422** | 1.841 | **1** |

La razón: con 11 observaciones anuales no hay estructura que identificar. El 83%
de los segmentos elegía ARIMA(0,1,0) — que es literalmente "último valor" o
"último valor + pendiente promedio". Box-Jenkins pide ~50 observaciones.
No es efecto de COVID: excluyendo 2020-21 el orden es idéntico.

El motor por defecto es el ensemble. El ARIMA sigue disponible en el selector
para comparar. Reproducible con `python validacion.py`.

**El hoyo de COVID es real y marcarlo no sirve — también medido.** Nacionalmente
el nuevo ingreso cae -7.0% en 2020-2021, el único ciclo negativo de la serie.
Contra la interpolación de sus vecinos sanos (2019 y 2022), el desvío mediano de
los 108 segmentos es **-8.6%** y el 84% queda por debajo de su propia línea. No
es un artefacto de un corte: es el ciclo anómalo de la base.

| Ciclo | Desvío mediano vs. vecinos | Segmentos por debajo |
|---|---|---|
| 2017-2018 | -3.2% | 72% |
| **2020-2021** | **-8.6%** | **84%** |
| 2021-2022 | -4.5% | 72% |
| resto | entre 0.0% y +5.6% | 14-50% |

Dos cosas que conviene leer de esa tabla. La primera: 2021-2022 ya es
recuperación parcial —la mitad del hoyo, y un tercio de los segmentos ya está
arriba de su línea—, así que tratar los dos ciclos como un mismo bloque anómalo
es tratar la recuperación como si fuera la caída. La segunda: el -3.2% de 2017 es
el cambio de catálogo, no mercado, y ya lo resuelve `concordancia.py`.

Marcarlo se probó de las dos formas en que se puede marcar, con el mismo
protocolo de origen móvil sobre los mismos 110 segmentos:

1. **Flag / dummy**, que es la versión literal: `y ~ a + b·t + c·D_covid`,
   proyectando con `D = 0`. Solo aplica a un método que estime coeficientes, así
   que se probó sobre la tendencia lineal.
2. **Limpieza del outlier**: sustituir 2020 (y 2021) por la interpolación
   geométrica de sus vecinos sanos antes de ajustar. Esto sí aplica a cualquier
   motor, incluido el ensemble que la app usa.

Se reporta el régimen de uso real —ventanas donde COVID ya quedó estrictamente
adentro y el objetivo es post-COVID— porque un backtest que predice 2021 está
prediciendo la pandemia, y ahí "limpiar" el entrenamiento es competir contra una
realidad que sí tuvo pandemia. Es la comparación que favorece a la corrección, y
aun así:

| Método | MASE (uso real) | MASE (todos los orígenes) |
|---|---|---|
| **ensemble (el de la app)** | **1.027** | **1.216** |
| ensemble + limpia 2020 | 1.030 | 1.428 |
| ensemble + limpia 2020-21 | 1.036 | 1.933 |
| naive | 1.040 | 1.379 |
| lineal | 1.316 | 1.384 |
| **lineal + dummy covid** | **1.433** | **1.981** |
| lineal + limpia 2020-21 | 1.506 | 2.370 |

El dummy pierde por 40% contra el motor actual, y limpiar el outlier queda en
empate exacto (1.027 vs 1.030) ganándole en solo 32% de los segmentos. La razón
es estructural y vale entenderla, porque dice cuándo *sí* habría que reabrirlo:
**el ensemble ya es robusto al outlier interior por construcción**. De sus cuatro
componentes, `naive` y `media móvil 3` solo miran los últimos 1 y 3 puntos —hoy
2022, 2023 y 2024, todos post-COVID—, `drift` solo mira los dos extremos de la
serie, y únicamente `lineal` ve el hoyo. La mediana de los cuatro lo ignora sin
que nadie se lo pida. Corregirlo a mano es corregir algo que ya estaba corregido,
y encima añade una interpolación inventada al historial.

**Dónde sí pega el COVID, y ahí se deja a propósito.** El ancho del intervalo es
proporcional a `mean|diff|` de la serie, y la entrada y la salida del hoyo son
dos diferencias grandes. Eso infla la escala: la mediana de los segmentos tiene
el intervalo **6% más ancho** por COVID, el 24% lo tiene más de 25% más ancho.
No se corrige, y no por pereza: 2020 pasó, y una serie que ya demostró que puede
moverse 9% en un ciclo por un shock exógeno *merece* un intervalo más ancho. El
semáforo de confiabilidad, en cambio, no se mueve —MAPE medio 11.13% con los
objetivos COVID contra 11.16% sin ellos, y los 9 segmentos que cambian de color
cambian en las dos direcciones—, porque el castigo cae parejo sobre todos.

Reproducible con `python validacion_covid.py`.

**Los intervalos salen del backtest, no de la fórmula.** Los intervalos
analíticos del ARIMA sub-cubrían: 80% nominal daba 73.7% real. Los actuales usan
los cuantiles del error observado, escalados por la volatilidad propia de cada
serie. Cobertura medida fuera de muestra (200 splits por segmento):

| Nominal | Real |
|---|---|
| 50% | 50.5% |
| 80% | 79.5% |
| 95% | 94.4% |

Cada motor tiene sus propios factores, porque cada uno se equivoca distinto.
Reproducible con `python calibrar.py`.

**El ensemble es conservador, a propósito.** Proyecta crecimientos por debajo del
CAGR histórico (nacional: +1.2% proyectado vs +3.1% histórico) porque dos de sus
cuatro componentes son planos. Ese sesgo es lo que le gana en error promedio,
pero si el crecimiento del sector continúa sin interrupción, subestima. El CAGR
histórico está siempre visible junto a la proyección para que veas el contraste,
y el límite superior del intervalo te da ese escenario.

**Datos externos: qué entra, qué no, y por qué.** Hay cuatro fuentes externas
cargadas y ninguna toca el pronóstico. Eso último es un resultado, no un
pendiente.

| Fuente | Qué aporta | Cobertura |
|---|---|---|
| CONAPO, proyecciones municipales por grandes grupos de edad | Población 12-29 ("edad educativa") y total | 2,475 municipios, **1990-2040** |
| SEP, serie histórica y prospectiva por entidad (hoja MATRICULA) | Matrícula de media superior = el nivel anterior | 32 entidades, **1990-91 a 2030-31** |
| La misma, hoja ESCUELAS | Escuelas de superior = capacidad instalada | 32 entidades, 1990-91 a 2030-31 |
| CONEVAL, Índice de Rezago Social municipal | Nivel estructural y su tendencia | 2,469 municipios, censos 2000-2020 |

Lo atractivo de las dos primeras es que **traen valores futuros**: CONAPO
proyecta a 2040 y la SEP publica su propia prospectiva a 2030-31. Eso permitía
usarlas sin gastar grados de libertad: en vez de meter la población como regresor
en una serie de 11 puntos —que no da— se proyecta la **tasa de captación**
(alumnos del corte por joven de 12 a 29 años) y se reescala por la población
futura ya publicada. Cero parámetros extra. Se implementó, se midió, y perdió.

Mismo protocolo que la competencia de métodos: origen móvil, 155 segmentos
geográficos comparables, 9,765 predicciones.

| Anclaje | MASE | MASE a 3 años | Le gana a no usarlo |
|---|---|---|---|
| población total (CONAPO) | **1.207** | **1.511** | 55.5% de segmentos |
| **sin anclaje (el motor actual)** | 1.214 | 1.515 | — |
| selección automática por segmento | 1.216 | 1.515 | 27.1% |
| población 12-29 (CONAPO) | 1.226 | 1.541 | 48.4% |
| 12-29 + corrección por rezago | 1.252 | 1.593 | 38.1% |
| escuelas de superior (SEP) | 1.324 | 1.672 | 43.2% |
| matrícula de media superior t-1 (SEP) | 1.434 | 1.719 | 17.4% |

Nada le gana a no usarlo. La fila que más importa es la tercera: dejar que el
modelo **elija por segmento** con su propio backtest —anclar donde ayuda, no
anclar donde estorba— también quedó en empate (1.216) y solo mejoró en 27% de
los segmentos. Con 11 observaciones anuales, elegir entre dos métodos por
backtest es perseguir ruido: la regla acierta menos veces de las que se equivoca
y se come la ganancia. Reproducible con `python validacion_externos.py`.

Las razones del empate, que conviene entender porque dicen qué *sí* serviría:

- **La demografía no se mueve lo suficiente en el horizonte de la app.** La
  población 12-29 cambia menos de 0.5% al año. En 3 o 5 ciclos el anclaje casi
  no mueve el punto, y lo que sí aporta es varianza.
- **El nivel anterior lo tenemos al nivel equivocado.** La matrícula de media
  superior solo existe por entidad; repartida entre municipios por población se
  vuelve ruido, y quedó última. El predictor bueno sería **egresados de media
  superior por municipio**, que no está en estas fuentes.
- **El IRS no es una serie.** Ver abajo.

**Y el rezago social tiene una trampa que se ve sola en los datos.** CONEVAL
reestima el índice por componentes principales en cada censo y lo normaliza a
media nacional **cero**: el promedio de los 2,469 municipios es exactamente
0.000 en los cinco cortes. O sea que mide posición *relativa*. La Ciudad de
México "empeora" de -1.91 a -1.31 entre 2000 y 2020 sin que ninguno de sus
indicadores empeore — es el resto del país mejorando más rápido. Extrapolar ese
índice en el tiempo mete el signo al revés. Para lo temporal hay que usar el `%
de población de 15+ con educación básica incompleta`, que sí tiene la misma
definición en los cinco censos (baja de 72.3% a 45.8% de promedio municipal) y
es el indicador con más señal transversal de los once (t = -6.3 contra la tasa de
captación). Aun haciéndolo bien, la corrección empeoró el backtest.

**Para qué sirven entonces.** Para lo que un extrapolador no puede decirte:
contra qué corre su propio número. La app muestra, sin un solo control, la
sección **"Contra qué corre esta proyección"**:

- La población 12-29 del corte hoy, al final del horizonte, y a 2040.
- La **tasa de captación**: nuevo ingreso por cada 1,000 jóvenes del corte.
- Una **alerta de divergencia** cuando la proyección y la demografía apuntan en
  direcciones distintas por más de 1 punto anual, con la cuenta hecha: la ZM de
  la Ciudad de México proyecta +1.1% anual mientras su cohorte joven cae 1.4%
  anual, así que cumplir esa proyección implica ganar 2.4 puntos de captación al
  año. Eso no es un error del modelo: es un supuesto, y alguien debería estar
  firmándolo a propósito.
- El **rezago social** del corte y, para cortes de hasta 20 municipios, la brecha
  entre lo que capta y lo que su nivel de rezago haría esperar entre municipios
  comparables. Los centros urbanos salen muy arriba de su línea, y esa es la
  lectura: absorben alumnos que viven fuera de su territorio.

La descarga masiva trae las mismas columnas por categoría, que es donde se
vuelven operativas: en un Excel de 15 zonas metropolitanas se ve de un golpe
cuáles están proyectando crecimiento contra su propia demografía.

La consistencia geográfica sí requirió trabajo: todo se arma por municipio y se
suma sobre el corte. Las zonas metropolitanas usan la delimitación completa (149
municipios), no solo los 110 con IES — el joven del municipio sin universidad se
matricula en el de al lado. Las fuentes estatales se reparten entre municipios
por participación en población 12-29. El empate de nombres con CONAPO quedó en
99.8% (827 de 829); los dos que faltan, Eldorado y Juan José Ríos, son municipios
creados en 2022 que no existen en la base CONAPO, y se dejan sin datos externos
en vez de cargarlos contra el municipio del que se separaron.

Una fuente que **no** se usó: `SEN_estadistica_historica_nacional.xls`. Es
escuelas/alumnos/docentes desde 1893, pero solo nacional, y para lo nacional la
serie por entidad de la SEP ya trae lo mismo con desglose. Sirve para la línea de
"más historia" que sigue pendiente, no para esto.

**Cuánto confiar.** Son 11 observaciones anuales: poco para cualquier método. El
semáforo de **confiabilidad** de cada segmento sale de su MAPE de backtest
(🟢 hasta 8%, 🟡 hasta 15%, 🔴 arriba de eso o serie muy rala). La app también
reporta el **MASE**: arriba de 1 significa que en ese segmento el método no le
gana a repetir el último valor, y lo avisa en pantalla.

Los cortes muy desagregados (un municipio chico × una modalidad × un área
específica) tienen series demasiado ralas para proyectar; la app avisa y en la
descarga masiva se filtran con el mínimo de alumnos. Cuando el corte corto es
una modalidad de reporte nuevo, en vez del aviso a secas sale la vista histórica
con su serie padre y, si el volumen aguanta, la derivada por participación
—ver arriba—.

## Archivos

| Archivo | Rol |
|---|---|
| `preparar_datos.py` | Xlsx ancho → panel largo. Homologa taxonomía y asigna ZM |
| `externos.py` | ETL de las cuatro fuentes externas → parquets + crosswalk geográfico |
| `drivers.py` | Arma la serie de población de cualquier corte, municipalizada |
| `rezago.py` | IRS: diagnóstico transversal y la corrección que se midió y se descartó |
| `contexto.py` | La lectura externa que sí se muestra. Documenta por qué no entra al número |
| `concordancia.py` | Correspondencia entre los dos catálogos ANUIES → 69 grupos comparables |
| `taxonomia.py` | Los dos quiebres de la fuente (catálogo 2017, modalidad 2023): recorte, avisos y detección |
| `validacion_externos.py` | Backtest anclaje contra nada. Genera la tabla de arriba |
| `validacion_covid.py` | Backtest del flag COVID y de la limpieza del outlier. Genera la tabla de arriba |
| `zonas.py` | Catálogo de zonas metropolitanas (Metrópolis de México 2020) |
| `metodos.py` | Los métodos de pronóstico puntual |
| `pronostico.py` | API que usa la app: punto + intervalo calibrado + backtest |
| `modelo.py` | Motor ARIMA (se conserva para comparación) |
| `validacion.py` | Competencia entre métodos. Genera la tabla de arriba |
| `calibrar.py` | Calibra los intervalos con los errores del backtest |
| `diag_escala.py` | Compara escaladores del error para la calibración |
| `comun.py` | Catálogos y helpers compartidos por las páginas |
| `app.py` | Página principal |
| `pages/2_Descarga_masiva.py` | Corrida por lote, hasta tres dimensiones cruzadas |
| `pages/3_Glosario.py` | Municipios de cada ZM y estados de cada región Nielsen |

Fuentes:

- `../data/Anuies_agregado_2014_2025.xlsx` — el panel educativo
- `series_historicas/pobproy_ggrupos.csv` — CONAPO, población municipal 1990-2040
- `series_historicas/serie_historica_entidades_sep (2).xlsm` — SEP, 1990-91 a 2030-31
- `../data/Indice de Rezago Social/IRS_entidades_mpios_{2000..2020}.xlsx` — CONEVAL

## Qué falta

Por orden de impacto:

1. **Pooling jerárquico entre zonas.** 15 ZM × 11 años son 165 observaciones; un
   modelo de panel con tendencia común y efectos por zona estima mucho mejor que
   15 modelos aislados de 11 puntos cada uno. Es la mejora más fuerte posible con
   los datos que ya están aquí.
2. **La tabla oficial de equivalencias de ANUIES.** La concordancia de
   `concordancia.py` se infirió de los datos y se validó contra los casos
   conocidos, pero sigue siendo inferencia: con el catálogo publicado con claves
   en vez de nombres, los 16 grupos frágiles y las 3 áreas específicas que hoy
   descansan solo en continuidad quedarían resueltos, y varios grupos podrían
   partirse en carreras individuales.
3. **Más historia.** ANUIES publica anuarios desde los 90s. Pasar de 11 a 25-30
   observaciones es lo único que volvería legítimo un ARIMA.
4. **Predictor adelantado a nivel municipal.** Lo intentado y medido está arriba:
   la demografía no alcanza en horizontes cortos y el nivel anterior solo existe
   por entidad. Lo que falta son **egresados de media superior por municipio**: el
   egresado de bachillerato del año *t* es el nuevo ingreso de superior en *t+1*
   casi mecánicamente, y a nivel municipal sí tendría variación que la demografía
   agregada no tiene. Hay 911 de EMS en `../data/` (4 ciclos; harían falta más).
   El enganche ya está escrito (`metodos.razon`), solo le falta el dato bueno.
5. **Reconciliación jerárquica**, para que las zonas sumen al nacional.
6. **Rezago con más resolución.** El IRS son cinco censos y por eso no da para
   más que diagnóstico. Indicadores anuales por municipio —ENIGH, IMSS— sí
   permitirían probar si el contexto socioeconómico mueve la captación.
