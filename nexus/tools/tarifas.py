"""Tarifas: precio de los títulos de transporte por zonas."""

from typing import Any

from langchain_core.tools import tool

from nexus.data import load


@tool
def consultar_tarifas(titulo: str | None = None) -> dict[str, Any]:
    """Precios y condiciones de los títulos de transporte (sencillo, T-10, T-Mes...).

    Args:
        titulo: Título concreto, por ejemplo "T-10" o "aeroport". Si se omite, todos.
    """

    titulos = load("tarifas")["titulos"]
    if titulo is None:
        return {"moneda": "EUR", "titulos": titulos}
    key = titulo.lower().replace("-", "").replace(" ", "").replace("billete", "")
    aliases = {"sencillo": "senzill", "turista": "tturista", "jove": "tjove", "mes": "tmes"}
    key = aliases.get(key, key)
    if key not in titulos:
        return {"error": f"No conozco el título {titulo!r}.", "titulos": sorted(titulos)}
    return {"moneda": "EUR", key: titulos[key]}
