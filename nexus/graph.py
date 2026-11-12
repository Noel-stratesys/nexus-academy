"""El grafo de Nexus: orquestador → executor.

    START → orchestrator ─(válida)→ executor → END
                         └(rechazada: ya respondió)→ END

``build_graph()`` es el contrato del proyecto: los experimentos, el simulador y la
evaluación del proyecto final construyen el agente siempre a través de esta función.
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from nexus.context import Context
from nexus.decisions import OrchestratorDecision, Verdict
from nexus.nodes.executor import build_executor_agent
from nexus.nodes.orchestrator import orchestrator
from nexus.state import GraphState

_STATE_TYPES = [OrchestratorDecision, Verdict]


def _after_orchestrator(state: GraphState) -> str:
    decision = state.get("orchestrator")
    return "executor" if decision is not None and decision.is_valid else END


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None, *, flags: frozenset[str] = frozenset()
) -> Any:
    """Compila el grafo. Sin checkpointer, guarda las conversaciones en memoria."""

    if checkpointer is None:
        checkpointer = MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_STATE_TYPES))
    graph = StateGraph(GraphState, context_schema=Context)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("executor", build_executor_agent(flags))
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator", _after_orchestrator, {END: END, "executor": "executor"}
    )
    graph.add_edge("executor", END)
    return graph.compile(checkpointer=checkpointer)
