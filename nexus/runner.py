"""Ejecutar un turno de conversación con Nexus, trazado en Langfuse.

Lo usan el chat de la terminal, los experimentos y el simulador de viajeros, para que
todas las trazas tengan la misma forma: una traza ``nexus-agent`` por turno, con el
viajero como usuario y la conversación como sesión.
"""

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
) -> TurnResult:
    """Un turno completo: la petición, las aprobaciones que pida y la respuesta final."""

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
    ):
        with langfuse.start_as_current_observation(
            name=TRACE_NAME, as_type="agent", input={"mensaje": text}
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
            root.update(output={"respuesta": answer})
            trace_id = root.trace_id
    decision = result.get("orchestrator")
    return TurnResult(
        answer=answer,
        trace_id=trace_id,
        tool_calls=_tool_calls(messages),
        approvals=approvals,
        verdict=decision.verdict.value if decision is not None else None,
        messages=messages,
    )
