"""Lo que cambia entre ejecuciones sin reconstruir el grafo.

Se pasa con ``graph.ainvoke(..., context=Context(...))``. Los nodos y las herramientas lo
leen de ``runtime.context``: quién escribe, qué día es en la historia y qué modelos usar.
"""

from dataclasses import dataclass, field
from datetime import date

from langgraph.runtime import Runtime

from nexus.data import Viajero, viajero
from nexus.settings import Models, RagSettings, settings

ANONIMO = Viajero(id="anonimo", nombre="Viajero", idioma="es", titulo="desconocido")


@dataclass(frozen=True)
class Context:
    viajero: Viajero = ANONIMO
    hoy: date = field(default_factory=lambda: settings.nexus_today)
    models: Models = field(default_factory=lambda: settings.models)
    rag: RagSettings = field(default_factory=lambda: settings.rag)
    # Funcionalidades activadas en esta ejecución (por ejemplo, una herramienta nueva).
    flags: frozenset[str] = frozenset()

    @classmethod
    def for_user(cls, user_id: str | None, **kwargs: object) -> "Context":
        """El contexto de un viajero conocido; uno anónimo si el id no existe."""

        found = viajero(user_id) if user_id else None
        return cls(viajero=found or ANONIMO, **kwargs)  # type: ignore[arg-type]


def run_context(runtime: Runtime[Context] | None) -> Context:
    """El contexto de esta ejecución, o uno por defecto si el nodo corre suelto."""

    if runtime is None or runtime.context is None:
        return Context()
    return runtime.context
