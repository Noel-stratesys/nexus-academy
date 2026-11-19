"""Tests de los datasets, los evaluadores y el cálculo de concordancia.

Los evaluadores que se completan en los capítulos 3 y 4 los comprueba ``uv run check``.
"""

from collections import Counter
from typing import Any

import pytest
from langfuse import Evaluation

from evaluation import evaluators as ev
from evaluation.agreement import category_levels, to_level, weighted_kappa
from evaluation.datasets import DATASETS
from evaluation.tasks import _fragments


def _value(result: Evaluation | list[Evaluation]) -> float:
    assert isinstance(result, Evaluation)
    return float(result.value)


# --- datasets ------------------------------------------------------------------


def test_case_ids_are_unique_in_every_dataset() -> None:
    for definition in DATASETS.values():
        ids = [case.case_id for case in definition.cases]
        assert len(ids) == len(set(ids)), definition.name


def test_binary_datasets_are_balanced() -> None:
    verdicts = Counter(
        case.expected["verdict"] == "valid" for case in DATASETS["orquestador"].cases
    )
    answers = Counter(case.expected["responde"] for case in DATASETS["rag"].cases)

    assert verdicts[True] == verdicts[False]
    assert answers[True] == answers[False]


# --- evaluadores ---------------------------------------------------------------


def test_veredicto_correcto() -> None:
    expected = {"verdict": "valid"}

    assert _value(ev.veredicto_correcto(output={"verdict": "valid"}, expected_output=expected)) == 1
    assert _value(ev.veredicto_correcto(output={"verdict": "empty"}, expected_output=expected)) == 0
    assert ev.veredicto_correcto(output={}, expected_output={}) == []


def test_evita_tools_prohibidas_counts_proposed_actions() -> None:
    expected = {"prohibidas": ["solicitar_devolucion"]}
    proposed = {"tools": [], "aprobaciones": ["solicitar_devolucion"]}

    assert _value(ev.evita_tools_prohibidas(output=proposed, expected_output=expected)) == 0
    assert _value(ev.evita_tools_prohibidas(output={"tools": []}, expected_output=expected)) == 1


def test_menciona_datos_ignores_accents_and_case() -> None:
    output = {"respuesta": "Hubo una AVERÍA a las 8:10."}

    result = ev.menciona_datos(output=output, expected_output={"menciona": ["averi", "8:10|08:10"]})

    assert _value(result) == 1


def test_averages_by_score_name() -> None:
    class Result:
        def __init__(self, *values: float) -> None:
            self.evaluations = [Evaluation(name="x", value=value) for value in values]

    (average,) = ev.averages(item_results=[Result(1), Result(0)])

    assert (average.name, average.value) == ("media_x", 0.5)


def test_fragments_reads_the_ids_returned_by_buscar_normativa() -> None:
    calls = [
        {"name": "consultar_horario", "result": "{}"},
        {"name": "buscar_normativa", "result": '{"fragmentos": [{"id": "accesibilidad#250-0"}]}'},
    ]

    assert _fragments(calls) == ["accesibilidad#250-0"]


# --- concordancia juez / personas ---------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ({"dataType": "NUMERIC", "value": 0.8}, 1),
        ({"dataType": "NUMERIC", "value": 0.4}, 0.5),
        ({"dataType": "NUMERIC", "value": 0.2}, 0),
        ({"dataType": "BOOLEAN", "value": 1}, 1),
        ({"dataType": "CATEGORICAL", "stringValue": "0.5"}, 0.5),
        ({"dataType": "CATEGORICAL", "stringValue": "0,5"}, 0.5),
        ({"dataType": "CATEGORICAL", "stringValue": "Relevant"}, 1),
        ({"dataType": "CATEGORICAL", "stringValue": "Partially relevant"}, 0.5),
        ({"dataType": "CATEGORICAL", "stringValue": "Not relevant"}, 0),
        ({"dataType": "CATEGORICAL", "stringValue": "inventa"}, None),
    ],
)
def test_to_level(score: dict[str, Any], expected: float | None) -> None:
    assert to_level(score) == expected


def test_category_levels_por_posicion() -> None:
    tono = [
        {"label": "cercano", "value": 2},
        {"label": "brusco", "value": 0},
        {"label": "seco", "value": 1},
    ]
    labels = category_levels(tono)
    assert labels == {"brusco": 0, "seco": 0.5, "cercano": 1}
    score = {"dataType": "CATEGORICAL", "value": "Seco"}
    assert to_level(score, labels) == 0.5
    # Sin configuración, se prueba con la etiqueta.
    assert to_level({"dataType": "CATEGORICAL", "value": "poco relevante"}) == 0.5


def test_weighted_kappa() -> None:
    assert weighted_kappa([(1, 1), (0, 0), (0.5, 0.5), (0, 0)]) == 1
    # Con dos niveles es la kappa de Cohen: coinciden lo mismo que por azar, kappa 0.
    assert weighted_kappa([(1, 1), (1, 0), (0, 1), (0, 0)]) == 0
    # Fallar por medio punto cuesta menos que fallar por uno entero.
    cerca = weighted_kappa([(0, 0.5), (0.5, 0.5), (1, 1), (0, 0), (1, 0.5)])
    lejos = weighted_kappa([(0, 1), (0.5, 0.5), (1, 1), (0, 0), (1, 0)])
    assert cerca > lejos
