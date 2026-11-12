"""El estado de los despliegues: qué hay en blue, qué hay en green y la puerta.

Vive en ``release.toml``, en la raíz del proyecto. Lo escribe ``uv run release`` y se
puede leer a mano:

- ``[blue]``: la versión estable. Sus prompts tienen el label ``production``.
- ``[green]``: el cambio que se está probando, con su label (``green``), sus flags y el
  porcentaje de viajeros que lo reciben (``traffic``, de 0 a 100).
- ``[gate]``: la puerta. La media de cada score del experimento tiene que llegar al
  mínimo que se indica.
- ``[[historial]]``: lo que se ha hecho, en orden, con su motivo.

Se lee con ``tomllib`` (biblioteca estándar) y se escribe con un escritor pequeño que
solo conoce los tipos que usa este fichero.
"""

import json
import tomllib
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from nexus.settings import PROJECT_ROOT

STATE_FILE = PROJECT_ROOT / "release.toml"

BLUE_LABEL = "production"
GREEN_LABEL = "green"

# Mínimos de la puerta si release.toml no dice otra cosa.
DEFAULT_GATE: dict[str, float] = {
    "sin_errores": 0.95,
    "usa_tools_esperadas": 0.8,
    "evita_tools_prohibidas": 1.0,
    "aprobacion_correcta": 0.9,
    "menciona_datos": 0.6,
}


@dataclass(frozen=True)
class Blue:
    """La versión estable: la que recibe todo el tráfico que no va a green."""

    label: str = BLUE_LABEL
    flags: frozenset[str] = frozenset()
    # Cambios promocionados hasta ahora, en orden.
    cambios: tuple[str, ...] = ()


@dataclass(frozen=True)
class Green:
    """El cambio en pruebas. ``cambio`` vacío significa que no hay ninguno."""

    cambio: str = ""
    label: str = GREEN_LABEL
    flags: frozenset[str] = frozenset()
    traffic: int = 0
    # Resultado de la última puerta de este cambio: "", "superada" o "fallida".
    puerta: str = ""


@dataclass(frozen=True)
class Evento:
    """Una línea del historial de despliegues."""

    fecha: str
    accion: str
    cambio: str = ""
    detalle: str = ""


@dataclass(frozen=True)
class ReleaseState:
    blue: Blue = Blue()
    green: Green = Green()
    gate: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_GATE))
    historial: tuple[Evento, ...] = ()

    def with_event(self, accion: str, cambio: str = "", detalle: str = "") -> "ReleaseState":
        """El mismo estado con un evento más en el historial."""

        evento = Evento(
            fecha=datetime.now().isoformat(timespec="seconds"),
            accion=accion,
            cambio=cambio,
            detalle=detalle,
        )
        return replace(self, historial=(*self.historial, evento))


# --- Lectura -----------------------------------------------------------------


def _flags(value: Any) -> frozenset[str]:
    return frozenset(str(flag) for flag in value or [])


def parse_state(data: dict[str, Any]) -> ReleaseState:
    """El estado a partir del contenido ya leído de ``release.toml``."""

    blue = data.get("blue", {})
    green = data.get("green", {})
    traffic = int(green.get("traffic", 0))
    if not 0 <= traffic <= 100:
        raise ValueError(f"green.traffic debe estar entre 0 y 100, no {traffic}")
    return ReleaseState(
        blue=Blue(
            label=str(blue.get("label", BLUE_LABEL)),
            flags=_flags(blue.get("flags")),
            cambios=tuple(str(cambio) for cambio in blue.get("cambios", [])),
        ),
        green=Green(
            cambio=str(green.get("cambio", "")),
            label=str(green.get("label", GREEN_LABEL)),
            flags=_flags(green.get("flags")),
            traffic=traffic,
            puerta=str(green.get("puerta", "")),
        ),
        gate={str(name): float(value) for name, value in data.get("gate", DEFAULT_GATE).items()},
        historial=tuple(
            Evento(
                fecha=str(item.get("fecha", "")),
                accion=str(item.get("accion", "")),
                cambio=str(item.get("cambio", "")),
                detalle=str(item.get("detalle", "")),
            )
            for item in data.get("historial", [])
        ),
    )


def state_file() -> Path:
    """Dónde está ``release.toml`` (los tests lo cambian con ``STATE_FILE``)."""

    return STATE_FILE


def load_state(path: Path | None = None) -> ReleaseState:
    """El estado guardado; el inicial si el fichero todavía no existe."""

    path = path or state_file()
    if not path.exists():
        return ReleaseState()
    with path.open("rb") as file:
        return parse_state(tomllib.load(file))


# --- Escritura ---------------------------------------------------------------


def _string(value: str) -> str:
    # Las cadenas JSON son cadenas básicas de TOML válidas (mismos escapes).
    return json.dumps(value, ensure_ascii=False)


def _strings(values: frozenset[str] | tuple[str, ...]) -> str:
    items = sorted(values) if isinstance(values, frozenset) else list(values)
    return "[" + ", ".join(_string(item) for item in items) + "]"


def _number(value: float) -> str:
    return repr(float(value))


def dump_state(state: ReleaseState) -> str:
    """El contenido de ``release.toml`` para ``state``."""

    lines = [
        "# Estado de los despliegues de Nexus (capítulo 5).",
        "# Lo escribe `uv run release`: mejor cambiarlo con ese comando que a mano.",
        "",
        "# La versión estable. Sus prompts tienen el label `production`.",
        "[blue]",
        f"label = {_string(state.blue.label)}",
        f"flags = {_strings(state.blue.flags)}",
        f"cambios = {_strings(state.blue.cambios)}",
        "",
        "# El cambio en pruebas y el porcentaje de viajeros que lo reciben (0-100).",
        "[green]",
        f"cambio = {_string(state.green.cambio)}",
        f"label = {_string(state.green.label)}",
        f"flags = {_strings(state.green.flags)}",
        f"traffic = {state.green.traffic}",
        f"puerta = {_string(state.green.puerta)}",
        "",
        "# La puerta: media mínima de cada score del experimento sobre el dataset agente.",
        "[gate]",
        *(f"{name} = {_number(value)}" for name, value in state.gate.items()),
    ]
    for evento in state.historial:
        lines += [
            "",
            "[[historial]]",
            f"fecha = {_string(evento.fecha)}",
            f"accion = {_string(evento.accion)}",
            f"cambio = {_string(evento.cambio)}",
            f"detalle = {_string(evento.detalle)}",
        ]
    return "\n".join(lines) + "\n"


def save_state(state: ReleaseState, path: Path | None = None) -> None:
    (path or state_file()).write_bytes(dump_state(state).encode("utf-8"))
