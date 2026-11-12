"""Cómo se define un prompt en el código antes de publicarlo en Langfuse."""

from dataclasses import dataclass, field
from typing import Any

# Un mensaje {"role": ..., "content": ...} o un hueco {"type": "placeholder", "name": ...}.
ChatMessage = dict[str, str]


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    """Un prompt de chat de Nexus.

    ``config`` viaja con cada versión en Langfuse. Su sección ``model`` puede fijar la
    temperatura y el límite de tokens; el proveedor y el modelo salen de la configuración.
    """

    name: str
    node: str
    messages: list[ChatMessage]
    tags: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
