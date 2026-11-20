"""Tareas de los experimentos: ejecutan una parte de Nexus sobre cada caso del dataset.

- ``orchestrator``: solo el orquestador. Devuelve el veredicto.
- ``agent``: el grafo completo, como en producción. Devuelve la respuesta, las
  herramientas usadas, las acciones que pidió aprobar y los fragmentos de normativa
  recuperados. En los experimentos se aprueban todas las acciones.

Todas las ejecuciones de un experimento usan las mismas versiones de prompt (fijadas
al empezar) y el mismo modelo, para que los resultados se puedan comparar.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage

from nexus.context import Context
from nexus.decisions import empty_request_decision
from nexus.graph import build_graph
from nexus.llm.langfuse_client import trace_run, with_langfuse
from nexus.llm.prompts import prompt_version_scope
from nexus.nodes.orchestrator import UNAVAILABLE_RESPONSE, classify_request
from nexus.runner import retrieved_context, run_turn
from nexus.settings import Models, RagSettings, settings

logger = logging.getLogger(__name__)

EXPERIMENT_ENVIRONMENT = "experimento"
Task = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class RunSettings:
    """Lo que define una variante de Nexus en un experimento."""

    prompt_versions: dict[str, int]
    models: Models = field(default_factory=lambda: settings.models)
    rag: RagSettings = field(default_factory=lambda: settings.rag)
    flags: frozenset[str] = frozenset()

    def context(self, item_input: dict[str, Any]) -> Context:
        return Context.for_user(
            item_input.get("viajero"),
            hoy=date.fromisoformat(item_input.get("hoy") or settings.nexus_today.isoformat()),
            models=self.models,
            rag=self.rag,
            flags=self.flags,
        )


class ModelUnavailableError(RuntimeError):
    """El orquestador no pudo llamar al modelo (normalmente, por límite de peticiones)."""


def _is_rate_limit(error: Exception) -> bool:
    return (
        isinstance(error, ModelUnavailableError)
        or "429" in str(error)
        # El modelo a veces inventa una herramienta y el proveedor rechaza la llamada.
        or "tool call validation failed" in str(error)
        or "rate" in type(error).__name__.lower()
    )


async def _with_retries(run: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Reintenta si el proveedor del modelo limita las peticiones; otro error se devuelve."""

    for attempt in range(4):
        try:
            return await run()
        except Exception as error:  # noqa: BLE001 - el error se guarda en la salida.
            if _is_rate_limit(error) and attempt < 3:
                await asyncio.sleep(20 * (attempt + 1))
                continue
            logger.warning("El caso falló: %s", error)
            return {"error": f"{type(error).__name__}: {error}"[:500]}
    return {"error": "Demasiados reintentos"}


def _fragments(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Ids de los fragmentos de normativa que devolvió ``buscar_normativa``."""

    return [fragment["id"] for fragment in retrieved_context(tool_calls)]


def make_task(target: str, run: RunSettings) -> Task:
    """La función que el experimento ejecuta en cada caso."""

    if target == "orchestrator":

        async def orchestrator_task(*, item: Any, **_: Any) -> dict[str, Any]:
            text = item.input.get("mensaje", "")
            context = run.context(item.input)

            async def classify() -> dict[str, Any]:
                with prompt_version_scope(run.prompt_versions):
                    decision = empty_request_decision(text) or await classify_request(
                        [HumanMessage(content=text)], context=context, config=with_langfuse()
                    )
                return {"verdict": decision.verdict.value}

            with trace_run(name="nexus-orchestrator", environment=EXPERIMENT_ENVIRONMENT):
                return await _with_retries(classify)

        return orchestrator_task

    graph = build_graph(flags=run.flags)

    async def agent_task(*, item: Any, **_: Any) -> dict[str, Any]:
        context = run.context(item.input)

        async def converse() -> dict[str, Any]:
            with prompt_version_scope(run.prompt_versions):
                turn = await run_turn(
                    graph,
                    item.input["mensaje"],
                    context=context,
                    thread_id=uuid4().hex,
                    tags=["experimento"],
                    environment=EXPERIMENT_ENVIRONMENT,
                )
            if turn.verdict is None and turn.answer == UNAVAILABLE_RESPONSE:
                raise ModelUnavailableError("El orquestador no pudo clasificar la petición")
            return {
                "respuesta": turn.answer,
                "verdict": turn.verdict,
                "tools": turn.tool_calls,
                "aprobaciones": [approval["name"] for approval in turn.approvals],
                "fragmentos": _fragments(turn.tool_calls),
            }

        return await _with_retries(converse)

    return agent_task


def con_guion_de_caso(task: Task) -> Task:
    """``task`` con el modelo con guion: cada caso del dataset hace de guion.

    Hace falta ``nexus.simulation.modelo.instalar()`` antes de crear la tarea.
    """

    from nexus.simulation.modelo import guion_de_caso, guion_scope

    async def tarea(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        guion = guion_de_caso(item.input or {}, item.expected_output or {}, item.metadata)
        with guion_scope(guion):
            return await task(item=item, **kwargs)

    return tarea
