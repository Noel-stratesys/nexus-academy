"""Tests de los datasets, los evaluadores y el cálculo de concordancia."""

from collections import Counter
from typing import Any

import pytest
from langfuse import Evaluation

from evaluation import evaluators as ev
from evaluation.agreement import binarize, cohen_kappa
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


def test_usa_tools_esperadas_accepts_alternatives() -> None:
    output = {"tools": [{"name": "buscar_normativa", "args": {}}]}
    expected = {"tools": ["consultar_tarifas|buscar_normativa", "consultar_horario"]}

    assert _value(ev.usa_tools_esperadas(output=output, expected_output=expected)) == 0.5


def test_evita_tools_prohibidas_counts_proposed_actions() -> None:
    expected = {"prohibidas": ["solicitar_devolucion"]}
    proposed = {"tools": [], "aprobaciones": ["solicitar_devolucion"]}

    assert _value(ev.evita_tools_prohibidas(output=proposed, expected_output=expected)) == 0
    assert _value(ev.evita_tools_prohibidas(output={"tools": []}, expected_output=expected)) == 1


def test_menciona_datos_ignores_accents_and_case() -> None:
    output = {"respuesta": "Hubo una AVERÍA a las 8:10."}

    result = ev.menciona_datos(output=output, expected_output={"menciona": ["averi", "8:10|08:10"]})

    assert _value(result) == 1


def test_rag_evaluators() -> None:
    output: dict[str, Any] = {
        "respuesta": "Sí, en cualquier horario.",
        "fragmentos": ["normativa-viajeros-2024#250-0", "guia-bicicletas-y-patinetes#250-0"],
    }
    expected = {
        "responde": True,
        "docs": ["normativa-viajeros-2026", "guia-bicicletas-y-patinetes"],
    }

    assert _value(ev.recupera_documento(output=output, expected_output=expected)) == 1
    assert _value(ev.precision_recuperacion(output=output, expected_output=expected)) == 0.5
    assert _value(ev.recupera_derogada(output=output)) == 1
    assert _value(ev.abstencion_correcta(output=output, expected_output=expected)) == 1


def test_abstencion_correcta_rewards_saying_there_is_no_answer() -> None:
    expected = {"responde": False}
    abstains = {"respuesta": "No consta en la normativa si hay descuento para jubilados."}
    invents = {"respuesta": "Sí, los jubilados tienen un 50 % de descuento."}

    assert _value(ev.abstencion_correcta(output=abstains, expected_output=expected)) == 1
    assert _value(ev.abstencion_correcta(output=invents, expected_output=expected)) == 0


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
        ({"dataType": "NUMERIC", "value": 0.2}, 0),
        ({"dataType": "BOOLEAN", "value": 1}, 1),
        ({"dataType": "CATEGORICAL", "stringValue": "Fiel"}, 1),
        ({"dataType": "CATEGORICAL", "stringValue": "inventa"}, 0),
    ],
)
def test_binarize(score: dict[str, Any], expected: int) -> None:
    assert binarize(score, threshold=0.5) == expected


def test_cohen_kappa() -> None:
    assert cohen_kappa([(1, 1), (0, 0), (1, 1), (0, 0)]) == 1
    # Coinciden la mitad de las veces, lo mismo que por azar: kappa 0.
    assert cohen_kappa([(1, 1), (1, 0), (0, 1), (0, 0)]) == 0
