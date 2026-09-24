# Extrae de los RDS del 911 de media superior (2014-2015 a 2020-2021) una tabla
# larga y homogenea: una fila por archivo x entidad x municipio x control x
# modalidad x subnivel, con nuevo ingreso a 1o y matricula total.
#
# Va en R y no en Python porque pyreadr no abre los RDS originales, y las copias
# _utf8 que si abre traen el texto doble-codificado. Aqui solo se usan claves y
# etiquetas cortas, asi que el encoding no importa.
#
# Uso: Rscript extraer_rds.R <carpeta Formatos 911/EMS> <salida.csv>
args <- commandArgs(trailingOnly = TRUE)
raiz <- args[1]; salida <- args[2]

# NI = alumnos de primer ingreso a 1er grado (no inscritos a 1o menos
# repetidores, que hasta 2018-2019 da 3-8% mas). Mat = matricula total.
# `bt` = el archivo es de bachillerato tecnologico (incluye profesional tecnico).
SPEC <- list(
  list(c="2014-2015", f="F9117G.RDS",   ni="MS130", mat="MS184", bt=FALSE),
  list(c="2014-2015", f="F9117BT.RDS",  ni="MS149", mat="MS210", bt=TRUE),
  list(c="2015-2016", f="F9117G.RDS",   ni="MS130", mat="MS184", bt=FALSE),
  list(c="2015-2016", f="F9117BTI.RDS", ni="MS149", mat="MS210", bt=TRUE),
  list(c="2016-2017", f="F9117G.RDS",   ni="MS130", mat="MS184", bt=FALSE),
  list(c="2016-2017", f="F9117BTI.RDS", ni="MS149", mat="MS210", bt=TRUE),
  list(c="2017-2018", f="BACHILLERATO GENERAL FIN DE CURSOS 2016-2017 E INICIO DE CURSOS 2017-2018.RDS",
       ni="MS130", mat="MS184", bt=FALSE),
  list(c="2017-2018", f="BACHILLERATO TECNOLOGICO INICIO DE CURSOS 2017-2018.RDS",
       ni="MS149", mat="MS210", bt=TRUE),
  list(c="2018-2019", f="Bachillerato general_I1819.RDS",    ni="V346", mat="V397", bt=FALSE),
  list(c="2018-2019", f="Bachillerato tecnologico_I1819.RDS", ni="V414", mat="V472", bt=TRUE),
  list(c="2019-2020", f="BACH_GENERAL_I1920-F1819.RDS",      ni="V346", mat="V397", bt=FALSE),
  list(c="2019-2020", f="BACH_TECNOLOGICO_I1920.RDS",        ni="V414", mat="V472", bt=TRUE),
  list(c="2020-2021", f="BACH_GENERAL_I2021_F1920.RDS",      ni="V346", mat="V397", bt=FALSE),
  list(c="2020-2021", f="BACH_TECNOLOGICO_I2021_F1920.RDS",  ni="V414", mat="V472", bt=TRUE)
)

col <- function(d, ...) {
  for (n in c(...)) { i <- match(toupper(n), toupper(names(d))); if (!is.na(i)) return(d[[i]]) }
  NULL
}
num <- function(x) { x <- suppressWarnings(as.numeric(as.character(x))); x[is.na(x)] <- 0; x }
chr <- function(x) toupper(trimws(as.character(x)))

# Subnivel homologado a tres valores. En los archivos BT el profesional tecnico
# se distingue por SUBNIVEL/NIVEL (2014-2017, 2018+) o por el servicio D52 (2017-18,
# que no trae subnivel).
subnivel <- function(d, bt) {
  if (!bt) return(rep("BACHILLERATO GENERAL", nrow(d)))
  sn <- col(d, "SUBNIVEL"); nv <- col(d, "NIVEL"); sv <- col(d, "cveser")
  pt <- rep(FALSE, nrow(d))
  if (!is.null(sn)) pt <- pt | grepl("PROFESIONAL", chr(sn))
  if (!is.null(nv)) pt <- pt | grepl("TECNICO|TÉCNICO", chr(nv))
  if (is.null(sn) && !is.null(sv)) pt <- pt | chr(sv) == "D52"
  ifelse(pt, "PROFESIONAL TECNICO", "BACHILLERATO TECNOLOGICO")
}

partes <- list()
for (s in SPEC) {
  d <- readRDS(file.path(raiz, s$c, "Bases de datos", s$f))
  ni <- col(d, s$ni); mat <- col(d, s$mat)
  if (is.null(ni) || is.null(mat)) stop(paste("faltan", s$ni, s$mat, "en", s$f))
  ctl <- chr(col(d, "CONTROL"))
  mod <- chr(col(d, "C_MODALIDAD", "MODALIDAD"))
  t <- data.frame(
    ciclo = s$c,
    cve_ent = as.integer(num(col(d, "CV_ENT_INMUEBLE", "ENTIDAD"))),
    cve_mun = as.integer(num(col(d, "CV_MUN", "MUNICIPIO"))),
    control = ifelse(grepl("PRIVADO", ctl), "PRIVADO", ifelse(grepl("BLICO", ctl), "PUBLICO", ctl)),
    modalidad = ifelse(grepl("^NO ESC", mod), "NO ESCOLARIZADA",
                       ifelse(grepl("MIXTA", mod), "MIXTA", "ESCOLARIZADA")),
    subnivel = subnivel(d, s$bt),
    NI = num(ni), Matricula = num(mat), stringsAsFactors = FALSE)
  partes[[length(partes) + 1]] <- aggregate(cbind(NI, Matricula) ~ ciclo + cve_ent + cve_mun +
                                              control + modalidad + subnivel, t, sum)
  cat(s$c, s$f, nrow(d), "filas; NI", sum(t$NI), "mat", sum(t$Matricula), "\n")
}
write.csv(do.call(rbind, partes), salida, row.names = FALSE)
