"""Cómo comprueban ``check 3`` y ``check 4`` los evaluadores que completan los alumnos.

Cada caso llama al evaluador con unos datos fijos y compara lo que devuelve con lo
esperado. Si no coincide, la pista enseña el caso, la entrada exacta (``output`` y
``expected_output``, tal como los recibe el evaluador), lo que ha devuelto y lo que
debería devolver:

    Caso «la única esperada, usada»
    output          = {'tools': [{'name': 'consultar_horario', 'args': {}}]}
    expected_output = {'tools': ['consultar_horario']}
    Ha devuelto:  Evaluation(name='usa_tools_esperadas', value=0.0)
    Debería dar:  Evaluation(name='usa_tools_esperadas', value=1)
"""

import inspect
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from langfuse import Evaluation

# Ancho de la columna de nombres de la entrada, para alinear los ``=``.
ANCHO = len("expected_output")


def _muestra(resultado: Any) -> str:
    """Lo que ha devuelto el evaluador, legible (un ``Evaluation`` no tiene repr útil)."""

    if isinstance(resultado, Evaluation):
        return f"Evaluation(name={resultado.name!r}, value={resultado.value!r})"
    return repr(resultado)


def _donde(error: BaseException, evaluador: Callable[..., Any]) -> str:
    """La línea del evaluador en la que saltó ``error``, con su código.

    Si el error salta dentro de otra función (por ejemplo, de Python), se enseña la última
    línea del fichero del evaluador por la que pasó: es la que el alumno tiene que mirar.
    """

    fichero = inspect.getsourcefile(evaluador)
    pasos = traceback.extract_tb(error.__traceback__)
    propios = [paso for paso in pasos if fichero and Path(paso.filename) == Path(fichero)]
    paso = (propios or pasos)[-1]
    try:
        ruta = Path(paso.filename).resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        ruta = Path(paso.filename).name
    return f"En:           {ruta}, línea {paso.lineno}: {(paso.line or '').strip()}"


def comprobar(
    evaluador: Callable[..., Any],
    caso: str,
    esperado: float | None,
    **argumentos: Any,
) -> None:
    """Falla con la entrada y la salida del caso si ``evaluador(**argumentos)`` no da ``esperado``.

    ``esperado`` es el ``value`` que debe tener el ``Evaluation``, o ``None`` si el
    evaluador no tiene nada que puntuar y debe devolver ``[]``.
    """

    nombre = evaluador.__name__
    debe = "[]" if esperado is None else f"Evaluation(name={nombre!r}, value={esperado!r})"

    def falla(salida: str) -> None:
        entrada = [f"{clave:<{ANCHO}} = {valor!r}" for clave, valor in argumentos.items()]
        pytest.fail("\n".join([f"Caso «{caso}»", *entrada, salida, f"Debería dar:  {debe}"]))

    try:
        resultado = evaluador(**argumentos)
    except NotImplementedError:
        pytest.fail(
            f"{nombre} está sin completar: sustituye el raise NotImplementedError por tu código."
        )
    except Exception as error:  # el fallo del alumno, sea cual sea, es la pista
        falla(f"Ha lanzado:   {type(error).__name__}: {error}\n{_donde(error, evaluador)}")
        return

    if esperado is None:
        correcto = resultado == []
    else:
        correcto = (
            isinstance(resultado, Evaluation)
            and resultado.name == nombre
            and isinstance(resultado.value, int | float)
            and resultado.value == pytest.approx(esperado)
        )
    if not correcto:
        falla(f"Ha devuelto:  {_muestra(resultado)}")
