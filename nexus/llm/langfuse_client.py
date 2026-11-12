"""Cliente de Langfuse, el handler de LangChain y cómo empieza una ejecución trazada.

Una ejecución (un turno de conversación, un caso de un experimento) se traza así::

    with trace_run(name="nexus-agent", session_id=..., user_id=...):
        await graph.ainvoke(..., config=with_langfuse())

``with_langfuse`` añade el handler donde empieza la ejecución; todo lo que corre dentro
(nodos, modelos, tools, el buscador de normativa) lo hereda y queda en la misma traza.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler
from opentelemetry import trace as otel_trace
from opentelemetry.context import Context as OtelContext
from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider

from nexus.settings import initialize_environment, settings

initialize_environment()

langfuse = get_client()
langfuse_handler = CallbackHandler()

RELEASE_ATTRIBUTE = "langfuse.release"
_release: ContextVar[str | None] = ContextVar("nexus_release", default=None)


class _ReleaseProcessor(SpanProcessor):
    """Pone la release de la ejecución en curso a cada observación que empieza."""

    def on_start(self, span: Span, parent_context: OtelContext | None = None) -> None:
        release = _release.get()
        if release:
            span.set_attribute(RELEASE_ATTRIBUTE, release)


# get_client() deja como global el TracerProvider de Langfuse (del SDK de OpenTelemetry).
_provider = otel_trace.get_tracer_provider()
if isinstance(_provider, TracerProvider):
    _provider.add_span_processor(_ReleaseProcessor())


def with_langfuse(config: RunnableConfig | None = None) -> RunnableConfig:
    """``config`` con el handler de Langfuse."""

    return merge_configs(config, {"callbacks": [langfuse_handler]})


@contextmanager
def trace_run(
    *,
    name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    environment: str | None = None,
    release: str | None = None,
) -> Iterator[None]:
    """Nombra la traza y le pone sesión, usuario, etiquetas, metadatos, entorno y release.

    El entorno separa el tráfico real (``production``) de los experimentos, para que
    los paneles de producción no mezclen las dos cosas. La release dice qué versión de
    Nexus atendió la ejecución (``blue``, ``green``...): es lo que comparan los paneles
    durante un canary.
    """

    token = _release.set(release) if release else None
    try:
        with propagate_attributes(
            trace_name=name,
            session_id=session_id,
            user_id=user_id,
            tags=list(tags),
            metadata=dict(metadata or {}),
            environment=environment or settings.environment,
        ):
            yield
    finally:
        if token is not None:
            _release.reset(token)
