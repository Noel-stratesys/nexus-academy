"""Búsqueda en la normativa: la herramienta que usa el RAG."""

from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from nexus.context import Context
from nexus.rag.retriever import retriever


@tool
def buscar_normativa(pregunta: str, runtime: ToolRuntime[Context]) -> dict[str, Any]:
    """Busca en la normativa y guías de MdV: bicicletas, patinetes, mascotas, equipaje,
    sanciones, devoluciones, reclamaciones, accesibilidad, títulos y objetos perdidos.

    Args:
        pregunta: La duda del viajero con sus palabras, por ejemplo
            "¿puedo llevar la bici en el metro un lunes por la mañana?".
    """

    # Con la configuración de la ejecución, el buscador queda dentro de la misma traza.
    documents = retriever(runtime.context.rag).invoke(pregunta, config=runtime.config)
    return {
        "fragmentos": [
            {
                "id": document.metadata["chunk_id"],
                "documento": document.metadata["titulo"],
                "seccion": ", ".join(document.metadata["secciones"]),
                "texto": document.page_content,
            }
            for document in documents
        ]
    }
