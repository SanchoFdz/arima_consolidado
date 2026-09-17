# Tendencias de Nuevo Ingreso

App de Streamlit para que el equipo de finanzas tome la tendencia proyectada de
nuevo ingreso (NI) de cualquier corte del mercado y la meta en sus modelos.

## Correr

```bash
pip install -r requirements.txt
streamlit run app.py
```

El panel ya procesado (`datos/panel_ni.parquet`) viene en el repo, así que la app
arranca sin más. La fuente de 25 MB no está versionada: para regenerar el panel
desde cero hace falta `Anuies_agregado_2014_2025.xlsx` en `../data/` y correr
`python preparar_datos.py`.

### Deploy en Streamlit Community Cloud

Apuntar a este repo, rama `main`, archivo principal `app.py`. No necesita
secretos ni variables de entorno. El tema claro viene en `.streamlit/config.toml`.

## Qué hace

- **Página principal**: eliges un corte y devuelve la serie 2014-2025, la
  proyección con intervalo, y la descarga en CSV/Excel.
- **Descarga masiva**: proyecta todas las categorías de una dimensión
  (p. ej. las 15 zonas metropolitanas) y entrega un solo Excel.

Cortes disponibles:

| Dimensión | Valores |
|---|---|
| Geográfico | Nacional · Región Nielsen · Área Nielsen · **Zona metropolitana** · Estado · Municipio |
| Nivel educativo | TSU, Licenciatura, Normal, Especialidad, Maestría, Doctorado |
| Modalidad | Escolarizada · Online (no escolarizada + mixta) · Dual |
| Área de conocimiento | Área → Subárea → Área específica (taxonomía 2014) |
| Métrica | NI · Matrícula · Egresados · Solicitudes |

## Decisiones que conviene conocer antes de usar los números

**Taxonomía homologada a 2014.** ANUIES cambió de catálogo de áreas en el ciclo
2017-2018. Sin homologar, toda serie por área se rompe a la mitad (las áreas
viejas caen a cero y aparecen otras nuevas). `preparar_datos.py` mapea el
catálogo nuevo al de 2014, que es el que permite comparar los 11 ciclos.

**Zonas metropolitanas.** Delimitación *Metrópolis de México 2020*: 15 zonas.
De los 149 municipios que las integran, 110 tienen oferta de educación superior
en la base; los otros 39 simplemente no tienen IES y aportan cero.

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

**Cuánto confiar.** Son 11 observaciones anuales: poco para cualquier método. El
semáforo de **confiabilidad** de cada segmento sale de su MAPE de backtest
(🟢 hasta 8%, 🟡 hasta 15%, 🔴 arriba de eso o serie muy rala). La app también
reporta el **MASE**: arriba de 1 significa que en ese segmento el método no le
gana a repetir el último valor, y lo avisa en pantalla.

Los cortes muy desagregados (un municipio chico × una modalidad × un área
específica) tienen series demasiado ralas para proyectar; la app avisa y en la
descarga masiva se filtran con el mínimo de alumnos.

## Archivos

| Archivo | Rol |
|---|---|
| `preparar_datos.py` | Xlsx ancho → panel largo. Homologa taxonomía y asigna ZM |
| `zonas.py` | Catálogo de zonas metropolitanas (Metrópolis de México 2020) |
| `metodos.py` | Los métodos de pronóstico puntual |
| `pronostico.py` | API que usa la app: punto + intervalo calibrado + backtest |
| `modelo.py` | Motor ARIMA (se conserva para comparación) |
| `validacion.py` | Competencia entre métodos. Genera la tabla de arriba |
| `calibrar.py` | Calibra los intervalos con los errores del backtest |
| `diag_escala.py` | Compara escaladores del error para la calibración |
| `comun.py` | Catálogos y helpers compartidos por las páginas |
| `app.py` | Página principal |
| `pages/2_Descarga_masiva.py` | Corrida por lote |

Fuente: `../data/Anuies_agregado_2014_2025.xlsx`

## Qué falta

Por orden de impacto:

1. **Pooling jerárquico entre zonas.** 15 ZM × 11 años son 165 observaciones; un
   modelo de panel con tendencia común y efectos por zona estima mucho mejor que
   15 modelos aislados de 11 puntos cada uno. Es la mejora más fuerte posible con
   los datos que ya están aquí.
2. **Más historia.** ANUIES publica anuarios desde los 90s. Pasar de 11 a 25-30
   observaciones es lo único que volvería legítimo un ARIMA.
3. **Predictor adelantado.** Los egresados de bachillerato del año *t* son el
   nuevo ingreso de superior en *t+1* casi mecánicamente. Hay 911 de EMS en
   `../data/` (4 ciclos; harían falta más). CONAPO además da demografía a futuro,
   que es justo lo que un extrapolador ciego no tiene.
4. **Reconciliación jerárquica**, para que las zonas sumen al nacional.
