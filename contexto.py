# -*- coding: utf-8 -*-
"""Los datos externos como lectura del corte, no como parte del pronostico.

Por que no entran al numero: se probo, y no funciono. `validacion_externos.py`
compara, sobre 155 segmentos y 9,765 predicciones de origen movil, extrapolar a
secas contra anclar la serie a un driver externo --- proyectar la tasa de
captacion y reescalarla por la poblacion futura que CONAPO ya publica. El
resultado, en MASE:

    poblacion total (CONAPO)        1.207
    SIN DRIVER                      1.214
    seleccion automatica            1.216
    poblacion 12-29 (CONAPO)        1.226
    12-29 + correccion por rezago   1.252
    escuelas de superior (SEP)      1.324
    matricula de media superior t-1 1.434

Nada le gana a no usarlo. Ni siquiera dejar que el modelo elija por segmento con
su propio backtest: eso quedo en 1.216 y solo mejoro en 27% de los segmentos ---
con 11 observaciones anuales, elegir entre dos metodos por backtest es perseguir
ruido. La razon del empate es aritmetica: la poblacion 12-29 se mueve menos de
0.5% al ano, asi que en el horizonte de la app (hasta 5 ciclos) el driver casi no
cambia el punto, y lo que si mete es varianza.

Lo que estas fuentes SI hacen bien es decirte contra que corre tu proyeccion.
Que un corte crezca 3% anual proyectado mientras su poblacion joven cae 1% anual
no es un error del modelo, es un supuesto de ganancia de participacion que
alguien deberia estar firmando a proposito. Eso es lo que este modulo devuelve,
y por eso no tiene un solo control: no hay nada que el usuario tenga que decidir.

Fuentes: CONAPO (poblacion municipal 1990-2040) y CONEVAL (rezago social
municipal, censos 2000-2020). Ver `externos.py`.
"""
import numpy as np

import drivers
import rezago

# Brecha, en puntos porcentuales de crecimiento anual, a partir de la cual vale
# la pena decir en voz alta que la proyeccion y la demografia van en direcciones
# distintas. Debajo de eso es ruido de un horizonte corto.
UMBRAL_DIVERGENCIA = 1.0

DRIVER_POBLACION = "Poblacion 12-29 anios (CONAPO)"


def _cagr(inicio, fin, periodos):
    if not inicio or inicio <= 0 or not fin or fin <= 0 or periodos <= 0:
        return None
    return ((fin / inicio) ** (1 / periodos) - 1) * 100


def lectura(filtros, serie, anios_proyectados, cagr_proyectado=None):
    """Contexto externo del corte. None si no hay fuentes o no se pudo mapear.

    serie: la historica del segmento, para la tasa de captacion.
    anios_proyectados: los anos que cubre la proyeccion, para medir la demografia
        en la misma ventana y que las dos cifras sean comparables.
    """
    try:
        ext = drivers.externos()
    except FileNotFoundError:
        return None

    pob, meta = ext.serie(filtros, DRIVER_POBLACION)
    if pob is None:
        return None
    claves, _ = ext.claves(filtros)

    anio_base = int(serie.index[-1])
    anio_fin = int(max(anios_proyectados))
    if anio_base not in pob.index or anio_fin not in pob.index:
        return None

    pob_base, pob_fin = float(pob.loc[anio_base]), float(pob.loc[anio_fin])
    cagr_pob = _cagr(pob_base, pob_fin, anio_fin - anio_base)
    tasa = float(serie.iloc[-1]) / pob_base

    out = {
        "municipios": meta.get("municipios"),
        "anio_base": anio_base,
        "anio_fin": anio_fin,
        "pob_base": pob_base,
        "pob_fin": pob_fin,
        "cagr_pob_%": cagr_pob,
        "tasa_captacion_x1000": tasa * 1000,
        "pob_2030": float(pob.loc[2030]) if 2030 in pob.index else None,
        "pob_2040": float(pob.loc[2040]) if 2040 in pob.index else None,
    }
    if out["pob_2040"]:
        out["cambio_2040_%"] = (out["pob_2040"] / pob_base - 1) * 100

    # Divergencia: cuanta participacion tendria que ganar el corte para que la
    # proyeccion se cumpla con esa demografia.
    if cagr_proyectado is not None and cagr_pob is not None:
        brecha = cagr_proyectado - cagr_pob
        out["brecha_pp"] = brecha
        if abs(brecha) >= UMBRAL_DIVERGENCIA:
            direccion = "ganar" if brecha > 0 else "perder"
            out["divergencia"] = (
                f"La proyeccion crece {cagr_proyectado:+.1f}% anual y la poblacion "
                f"de 12 a 29 anos del corte {cagr_pob:+.1f}% anual (CONAPO). "
                f"Cumplirla implica {direccion} "
                f"{abs(brecha):.1f} puntos de captacion al ano sobre esa base.")

    diag = rezago.diagnostico(claves, tasa)
    if diag:
        out["rezago"] = diag
    return out


def linea_demografia(ctx):
    """Una linea de texto con la trayectoria demografica del corte."""
    if ctx.get("pob_2040") is None:
        return None
    return (f"Poblacion de 12 a 29 anos del corte: "
            f"{ctx['pob_base'] / 1e6:.2f} M en {ctx['anio_base']}, "
            f"{ctx['pob_2030'] / 1e6:.2f} M en 2030, "
            f"{ctx['pob_2040'] / 1e6:.2f} M en 2040 "
            f"({ctx['cambio_2040_%']:+.1f}% contra hoy, CONAPO).")


def linea_rezago(ctx):
    """Una linea con el rezago social del corte, y la brecha si es legible."""
    d = ctx.get("rezago")
    if not d:
        return None
    linea = (f"Rezago social (CONEVAL 2020): grado "
             f"{str(d['grado_rezago']).lower()} · "
             f"{d['basica_incompleta']:.1f}% de la poblacion de 15 anos y mas con "
             f"educacion basica incompleta, contra "
             f"{d['basica_incompleta_2000']:.1f}% en 2000.")
    b = d.get("brecha_%")
    if b is None:
        return linea
    # Arriba de duplicar lo esperado, el porcentaje deja de leerse y ademas deja
    # de significar "capta bien": significa que el corte absorbe alumnos que
    # viven fuera de el. Un centro urbano siempre va a salir asi, y esa es la
    # lectura util.
    if b >= 100:
        linea += (f" Capta {1 + b / 100:.1f} veces lo que su propio rezago haria "
                  f"esperar: atrae matricula de fuera de su territorio.")
    else:
        signo = "arriba" if b > 0 else "abajo"
        linea += (f" Capta {abs(b):.0f}% por {signo} de lo que su nivel de rezago "
                  f"haria esperar entre municipios comparables.")
    return linea
