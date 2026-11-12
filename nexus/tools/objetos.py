"""Objetos perdidos encontrados en la red."""

from typing import Any

from langchain_core.tools import tool

from nexus.calendar import _normalize
from nexus.data import estaciones, load, normalize_line


@tool
def buscar_objeto_perdido(descripcion: str, linea: str | None = None) -> dict[str, Any]:
    """Busca un objeto perdido entre los que se han encontrado en la red.

    Args:
        descripcion: Qué se perdió, en pocas palabras, por ejemplo "paraguas rojo".
        linea: Línea en la que se perdió, si se sabe.
    """

    words = [word for word in _normalize(descripcion).split() if len(word) > 2]
    line = normalize_line(linea) if linea else None
    found = []
    for item in load("objetos_perdidos"):
        text = _normalize(item["descripcion"])
        if line and item["linea"] != line:
            continue
        if any(word in text for word in words):
            found.append({**item, "estacion": estaciones()[item["estacion"]]["nombre"]})
    return {
        "encontrados": found,
        "como_recoger": "Oficina de objetos perdidos de Estació Central, de 8:00 a 20:00, con DNI.",
    }
