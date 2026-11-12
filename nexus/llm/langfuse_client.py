"""Cliente de Langfuse, el handler de LangChain y cómo empieza una ejecución trazada.

Una ejecución (un turno de conversación, un caso de un experimento) se traza así::

    with trace_run(name="nexus-agent", session_id=..., user_id=...):
        await graph.ainvoke(..., config=with_langfuse())

``with_langfuse`` añade el handler donde empieza la ejecución; todo lo que corre dentro
(nodos, modelos, tools, el buscador de normativa) lo hereda y queda en la misma traza.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

from nexus.settings import initialize_environment, settings

initialize_environment()

langfuse = get_client()
langfuse_handler = CallbackHandler()


def with_langfuse(config: RunnableConfig | None = None) -> RunnableConfig:
    """``config`` con el handler de Langfuse."""

    return merge_configs(config, {"callbacks": [langfuse_handler]})


def trace_run(
    *,
    name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    environment: str | None = None,
) -> Any:
    """Nombra la traza y le pone sesión, usuario, etiquetas, metadatos y entorno.

    El entorno separa el tráfico real (``production``) de los experimentos, para que
    los paneles de producción no mezclen las dos cosas.
    """

    return propagate_attributes(
        trace_name=name,
        session_id=session_id,
        user_id=user_id,
        tags=list(tags),
        metadata=dict(metadata or {}),
        environment=environment or settings.environment,
    )
