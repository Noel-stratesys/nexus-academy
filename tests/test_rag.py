"""Tests del buscador de normativa."""

from nexus.rag.bm25 import BM25, tokenize
from nexus.rag.documents import CHUNK_SIZES, approx_tokens, chunks_for, load_documents
from nexus.rag.retriever import retriever


def test_every_document_has_a_header_and_sections() -> None:
    documents = load_documents()

    assert len(documents) == 10
    assert all(document.sections for document in documents)
    assert [d.doc_id for d in documents if not d.vigente] == ["normativa-viajeros-2024"]


def test_smaller_chunk_sizes_give_more_chunks() -> None:
    counts = [len(chunks_for(size)) for size in CHUNK_SIZES]

    assert counts == sorted(counts, reverse=True)
    assert len(set(counts)) == len(counts)


def test_chunks_only_exceed_their_size_with_a_single_long_paragraph() -> None:
    for chunk in chunks_for(100):
        paragraphs = chunk.text.split("\n\n")[1:]
        assert approx_tokens(chunk.text) <= 140 or len(paragraphs) == 1


def test_bm25_ignores_accents_and_stopwords() -> None:
    assert tokenize("¿Puedo llevar la Bicicleta?") == ["llevar", "bicicleta"]
    scores = BM25(["perros en transportín", "bicicletas plegadas"]).scores("transportin")
    assert scores[0] > 0 and scores[1] == 0


def test_only_current_leaves_out_repealed_documents() -> None:
    question = "¿Puedo subir con la bici al metro?"

    everything = retriever(top_k=10).invoke(question)
    current = retriever(top_k=10, only_current=True).invoke(question)

    assert any(not doc.metadata["vigente"] for doc in everything)
    assert all(doc.metadata["vigente"] for doc in current)
