"""Misión 2 · El viajero enfadado (``uv run check 2``).

El ticket #4471: Pere (viajero 1042) preguntó el martes si la L3 funcionaba el jueves y
Nexus le dijo que sí. Comprueba que el fallo está corregido y que el caso ha entrado en
el dataset como regresión.
"""

import unicodedata
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from nexus.calendar import describe, resolve_day
from nexus.context import Context

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
# Un "hoy" para cada día de la semana, del lunes 9 al domingo 15 de noviembre de 2026.
HOY_DATES = [date(2026, 11, 9) + timedelta(days=offset) for offset in range(7)]


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def test_resolve_day_acierta_el_caso_de_pere() -> None:
    """resolve_day("jueves") visto desde el martes 10 de noviembre es el jueves 12"""

    hoy = date(2026, 11, 10)
    result = resolve_day("jueves", hoy)
    assert result == date(2026, 11, 12), (
        f"Desde el {describe(hoy)}, «jueves» da el {describe(result)}. Compara lo que pidió "
        "el modelo a la herramienta con la fecha que devolvió, y revisa nexus/calendar.py."
    )


def test_resolve_day_acierta_todos_los_dias_de_la_semana() -> None:
    """resolve_day convierte cada día de la semana en la fecha correcta, sea cual sea hoy"""

    errors = []
    for hoy in HOY_DATES:
        for target, name in enumerate(WEEKDAYS):
            expected = hoy + timedelta(days=(target - hoy.weekday()) % 7)
            result = resolve_day(name, hoy)
            if result != expected:
                errors.append(
                    f"desde el {describe(hoy)}, «{name}» da {describe(result)} "
                    f"(debería ser {describe(expected)})"
                )
    assert not errors, (
        f"{len(errors)} de {len(HOY_DATES) * len(WEEKDAYS)} fechas mal. Por ejemplo, "
        f"{errors[0]}. ¿Qué número tiene el lunes en weekday() y en isoweekday()?"
    )


def test_el_caso_de_pere_esta_en_el_dataset() -> None:
    """El caso de Pere está en el dataset del agente como regresión"""

    from evaluation.datasets.agente import CASES

    found = [
        case
        for case in CASES
        if case.viajero == "1042"
        and "l3" in _plain(case.mensaje)
        and "jueves" in _plain(case.mensaje)
    ]
    assert found, (
        "No hay en evaluation/datasets/agente.py ningún caso del viajero 1042 que pregunte "
        "por la L3 el jueves. Añade a CASES un _case(...) con viajero='1042', el día en que "
        "preguntó (hoy='2026-11-10') y lo que esperas: la herramienta y el dato de las obras."
    )


def _incidencias_de_toda_la_red(dia: str) -> dict[str, Any]:
    """Llama a la herramienta como lo haría el agente, sin indicar línea."""

    from nexus.tools.incidencias import consultar_incidencias

    # La función original, sin la capa de LangChain que inyecta el runtime del grafo.
    function = getattr(consultar_incidencias, "func", None)
    assert function is not None, "consultar_incidencias no es una herramienta de LangChain."
    # La herramienta solo lee runtime.context.hoy.
    runtime = SimpleNamespace(context=Context(hoy=date(2026, 11, 10)))
    return function(dia=dia, runtime=runtime, linea=None)


@pytest.mark.extra
def test_incidencias_sin_linea_consulta_toda_la_red() -> None:
    """consultar_incidencias sin línea devuelve las incidencias de toda la red"""

    result = _incidencias_de_toda_la_red("2026-11-12")
    ids = [incident.get("id") for incident in result.get("incidencias", [])]
    assert "INC-0301" in ids, (
        f"Sin línea, la herramienta responde {result}. El modelo lo reintenta en bucle: "
        "busca en Langfuse la traza que tarda más de 40 s. Haz que, sin línea, consulte "
        "todas las líneas (incidents_on para cada una)."
    )
