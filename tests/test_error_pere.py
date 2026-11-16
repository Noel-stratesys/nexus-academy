"""El caso de Pere (ticket #4471) como test de regresión.

El martes 10 de noviembre de 2026, Pere preguntó si la L3 funcionaba con normalidad el
jueves, y Nexus le dijo que sí. Hay un test por componente: completa **solo** el del
componente en el que has visto el fallo, con lo que muestra la traza, y deja el otro como
está.

    uv run pytest tests/test_error_pere.py -v

Mientras falte algo por rellenar, el test falla con un mensaje que dice qué falta. Una vez
completo, antes de corregir el fallo tiene que fallar en un ``assert``. Si pasa, no está
probando lo que crees.
"""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from nexus.context import Context
from nexus.data import DATA_DIR, load
from nexus.tools import BASE_TOOLS


def llamar_herramienta(nombre: str, hoy: date | None, argumentos: dict[str, Any]) -> Any:
    """Llama a una herramienta de Nexus como lo hace el agente, con ``hoy`` como fecha.

    ``nombre`` y ``argumentos`` son los que ves en la traza: el nombre de la observation de
    la herramienta y su **Input**. Devuelve los datos que en la traza ves dentro del
    ``content`` de su **Output**, ya como diccionario.
    """

    if hoy is None:
        pytest.fail("Falta hoy: el día en que preguntó Pere, como date(año, mes, día).")
    herramientas = {herramienta.name: herramienta for herramienta in BASE_TOOLS}
    if nombre not in herramientas:
        pytest.fail(f"Nexus no tiene ninguna herramienta {nombre!r}: {', '.join(herramientas)}.")
    herramienta = herramientas[nombre]
    if not argumentos:
        pytest.fail(f"Faltan los argumentos: copia el Input de {nombre} en la traza.")
    desconocidos = set(argumentos) - set(herramienta.args)
    if desconocidos:
        pytest.fail(
            f"{nombre} no tiene los argumentos {', '.join(sorted(desconocidos))}; "
            f"tiene {', '.join(herramienta.args)}."
        )
    assert isinstance(herramienta, StructuredTool) and herramienta.func is not None
    # La función de la herramienta, sin la capa de LangChain que le pasa el contexto.
    return herramienta.func(runtime=SimpleNamespace(context=Context(hoy=hoy)), **argumentos)


def leer_datos(fichero: str) -> Any:
    """El contenido de ``nexus/data/<fichero>.json``, la fuente de la que leen las herramientas."""

    disponibles = sorted(path.stem for path in DATA_DIR.glob("*.json"))
    if fichero not in disponibles:
        pytest.fail(f"No hay ningún fichero {fichero!r} en nexus/data: {', '.join(disponibles)}.")
    return load(fichero)


def test_la_herramienta() -> None:
    """El fallo está en la herramienta: recibe bien los argumentos y calcula mal."""

    # Si el fallo está aquí, borra esta línea y completa el test.
    pytest.skip("Sin completar: es el test de la herramienta.")

    hoy = None  # el día en que preguntó Pere, como date(2026, 11, ...)
    herramienta = ""  # la herramienta, tal como se llama en la traza
    argumentos: dict[str, Any] = {}  # su Input en la traza

    salida = llamar_herramienta(herramienta, hoy, argumentos)
    assert salida == {'fecha': 'viernes 12 de noviembre de 2026', 'linea': 'L3', 'incidencias': [], 'estado': 'servicio normal'}



def test_los_datos() -> None:
    """El fallo está en los datos: la herramienta funciona, pero la fuente está mal."""

    # Si el fallo está aquí, borra esta línea y completa el test.
    pytest.skip("Sin completar: es el test de los datos.")

    datos = leer_datos("")  # el fichero de nexus/data/ que lee la herramienta, sin .json
    print(datos)  # pytest lo enseña si el test falla

    # Sustituye esta línea por uno o varios assert con lo que tendría que estar en los datos.
    pytest.fail("Escribe aquí lo que tendrían que contener los datos.")
