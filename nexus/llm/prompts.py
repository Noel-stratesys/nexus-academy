"""Prompts de Langfuse: qué versión usa cada ejecución y cómo se convierte en plantilla.

La aplicación pide cada prompt por **label** (``production`` por defecto). Dos cosas
pueden cambiar esa elección sin tocar el código de los nodos:

- un experimento fija versiones concretas (``prompt_version_scope``), para que todos
  los casos usen exactamente las mismas;
- el enrutador de despliegues elige otro label (``prompt_label_scope``), por ejemplo
  ``green`` para la parte del tráfico que prueba una versión nueva.
"""

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

from langchain_core.prompts import ChatPromptTemplate
from langfuse.model import ChatPromptClient

from nexus.llm.langfuse_client import langfuse
from nexus.prompts import PROMPTS_BY_NAME
from nexus.settings import ModelConfig, settings

_PINNED_VERSIONS: ContextVar[Mapping[str, int] | None] = ContextVar("pinned_versions", default=None)
_LABEL: ContextVar[str | None] = ContextVar("prompt_label", default=None)

CACHE_TTL_SECONDS = 60


@contextmanager
def prompt_version_scope(versions: Mapping[str, int]) -> Iterator[None]:
    """Fija versiones de prompt para lo que se ejecute dentro (un caso de experimento)."""

    token = _PINNED_VERSIONS.set(versions)
    try:
        yield
    finally:
        _PINNED_VERSIONS.reset(token)


@contextmanager
def prompt_label_scope(label: str) -> Iterator[None]:
    """Lee los prompts con otro label mientras dure el bloque (blue/green)."""

    token = _LABEL.set(label)
    try:
        yield
    finally:
        _LABEL.reset(token)


def active_label() -> str:
    return _LABEL.get() or settings.environment


def langfuse_prompt(name: str, *, label: str | None = None) -> ChatPromptClient:
    """El prompt de chat que toca usar ahora.

    Si Langfuse no responde, se usa el prompt definido en el código (``fallback``): Nexus
    sigue funcionando y la generación queda marcada como ``is_fallback``.
    """

    definition = PROMPTS_BY_NAME[name]
    version = (_PINNED_VERSIONS.get() or {}).get(name)
    if version is not None:
        return langfuse.get_prompt(name=name, type="chat", version=version)
    return langfuse.get_prompt(
        name=name,
        type="chat",
        label=label or active_label(),
        cache_ttl_seconds=CACHE_TTL_SECONDS,
        fallback=cast(Any, definition.messages),
    )


def model_for(prompt: ChatPromptClient, base: ModelConfig) -> ModelConfig:
    """El modelo del nodo con los parámetros que fije el prompt (``config.model``).

    El proveedor y el nombre del modelo salen de la configuración; la temperatura y el
    límite de tokens pueden venir del prompt, para versionarlos junto a él.
    """

    overrides = (prompt.config or {}).get("model") or {}
    allowed = {key: overrides[key] for key in ("temperature", "max_tokens") if key in overrides}
    return base.model_copy(update=allowed) if allowed else base


class _OpenPlaceholdersFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "have not been resolved" not in record.getMessage()


def chat_template(prompt: ChatPromptClient) -> ChatPromptTemplate:
    """Convierte un prompt de chat de Langfuse en una plantilla de LangChain.

    Los placeholders (``{"type": "placeholder", "name": "messages"}``) se convierten en
    ``MessagesPlaceholder``. La metadata enlaza cada generación con esta versión del
    prompt, y así Langfuse sabe qué versión produjo cada respuesta.
    """

    langfuse_logger = logging.getLogger("langfuse")
    quiet = _OpenPlaceholdersFilter()
    langfuse_logger.addFilter(quiet)
    try:
        messages = prompt.get_langchain_prompt()
    finally:
        langfuse_logger.removeFilter(quiet)
    template = ChatPromptTemplate.from_messages(cast(Any, messages))
    template.metadata = {"langfuse_prompt": prompt}
    return template
