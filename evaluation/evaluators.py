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
    """La proporción de herramientas esperadas que Nexus usó.

    - Las esperadas están en ``expected_output["tools"]``. ``"a|b"`` se cumple con
      cualquiera de las dos.
    - Las que usó, en ``output["tools"]``: una lista de llamadas, cada una con su ``name``.
    - Una de dos es 0,5. Usar herramientas de más no resta.
    - Sin herramientas esperadas, devuelve ``[]``.
    - Si la tarea terminó con un error, ``output`` solo trae ``"error"`` y no tiene
      ``"tools"``: cuenta como si no hubiera usado ninguna.
    - Devuelve ``Evaluation(name="usa_tools_esperadas", value=...)``.

    Ejemplo: se esperaban dos y usó una, así que vale 0,5.

        output = {
            "respuesta": "...",
            "tools": [
                {"name": "buscar_normativa", "args": {"pregunta": "¿Puedo subir con la bici?"}},
                {"name": "consultar_incidencias", "args": {"dia": "hoy"}},
            ],
        }
        expected_output = {"tools": ["consultar_tarifas|buscar_normativa", "consultar_horario"]}
        # devuelve Evaluation(name="usa_tools_esperadas", value=0.5)

    ``"consultar_tarifas|buscar_normativa"`` cuenta porque usó ``buscar_normativa``;
    ``consultar_horario`` no, porque no la llamó; y ``consultar_incidencias`` sobra, pero
    no resta. Fíjate en que ``output["tools"]`` no es una lista de nombres, sino de
    llamadas: el nombre está en ``["name"]`` de cada una.
    """

    raise NotImplementedError("Completa usa_tools_esperadas: es la misión del capítulo 3.")


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
    """1 si algún fragmento recuperado viene de un documento esperado y 0 si no.

    - Los documentos esperados están en ``expected_output["docs"]``.
    - Los fragmentos recuperados, en ``output["fragmentos"]``. Sus ids tienen la forma
      ``doc_id#chunk``.
    - Sin documentos esperados, devuelve ``[]``.
    - Devuelve ``Evaluation(name="recupera_documento", value=...)``.

    Ejemplo: el segundo fragmento viene de ``doc-b``, que es uno de los esperados, así que
    vale 1.

        output = {"respuesta": "...", "fragmentos": ["doc-a#250-0", "doc-b#250-3"]}
        expected_output = {"docs": ["doc-b", "doc-c"]}
        # devuelve Evaluation(name="recupera_documento", value=1)
    """

    raise NotImplementedError("Completa recupera_documento: es la misión del capítulo 4.")


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
    """1 si algún fragmento recuperado viene de un documento que ya no está vigente.

    - Los fragmentos recuperados están en ``output["fragmentos"]``, con ids de la forma
      ``doc_id#chunk``.
    - Cada documento dice si está vigente en su campo ``vigente`` (``load_documents()``).
    - Sin fragmentos, devuelve ``[]``.
    - Devuelve ``Evaluation(name="recupera_derogada", value=...)``.

    Ejemplo: si ``load_documents()`` dice que ``doc-a`` tiene ``vigente`` a ``False``,
    vale 1 aunque el otro fragmento sea de un documento vigente.

        output = {"respuesta": "...", "fragmentos": ["doc-a#250-0", "doc-b#250-3"]}
        # devuelve Evaluation(name="recupera_derogada", value=1)
    """

    raise NotImplementedError("Completa recupera_derogada: es la misión del capítulo 4.")


def abstencion_correcta(
    *, output: dict[str, Any], expected_output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """1 si Nexus responde cuando hay respuesta y se abstiene cuando no la hay.

    - ``expected_output["responde"]`` dice si la normativa tiene la respuesta.
    - Abstenerse es decir que no consta («no consta…», «no tengo información…»): las
      frases están en ``ABSTENTION_PHRASES``. La respuesta de Nexus está en
      ``output["respuesta"]``.
    - Si el caso no dice si hay respuesta, devuelve ``[]``.
    - Devuelve ``Evaluation(name="abstencion_correcta", value=...)``.

    Ejemplo: la normativa no tiene la respuesta y Nexus dice que no consta, así que vale 1.

        output = {"respuesta": "No consta en la normativa si se puede subir con patinete."}
        expected_output = {"responde": False}
        # devuelve Evaluation(name="abstencion_correcta", value=1)
    """

    raise NotImplementedError("Completa abstencion_correcta: es la misión del capítulo 4.")


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
