"""Misión 4 · La normativa que nadie leía (``uv run check 4``).

El ticket #4502: Marta (viajera 1017) preguntó si podía subir con la bici un martes a
las 8:15, Nexus le dijo que sí y le pusieron una multa. Comprueba los evaluadores de RAG
y que, con la configuración de tu .env, el buscador trae lo correcto para Marta.
"""

from typing import Any

from evaluation.evaluators import fallo_marta
from nexus.checks.evaluadores import comprobar

MARTA_QUESTION = "¿Puedo subir con la bici al metro un martes a las 8:15?"
VIGENTE = "normativa-viajeros-2026"
DEROGADA = "normativa-viajeros-2024"
GUIA_BICIS = "guia-bicicletas-y-patinetes"


def _retrieved(*doc_ids: str) -> dict[str, Any]:
    """Salida de la tarea con un fragmento recuperado de cada documento."""

    return {"fragmentos": [f"{doc_id}#250-{index}" for index, doc_id in enumerate(doc_ids)]}


def test_fallo_marta() -> None:
    """fallo_marta da 1 en los casos con el mismo fallo que el de Marta"""

    cases = [
        (_retrieved(DEROGADA, GUIA_BICIS), 1, "lo que recuperó el buscador para Marta"),
        (_retrieved(VIGENTE, GUIA_BICIS), 0, "la normativa de 2026 y la guía de bicis"),
        (_retrieved(), None, "sin fragmentos recuperados"),
    ]
    for output, score, caso in cases:
        comprobar(fallo_marta, caso, score, output=output)


def test_el_caso_de_marta_ya_no_falla() -> None:
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
