"""Misión 3 · ¿Qué significa que Nexus va bien? (``uv run check 3``).

Comprueba el evaluador ``usa_tools_esperadas`` de ``evaluation/evaluators.py`` con casos fijos y
que los dos jueces coinciden con tus anotaciones sobre las 10 trazas del capítulo:

- tu juez «tono» con «tono_humano»;
- la plantilla de Langfuse «answer_relevance» con «relevancia_humana».
"""

from typing import Any

import httpx
import pytest

from evaluation.evaluators import usa_tools_esperadas
from nexus.checks.evaluadores import comprobar

MIN_KAPPA = 0.6
MIN_PAIRS = 10
TONO = ("tono_humano", "tono")
RELEVANCIA = ("relevancia_humana", "answer_relevance")


def _tools(*names: str) -> dict[str, Any]:
    """Salida de la tarea con estas herramientas llamadas."""

    return {"tools": [{"name": name, "args": {}} for name in names]}


def test_usa_tools_esperadas() -> None:
    """usa_tools_esperadas puntúa la proporción de herramientas esperadas que se usaron"""

    cases = [
        (["consultar_horario"], _tools("consultar_horario"), 1, "la única esperada, usada"),
        (["consultar_horario"], _tools(), 0, "ninguna herramienta usada"),
        (["consultar_horario"], _tools("consultar_tarifas"), 0, "otra herramienta"),
        (
            ["consultar_horario|buscar_normativa"],
            _tools("buscar_normativa"),
            1,
            "«a|b» se cumple con b",
        ),
        (
            ["consultar_horario|buscar_normativa"],
            _tools("consultar_horario", "buscar_normativa"),
            1,
            "«a|b» con las dos usadas cuenta una sola vez",
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
            1,
            "las dos esperadas, con una herramienta de más",
        ),
    ]
    for expected, output, score, caso in cases:
        comprobar(
            usa_tools_esperadas, caso, score, output=output, expected_output={"tools": expected}
        )

    comprobar(
        usa_tools_esperadas,
        "la tarea terminó con un error y output no tiene tools",
        0,
        output={"error": "TimeoutError: el modelo no respondió"},
        expected_output={"tools": ["consultar_horario"]},
    )
    comprobar(
        usa_tools_esperadas,
        "lista de esperadas vacía",
        None,
        output=_tools("consultar_horario"),
        expected_output={"tools": []},
    )
    comprobar(
        usa_tools_esperadas,
        "el caso no tiene la clave tools",
        None,
        output=_tools("consultar_horario"),
        expected_output={},
    )


def _pairs(client: httpx.Client, human_name: str, judge_name: str) -> list[tuple[float, float]]:
    """(persona, juez) en niveles 0, 0,5 y 1, para cada traza con los dos scores."""

    from evaluation.agreement import collect_pair

    try:
        human, judge, unknown_h, unknown_j = collect_pair(client, human_name, judge_name)
    except httpx.HTTPError as error:
        pytest.fail(f"No he podido leer los scores de Langfuse ({type(error).__name__}).")
    for name, unknown in ((human_name, unknown_h), (judge_name, unknown_j)):
        assert not unknown, (
            f"«{name}» tiene etiquetas que no sé convertir a 0, 0,5 o 1: "
            f"{', '.join(sorted(set(unknown)))}. El juez tiene que devolver las mismas "
            f"etiquetas que tu score «{human_name}» (Settings → Scores)."
        )
    return [(human[key], judge[key]) for key in sorted(human.keys() & judge.keys())]


def _comprobar_acuerdo(client: httpx.Client, human_name: str, judge_name: str) -> None:
    from evaluation.agreement import weighted_kappa

    pairs = _pairs(client, human_name, judge_name)
    assert pairs, (
        f"Todavía no hay trazas con los dos scores, «{human_name}» y «{judge_name}». "
        "Anota en tu cola las 10 trazas con la etiqueta cap3, crea el juez en Evaluators y "
        "deja que puntúe esas mismas trazas (si no las ves en Tracing: uv run trazas-cap3)."
    )
    assert len(pairs) >= MIN_PAIRS, (
        f"Solo {len(pairs)} trazas tienen los dos scores: anota las {MIN_PAIRS} trazas del "
        "capítulo (etiqueta cap3) para que la kappa signifique algo."
    )
    assert any(human == 0.5 for human, _ in pairs), (
        f"Ninguna de tus notas de «{human_name}» es la categoría del medio. ¿Has creado el "
        "score con tres categorías? Hay trazas que no están ni bien ni mal."
    )
    kappa = weighted_kappa(pairs)
    assert kappa >= MIN_KAPPA, (
        f"Kappa ponderada de «{judge_name}»: {kappa:.2f} con {len(pairs)} trazas. Ejecuta "
        "uv run judge-agreement, mira los desacuerdos y ajusta el juez hasta llegar a 0,6."
    )


def test_tu_juez_de_tono_coincide_contigo(langfuse_http: httpx.Client) -> None:
    """Tu juez «tono» coincide con «tono_humano» (kappa ponderada de 0,6 o más)"""

    _comprobar_acuerdo(langfuse_http, *TONO)


def test_la_plantilla_de_relevancia_coincide_contigo(langfuse_http: httpx.Client) -> None:
    """La plantilla «answer_relevance» coincide con «relevancia_humana» (kappa de 0,6 o más)"""

    _comprobar_acuerdo(langfuse_http, *RELEVANCIA)
