"""Acciones con consecuencias: necesitan que el viajero las apruebe antes de ejecutarse.

Son simuladas: devuelven un número de trámite pero no guardan nada.
"""

import hashlib
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from nexus.context import Context


def _reference(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode()).hexdigest()[:6].upper()
    return f"{prefix}-{digest}"


@tool
def abrir_reclamacion(motivo: str, detalle: str, runtime: ToolRuntime[Context]) -> dict[str, Any]:
    """Abre una reclamación a nombre del viajero.

    Args:
        motivo: Motivo breve, por ejemplo "información incorrecta" o "trato recibido".
        detalle: Lo que ocurrió, con fecha, línea y estación si se conocen.
    """

    viajero = runtime.context.viajero
    return {
        "estado": "registrada",
        "referencia": _reference("REC", viajero.id, motivo, detalle),
        "plazo_respuesta": "15 días hábiles",
    }


@tool
def solicitar_devolucion(
    titulo: str,
    importe: float,
    motivo: str,
    runtime: ToolRuntime[Context],
    incidencia_id: str | None = None,
) -> dict[str, Any]:
    """Solicita la devolución del importe de un viaje. Solo si la normativa la permite.

    Args:
        titulo: Título con el que viajó, por ejemplo "senzill" o "T-10".
        importe: Importe que se pide devolver, en euros.
        motivo: Motivo de la devolución.
        incidencia_id: Incidencia que la justifica, por ejemplo "INC-0291", si la hay.
    """

    viajero = runtime.context.viajero
    return {
        "estado": "solicitada",
        "referencia": _reference("DEV", viajero.id, titulo, str(importe), motivo),
        "importe": importe,
        "plazo": "El abono se hace en 10 días hábiles.",
    }


@tool
def suscribir_alertas(linea: str, runtime: ToolRuntime[Context]) -> dict[str, Any]:
    """Suscribe al viajero a los avisos de incidencias de una línea.

    Args:
        linea: Línea de la que quiere recibir avisos, por ejemplo "L2".
    """

    viajero = runtime.context.viajero
    return {
        "estado": "suscrito",
        "linea": linea,
        "referencia": _reference("ALR", viajero.id, linea),
    }


for _action in (abrir_reclamacion, solicitar_devolucion, suscribir_alertas):
    # El executor pide aprobación antes de ejecutar las herramientas marcadas así.
    _action.metadata = {"requires_approval": True}
