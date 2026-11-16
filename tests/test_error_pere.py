"""El caso de Pere (ticket #4471) como test de regresión.

El martes 10 de noviembre de 2026, Pere preguntó si la L3 funcionaba con normalidad el
jueves, y Nexus le dijo que sí. Este test repite el paso de la traza que se equivocó y
comprueba lo que tendría que haber devuelto.

Complétalo con lo que has visto en la traza y lánzalo:

    uv run pytest tests/test_error_pere.py

Antes de corregir el fallo tiene que fallar. Si pasa, no está probando lo que crees.
"""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from nexus.context import Context
from nexus.tools import BASE_TOOLS


def llamar_herramienta(nombre: str, hoy: date, argumentos: dict[str, Any]) -> Any:
    """Llama a una herramienta de Nexus como lo hace el agente, con ``hoy`` como fecha.

    ``nombre`` y ``argumentos`` son los que ves en la traza: el nombre de la observation de
    la herramienta y su **Input**. Devuelve los datos que en la traza ves dentro del
    ``content`` de su **Output**, ya como diccionario.
    """

    herramientas = {herramienta.name: herramienta for herramienta in BASE_TOOLS}
    if nombre not in herramientas:
        pytest.fail(f"Nexus no tiene ninguna herramienta {nombre!r}: {', '.join(herramientas)}.")
    herramienta = herramientas[nombre]
    assert isinstance(herramienta, StructuredTool) and herramienta.func is not None
    # La función de la herramienta, sin la capa de LangChain que le pasa el contexto.
    return herramienta.func(runtime=SimpleNamespace(context=Context(hoy=hoy)), **argumentos)


def test_el_caso_de_pere() -> None:
    # 1. Borra esta línea.
    pytest.skip("Plantilla sin completar: rellénala con lo que ves en la traza de Pere.")

    # 2. Lo que pasó, tal como lo ves en la traza.
    hoy = date(2026, 11, 0)  # el día en que preguntó Pere (cambia el 0)
    herramienta = ""  # la herramienta que se equivocó
    argumentos: dict[str, Any] = {}  # su Input en la traza

    salida = llamar_herramienta(herramienta, hoy, argumentos)
    print(salida)  # pytest lo enseña si el test falla

    # 3. Sustituye esta línea por uno o varios assert con lo que tendría que haber
    #    devuelto la herramienta.
    pytest.fail("Escribe aquí lo que tendría que haber devuelto la herramienta.")
