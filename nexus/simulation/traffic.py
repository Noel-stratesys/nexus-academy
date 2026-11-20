"""Conversaciones simuladas con Nexus: las de ``uv run simulate`` y las del historial.

Cada conversación es un turno de ``run_turn`` con un viajero, su petición (un
``Scenario``) y la versión de Nexus que le toca (un ``Assignment``). El viajero aprueba o
rechaza las acciones según ``scenario.approvals`` y, al acabar, puede valorar la
respuesta (``feedback_for``): esa valoración es el score ``user_feedback`` de la traza.

``run_traffic`` (``uv run simulate``) no llama a ningún modelo de lenguaje: Nexus usa el
modelo con guion (``nexus.simulation.modelo``), que tarda lo que tardaría uno de verdad.
"""

import asyncio
import random
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any
from uuid import uuid4

from nexus.context import Context
from nexus.data import viajero as buscar_viajero
from nexus.graph import build_graph
from nexus.llm.langfuse_client import langfuse
from nexus.llm.prompts import prompt_label_scope, prompt_version_scope
from nexus.runner import Approver, run_turn
from nexus.settings import Models, RagSettings, settings
from nexus.simulation.feedback import comentario_for, feedback_for
from nexus.simulation.modelo import Guion, guion_scope, instalar
from nexus.simulation.scenarios import pick_scenario
from nexus.simulation.types import Assignment, Scenario, SimResult

FEEDBACK_SCORE = "user_feedback"


def aprobador(scenario: Scenario) -> Approver:
    """El viajero responde a las aprobaciones con ``scenario.approvals``, en orden."""

    respuestas = list(scenario.approvals) or ["approve"]
    pedidas = 0

    async def approver(actions: list[dict[str, Any]]) -> list[str]:
        nonlocal pedidas
        replies = []
        for _ in actions:
            replies.append(respuestas[min(pedidas, len(respuestas) - 1)])
            pedidas += 1
        return replies

    return approver


async def conversar(
    graph: Any,
    scenario: Scenario,
    assignment: Assignment,
    *,
    thread_id: str,
    environment: str | None = None,
    tags: Sequence[str] = (),
    versions: Mapping[str, int] | None = None,
    models: Models | None = None,
    rag: RagSettings | None = None,
) -> SimResult:
    """Una conversación: el viajero escribe y Nexus (la versión ``assignment``) responde.

    Los prompts se leen con el label de ``assignment`` o, si se indican, con ``versions``
    concretas. ``models`` y ``rag`` sustituyen a los del ``.env``. No valora la
    respuesta: eso lo hace quien llama.
    """

    extra: dict[str, Any] = {
        "models": models,
        "rag": rag,
        "viajero": buscar_viajero(scenario.viajero),
    }
    context = Context(
        hoy=scenario.hoy,
        flags=assignment.flags,
        **{campo: valor for campo, valor in extra.items() if valor is not None},
    )
    alcance = prompt_version_scope(versions) if versions else prompt_label_scope(assignment.label)
    inicio = time.perf_counter()
    try:
        with alcance:
            turn = await run_turn(
                graph,
                scenario.mensaje,
                context=context,
                thread_id=thread_id,
                approver=aprobador(scenario),
                tags=(*tags, scenario.categoria),
                metadata={"categoria": scenario.categoria},
                environment=environment,
                release=assignment.release,
            )
    except Exception as error:  # una conversación fallida no para la simulación
        return SimResult(
            scenario=scenario,
            assignment=assignment,
            trace_id=None,
            answer="",
            error=f"{type(error).__name__}: {error}",
            latency_s=time.perf_counter() - inicio,
        )
    return SimResult(
        scenario=scenario,
        assignment=assignment,
        trace_id=turn.trace_id,
        answer=turn.answer,
        tool_calls=turn.tool_calls,
        latency_s=time.perf_counter() - inicio,
    )


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
    """``n`` conversaciones de viajeros al azar (reproducible con ``seed``).

    ``assign(user_id)`` decide a qué versión va cada viajero. La valoración de cada
    conversación queda en Langfuse como el score ``user_feedback`` (1 = 👍, 0 = 👎).
    Nexus contesta con el modelo con guion: sin tokens, pero con la latencia de un modelo.
    """

    instalar(latencia=True)
    dia = hoy or settings.nexus_today
    rng = random.Random(seed)
    peticiones = [pick_scenario(rng, dia, proximos=True) for _ in range(n)]
    asignaciones = [assign(scenario.viajero) for scenario in peticiones]
    graphs = {flags: build_graph(flags=flags) for flags in {a.flags for a in asignaciones}}
    semaforo = asyncio.Semaphore(max(1, concurrency))
    entorno = environment or settings.environment

    async def una(scenario: Scenario, assignment: Assignment) -> SimResult:
        thread_id = uuid4().hex
        async with semaforo:
            with guion_scope(Guion(scenario, thread_id)):
                result = await conversar(
                    graphs[assignment.flags],
                    scenario,
                    assignment,
                    thread_id=thread_id,
                    environment=entorno,
                    tags=tags,
                )
        if result.trace_id and not result.error:
            result.feedback = feedback_for(
                scenario, result.answer, result.tool_calls, semilla=result.trace_id
            )
            if result.feedback is not None:
                langfuse.create_score(
                    name=FEEDBACK_SCORE,
                    value=result.feedback,
                    trace_id=result.trace_id,
                    data_type="NUMERIC",
                    environment=entorno,
                    # Para filtrar los comentarios en la tabla Scores por categoría y versión.
                    metadata={"categoria": scenario.categoria, "release": assignment.release},
                    comment=comentario_for(
                        scenario,
                        result.answer,
                        result.tool_calls,
                        result.feedback,
                        semilla=result.trace_id,
                    ),
                )
        return result

    results = await asyncio.gather(
        *(
            una(scenario, assignment)
            for scenario, assignment in zip(peticiones, asignaciones, strict=True)
        )
    )
    langfuse.flush()
    return list(results)
