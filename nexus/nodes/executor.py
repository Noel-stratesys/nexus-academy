"""Executor: el agente que resuelve las peticiones que el orquestador acepta.

Es un agente de LangChain (``create_agent``) con las herramientas de Nexus. Antes de cada
llamada al modelo, ``prompt_and_model`` lee el prompt de Langfuse, lo rellena con el
viajero y la fecha, y elige el modelo con la temperatura que fije el prompt.

Las herramientas marcadas con ``metadata={"requires_approval": True}`` (reclamaciones,
devoluciones, alertas) pausan la ejecución hasta que el viajero aprueba o rechaza.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
    wrap_model_call,
)
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool

from nexus.calendar import describe
from nexus.context import Context, run_context
from nexus.llm.models import MALFORMED_OUTPUT_RETRIES, chat_model, is_malformed_output
from nexus.llm.prompts import chat_template, langfuse_prompt, model_for
from nexus.prompts import EXECUTOR_PROMPT_NAME
from nexus.settings import settings
from nexus.tools import format_tool_catalog, tools_for

# Llamadas al modelo por turno como máximo: corta los bucles de herramientas.
MAX_MODEL_CALLS = 12


def _prompt_and_model(tools: Sequence[BaseTool]) -> Any:
    catalog = format_tool_catalog(tools)

    @wrap_model_call
    async def prompt_and_model(request: ModelRequest[Context], handler: Any) -> Any:
        context = run_context(request.runtime)
        prompt = langfuse_prompt(EXECUTOR_PROMPT_NAME)
        # Invocar la plantilla dentro de la ejecución enlaza la generación con esta versión.
        messages = (
            chat_template(prompt)
            .invoke(
                {
                    "viajero": context.viajero.describe(),
                    "hoy": describe(context.hoy),
                    "tool_catalog": catalog,
                }
            )
            .to_messages()
        )
        system = SystemMessage(content="\n\n".join(str(message.content) for message in messages))
        model = chat_model(model_for(prompt, context.models.executor))
        return await handler(request.override(model=model, system_message=system))

    return prompt_and_model


def _model_call_timeout() -> Any:
    seconds = settings.llm_call_timeout_seconds

    @wrap_model_call
    async def bounded_call(request: Any, handler: Any) -> Any:
        try:
            async with asyncio.timeout(seconds):
                return await handler(request)
        except TimeoutError as error:
            raise TimeoutError(f"La llamada al modelo superó {seconds:g} segundos.") from error

    return bounded_call


def human_approval(tools: Sequence[BaseTool]) -> HumanInTheLoopMiddleware | None:
    """Pausa antes de cada herramienta que necesita la aprobación del viajero."""

    interrupt_on: dict[str, Any] = {
        tool.name: {"allowed_decisions": ["approve", "reject"]}
        for tool in tools
        if (tool.metadata or {}).get("requires_approval")
    }
    return HumanInTheLoopMiddleware(interrupt_on=interrupt_on) if interrupt_on else None


def build_executor_agent(flags: frozenset[str] = frozenset()) -> Any:
    """El agente del executor con las herramientas que activan ``flags``."""

    tools = tools_for(flags)
    middleware: list[Any] = [
        _prompt_and_model(tools),
        # Si el modelo escribe mal una llamada a herramienta, se repite al momento.
        ModelRetryMiddleware(
            max_retries=MALFORMED_OUTPUT_RETRIES,
            retry_on=is_malformed_output,
            on_failure="error",
            initial_delay=0.5,
            backoff_factor=0.0,
            jitter=False,
        ),
        ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end"),
        ToolRetryMiddleware(
            max_retries=settings.executor_tool_max_retries,
            retry_on=(ValueError, TypeError, KeyError, TimeoutError),
            on_failure="continue",
        ),
        _model_call_timeout(),
    ]
    approval = human_approval(tools)
    if approval is not None:
        middleware.insert(0, approval)
    return create_agent(
        model=chat_model(settings.models.executor),
        tools=tools,
        middleware=middleware,
        context_schema=Context,
        name="executor",
    )
