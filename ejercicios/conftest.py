"""Configuración común de las comprobaciones de las misiones (``uv run check N``).

Cada ``test_capN.py`` comprueba una misión. Las reglas para escribirlas:

- El docstring del test es lo que lee la persona en el informe: una frase en positivo
  que describe lo que tiene que cumplirse.
- Cada ``assert`` lleva un mensaje con una pista de qué revisar; es lo que se muestra
  cuando falla, sin traceback.
- ``@pytest.mark.extra`` marca una comprobación de nivel extra: se muestra, pero no
  hace fallar la misión.
"""

import os
from collections.abc import Iterator

import httpx
import pytest

from nexus.settings import initialize_environment


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "extra: comprobación de nivel extra; no hace fallar la misión"
    )


@pytest.fixture
def langfuse_http() -> Iterator[httpx.Client]:
    """Cliente HTTP de la API pública del Langfuse local, con las claves del .env."""

    initialize_environment()
    missing = [
        name
        for name in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
        if not os.environ.get(name)
    ]
    assert not missing, f"Faltan variables en .env: {', '.join(missing)}. Copia .env.example."
    with httpx.Client(
        base_url=os.environ["LANGFUSE_BASE_URL"],
        auth=(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]),
        timeout=10,
    ) as client:
        yield client
