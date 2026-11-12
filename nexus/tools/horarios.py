"""Horarios: primer y último tren y frecuencia de una línea en una estación y un día."""

from datetime import date, time, timedelta
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from nexus.calendar import describe, resolve_day
from nexus.context import Context
from nexus.data import estaciones, find_station, lineas, load, normalize_line


def day_type(day: date) -> str:
    """``laborable``, ``viernes``, ``sabado`` o ``domingo_festivo``."""

    festivos = load("horarios")["festivos"]
    if day.isoformat() in festivos or day.weekday() == 6:
        return "domingo_festivo"
    if day.weekday() == 5:
        return "sabado"
    if day.weekday() == 4 or (day + timedelta(days=1)).isoformat() in festivos:
        return "viernes"
    return "laborable"


def _minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _clock(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _hour_minutes(hora: str, opening: int) -> int:
    """Minutos de ``hora`` en el día de servicio: la madrugada cuenta como 24:00 o más."""

    parsed = time.fromisoformat(hora if len(hora) > 2 else f"{hora}:00")
    minutes = parsed.hour * 60 + parsed.minute
    return minutes + 24 * 60 if minutes < opening else minutes


def schedule(linea: str, estacion: str, day: date, hora: str | None = None) -> dict[str, Any]:
    """El horario de ``linea`` en ``estacion`` el día ``day``; con ``hora``, su frecuencia."""

    horarios = load("horarios")
    kind = day_type(day)
    rules = horarios["tipos_dia"][kind]
    line = lineas()[linea]
    offset = line["estaciones"].index(estacion) * line["minutos_entre_estaciones"]
    opening, closing = _minutes(rules["apertura"]), _minutes(rules["cierre"])
    nocturno = kind == "sabado" and linea in horarios["servicio_nocturno"]["lineas"]

    result: dict[str, Any] = {
        "linea": linea,
        "estacion": estaciones()[estacion]["nombre"],
        "fecha": describe(day),
        "tipo_dia": rules["descripcion"],
        "primer_tren": _clock(opening + offset),
        "ultimo_tren": (
            "servicio toda la noche (sábado a domingo)" if nocturno else _clock(closing + offset)
        ),
        "desde_cabecera": estaciones()[line["estaciones"][0]]["nombre"],
    }
    if hora is not None:
        minutes = _hour_minutes(hora, opening)
        franjas = [
            franja
            for franja in rules["franjas"]
            if _minutes(franja["desde"]) <= minutes < _minutes(franja["hasta"])
        ]
        if franjas:
            result["frecuencia_min"] = franjas[0]["frecuencia_min"]
        elif nocturno:
            result["frecuencia_min"] = horarios["servicio_nocturno"]["frecuencia_min"]
        else:
            result["trenes_en_esa_hora"] = []
    return result


@tool
def consultar_horario(
    linea: str, estacion: str, dia: str, runtime: ToolRuntime[Context], hora: str | None = None
) -> dict[str, Any]:
    """Horario de una línea en una estación: primer tren, último tren y frecuencia.

    Args:
        linea: Línea, por ejemplo "L1".
        estacion: Nombre o código de la estación, por ejemplo "Plaça Major".
        dia: "hoy", "mañana", un día de la semana ("jueves") o una fecha AAAA-MM-DD.
        hora: Hora HH:MM para saber la frecuencia en ese momento (opcional).
    """

    line = normalize_line(linea)
    if line is None:
        return {"error": f"No existe la línea {linea!r}. Líneas: {', '.join(lineas())}."}
    station = find_station(estacion)
    if station is None or station not in lineas()[line]["estaciones"]:
        names = [estaciones()[code]["nombre"] for code in lineas()[line]["estaciones"]]
        return {"error": f"La {line} no pasa por {estacion!r}. Estaciones: {', '.join(names)}."}
    day = resolve_day(dia, runtime.context.hoy)
    return schedule(line, station, day, hora)
