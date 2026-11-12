"""El buscador de normativa: un retriever de LangChain.

Al ser un retriever, cuando se invoca con la configuración de la ejecución aparece en
Langfuse como una observation de tipo ``retriever``, con la pregunta como entrada y los
chunks recuperados (texto y metadata) como salida.
"""

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from nexus.rag import bm25, embeddings
from nexus.rag.documents import chunks_for
from nexus.settings import RagSettings, settings


class NormativaRetriever(BaseRetriever):
    """Devuelve los ``top_k`` chunks de normativa más parecidos a la pregunta."""

    config: RagSettings

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        chunks = list(chunks_for(self.config.chunk_size))
        if self.config.only_current:
            chunks = [chunk for chunk in chunks if chunk.vigente]
        if self.config.strategy == "bm25":
            scores = bm25.BM25([chunk.text for chunk in chunks]).scores(query)
        else:
            scores = embeddings.scores(
                query, chunks, self.config.chunk_size, self.config.embedding_model
            )
        ranked = sorted(zip(scores, chunks, strict=True), key=lambda pair: pair[0], reverse=True)
        return [
            Document(
                page_content=chunk.text,
                metadata={
                    "chunk_id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "titulo": chunk.titulo,
                    "secciones": chunk.secciones,
                    "vigente": chunk.vigente,
                    "score": round(score, 4),
                    "rank": rank,
                },
            )
            for rank, (score, chunk) in enumerate(ranked[: self.config.top_k], start=1)
            if score > 0
        ]


def retriever(config: RagSettings | None = None, **overrides: Any) -> NormativaRetriever:
    """El buscador con la configuración del .env, o con la que se pase."""

    base = config or settings.rag
    return NormativaRetriever(config=base.model_copy(update=overrides) if overrides else base)
