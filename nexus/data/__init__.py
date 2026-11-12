"""Datos inventados de Metro de Vilaverda: red, horarios, incidencias, tarifas y viajeros.

Todo es ficticio y está en los JSON de esta carpeta. Las herramientas los leen con las
funciones de este módulo, que los cargan una sola vez.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent
IDIOMAS = {"es": "castellano", "ca": "catalán", "en": "inglés"}


@cache
def load(name: str) -> Any:
    """El contenido de ``<name>.json``."""

    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Viajero:
    id: str
    nombre: str
    idioma: str
    titulo: str

    def describe(self) -> str:
        idioma = IDIOMAS.get(self.idioma, self.idioma)
        return f"{self.nombre} (id {self.id}), escribe en {idioma}, título {self.titulo}"


@cache
def viajeros() -> dict[str, Viajero]:
    return {item["id"]: Viajero(**item) for item in load("viajeros")}


def viajero(user_id: str) -> Viajero | None:
    return viajeros().get(user_id)


def estaciones() -> dict[str, dict[str, Any]]:
    return load("red")["estaciones"]


def lineas() -> dict[str, dict[str, Any]]:
    return load("red")["lineas"]


def find_station(text: str) -> str | None:
    """El código de la estación que nombra ``text`` (código o nombre, sin importar tildes)."""

    from nexus.calendar import _normalize

    wanted = _normalize(text)
    for code, station in estaciones().items():
        if wanted in (code.lower(), _normalize(station["nombre"])):
            return code
    for code, station in estaciones().items():
        if wanted and wanted in _normalize(station["nombre"]):
            return code
    return None


def normalize_line(text: str) -> str | None:
    """``L3`` a partir de ``l3``, ``3`` o ``línea 3``."""

    digits = "".join(char for char in text if char.isdigit())
    code = f"L{digits}" if digits else text.strip().upper()
    return code if code in lineas() else None
