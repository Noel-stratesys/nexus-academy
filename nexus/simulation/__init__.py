"""Simulador de viajeros: genera conversaciones con Nexus y las valora sin intervención humana.

API pública (la implementa el bloque del historial):

- ``scenarios(...) -> list[Scenario]``: el catálogo de peticiones de viajeros, con su verdad.
- ``feedback_for(scenario, answer, tool_calls) -> int | None``: la valoración del viajero.
- ``async run_traffic(n, *, assign, hoy=None, seed=0, concurrency=1, environment=None,
  tags=()) -> list[SimResult]``: ``n`` conversaciones; ``assign(user_id) -> Assignment``
  decide a qué versión va cada viajero. Registra el score ``user_feedback`` en Langfuse.
"""

from nexus.simulation.types import Assignment, Scenario, SimResult

__all__ = ["Assignment", "Scenario", "SimResult"]
