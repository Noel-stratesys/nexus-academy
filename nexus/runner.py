"""Ejecutar un turno de conversación con Nexus, trazado en Langfuse.

Lo usan el chat de la terminal, los experimentos y el simulador de viajeros, para que
todas las trazas tengan la misma forma: una traza ``nexus-agent`` por turno, con el
viajero como usuario y la conversación como sesión.

La observation raíz lleva todo lo que necesita un evaluador que la juzgue: la pregunta en
la entrada y, en la salida, la respuesta y el contexto (los fragmentos de normativa que
leyó el modelo). Así los jueces de Langfuse no tienen que buscar nada en las hijas.
"""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from nexus.context import Context
from nexus.llm.langfuse_client import langfuse, trace_run, with_langfuse
from nexus.state import answer_text

# Recibe las acciones pendientes y devuelve, para cada una, "approve" o un motivo de rechazo.
Approver = Callable[[list[dict[str, Any]]], Awaitable[list[str]]]

TRACE_NAME = "nexus-agent"


async def approve_all(actions: list[dict[str, Any]]) -> list[str]:
    return ["approve"] * len(actions)


@dataclass
class TurnResult:
    answer: str
    trace_id: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    verdict: str | None = None
    messages: list[Any] = field(default_factory=list)
    contexto: list[dict[str, Any]] = field(default_factory=list)


def _decision(reply: str) -> dict[str, Any]:
    if reply == "approve":
        return {"type": "approve"}
    return {
        "type": "reject",
        "message": f"El viajero no aprobó la acción y no se ha ejecutado. Respondió: «{reply}».",
    }


def _tool_calls(messages: Sequence[Any]) -> list[dict[str, Any]]:
    results = {
        message.tool_call_id: message.content
        for message in messages
        if isinstance(message, ToolMessage)
    }
    return [
        {"name": call["name"], "args": call["args"], "result": results.get(call["id"] or "")}
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


def retrieved_context(tool_calls: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los fragmentos de normativa que leyó el modelo: los que devolvió ``buscar_normativa``.

    Es el contexto contra el que se juzga la respuesta, tal como le llegó al modelo y en
    el orden de las llamadas. Sin llamadas a ``buscar_normativa``, la lista está vacía.
    """

    fragments: list[dict[str, Any]] = []
    for call in tool_calls:
        if call["name"] != "buscar_normativa" or not call.get("result"):
            continue
        payload = call["result"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            fragments.extend(payload.get("fragmentos", []))
    return fragments


def root_output(answer: str, tool_calls: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """La salida de la observation raíz: la respuesta y el contexto en que se basó."""

    return {"respuesta": answer, "contexto": retrieved_context(tool_calls)}


async def run_turn(
    graph: Any,
    text: str,
    *,
    context: Context,
    thread_id: str,
    approver: Approver = approve_all,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    environment: str | None = None,
    release: str | None = None,
) -> TurnResult:
    """Un turno completo: la petición, las aprobaciones que pida y la respuesta final.

    ``release`` es la versión de Nexus que atiende el turno (la ponen el simulador y el
    historial); sin ella, la traza no lleva release.
    """

    config = with_langfuse({"configurable": {"thread_id": thread_id}})
    before = len((await graph.aget_state(config)).values.get("messages", []))
    approvals: list[dict[str, Any]] = []
    trace_metadata = {"idioma": context.viajero.idioma, **(metadata or {})}
    with trace_run(
        name=TRACE_NAME,
        session_id=thread_id,
        user_id=context.viajero.id,
        tags=tags,
        metadata=trace_metadata,
        environment=environment,
        release=release,
    ):
        with langfuse.start_as_current_observation(
            name=TRACE_NAME,
            as_type="agent",
            # El nombre va en la entrada porque Nexus saluda con él: así el juez de
            # fidelidad sabe de dónde sale y no lo toma por un dato inventado.
            input={"mensaje": text, "viajero": context.viajero.nombre},
        ) as root:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=text)]}, config=config, context=context
            )
            while result.get("__interrupt__"):
                actions = result["__interrupt__"][0].value["action_requests"]
                replies = await approver(actions)
                approvals.extend(
                    {"name": action["name"], "args": action["args"], "decision": reply}
                    for action, reply in zip(actions, replies, strict=True)
                )
                result = await graph.ainvoke(
                    Command(resume={"decisions": [_decision(reply) for reply in replies]}),
                    config=config,
                    context=context,
                )
            messages = result.get("messages", [])[before:]
            answer = answer_text(messages)
            tool_calls = _tool_calls(messages)
            output = root_output(answer, tool_calls)
            root.update(output=output)
            trace_id = root.trace_id
    decision = result.get("orchestrator")
    return TurnResult(
        answer=answer,
        trace_id=trace_id,
        tool_calls=tool_calls,
        approvals=approvals,
        verdict=decision.verdict.value if decision is not None else None,
        messages=messages,
        contexto=output["contexto"],
    )
