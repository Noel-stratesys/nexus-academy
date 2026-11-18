"""Misión 4 · La normativa que nadie leía (``uv run check 4``).

El ticket #4502: Marta (viajera 1017) preguntó si podía subir con la bici un martes a
las 8:15, Nexus le dijo que sí y le pusieron una multa. Comprueba los evaluadores de RAG
y que, con la configuración de tu .env, el buscador trae lo correcto para Marta.
"""

from typing import Any

from evaluation.evaluators import abstencion_correcta, recupera_derogada, recupera_documento
from nexus.checks.evaluadores import comprobar

MARTA_QUESTION = "¿Puedo subir con la bici al metro un martes a las 8:15?"
VIGENTE = "normativa-viajeros-2026"
DEROGADA = "normativa-viajeros-2024"
GUIA_BICIS = "guia-bicicletas-y-patinetes"


def _retrieved(*doc_ids: str) -> dict[str, Any]:
    """Salida de la tarea con un fragmento recuperado de cada documento."""

    return {"fragmentos": [f"{doc_id}#250-{index}" for index, doc_id in enumerate(doc_ids)]}


def test_recupera_documento() -> None:
    """recupera_documento da 1 si se recuperó algún documento con la respuesta"""

    expected = {"docs": [VIGENTE, GUIA_BICIS]}
    cases = [
        (_retrieved(DEROGADA, GUIA_BICIS), 1, "uno de los esperados, entre otros"),
        (_retrieved(VIGENTE), 1, "el esperado"),
        (_retrieved(DEROGADA, "objetos-perdidos"), 0, "ninguno de los esperados"),
        (_retrieved(), 0, "nada recuperado"),
    ]
    for output, score, caso in cases:
        comprobar(recupera_documento, caso, score, output=output, expected_output=expected)
    comprobar(
        recupera_documento,
        "el caso no espera documentos",
        None,
        output=_retrieved(VIGENTE),
        expected_output={"docs": []},
    )


def test_recupera_derogada() -> None:
    """recupera_derogada da 1 si algún fragmento viene de un documento no vigente"""

    cases = [
        (_retrieved(DEROGADA, GUIA_BICIS), 1, "la edición 2024 está derogada"),
        (_retrieved(VIGENTE, GUIA_BICIS), 0, "todo vigente"),
        (_retrieved(), None, "sin fragmentos recuperados"),
    ]
    for output, score, caso in cases:
        comprobar(recupera_derogada, caso, score, output=output)


def test_abstencion_correcta() -> None:
    """abstencion_correcta premia responder cuando hay respuesta y abstenerse cuando no"""

    answer = "Sí: las bicicletas plegadas pueden subir siempre, también en hora punta."
    abstention = "No consta en la normativa de Metro de Vilaverda si se puede."
    cases = [
        ({"responde": True}, answer, 1, "debía responder y respondió"),
        ({"responde": True}, abstention, 0, "debía responder y se abstuvo"),
        ({"responde": False}, abstention, 1, "debía abstenerse y se abstuvo"),
        ({"responde": False}, answer, 0, "debía abstenerse y se inventó una respuesta"),
        ({}, answer, None, "el caso no dice si hay respuesta"),
    ]
    for expected_output, text, score, caso in cases:
        comprobar(
            abstencion_correcta,
            caso,
            score,
            output={"respuesta": text},
            expected_output=expected_output,
        )


def test_el_caso_de_marta_no_recupera_normativa_derogada() -> None:
    """Con tu configuración de RAG, el buscador trae lo correcto para la pregunta de Marta"""

    from nexus.rag.retriever import retriever
    from nexus.settings import settings

    config = settings.rag
    documents = retriever(config).invoke(MARTA_QUESTION)
    repealed = [doc.metadata["chunk_id"] for doc in documents if not doc.metadata["vigente"]]
    assert documents, "El buscador no ha devuelto nada para la pregunta de Marta."
    assert not repealed, (
        f"Con RAG__STRATEGY={config.strategy}, RAG__CHUNK_SIZE={config.chunk_size}, "
        f"RAG__TOP_K={config.top_k} y RAG__ONLY_CURRENT={str(config.only_current).lower()}, "
        f"el buscador trae fragmentos que no deberían llegarle al modelo: "
        f"{', '.join(repealed)}. Abre esos documentos en nexus/docs/ y elige en tu .env "
        "la configuración que defiendas con el barrido de experimentos."
    )
