"""Estado del grafo: la conversación y la decisión del orquestador."""

from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph.message import add_messages

from nexus.decisions import OrchestratorDecision


class GraphState(TypedDict, total=False):
    """``messages`` es la fuente de verdad: el turno empieza con la petición del viajero
    como último mensaje y termina con la respuesta de Nexus (ver ``answer_text``)."""

    messages: Annotated[list[AnyMessage], add_messages]
    orchestrator: OrchestratorDecision | None


def answer_text(messages: Sequence[AnyMessage]) -> str:
    """El texto de la respuesta: el último mensaje de Nexus que no llama a herramientas."""

    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return message.text
    return ""
