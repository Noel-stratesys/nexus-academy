"""Tests de ``uv run check``: el informe a partir de unas comprobaciones de ejemplo.

Cada test escribe un ``ejercicios/test_capN.py`` falso en una carpeta temporal y ejecuta
el comando sobre él, sin tocar las comprobaciones reales de las misiones.
"""

from pathlib import Path

import pytest

import nexus.checks as checks
from nexus.checks.plugin import hint_from

CONFTEST = """
def pytest_configure(config):
    config.addinivalue_line("markers", "extra: nivel extra")
"""

MIXED_CHECKS = '''
import pytest


def test_ok():
    """Langfuse responde"""


def test_falla():
    """El caso de Pere está en el dataset"""
    assert 1 == 2, "Añade el caso de Pere a CASES."


@pytest.mark.extra
def test_extra():
    """La herramienta consulta toda la red"""
    assert False, "Sin línea, consulta todas las líneas."
'''

ONLY_EXTRA_FAILS = '''
import pytest


def test_ok():
    """resolve_day acierta"""


@pytest.mark.extra
def test_extra():
    """Nivel extra pendiente"""
    raise ValueError("boom")
'''


@pytest.fixture
def exercises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "ejercicios"
    folder.mkdir()
    (folder / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nasyncio_default_fixture_loop_scope = function\n", encoding="utf-8"
    )
    monkeypatch.setattr(checks, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(checks, "EXERCISES_DIR", folder)
    return folder


def test_report_shows_each_check_with_its_docstring_and_hint(
    exercises: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (exercises / "test_cap1.py").write_text(MIXED_CHECKS, encoding="utf-8")

    exit_code = checks.main(["1"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Misión 1 · Dos prompts y una discusión" in output
    assert "✔ Langfuse responde" in output
    assert "✘ El caso de Pere está en el dataset" in output
    assert "Pista: Añade el caso de Pere a CASES." in output
    assert "✘ [nivel extra] La herramienta consulta toda la red" in output
    assert "1 de 2 comprobaciones superadas" in output
    assert "Nivel extra: 0 de 1" in output
    assert "assert 1 == 2" not in output
    assert "Traceback" not in output


def test_failing_extra_checks_do_not_fail_the_mission(
    exercises: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (exercises / "test_cap2.py").write_text(ONLY_EXTRA_FAILS, encoding="utf-8")

    exit_code = checks.main(["2"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "✔ Misión 2 superada: 1 de 1." in output
    assert "Error inesperado (ValueError): boom" in output


def test_keyword_filter_skips_checks(exercises: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (exercises / "test_cap3.py").write_text(MIXED_CHECKS, encoding="utf-8")

    exit_code = checks.main(["3", "-k", "not falla and not extra"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Langfuse responde" in output
    assert "El caso de Pere" not in output


def test_missing_exercise_file_is_reported(
    exercises: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = checks.main(["4"])

    assert exit_code == 1
    assert "La misión 4 todavía no tiene comprobaciones" in capsys.readouterr().out


def test_import_errors_are_reported_without_running_anything(
    exercises: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (exercises / "test_cap0.py").write_text("import modulo_que_no_existe\n", encoding="utf-8")

    exit_code = checks.main(["0"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "No se han podido cargar las comprobaciones" in output
    assert "modulo_que_no_existe" in output


def test_chapter_must_be_between_0_and_5() -> None:
    with pytest.raises(SystemExit):
        checks.main(["6"])


def test_hint_keeps_the_assert_message_and_drops_the_comparison() -> None:
    assert hint_from(AssertionError("Revisa calendar.py.\nassert 1 == 2")) == "Revisa calendar.py."
    assert hint_from(AssertionError()) == "La comprobación no se cumple."
    assert hint_from(KeyError("x")) == "Error inesperado (KeyError): 'x'"
