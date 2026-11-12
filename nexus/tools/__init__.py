"""Herramientas de Nexus y el catálogo que ve el modelo."""

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from nexus.tools.acciones import abrir_reclamacion, solicitar_devolucion, suscribir_alertas
from nexus.tools.horarios import consultar_horario
from nexus.tools.incidencias import consultar_incidencias
from nexus.tools.normativa import buscar_normativa
from nexus.tools.objetos import buscar_objeto_perdido
from nexus.tools.proximos import proximos_trenes
from nexus.tools.tarifas import consultar_tarifas

BASE_TOOLS: list[BaseTool] = [
    consultar_horario,
    consultar_incidencias,
    consultar_tarifas,
    buscar_normativa,
    buscar_objeto_perdido,
    abrir_reclamacion,
    solicitar_devolucion,
    suscribir_alertas,
]

# Herramientas que solo existen si su flag está activo (por ejemplo, en un despliegue).
FLAGGED_TOOLS: dict[str, list[BaseTool]] = {
    "proximos_trenes": [proximos_trenes],  # cambio D del capítulo 5
}


def tools_for(flags: frozenset[str] = frozenset()) -> list[BaseTool]:
    extra = [tool for flag in sorted(flags) for tool in FLAGGED_TOOLS.get(flag, [])]
    return [*BASE_TOOLS, *extra]


def format_tool_catalog(tools: Sequence[BaseTool]) -> str:
    """Una línea por herramienta: su nombre y el primer párrafo de su descripción."""

    rows = []
    for tool in tools:
        summary = " ".join(tool.description.partition("\n\n")[0].split())
        approval = (
            " (requiere aprobación del viajero)"
            if (tool.metadata or {}).get("requires_approval")
            else ""
        )
        rows.append(f"- {tool.name}: {summary}{approval}")
    return "\n".join(rows)
