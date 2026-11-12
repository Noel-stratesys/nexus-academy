"""Documentos de normativa y su división en fragmentos (chunks).

Cada documento de ``nexus/docs`` empieza con una cabecera::

    ---
    doc_id: normativa-viajeros-2026
    titulo: ...
    vigente: true
    fecha: 2026-03-01
    ---

y se divide en secciones por sus títulos ``##``. Un chunk junta párrafos seguidos del
mismo documento hasta llegar a ``chunk_size`` tokens aproximados, y recuerda de qué
sección viene cada párrafo.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
CHUNK_SIZES = (100, 250, 800)


@dataclass(frozen=True)
class Document:
    doc_id: str
    titulo: str
    vigente: bool
    fecha: str
    sections: list[tuple[str, str]]  # (título de la sección, texto)


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    titulo: str
    vigente: bool
    secciones: list[str]
    text: str
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def seccion(self) -> str:
        return self.secciones[0] if self.secciones else ""


def approx_tokens(text: str) -> int:
    """Tokens aproximados: unas 4 de cada 3 palabras."""

    return round(len(text.split()) * 4 / 3)


def _parse(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.DOTALL)
    if match is None:
        raise ValueError(f"{path.name} no tiene cabecera ---")
    header = dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)
    sections: list[tuple[str, str]] = []
    current, lines = "Introducción", []
    for line in match.group(2).splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            if "".join(lines).strip():
                sections.append((current, "\n".join(lines).strip()))
            current, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if "".join(lines).strip():
        sections.append((current, "\n".join(lines).strip()))
    return Document(
        doc_id=header["doc_id"],
        titulo=header["titulo"],
        vigente=header.get("vigente", "true").strip().lower() == "true",
        fecha=header.get("fecha", ""),
        sections=sections,
    )


def load_documents(docs_dir: Path = DOCS_DIR) -> list[Document]:
    return [_parse(path) for path in sorted(docs_dir.glob("*.md"))]


def chunk_document(document: Document, chunk_size: int) -> list[Chunk]:
    """Los chunks de un documento: párrafos seguidos hasta ``chunk_size`` tokens."""

    paragraphs = [
        (title, paragraph.strip())
        for title, text in document.sections
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]
    chunks: list[Chunk] = []
    current: list[tuple[str, str]] = []

    def flush() -> None:
        if not current:
            return
        titles = list(dict.fromkeys(title for title, _ in current))
        body = "\n\n".join(
            f"{title}\n{text}" if index == 0 or current[index - 1][0] != title else text
            for index, (title, text) in enumerate(current)
        )
        chunks.append(
            Chunk(
                id=f"{document.doc_id}#{chunk_size}-{len(chunks)}",
                doc_id=document.doc_id,
                titulo=document.titulo,
                vigente=document.vigente,
                secciones=titles,
                text=f"{document.titulo}\n\n{body}",
            )
        )
        current.clear()

    for title, paragraph in paragraphs:
        size = sum(approx_tokens(text) for _, text in current)
        if current and size + approx_tokens(paragraph) > chunk_size:
            flush()
        current.append((title, paragraph))
    flush()
    return chunks


@cache
def chunks_for(chunk_size: int) -> tuple[Chunk, ...]:
    """Todos los chunks de la normativa con ese tamaño."""

    return tuple(
        chunk for document in load_documents() for chunk in chunk_document(document, chunk_size)
    )
