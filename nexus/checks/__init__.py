"""Comprobaciones de cada misión (``uv run check N``).

Las comprobaciones son tests de pytest en ``ejercicios/test_capN.py``. Este comando los
ejecuta y, en lugar de la salida de pytest, muestra un informe en castellano: una línea
por comprobación (su docstring) y, si falla, una pista sacada del mensaje del ``assert``.

Las comprobaciones marcadas con ``@pytest.mark.extra`` son de nivel extra: se muestran,
pero no hacen fallar la misión.

    uv run check 2
    uv run check 0 -k "not modelo"
"""

import argparse
import sys
import textwrap
from pathlib import Path

import pytest

from nexus.checks.plugin import Outcome, ResultCollector

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXERCISES_DIR = PROJECT_ROOT / "ejercicios"

CHAPTERS = {
    0: "Todo listo para empezar",
    1: "Dos prompts y una discusión",
    2: "El viajero enfadado",
    3: "¿Qué significa que Nexus va bien?",
    4: "La normativa que nadie leía",
    5: "El viernes de los despliegues",
}

PASSED, FAILED, SKIPPED = "✔", "✘", "–"
# Ancho de las pistas en la terminal.
WIDTH = 92


def exercise_file(chapter: int) -> Path:
    return EXERCISES_DIR / f"test_cap{chapter}.py"


def run_checks(path: Path, keyword: str | None = None) -> tuple[ResultCollector, int]:
    """Ejecuta pytest sobre ``path`` sin su salida habitual y devuelve lo recogido."""

    collector = ResultCollector()
    args = [
        str(path),
        f"--rootdir={path.parent.parent}",
        "--import-mode=importlib",
        "-p",
        "no:terminal",
        "-p",
        "no:cacheprovider",
    ]
    if keyword:
        args += ["-k", keyword]
    exit_code = pytest.main(args, plugins=[collector])
    return collector, int(exit_code)


def _indent(text: str, prefix: str) -> str:
    """``text`` sangrado con ``prefix`` y partido en líneas de ``WIDTH`` caracteres."""

    return "\n".join(
        textwrap.fill(line, WIDTH, initial_indent=prefix, subsequent_indent=prefix)
        for line in text.splitlines()
    )


def format_outcome(outcome: Outcome) -> str:
    symbol = {"passed": PASSED, "failed": FAILED, "skipped": SKIPPED}[outcome.status]
    label = "[nivel extra] " if outcome.extra else ""
    line = f"  {symbol} {label}{outcome.description}"
    if outcome.status != "passed" and outcome.hint:
        prefix = "Pista: " if outcome.status == "failed" else "Omitida: "
        line += "\n" + _indent(prefix + outcome.hint, "      ")
    return line


def report(chapter: int, collector: ResultCollector, exit_code: int = 0) -> tuple[str, bool]:
    """El informe para la terminal y si la misión está superada."""

    path = exercise_file(chapter).relative_to(PROJECT_ROOT).as_posix()
    lines = [f"Misión {chapter} · {CHAPTERS[chapter]}  ({path})", ""]

    if collector.collection_errors:
        lines.append(f"  {FAILED} No se han podido cargar las comprobaciones:")
        lines.extend(_indent(error, "      ") for error in collector.collection_errors)
        return "\n".join(lines), False

    results = collector.results
    if not results and exit_code in (pytest.ExitCode.INTERNAL_ERROR, pytest.ExitCode.USAGE_ERROR):
        lines.append(
            f"  {FAILED} pytest no ha podido ejecutar las comprobaciones (código {exit_code}). "
            "El detalle está justo encima."
        )
        return "\n".join(lines), False
    if not results:
        lines.append("  No hay comprobaciones que ejecutar (¿el filtro -k las excluye todas?).")
        return "\n".join(lines), False

    lines.extend(format_outcome(outcome) for outcome in results)
    required = [outcome for outcome in results if not outcome.extra]
    extra = [outcome for outcome in results if outcome.extra]
    failed = [outcome for outcome in required if outcome.status == "failed"]
    passed = [outcome for outcome in required if outcome.status == "passed"]

    lines.append("")
    if failed:
        lines.append(
            f"{FAILED} Misión {chapter} pendiente: {len(passed)} de {len(required)} "
            "comprobaciones superadas. Sigue las pistas y vuelve a probar."
        )
    else:
        lines.append(f"{PASSED} Misión {chapter} superada: {len(passed)} de {len(required)}.")
    if extra:
        done = sum(outcome.status == "passed" for outcome in extra)
        lines.append(f"  Nivel extra: {done} de {len(extra)} (opcional, no cuenta para la misión).")
    return "\n".join(lines), not failed


def _utf8_output() -> None:
    # Las terminales de Windows no siempre escriben en UTF-8: ✔ y ✘ se verían mal.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def main(argv: list[str] | None = None) -> int:
    """``uv run check N``: 0 si la misión N está superada, 1 si no."""

    _utf8_output()
    parser = argparse.ArgumentParser(
        prog="check", description="Comprueba una misión: uv run check 0 … uv run check 5."
    )
    parser.add_argument("capitulo", type=int, choices=sorted(CHAPTERS), help="Número de misión.")
    parser.add_argument(
        "-k",
        dest="filtro",
        help='Solo las comprobaciones cuyo nombre encaje, como en pytest (-k "not modelo").',
    )
    args = parser.parse_args(argv)

    path = exercise_file(args.capitulo)
    if not path.exists():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        print(
            f"La misión {args.capitulo} todavía no tiene comprobaciones: no existe {relative}.\n"
            "Si acabas de actualizar el repositorio, pregunta a quien imparte la academy."
        )
        return 1

    collector, exit_code = run_checks(path, args.filtro)
    text, ok = report(args.capitulo, collector, exit_code)
    print(text)
    return 0 if ok else 1
