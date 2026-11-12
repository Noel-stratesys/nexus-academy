"""Las trazas del historial: se capturan en memoria y se reescriben en su fecha.

El historial ejecuta Nexus de verdad, pero hoy y en milisegundos. Antes de mandar cada
traza a Langfuse, ``rehacer_traza`` la reescribe:

- en su momento del historial (``inicio``) y con duraciones verosímiles: lo que tarda el
  modelo según los tokens, una consulta al sistema central de incidencias cuando está
  ocupado, lo que tarda el viajero en aprobar una acción...;
- con identificadores que salen de la conversación, no del azar: la misma conversación es
  siempre la misma traza, y ``uv run seed`` sabe qué días ya están en Langfuse.

La estructura (qué observación cuelga de cuál), los atributos y los datos no se tocan.
"""

import base64
import hashlib
import json
import os
import threading
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from importlib.metadata import version

from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanContext, TraceFlags

TIPO = "langfuse.observation.type"
PASO = "langfuse.observation.metadata.langgraph_step"
ENTRADA = "langfuse.observation.input"
SALIDA = "langfuse.observation.output"
USO = "langfuse.observation.usage_details"

NS = 1_000_000_000


class SpanBuffer(SpanExporter):
    """Exportador que guarda los spans en memoria en vez de mandarlos."""

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def take(self) -> list[ReadableSpan]:
        """Los spans recibidos desde la última vez, y vacía el buffer."""

        with self._lock:
            spans, self._spans = self._spans, []
        return spans

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def exportador_langfuse() -> OTLPSpanExporter:
    """El exportador OTLP que usa el SDK de Langfuse, apuntando al Langfuse del ``.env``."""

    base_url = (
        os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or "https://cloud.langfuse.com"
    ).rstrip("/")
    public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
    secret_key = os.environ["LANGFUSE_SECRET_KEY"]
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
    return OTLPSpanExporter(
        endpoint=f"{base_url}/api/public/otel/v1/traces",
        headers={
            "Authorization": f"Basic {auth}",
            "x-langfuse-sdk-name": "python",
            "x-langfuse-sdk-version": version("langfuse"),
            "x-langfuse-public-key": public_key,
            "x-langfuse-ingestion-version": "4",
        },
        timeout=60,
        compression=Compression.Gzip,
    )


def exportar(exportador: SpanExporter, spans: Sequence[ReadableSpan], lote: int = 200) -> None:
    for inicio in range(0, len(spans), lote):
        if exportador.export(spans[inicio : inicio + lote]) is not SpanExportResult.SUCCESS:
            raise RuntimeError("Langfuse no ha aceptado las trazas del historial.")


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def trace_id_de(semilla: str) -> str:
    """El identificador de traza (32 hex) de la conversación ``semilla``."""

    return _hash("traza", semilla)[:32]


def agrupar_por_traza(spans: Sequence[ReadableSpan]) -> dict[int, list[ReadableSpan]]:
    trazas: dict[int, list[ReadableSpan]] = defaultdict(list)
    for span in spans:
        if span.context is not None:
            trazas[span.context.trace_id].append(span)
    return dict(trazas)


def _segundos_hoja(span: ReadableSpan, azar: Callable[[str], float]) -> float:
    """Lo que tarda una observación sin hijas."""

    atributos = span.attributes or {}
    tipo = atributos.get(TIPO)
    if tipo == "generation":
        uso = json.loads(str(atributos.get(USO) or "{}"))
        segundos = 0.25 + uso.get("output", 0) / 210 + uso.get("input", 0) / 9000
        segundos *= 0.85 + 0.5 * azar("ritmo")
        if azar("espera") < 0.03:
            segundos += 2 + 4 * azar("reintento")  # el proveedor pidió esperar (429)
        return segundos
    if tipo == "tool":
        if "ocupado" in str(atributos.get(SALIDA) or ""):
            return 3.8 + 0.6 * azar("ocupado")  # el sistema central agota su espera
        return 0.02 + 0.07 * azar("tool")
    if tipo == "retriever":
        return 0.03 + 0.09 * azar("retriever")
    return 0.0004 + 0.0026 * azar("paso")


def _oleadas(hijos: Sequence[ReadableSpan]) -> list[list[ReadableSpan]]:
    """Las hijas agrupadas por lo que corre a la vez, en orden.

    LangGraph ejecuta en paralelo las tareas de un mismo paso (``langgraph_step``) con el
    mismo nombre: por ejemplo, varias llamadas a herramientas pedidas a la vez. El resto va
    una detrás de otra, en el orden en que empezaron.
    """

    oleadas: list[list[ReadableSpan]] = []
    for span in sorted(hijos, key=lambda s: s.start_time or 0):
        paso = (span.attributes or {}).get(PASO)
        anterior = oleadas[-1][0] if oleadas else None
        if (
            anterior is not None
            and paso is not None
            and anterior.name == span.name
            and (anterior.attributes or {}).get(PASO) == paso
        ):
            oleadas[-1].append(span)
        else:
            oleadas.append([span])
    return [
        sorted(oleada, key=lambda s: (s.name, str((s.attributes or {}).get(ENTRADA))))
        for oleada in oleadas
    ]


def rehacer_traza(
    spans: Sequence[ReadableSpan], *, semilla: str, inicio: datetime
) -> tuple[str, list[ReadableSpan]]:
    """La traza ``spans`` empezando en ``inicio``, con identificadores de ``semilla``.

    Devuelve el identificador de la traza nueva y sus spans.
    """

    ids = {span.context.span_id for span in spans if span.context is not None}
    hijos: dict[int, list[ReadableSpan]] = defaultdict(list)
    raices = []
    for span in spans:
        padre = span.parent.span_id if span.parent is not None else None
        if padre in ids:
            hijos[padre].append(span)
        else:
            raices.append(span)
    if len(raices) != 1:
        raise ValueError(f"La traza tiene {len(raices)} raíces; esperaba una.")

    trace_hex = trace_id_de(semilla)
    trace_id = int(trace_hex, 16)
    nuevos: list[ReadableSpan] = []

    def contexto(ruta: str) -> SpanContext:
        span_id = int(_hash(trace_hex, ruta)[:16], 16) or 1
        return SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )

    def colocar(span: ReadableSpan, padre: SpanContext | None, ruta: str, desde: int) -> int:
        def azar(clave: str) -> float:
            return int(_hash(trace_hex, ruta, clave)[:12], 16) / 16**12

        propio = contexto(ruta)
        mias = hijos.get(span.context.span_id, []) if span.context is not None else []
        if not mias:
            hasta = desde + int(_segundos_hoja(span, azar) * NS)
        else:
            cursor = desde + int((0.0003 + 0.0012 * azar("entrada")) * NS)
            if (span.attributes or {}).get(TIPO) == "tool":
                cursor += int((0.01 + 0.03 * azar("preparar")) * NS)
            vistos: dict[str, int] = defaultdict(int)
            for numero, oleada in enumerate(_oleadas(mias)):
                if numero:
                    if padre is None:
                        pausa = 4 + 14 * azar(f"viajero-{numero}")  # el viajero decide
                    else:
                        pausa = 0.0002 + 0.0013 * azar(f"hueco-{numero}")
                    cursor += int(pausa * NS)
                finales = []
                for orden, hija in enumerate(oleada):
                    ruta_hija = f"{ruta}/{hija.name}#{vistos[hija.name]}"
                    vistos[hija.name] += 1
                    arranque = cursor + int(orden * (0.0001 + 0.0003 * azar(ruta_hija)) * NS)
                    finales.append(colocar(hija, propio, ruta_hija, arranque))
                cursor = max(finales)
            hasta = cursor + int((0.0003 + 0.0012 * azar("salida")) * NS)
        nuevos.append(
            ReadableSpan(
                name=span.name,
                context=propio,
                parent=padre,
                resource=span.resource,
                attributes=span.attributes,
                events=(),
                links=(),
                kind=span.kind,
                status=span.status,
                start_time=desde,
                end_time=hasta,
                instrumentation_scope=span.instrumentation_scope,
            )
        )
        return hasta

    desde = int(inicio.timestamp()) * NS + inicio.microsecond * 1000
    colocar(raices[0], None, raices[0].name, desde)
    return trace_hex, nuevos
