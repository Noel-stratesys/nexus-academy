"""Incidencias: obras, averías, huelgas y cortes de servicio de un día."""

from datetime import date, datetime, time
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from nexus.calendar import describe, resolve_day
from nexus.context import Context
from nexus.data import estaciones, lineas, load, normalize_line


def _bounds(text: str) -> datetime:
    day, _, clock = text.partition("T")
    if clock == "24:00":
        return datetime.combine(date.fromisoformat(day), time.max)
    return datetime.fromisoformat(text)


def incidents_on(day: date, linea: str) -> list[dict[str, Any]]:
    """Las incidencias de ``linea`` activas en algún momento de ``day``."""

    start, end = datetime.combine(day, time.min), datetime.combine(day, time.max)
    found = []
    for incident in load("incidencias"):
        if incident["linea"] != linea:
            continue
        if _bounds(incident["desde"]) <= end and _bounds(incident["hasta"]) >= start:
            found.append(
                {
                    **incident,
                    "tramo": [estaciones()[code]["nombre"] for code in incident["tramo"]],
                }
            )
    return found


def _central_system_lookup(day: date) -> dict[str, Any]:
    """Consulta de todas las líneas al sistema central de incidencias.

    En la prueba de concepto este sistema todavía no está conectado y responde ocupado.
    """

    return {
        "estado": "ocupado",
        "mensaje": "El sistema central de incidencias está ocupado. Reintenta la consulta.",
    }


@tool
def consultar_incidencias(
    dia: str, runtime: ToolRuntime[Context], linea: str | None = None
) -> dict[str, Any]:
    """Incidencias, obras y cortes de servicio de un día, de una línea o de toda la red.

    Args:
        dia: "hoy", "mañana", un día de la semana ("jueves") o una fecha AAAA-MM-DD.
        linea: Línea, por ejemplo "L3". Si se omite, consulta todas las líneas.
    """

    day = resolve_day(dia, runtime.context.hoy)
    if linea is None:
        return _central_system_lookup(day)
    line = normalize_line(linea)
    if line is None:
        return {"error": f"No existe la línea {linea!r}. Líneas: {', '.join(lineas())}."}
    found = incidents_on(day, line)
    return {
        "fecha": describe(day),
        "linea": line,
        "incidencias": found,
        "estado": "con incidencias" if found else "servicio normal",
    }
