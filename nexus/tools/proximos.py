"""Próximos trenes: cuándo pasan los siguientes trenes de una línea por una estación.

Es la herramienta nueva de Jordi (cambio D del capítulo 5). Solo está disponible con el
flag ``proximos_trenes``. Los datos salen del panel de tiempo real de cada línea, que se
calcula a partir de los horarios (``nexus/data/horarios.json``): salidas desde la
cabecera según la frecuencia de cada franja, más el tiempo de viaje hasta la estación.
"""

from datetime import date
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from nexus.calendar import describe
from nexus.context import Context
from nexus.data import estaciones, find_station, lineas, load, normalize_line
from nexus.tools.horarios import _clock, _hour_minutes, _minutes, day_type

# La historia no tiene reloj: sin hora, los próximos trenes se cuentan desde las 08:00.
HORA_POR_DEFECTO = "08:00"


def _salidas(linea: str, day: date) -> list[int]:
    """Minutos del día de servicio a los que sale un tren de la cabecera de ``linea``."""

    horarios = load("horarios")
    rules = horarios["tipos_dia"][day_type(day)]
    opening, closing = _minutes(rules["apertura"]), _minutes(rules["cierre"])
    salidas: list[int] = []
    minute = opening
    while minute < closing:
        salidas.append(minute)
        franja = next(
            (f for f in rules["franjas"] if _minutes(f["desde"]) <= minute < _minutes(f["hasta"])),
            None,
        )
        if franja is None:
            break
        minute += franja["frecuencia_min"]
    nocturno = horarios["servicio_nocturno"]
    if day_type(day) == "sabado" and linea in nocturno["lineas"]:
        # Toda la noche hasta la apertura del domingo (06:00 del día siguiente).
        domingo = _minutes(horarios["tipos_dia"]["domingo_festivo"]["apertura"]) + 24 * 60
        minute = closing
        while minute < domingo:
            salidas.append(minute)
            minute += nocturno["frecuencia_min"]
    return salidas


def panel_tiempo_real(linea: str, day: date) -> dict[str, list[int]]:
    """Las llegadas de ``linea`` a cada estación el día ``day``.

    Como el sistema de tiempo real de MdV, identifica cada estación por su código en
    minúsculas (``"pma"``) y da las llegadas en minutos del día de servicio.
    """

    line = lineas()[linea]
    salidas = _salidas(linea, day)
    return {
        code.lower(): [salida + index * line["minutos_entre_estaciones"] for salida in salidas]
        for index, code in enumerate(line["estaciones"])
    }


def proximos(
    linea: str, estacion: str, day: date, hora: str | None = None, cuantos: int = 3
) -> dict[str, Any]:
    """Los ``cuantos`` próximos trenes de ``linea`` en ``estacion`` desde ``hora``."""

    line = normalize_line(linea)
    if line is None:
        return {"error": f"No existe la línea {linea!r}. Líneas: {', '.join(lineas())}."}
    code = find_station(estacion)
    if code is None or code not in lineas()[line]["estaciones"]:
        names = [estaciones()[stop]["nombre"] for stop in lineas()[line]["estaciones"]]
        return {"error": f"La {line} no pasa por {estacion!r}. Estaciones: {', '.join(names)}."}

    llegadas = panel_tiempo_real(line, day).get(code)
    if llegadas is None:
        # El panel todavía no tiene esa estación: el sistema pide volver a consultar.
        return {
            "estado": "calculando",
            "mensaje": "Calculando los próximos trenes… Vuelve a consultar en unos segundos.",
        }

    opening = _minutes(load("horarios")["tipos_dia"][day_type(day)]["apertura"])
    desde = _hour_minutes(hora or HORA_POR_DEFECTO, opening)
    siguientes = [minute for minute in llegadas if minute >= desde][:cuantos]
    cabecera = estaciones()[lineas()[line]["estaciones"][0]]["nombre"]
    result: dict[str, Any] = {
        "linea": line,
        "estacion": estaciones()[code]["nombre"],
        "fecha": describe(day),
        "desde": _clock(desde),
        "sentido": f"trenes que salen de {cabecera}",
        "proximos_trenes": [
            {"hora": _clock(minute), "en_minutos": minute - desde} for minute in siguientes
        ],
    }
    if not siguientes:
        result["aviso"] = "No pasan más trenes hoy por esta estación."
    return result


@tool
def proximos_trenes(
    linea: str, estacion: str, runtime: ToolRuntime[Context], hora: str | None = None
) -> dict[str, Any]:
    """Próximos trenes de una línea en una estación, en tiempo real.

    Args:
        linea: Línea, por ejemplo "L1".
        estacion: Nombre o código de la estación, por ejemplo "Plaça Major".
        hora: Hora HH:MM desde la que buscar (opcional; por defecto, ahora).
    """

    return proximos(linea, estacion, runtime.context.hoy, hora)
