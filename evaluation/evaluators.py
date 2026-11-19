"""Evaluadores de código: comprueban la salida de Nexus contra lo esperado en cada caso.

Cada evaluador recibe la salida de la tarea (``output``) y lo esperado del caso
(``expected_output``) y devuelve un score de Langfuse, normalmente 1 (bien) o 0 (mal).
Si el caso no tiene nada que comprobar para ese evaluador, devuelve una lista vacía y
no se registra ningún score.

Las capas, de lo más objetivo a lo más subjetivo:

1. Nodo: ¿el orquestador dio el veredicto correcto?
2. Trayectoria: ¿usó las herramientas correctas, evitó las prohibidas, pidió aprobación?
3. Respuesta: ¿contiene los datos que tiene que dar?
4. RAG: ¿el buscador trae lo que debe?

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


# --- 4. RAG --------------------------------------------------------------------


def _retrieved_docs(output: dict[str, Any]) -> list[str]:
    return [chunk_id.split("#", 1)[0] for chunk_id in output.get("fragmentos", [])]


def _current_docs() -> dict[str, bool]:
    return {document.doc_id: document.vigente for document in load_documents()}


def fallo_marta(
    *, output: dict[str, Any], **_: Any
) -> Evaluation | list[Evaluation]:
    """Tu evaluador: 1 si el caso tiene el mismo fallo que el de Marta y 0 si no.

    Qué mirar para saberlo lo decides tú: es el diseño que has hecho en el cuaderno.

    - Recibe la salida de la tarea, ``output``, con la respuesta de Nexus
      (``output["respuesta"]``) y los ids de los fragmentos que recuperó el buscador
      (``output["fragmentos"]``, de la forma ``doc_id#chunk``).
    - ``load_documents()`` devuelve los documentos de ``nexus/docs/``, cada uno con los
      datos de su cabecera.
    - Dos funciones de ayuda, justo encima:

      - ``_retrieved_docs(output)``: los ``doc_id`` de ``output["fragmentos"]`` (lo que
        va antes de ``#``), en el mismo orden y con repetidos.

            output = {
                "respuesta": "...",
                "fragmentos": [
                    "normativa-viajeros-2026#250-3",
                    "guia-bicicletas-y-patinetes#250-0",
                    "normativa-viajeros-2026#250-1",
                ],
            }
            _retrieved_docs(output)
            # ["normativa-viajeros-2026", "guia-bicicletas-y-patinetes", "normativa-viajeros-2026"]

            _retrieved_docs({"respuesta": "..."})  # sin fragmentos
            # []

      - ``_current_docs()``: no recibe nada y devuelve un diccionario con el ``doc_id``
        de cada documento de ``nexus/docs/`` y si está vigente.

            docs = _current_docs()
            # {"normativa-viajeros-2026": True, "objetos-perdidos": True, ...}
            docs["normativa-viajeros-2026"]
            # True

    - Si el caso no tiene nada que puedas mirar, devuelve ``[]``.
    - Devuelve ``Evaluation(name="fallo_marta", value=...)``.
    """

    raise NotImplementedError("Completa fallo_marta: es la misión del capítulo 4.")


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
        fallo_marta,
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
