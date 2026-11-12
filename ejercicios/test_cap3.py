"""Misión 3 · ¿Qué significa que Nexus va bien? (``uv run check 3``).

Comprueba los evaluadores de código de ``evaluation/evaluators.py`` con casos fijos y
que tu juez «fidelidad» coincide con las anotaciones humanas «fidelidad_humana».
"""

from typing import Any

import httpx
import pytest
from langfuse import Evaluation

from evaluation.evaluators import usa_tools_esperadas, veredicto_correcto

MIN_KAPPA = 0.6
MIN_PAIRS = 10
HUMAN_SCORE, JUDGE_SCORE = "fidelidad_humana", "fidelidad"


def _tools(*names: str) -> dict[str, Any]:
    """Salida de la tarea con estas herramientas llamadas."""

    return {"tools": [{"name": name, "args": {}} for name in names]}


def _value(result: Evaluation | list[Evaluation], evaluator: str) -> float:
    assert isinstance(result, Evaluation), (
        f"{evaluator} debe devolver un Evaluation cuando el caso tiene algo que comprobar; "
        f"ha devuelto {result!r}."
    )
    assert result.name == evaluator, (
        f"El score debe llamarse {evaluator!r} (Evaluation(name=...)); se llama {result.name!r}."
    )
    assert isinstance(result.value, int | float), f"{evaluator} debe devolver un número."
    return float(result.value)


def test_veredicto_correcto() -> None:
    """veredicto_correcto da 1 si el orquestador acierta, 0 si no y nada si no hay veredicto"""

    hit = veredicto_correcto(output={"verdict": "valid"}, expected_output={"verdict": "valid"})
    assert _value(hit, "veredicto_correcto") == 1, (
        "Esperado «valid» y obtenido «valid» debería puntuar 1."
    )
    miss = veredicto_correcto(output={"verdict": "valid"}, expected_output={"verdict": "empty"})
    assert _value(miss, "veredicto_correcto") == 0, (
        "Esperado «empty» y obtenido «valid» debería puntuar 0."
    )
    none = veredicto_correcto(output={"verdict": None}, expected_output={"verdict": "valid"})
    assert _value(none, "veredicto_correcto") == 0, (
        "Si el orquestador no da veredicto (None) y se esperaba «valid», es un 0."
    )
    nothing = veredicto_correcto(output={"verdict": "valid"}, expected_output={})
    assert nothing == [], (
        "Si el caso no tiene «verdict» esperado no hay nada que puntuar: devuelve [] "
        f"(ha devuelto {nothing!r})."
    )


def test_usa_tools_esperadas() -> None:
    """usa_tools_esperadas puntúa la proporción de herramientas esperadas que se usaron"""

    cases = [
        (["consultar_horario"], _tools("consultar_horario"), 1.0, "la única esperada, usada"),
        (["consultar_horario"], _tools(), 0.0, "ninguna herramienta usada"),
        (["consultar_horario"], _tools("consultar_tarifas"), 0.0, "otra herramienta"),
        (
            ["consultar_horario|buscar_normativa"],
            _tools("buscar_normativa"),
            1.0,
            "«a|b» se cumple con b",
        ),
        (
            ["consultar_incidencias", "consultar_tarifas"],
            _tools("consultar_incidencias"),
            0.5,
            "una de dos: crédito parcial",
        ),
        (
            ["consultar_incidencias", "consultar_horario|buscar_normativa"],
            _tools("consultar_incidencias", "consultar_horario", "consultar_tarifas"),
            1.0,
            "las dos esperadas, con una herramienta de más",
        ),
    ]
    for expected, output, score, why in cases:
        result = usa_tools_esperadas(output=output, expected_output={"tools": expected})
        value = _value(result, "usa_tools_esperadas")
        used = [call["name"] for call in output["tools"]]
        assert value == pytest.approx(score), (
            f"Esperadas {expected}, usadas {used} ({why}): debería dar {score} y da {value}."
        )

    for expected_output in ({"tools": []}, {}):
        nothing = usa_tools_esperadas(
            output=_tools("consultar_horario"), expected_output=expected_output
        )
        assert nothing == [], (
            f"Con expected_output={expected_output} no hay herramientas que comprobar: "
            f"devuelve [] (ha devuelto {nothing!r})."
        )


def _pairs(client: httpx.Client) -> list[tuple[int, int]]:
    """(persona, juez) binarizados, para cada traza con los dos scores."""

    from evaluation.agreement import binarize, fetch_scores

    def by_trace(name: str) -> dict[str, int]:
        found: dict[str, int] = {}
        for score in fetch_scores(client, name):
            subject = score.get("subject") or {}
            trace_id = (
                subject.get("id") if subject.get("kind") == "trace" else subject.get("traceId")
            ) or score.get("traceId")
            if trace_id:
                found[trace_id] = binarize(score, 0.5)
        return found

    human, judge = by_trace(HUMAN_SCORE), by_trace(JUDGE_SCORE)
    return [(human[key], judge[key]) for key in sorted(human.keys() & judge.keys())]


def test_el_juez_coincide_con_las_personas(langfuse_http: httpx.Client) -> None:
    """El juez «fidelidad» coincide con «fidelidad_humana» (kappa de Cohen de 0,6 o más)"""

    from evaluation.agreement import cohen_kappa

    try:
        pairs = _pairs(langfuse_http)
    except httpx.HTTPError as error:
        pytest.fail(f"No he podido leer los scores de Langfuse ({type(error).__name__}).")
    assert pairs, (
        f"Todavía no hay trazas con los dos scores, «{HUMAN_SCORE}» y «{JUDGE_SCORE}». "
        "Crea el juez en Evaluators, deja que puntúe y anota en tu cola las mismas trazas."
    )
    assert len(pairs) >= MIN_PAIRS, (
        f"Solo {len(pairs)} trazas tienen los dos scores: anota al menos {MIN_PAIRS} "
        "(la misión pide 15) para que la kappa signifique algo."
    )
    kappa = cohen_kappa(pairs)
    assert kappa >= MIN_KAPPA, (
        f"Kappa de Cohen: {kappa:.2f} con {len(pairs)} trazas. Ejecuta uv run judge-agreement, "
        "mira los desacuerdos y ajusta la rúbrica del juez hasta llegar a 0,6."
    )
