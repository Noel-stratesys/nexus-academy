"""Misión 4 · La normativa que nadie leía (``uv run check 4``).

El ticket #4502: Marta (viajera 1017) preguntó si podía subir con la bici un martes a
las 8:15, Nexus le dijo que sí y le pusieron una multa. Comprueba los evaluadores de RAG
y que, con la configuración de tu .env, el buscador trae lo correcto para Marta.
"""

from typing import Any

from langfuse import Evaluation

from evaluation.evaluators import abstencion_correcta, recupera_derogada, recupera_documento

MARTA_QUESTION = "¿Puedo subir con la bici al metro un martes a las 8:15?"
VIGENTE = "normativa-viajeros-2026"
DEROGADA = "normativa-viajeros-2024"
GUIA_BICIS = "guia-bicicletas-y-patinetes"


def _retrieved(*doc_ids: str) -> dict[str, Any]:
    """Salida de la tarea con un fragmento recuperado de cada documento."""

    return {"fragmentos": [f"{doc_id}#250-{index}" for index, doc_id in enumerate(doc_ids)]}


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


def test_recupera_documento() -> None:
    """recupera_documento da 1 si se recuperó algún documento con la respuesta"""

    expected = {"docs": [VIGENTE, GUIA_BICIS]}
    cases = [
        (_retrieved(DEROGADA, GUIA_BICIS), 1, "uno de los esperados, entre otros"),
        (_retrieved(VIGENTE), 1, "el esperado"),
        (_retrieved(DEROGADA, "objetos-perdidos"), 0, "ninguno de los esperados"),
        (_retrieved(), 0, "nada recuperado"),
    ]
    for output, score, why in cases:
        value = _value(
            recupera_documento(output=output, expected_output=expected), "recupera_documento"
        )
        assert value == score, (
            f"Esperados {expected['docs']}, recuperados {output['fragmentos']} ({why}): "
            f"debería dar {score} y da {value}. Ojo: los ids de fragmento son «doc_id#chunk»."
        )
    nothing = recupera_documento(output=_retrieved(VIGENTE), expected_output={"docs": []})
    assert nothing == [], (
        "Si el caso no espera documentos (docs vacío) no hay nada que puntuar: devuelve [] "
        f"(ha devuelto {nothing!r})."
    )


def test_recupera_derogada() -> None:
    """recupera_derogada da 1 si algún fragmento viene de un documento no vigente"""

    cases = [
        (_retrieved(DEROGADA, GUIA_BICIS), 1, "la edición 2024 está derogada"),
        (_retrieved(VIGENTE, GUIA_BICIS), 0, "todo vigente"),
    ]
    for output, score, why in cases:
        value = _value(recupera_derogada(output=output), "recupera_derogada")
        assert value == score, (
            f"Recuperados {output['fragmentos']} ({why}): debería dar {score} y da {value}. "
            "¿Cómo sabes si un documento sigue en vigor? Lo explica la misión."
        )
    nothing = recupera_derogada(output=_retrieved())
    assert nothing == [], (
        "Sin fragmentos recuperados no hay nada que puntuar: devuelve [] "
        f"(ha devuelto {nothing!r})."
    )


def test_abstencion_correcta() -> None:
    """abstencion_correcta premia responder cuando hay respuesta y abstenerse cuando no"""

    answer = "Sí: las bicicletas plegadas pueden subir siempre, también en hora punta."
    abstention = "No consta en la normativa de Metro de Vilaverda si se puede."
    cases = [
        (True, answer, 1, "debía responder y respondió"),
        (True, abstention, 0, "debía responder y se abstuvo"),
        (False, abstention, 1, "debía abstenerse y se abstuvo"),
        (False, answer, 0, "debía abstenerse y se inventó una respuesta"),
    ]
    for responde, text, score, why in cases:
        result = abstencion_correcta(
            output={"respuesta": text}, expected_output={"responde": responde}
        )
        value = _value(result, "abstencion_correcta")
        assert value == score, (
            f"Con responde={responde} y la respuesta «{text}» ({why}): "
            f"debería dar {score} y da {value}."
        )
    nothing = abstencion_correcta(output={"respuesta": answer}, expected_output={})
    assert nothing == [], (
        "Si el caso no dice si se puede responder («responde») no hay nada que puntuar: "
        f"devuelve [] (ha devuelto {nothing!r})."
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
