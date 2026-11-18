"""Orquestador: clasifica la petición con salida estructurada y responde a las que rechaza.

Si la petición no es válida, contesta aquí con una frase fija y el executor no se ejecuta.
"""

import logging
from collections.abc import Sequence
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from nexus.context import Context, run_context
from nexus.decisions import (
    ModelVerdict,
    OrchestratorDecision,
    Verdict,
    criteria_text,
    empty_request_decision,
)
from nexus.llm.models import MALFORMED_OUTPUT_RETRIES, chat_model, is_malformed_output
from nexus.llm.prompts import chat_template, langfuse_prompt, model_for
from nexus.prompts import ORCHESTRATOR_PROMPT_NAME
from nexus.state import GraphState

logger = logging.getLogger(__name__)

# Turnos anteriores que ve el modelo: suficientes para entender "¿y mañana?".
_CONVERSATION_WINDOW = 6

UNAVAILABLE_RESPONSE = (
    "Ahora mismo no puedo atender tu consulta. Vuelve a intentarlo en unos minutos."
)

REJECTIONS = {
    Verdict.EMPTY: "Escribe tu consulta: horarios, incidencias, tarifas, normativa del metro...",
    Verdict.UNINTELLIGIBLE: (
        "No he entendido tu consulta. ¿Puedes reformularla? Puedo ayudarte con horarios, "
        "incidencias, tarifas y normativa de Metro de Vilaverda."
    ),
    Verdict.OUT_OF_SCOPE: (
        "Solo puedo ayudarte con temas de Metro de Vilaverda: horarios, incidencias, "
        "tarifas, normativa, accesibilidad, objetos perdidos y reclamaciones."
    ),
}


async def classify_request(
    messages: Sequence[BaseMessage], *, context: Context, config: RunnableConfig | None = None
) -> OrchestratorDecision:
    """Pide al modelo el veredicto sobre el último mensaje de ``messages``.

    Dentro del grafo, la llamada hereda la configuración de la ejecución. Fuera de él
    (por ejemplo, en un experimento del orquestador), pásala con ``with_langfuse()``.

    El veredicto se pide como JSON con esquema (``method="json_schema"``), no como una
    llamada a herramienta: el modelo solo escribe ``{"verdict": "..."}``, sin las
    etiquetas de herramienta en las que a veces se equivoca, y gasta menos tokens. Si
    aun así escribe mal la salida, la llamada se repite al momento.
    """

    prompt = langfuse_prompt(ORCHESTRATOR_PROMPT_NAME)
    model = chat_model(model_for(prompt, context.models.orchestrator))
    structured = model.with_structured_output(ModelVerdict, method="json_schema")
    chain = (chat_template(prompt) | structured).with_config(run_name="orchestrator")
    inputs = {"messages": list(messages), "criteria": criteria_text()}
    for attempt in range(MALFORMED_OUTPUT_RETRIES + 1):
        try:
            answer = cast(ModelVerdict, await chain.ainvoke(inputs, config))
            return answer.decision()
        except Exception as error:
            if attempt == MALFORMED_OUTPUT_RETRIES or not is_malformed_output(error):
                raise
            logger.info("El modelo escribió mal el veredicto; se repite la llamada: %s", error)
    raise AssertionError("inalcanzable: el bucle devuelve o lanza")


def _conversation(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """El diálogo reciente, sin llamadas a herramientas, terminando en la petición."""

    dialogue: list[BaseMessage] = [
        message
        for message in messages
        if isinstance(message, HumanMessage)
        or (isinstance(message, AIMessage) and not message.tool_calls)
    ]
    return dialogue[-(_CONVERSATION_WINDOW + 1) :]


async def orchestrator(state: GraphState, *, runtime: Runtime[Context]) -> dict[str, Any]:
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    request = last.text if isinstance(last, HumanMessage) else ""
    decision = empty_request_decision(request)
    if decision is None:
        try:
            decision = await classify_request(_conversation(messages), context=run_context(runtime))
        except Exception as error:  # noqa: BLE001 - cualquier fallo rechaza la petición.
            logger.warning("No se pudo clasificar la petición: %s", error)
            return {"orchestrator": None, "messages": [AIMessage(content=UNAVAILABLE_RESPONSE)]}

    if not decision.is_valid:
        return {
            "orchestrator": decision,
            "messages": [AIMessage(content=REJECTIONS[decision.verdict])],
        }
    return {"orchestrator": decision}
