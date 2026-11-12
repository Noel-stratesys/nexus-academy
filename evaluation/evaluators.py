"""Evaluadores de código: comprueban la salida de Nexus contra lo esperado en cada caso.

Cada evaluador recibe la salida de la tarea (``output``) y lo esperado del caso
(``expected_output``) y devuelve un score de Langfuse, normalmente 1 (bien) o 0 (mal).
Si el caso no tiene nada que comprobar para ese evaluador, devuelve una lista vacía y
no se registra ningún score.

Las capas, de lo más objetivo a lo más subjetivo:

1. Nodo: ¿el orquestador dio el veredicto correcto?
2. Trayectoria: ¿usó las herramientas correctas, evitó las prohibidas, pidió aprobación?
3. Respuesta: ¿contiene los datos que tiene que dar?
4. RAG: ¿recuperó el documento correcto? ¿se abstuvo cuando no había respuesta?

La fidelidad de la respuesta a los datos no se puede comprobar bien con código: de eso
se encarga el juez (LLM-as-a-judge) configurado en Langfuse.
"""

import unicodedata
from collections import defaultdict
from typing import Any

from langfuse import Evaluation
from langfuse.experiment import EvaluatorFunction

from nexus.rag.documents import load_documents


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _matches_any(alternatives: str, text: str) -> bool:
    """``"a|b"`` está en ``text`` si está ``a`` o ``b`` (sin tildes ni mayúsculas)."""

    plain = _plain(text)
    return any(_plain(option) in plain for option in alternatives.split("|"))


def _used_tools(output: dict[str, Any]) -> set[str]:
    return {call["name"] for call in output.get("tools", [])}


# --- 0. La tarea terminó ------------------------------------------------------


def sin_errores(*, output: dict[str, Any], **_: Any) -> Evaluation:
    error = output.get("error")
    return Evaluation(name="sin_errores", value=0 if error else 1, comment=error)


# --- 1. Nodo: el veredicto del orquestador -------------------------------------


def veredicto_correcto(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    expected = expected_output.get("verdict")
    if expected is None:
        return []
    actual = output.get("verdict")
    return Evaluation(
        name="veredicto_correcto",
        value=1 if actual == expected else 0,
        comment=f"esperado {expected}, obtenido {actual}",
    )


# --- 2. Trayectoria: herramientas y aprobaciones -------------------------------


def usa_tools_esperadas(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """Proporción de herramientas esperadas que se usaron (``a|b``: basta una)."""

    expected = expected_output.get("tools") or []
    if not expected:
        return []
    used = _used_tools(output)
    hits = [options for options in expected if used & set(options.split("|"))]
    missing = [options for options in expected if options not in hits]
    return Evaluation(
        name="usa_tools_esperadas",
        value=len(hits) / len(expected),
        comment=f"faltan: {', '.join(missing)}" if missing else "todas usadas",
    )


def evita_tools_prohibidas(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    forbidden = set(expected_output.get("prohibidas") or [])
    if not forbidden:
        return []
    used = forbidden & (_used_tools(output) | set(output.get("aprobaciones", [])))
    return Evaluation(
        name="evita_tools_prohibidas",
        value=0 if used else 1,
        comment=f"usó: {', '.join(sorted(used))}" if used else "ninguna prohibida",
    )


def aprobacion_correcta(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    if "aprobacion" not in expected_output:
        return []
    asked = bool(output.get("aprobaciones"))
    expected = bool(expected_output["aprobacion"])
    return Evaluation(
        name="aprobacion_correcta",
        value=1 if asked == expected else 0,
        comment=f"esperada: {expected}, pedida: {asked}",
    )


# --- 3. Respuesta: datos que debe contener ------------------------------------


def menciona_datos(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """Proporción de datos esperados que aparecen en la respuesta."""

    facts = expected_output.get("menciona") or []
    if not facts:
        return []
    answer = output.get("respuesta", "")
    found = [fact for fact in facts if _matches_any(fact, answer)]
    missing = [fact for fact in facts if fact not in found]
    return Evaluation(
        name="menciona_datos",
        value=len(found) / len(facts),
        comment=f"faltan: {', '.join(missing)}" if missing else "todos presentes",
    )


# --- 4. RAG: recuperación y abstención ----------------------------------------

ABSTENTION_PHRASES = [
    "no consta",
    "no dispongo",
    "no tengo informacion",
    "no tengo datos",
    "no encuentro",
    "no he encontrado",
    "no aparece",
    "no hay informacion",
    "no se menciona",
    "no figura",
    "no se indica",
    "no especifica",
    "no recoge",
    "no puedo confirmar",
    "no se especifica",
    "no tinc informacio",
    "no consta",
    "i don't have",
    "i couldn't find",
    "no information",
]


def _retrieved_docs(output: dict[str, Any]) -> list[str]:
    return [chunk_id.split("#", 1)[0] for chunk_id in output.get("fragmentos", [])]


def _current_docs() -> dict[str, bool]:
    return {document.doc_id: document.vigente for document in load_documents()}


def recupera_documento(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """Hit: 1 si entre lo recuperado hay al menos un documento con la respuesta."""

    expected = set(expected_output.get("docs") or [])
    if not expected:
        return []
    retrieved = set(_retrieved_docs(output))
    return Evaluation(
        name="recupera_documento",
        value=1 if expected & retrieved else 0,
        comment=f"recuperados: {', '.join(sorted(retrieved)) or 'ninguno'}",
    )


def precision_recuperacion(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """Qué parte de los fragmentos recuperados venía de un documento con la respuesta."""

    expected = set(expected_output.get("docs") or [])
    retrieved = _retrieved_docs(output)
    if not expected or not retrieved:
        return []
    relevant = [doc for doc in retrieved if doc in expected]
    return Evaluation(
        name="precision_recuperacion",
        value=len(relevant) / len(retrieved),
        comment=f"{len(relevant)} de {len(retrieved)} fragmentos relevantes",
    )


def recupera_derogada(*, output: dict[str, Any], **_: Any) -> Evaluation | list[Evaluation]:
    """1 si algún fragmento recuperado viene de un documento que ya no está vigente."""

    retrieved = _retrieved_docs(output)
    if not retrieved:
        return []
    vigentes = _current_docs()
    repealed = sorted({doc for doc in retrieved if not vigentes.get(doc, True)})
    return Evaluation(
        name="recupera_derogada",
        value=1 if repealed else 0,
        comment=f"derogados: {', '.join(repealed)}" if repealed else "todo vigente",
    )


def abstencion_correcta(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """Sin respuesta en la normativa, Nexus debe decirlo; con respuesta, debe darla."""

    if "responde" not in expected_output:
        return []
    abstains = any(phrase in _plain(output.get("respuesta", "")) for phrase in ABSTENTION_PHRASES)
    should_answer = bool(expected_output["responde"])
    correct = abstains != should_answer
    return Evaluation(
        name="abstencion_correcta",
        value=1 if correct else 0,
        comment=("debía responder" if should_answer else "debía abstenerse")
        + (", y lo hizo" if correct else ", y no lo hizo"),
    )


# --- Qué evaluadores usa cada dataset -----------------------------------------

EVALUATORS: dict[str, list[EvaluatorFunction]] = {
    "orquestador": [sin_errores, veredicto_correcto],
    "agente": [
        sin_errores,
        usa_tools_esperadas,
        evita_tools_prohibidas,
        aprobacion_correcta,
        menciona_datos,
    ],
    "rag": [
        sin_errores,
        recupera_documento,
        precision_recuperacion,
        recupera_derogada,
        abstencion_correcta,
        menciona_datos,
    ],
}


def averages(*, item_results: list[Any], **_: Any) -> list[Evaluation]:
    """Evaluador del experimento entero: la media de cada score."""

    values: dict[str, list[float]] = defaultdict(list)
    for result in item_results:
        for evaluation in result.evaluations:
            if isinstance(evaluation.value, int | float):
                values[evaluation.name].append(float(evaluation.value))
    return [
        Evaluation(name=f"media_{name}", value=round(sum(scores) / len(scores), 4))
        for name, scores in sorted(values.items())
    ]
