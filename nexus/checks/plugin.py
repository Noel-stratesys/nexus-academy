"""Plugin de pytest que recoge el resultado de cada comprobación sin imprimir nada.

``uv run check`` ejecuta pytest dentro del mismo proceso y, en lugar de la salida
habitual de pytest, muestra un informe pensado para personas. Este plugin guarda lo
necesario para ese informe: la descripción de cada test (su docstring), si es de nivel
extra, cómo ha terminado y una pista corta cuando falla.
"""

import inspect
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Literal

import pytest

Status = Literal["passed", "failed", "skipped"]

# Las pistas largas no ayudan: se recortan a unas pocas líneas.
MAX_HINT_LINES = 6


@dataclass
class Outcome:
    """Cómo ha ido una comprobación."""

    nodeid: str
    description: str
    extra: bool
    status: Status = "skipped"
    hint: str = ""


@dataclass(eq=False)  # pluggy guarda los plugins en conjuntos: deben ser hashables
class ResultCollector:
    """Guarda las comprobaciones en el orden en que pytest las ejecuta."""

    outcomes: dict[str, Outcome] = field(default_factory=dict)
    collection_errors: list[str] = field(default_factory=list)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collection_errors.append(_last_lines(str(report.longrepr)))

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        for item in session.items:
            self.outcomes[item.nodeid] = Outcome(
                nodeid=item.nodeid,
                description=_description(item),
                extra=item.get_closest_marker("extra") is not None,
            )

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> Generator[None, pytest.TestReport, pytest.TestReport]:
        report = yield
        outcome = self.outcomes.get(item.nodeid)
        if outcome is None:
            return report
        if report.when == "call" or not report.passed:
            if outcome.status == "failed":
                return report  # el primer fallo es el que explica lo que pasa
            outcome.status = "passed" if report.passed else report.outcome
            if call.excinfo is not None and not report.passed:
                outcome.hint = hint_from(call.excinfo.value)
        return report

    @property
    def results(self) -> list[Outcome]:
        return list(self.outcomes.values())


def _description(item: pytest.Item) -> str:
    """El primer párrafo del docstring del test (o su nombre) y, si está parametrizado, el caso."""

    function = getattr(item, "obj", None)
    doc = inspect.getdoc(function) if function is not None else None
    if doc:
        text = " ".join(doc.split("\n\n", 1)[0].split())
    else:
        text = item.name.split("[", 1)[0].removeprefix("test_").replace("_", " ")
    callspec = getattr(item, "callspec", None)
    return f"{text} ({callspec.id})" if callspec is not None else text


def hint_from(error: BaseException) -> str:
    """Una pista legible a partir de la excepción del test, sin traceback.

    En un ``assert condición, "mensaje"`` la pista es el mensaje. pytest añade debajo
    la comparación (``assert ...``): esa parte se descarta.
    """

    if isinstance(error, AssertionError):
        lines: list[str] = []
        for line in str(error).splitlines():
            if line.startswith("assert "):
                break
            lines.append(line)
        message = "\n".join(lines).strip()
        return _first_lines(message) or "La comprobación no se cumple."
    if isinstance(error, pytest.fail.Exception | pytest.skip.Exception):
        return _first_lines(str(error))
    first = str(error).strip().splitlines()[0] if str(error).strip() else ""
    return f"Error inesperado ({type(error).__name__}): {first}".rstrip(": ")


def _first_lines(text: str) -> str:
    return "\n".join(text.strip().splitlines()[:MAX_HINT_LINES])


def _last_lines(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[-3:])
