"""Tests de las ejecuciones grabadas del capítulo 4 (``evaluation/experimentos_grabados``).

Sin Langfuse: comprueban cómo se preparan los spans y los scores de una grabación falsa
para el proyecto y el dataset de cada alumno.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

from evaluation.experimentos_grabados import (
    EXPERIMENTO_DATASET,
    EXPERIMENTO_ID,
    EXPERIMENTO_NOMBRE,
    NS,
    PRIMER_DIA,
    experiment_id,
    guardar,
    leer,
    preparar,
)

VIEJO_EXPERIMENTO = "aaaaaaaaaaaaaaaa"
VIEJO_DATASET = "dataset-del-instructor"
VIEJA_TRAZA = "1" * 32


def _span(span_id: str, padre: str | None, inicio: int, fin: int) -> dict[str, Any]:
    return {
        "name": f"span-{span_id[-1]}",
        "trace_id": VIEJA_TRAZA,
        "span_id": span_id,
        "parent_id": padre,
        "start": inicio,
        "end": fin,
        "attributes": {
            EXPERIMENTO_ID: VIEJO_EXPERIMENTO,
            EXPERIMENTO_NOMBRE: "grabacion-partida-1",
            EXPERIMENTO_DATASET: VIEJO_DATASET,
            "langfuse.experiment.item.root_observation_id": "000000000000000b",
            "langfuse.observation.metadata": f'{{"dataset_id": "{VIEJO_DATASET}"}}',
            "langfuse.trace.tags": ["experimento"],
        },
        "kind": "INTERNAL",
        "status": ["UNSET", None],
        "resource": {"service.name": "nexus"},
        "scope": ["langfuse-sdk", "5.2.0"],
    }


def _grabacion() -> dict[str, Any]:
    caso = {
        "item_id": "item-1",
        "case_id": "rag-01",
        "spans": [
            _span("000000000000000a", None, 1_000 * NS, 1_010 * NS),
            _span("000000000000000b", "000000000000000a", 1_001 * NS, 1_009 * NS),
        ],
        "scores": [
            {
                "name": "fallo_marta",
                "value": 1,
                "comment": "derogados: normativa-viajeros-2024",
                "data_type": None,
                "observation_id": "000000000000000b",
            }
        ],
    }
    variante = {"nombre": "partida", "medias": {"fallo_marta": 1.0}, "casos": [caso]}
    return {"orden": ["partida", "top_k-8"], "variantes": {"partida": variante}}


def test_spans_get_this_project_ids_and_keep_their_tree() -> None:
    spans, _, primeras = preparar(_grabacion(), project_id="proyecto", dataset_id="dataset-mio")

    nuevo = experiment_id("proyecto", "dataset-mio", "01-partida")
    raiz, hija = spans
    assert len(primeras) == 1 and f"{raiz.context.trace_id:032x}" == primeras[0]
    assert hija.parent is not None and hija.parent.span_id == raiz.context.span_id
    assert raiz.parent is None
    atributos = raiz.attributes or {}
    assert atributos[EXPERIMENTO_ID] == nuevo
    assert atributos[EXPERIMENTO_NOMBRE] == "01-partida"
    assert atributos[EXPERIMENTO_DATASET] == "dataset-mio"
    assert (
        atributos["langfuse.experiment.item.root_observation_id"] == f"{hija.context.span_id:016x}"
    )
    assert VIEJO_DATASET not in str(atributos["langfuse.observation.metadata"])
    assert atributos["langfuse.trace.tags"] == ("experimento",)


def test_each_run_starts_on_its_day_and_keeps_real_durations() -> None:
    spans, _, _ = preparar(_grabacion(), project_id="p", dataset_id="d")

    raiz = spans[0]
    assert raiz.start_time == int(PRIMER_DIA.timestamp()) * NS
    assert raiz.end_time is not None and raiz.end_time - raiz.start_time == 10 * NS


def test_scores_point_to_the_new_trace_and_the_run() -> None:
    spans, scores, _ = preparar(_grabacion(), project_id="p", dataset_id="d")

    del_caso, media = scores
    hija = spans[1]
    assert del_caso["trace_id"] == f"{hija.context.trace_id:032x}"
    assert del_caso["observation_id"] == f"{hija.context.span_id:016x}"
    assert media == {
        "name": "media_fallo_marta",
        "value": 1.0,
        "dataset_run_id": experiment_id("p", "d", "01-partida"),
        "score_id": media["score_id"],
        "timestamp": media["timestamp"],
    }
    assert media["timestamp"] >= PRIMER_DIA and media["timestamp"] < PRIMER_DIA + timedelta(days=1)


def test_loading_twice_gives_the_same_ids() -> None:
    primero = preparar(_grabacion(), project_id="p", dataset_id="d")
    segundo = preparar(_grabacion(), project_id="p", dataset_id="d")

    assert [s.context.span_id for s in primero[0]] == [s.context.span_id for s in segundo[0]]
    assert [s["score_id"] for s in primero[1]] == [s["score_id"] for s in segundo[1]]


def test_runs_not_recorded_yet_are_skipped_but_keep_their_number(tmp_path: Path) -> None:
    grabacion = _grabacion()
    grabacion["orden"] = ["antes", "partida"]
    fichero = tmp_path / "rag.json.gz"
    guardar(grabacion, fichero)

    spans, _, primeras = preparar(leer(fichero), project_id="p", dataset_id="d")

    assert len(primeras) == 1
    assert (spans[0].attributes or {})[EXPERIMENTO_NOMBRE] == "02-partida"
    assert spans[0].start_time == int((PRIMER_DIA + timedelta(days=1)).timestamp()) * NS
