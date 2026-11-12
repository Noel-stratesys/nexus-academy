"""El router: decide si un viajero va a blue o a green.

Cada viajero cae en un cubo del 0 al 99 según un hash de su id. Si su cubo es menor que
el tráfico de green, va a green. Así:

- el mismo viajero va siempre a la misma versión (no salta de una a otra entre
  conversaciones);
- al subir el tráfico del 10 % al 50 %, los que ya estaban en green siguen en green.
"""

import hashlib
from collections.abc import Callable

from nexus.simulation.types import Assignment
from release.state import ReleaseState, load_state

# La sal separa este reparto de cualquier otro hash del id del viajero.
SALT = "nexus:"


def bucket(user_id: str) -> int:
    """El cubo (0-99) del viajero; siempre el mismo para el mismo id."""

    digest = hashlib.sha1(f"{SALT}{user_id}".encode()).hexdigest()
    return int(digest, 16) % 100


def assign(user_id: str, state: ReleaseState | None = None) -> Assignment:
    """La versión de Nexus que atiende a ``user_id`` con el estado ``state``."""

    state = state or load_state()
    green = state.green
    if green.cambio and bucket(user_id) < green.traffic:
        return Assignment(release="green", label=green.label, flags=green.flags)
    return Assignment(release="blue", label=state.blue.label, flags=state.blue.flags)


def router(state: ReleaseState) -> Callable[[str], Assignment]:
    """``assign`` con un estado fijo: lo que necesita el simulador."""

    def assign_with_state(user_id: str) -> Assignment:
        return assign(user_id, state)

    return assign_with_state
