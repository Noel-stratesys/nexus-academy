"""Búsqueda por significado: vectores (embeddings) de los chunks y de la pregunta.

Los vectores de los chunks se calculan una vez con ``uv run index --embeddings`` y se
guardan en ``nexus/index/``. La pregunta se convierte en vector en cada búsqueda.
"""

import hashlib
import json
import math
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from nexus.rag.documents import Chunk
from nexus.settings import settings

INDEX_DIR = Path(__file__).resolve().parent.parent / "index"


def embedding_model(name: str) -> Embeddings:
    provider = name.split(":", 1)[0]
    extra = {"base_url": settings.ollama_host} if provider == "ollama" else {}
    return init_embeddings(name, **extra)


def _index_path(chunk_size: int, model: str) -> Path:
    slug = model.replace(":", "_").replace("/", "_")
    return INDEX_DIR / f"embeddings-{chunk_size}-{slug}.json"


def _fingerprint(chunk: Chunk) -> str:
    return hashlib.sha1(chunk.text.encode()).hexdigest()[:12]


def build_index(chunks: Sequence[Chunk], chunk_size: int, model: str) -> Path:
    """Calcula y guarda los vectores de ``chunks``."""

    vectors = embedding_model(model).embed_documents([chunk.text for chunk in chunks])
    payload = {
        "model": model,
        "chunks": {
            chunk.id: {"fingerprint": _fingerprint(chunk), "vector": vector}
            for chunk, vector in zip(chunks, vectors, strict=True)
        },
    }
    INDEX_DIR.mkdir(exist_ok=True)
    path = _index_path(chunk_size, model)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@cache
def _load_index(chunk_size: int, model: str) -> dict[str, dict]:
    path = _index_path(chunk_size, model)
    if not path.exists():
        raise FileNotFoundError(
            f"No hay índice de embeddings para chunks de {chunk_size} con {model}. "
            "Créalo con: uv run index --embeddings"
        )
    return json.loads(path.read_text(encoding="utf-8"))["chunks"]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def scores(query: str, chunks: Sequence[Chunk], chunk_size: int, model: str) -> list[float]:
    index = _load_index(chunk_size, model)
    stale = [
        chunk.id
        for chunk in chunks
        if index.get(chunk.id, {}).get("fingerprint") != _fingerprint(chunk)
    ]
    if stale:
        raise RuntimeError(
            f"El índice de embeddings no coincide con los documentos ({len(stale)} chunks "
            "cambiados o nuevos). Reconstrúyelo con: uv run index --embeddings"
        )
    query_vector = embedding_model(model).embed_query(query)
    return [_cosine(query_vector, index[chunk.id]["vector"]) for chunk in chunks]
