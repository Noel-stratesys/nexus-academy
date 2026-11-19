"""Las ejecuciones grabadas del capítulo 4: el historial de experimentos sobre ``nexus/rag``.

Son experimentos de verdad, lanzados una vez con el modelo de Groq, cada uno con una
configuración del buscador (``partida``, ``top_k 8``, ``solo vigentes``...). El fichero
``experimentos_grabados/rag.json.gz`` guarda, por ejecución y por caso, las trazas
completas y los scores de los evaluadores.

``uv run seed`` las carga en el Langfuse de cada alumno como si las hubiera lanzado él:

- Cada traza recibe identificadores nuevos y se enlaza con el caso de su dataset (los
  ids de los casos son fijos, ver ``evaluation/datasets/definition.py``).
- Cada ejecución queda en su día, desde el 7 de noviembre, en el orden en que se
  lanzaron, para que en la pestaña del dataset se lea como una evolución.
- Los identificadores salen de la ejecución y del caso: volver a cargar no duplica.

Las graba el instructor con ``instructor/grabaciones/grabar_experimentos.py``.
"""

import gzip
import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

FICHERO = Path(__file__).resolve().parent / "experimentos_grabados" / "rag.json.gz"
DATASET = "nexus/rag"
PRIMER_DIA = datetime(2026, 11, 7, 10, 0, tzinfo=timezone(timedelta(hours=1), "CET"))
NS = 1_000_000_000

EXPERIMENTO_ID = "langfuse.experiment.id"
EXPERIMENTO_NOMBRE = "langfuse.experiment.name"
EXPERIMENTO_DATASET = "langfuse.experiment.dataset.id"


# --- El fichero -------------------------------------------------------------------------


def span_a_dict(span: ReadableSpan) -> dict[str, Any]:
    """Un span de OpenTelemetry como datos que se pueden guardar en JSON."""

    assert span.context is not None
    scope = span.instrumentation_scope
    return {
        "name": span.name,
        "trace_id": f"{span.context.trace_id:032x}",
        "span_id": f"{span.context.span_id:016x}",
        "parent_id": f"{span.parent.span_id:016x}" if span.parent is not None else None,
        "start": span.start_time,
        "end": span.end_time,
        "attributes": {
            clave: list(valor) if isinstance(valor, tuple) else valor
            for clave, valor in (span.attributes or {}).items()
        },
        "kind": span.kind.name,
        "status": [span.status.status_code.name, span.status.description],
        "resource": dict(span.resource.attributes),
        "scope": [scope.name, scope.version] if scope is not None else None,
    }


def leer(fichero: Path = FICHERO) -> dict[str, Any]:
    with gzip.open(fichero, "rt", encoding="utf-8") as entrada:
        return json.load(entrada)


def guardar(grabacion: dict[str, Any], fichero: Path = FICHERO) -> None:
    fichero.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(fichero, "wt", encoding="utf-8") as salida:
        json.dump(grabacion, salida, ensure_ascii=False, separators=(",", ":"))


# --- Lo que se manda a Langfuse ---------------------------------------------------------


def _hash(*partes: object) -> str:
    return hashlib.sha256("|".join(str(parte) for parte in partes).encode()).hexdigest()


def experiment_id(project_id: str, dataset_id: str, run_name: str) -> str:
    """El id de la ejecución, calculado igual que lo calculan el SDK y el servidor."""

    payload = json.dumps(
        ["langfuse-experiment-v1", project_id, dataset_id, run_name],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def nombre_de_ejecucion(numero: int, variante: dict[str, Any]) -> str:
    return f"{numero:02d}-{variante['nombre']}"


def trace_id_de(run_name: str, item_id: str) -> str:
    return _hash("experimento-grabado", run_name, item_id)[:32]


def _reemplazar(valor: Any, cambios: dict[str, str]) -> Any:
    if isinstance(valor, str):
        for antes, despues in cambios.items():
            if antes in valor:
                valor = valor.replace(antes, despues)
        return valor
    if isinstance(valor, list):
        return tuple(_reemplazar(elemento, cambios) for elemento in valor)
    return valor


def _span(
    datos: dict[str, Any],
    *,
    trace_hex: str,
    ids: dict[str, int],
    desplazamiento: int,
    cambios: dict[str, str],
) -> ReadableSpan:
    trace_id = int(trace_hex, 16)

    def contexto(span_hex: str) -> SpanContext:
        return SpanContext(
            trace_id=trace_id,
            span_id=ids[span_hex],
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )

    padre = datos["parent_id"]
    scope = datos["scope"]
    codigo, descripcion = datos["status"]
    return ReadableSpan(
        name=datos["name"],
        context=contexto(datos["span_id"]),
        parent=contexto(padre) if padre in ids else None,
        resource=Resource(datos["resource"]),
        attributes={
            clave: _reemplazar(valor, cambios) for clave, valor in datos["attributes"].items()
        },
        events=(),
        links=(),
        kind=SpanKind[datos["kind"]],
        status=Status(StatusCode[codigo], descripcion),
        start_time=datos["start"] + desplazamiento,
        end_time=datos["end"] + desplazamiento,
        instrumentation_scope=InstrumentationScope(*scope) if scope else None,
    )


def _original(spans: Iterable[dict[str, Any]], clave: str) -> str | None:
    for span in spans:
        valor = span["attributes"].get(clave)
        if valor:
            return str(valor)
    return None


def preparar(
    grabacion: dict[str, Any], *, project_id: str, dataset_id: str
) -> tuple[list[ReadableSpan], list[dict[str, Any]], list[str]]:
    """Los spans y los scores de todas las ejecuciones, listos para este Langfuse.

    Devuelve los spans, los argumentos de ``create_score`` de cada score y el id de traza
    del primer caso de cada ejecución (para saber si ya está cargada).
    """

    spans: list[ReadableSpan] = []
    scores: list[dict[str, Any]] = []
    primeras: list[str] = []
    for numero, nombre in enumerate(grabacion["orden"], start=1):
        variante = grabacion["variantes"].get(nombre)
        if variante is None:  # todavía sin grabar
            continue
        run_name = nombre_de_ejecucion(numero, variante)
        nuevo_experimento = experiment_id(project_id, dataset_id, run_name)
        dia = PRIMER_DIA + timedelta(days=numero - 1)
        cursor = int(dia.timestamp()) * NS
        for caso in variante["casos"]:
            datos = caso["spans"]
            trace_hex = trace_id_de(run_name, caso["item_id"])
            if caso is variante["casos"][0]:
                primeras.append(trace_hex)
            ids = {
                span["span_id"]: int(_hash(trace_hex, span["span_id"])[:16], 16) or 1
                for span in datos
            }
            cambios = {
                antes: despues
                for antes, despues in {
                    _original(datos, EXPERIMENTO_ID): nuevo_experimento,
                    _original(datos, EXPERIMENTO_NOMBRE): run_name,
                    _original(datos, EXPERIMENTO_DATASET): dataset_id,
                    datos[0]["trace_id"]: trace_hex,
                    **{viejo: f"{nuevo:016x}" for viejo, nuevo in ids.items()},
                }.items()
                if antes
            }
            inicio = min(span["start"] for span in datos)
            fin = max(span["end"] for span in datos)
            desplazamiento = cursor - inicio
            spans.extend(
                _span(
                    span,
                    trace_hex=trace_hex,
                    ids=ids,
                    desplazamiento=desplazamiento,
                    cambios=cambios,
                )
                for span in datos
            )
            momento = datetime.fromtimestamp((fin + desplazamiento) / NS, tz=dia.tzinfo)
            for score in caso["scores"]:
                observacion = score.get("observation_id")
                scores.append(
                    {
                        "name": score["name"],
                        "value": score["value"],
                        "comment": score.get("comment"),
                        "data_type": score.get("data_type"),
                        "trace_id": trace_hex,
                        "observation_id": cambios.get(observacion, observacion),
                        "score_id": str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL, f"{run_name}/{caso['item_id']}/{score['name']}"
                            )
                        ),
                        "timestamp": momento,
                    }
                )
            cursor += (fin - inicio) + 2 * NS
        for nombre_score, valor in variante["medias"].items():
            scores.append(
                {
                    "name": f"media_{nombre_score}",
                    "value": valor,
                    "dataset_run_id": nuevo_experimento,
                    "score_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{run_name}/media_{nombre_score}")
                    ),
                    "timestamp": datetime.fromtimestamp(cursor / NS, tz=dia.tzinfo),
                }
            )
    return spans, scores, primeras


def _existe(langfuse: Any, trace_id: str) -> bool:
    encontradas = langfuse.api.observations.get_many(trace_id=trace_id, limit=1, fields="core")
    return bool(encontradas.data)


def cargar(
    langfuse: Any,
    *,
    report: Callable[[str], None] = print,
    exportar: Callable[[Sequence[ReadableSpan]], None] | None = None,
    fichero: Path = FICHERO,
) -> None:
    """Carga en Langfuse las ejecuciones grabadas que falten."""

    if not fichero.exists():
        report(
            "  No hay ejecuciones grabadas (falta evaluation/experimentos_grabados/rag.json.gz)."
        )
        return
    grabacion = leer(fichero)
    dataset_id = langfuse.get_dataset(DATASET).id
    project_id = langfuse._get_project_id()  # noqa: SLF001 - el SDK no lo expone de otra forma
    if not project_id:
        report("  ✘ No se pudo saber el proyecto de Langfuse: no se cargan las ejecuciones.")
        return
    spans, scores, primeras = preparar(grabacion, project_id=project_id, dataset_id=dataset_id)
    if all(_existe(langfuse, trace_id) for trace_id in primeras):
        report(f"  {len(primeras)} ejecuciones: ya estaban en Langfuse.")
        return

    if exportar is None:
        from nexus.simulation.trazas import exportador_langfuse
        from nexus.simulation.trazas import exportar as enviar

        exportador = exportador_langfuse()

        def exportar(lote: Sequence[ReadableSpan]) -> None:
            enviar(exportador, lote)

    exportar(spans)
    for score in scores:
        langfuse.create_score(**score)
    langfuse.flush()
    for numero, nombre in enumerate(grabacion["orden"], start=1):
        variante = grabacion["variantes"].get(nombre)
        if variante is None:
            report(f"  {numero:02d}-{nombre}: sin grabar")
            continue
        medias = ", ".join(f"{clave} {valor:.2f}" for clave, valor in variante["medias"].items())
        report(
            f"  {nombre_de_ejecucion(numero, variante)}: {len(variante['casos'])} casos · {medias}"
        )
