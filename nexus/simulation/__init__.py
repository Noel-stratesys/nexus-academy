"""Simulador de viajeros: genera conversaciones con Nexus y las valora sin intervención humana.

API pública:

- ``scenarios(...) -> list[Scenario]``: el catálogo de peticiones de viajeros, con su verdad.
- ``feedback_for(scenario, answer, tool_calls) -> int | None``: la valoración del viajero.
- ``async run_traffic(n, *, assign, hoy=None, seed=0, concurrency=1, environment=None,
  tags=()) -> list[SimResult]``: ``n`` conversaciones; ``assign(user_id) -> Assignment``
  decide a qué versión va cada viajero. Registra el score ``user_feedback`` en Langfuse.

El historial de ``uv run seed`` usa las mismas piezas con un modelo con guion
(``historial``, ``modelo`` y ``trazas``).
"""

from collections.abc import Callable, Sequence
from datetime import date

from nexus.simulation.feedback import feedback_for
from nexus.simulation.scenarios import scenarios
from nexus.simulation.types import Assignment, Scenario, SimResult


async def run_traffic(
    n: int,
    *,
    assign: Callable[[str], Assignment],
    hoy: date | None = None,
    seed: int = 0,
    concurrency: int = 1,
    environment: str | None = None,
    tags: Sequence[str] = (),
) -> list[SimResult]:
    """Ver ``nexus.simulation.traffic.run_traffic`` (se importa al usarlo: crea el cliente
    de Langfuse y el grafo)."""

    from nexus.simulation.traffic import run_traffic as _run_traffic

    return await _run_traffic(
        n,
        assign=assign,
        hoy=hoy,
        seed=seed,
        concurrency=concurrency,
        environment=environment,
        tags=tags,
    )


__all__ = ["Assignment", "Scenario", "SimResult", "feedback_for", "run_traffic", "scenarios"]
