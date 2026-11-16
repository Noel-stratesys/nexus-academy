"""Misión 1 · Dos prompts y una discusión (``uv run check 1``).

Comprueba que Nexus sigue funcionando si Langfuse cae (el prompt tiene un fallback) y
que la versión ``production`` del executor es una de las dos de la prueba A/B, la de
Marc o la de Jordi, con una temperatura baja.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus.prompts import PROMPTS_BY_NAME
from nexus.settings import settings

MAX_TEMPERATURE = 0.3


@pytest.mark.parametrize("name", ["nexus/orchestrator", "nexus/executor"])
def test_langfuse_prompt_usa_el_prompt_del_codigo_como_fallback(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """langfuse_prompt() lee el prompt por label y usa el del código como fallback"""

    from nexus.llm import prompts

    fake_langfuse = MagicMock()
    monkeypatch.setattr(prompts, "langfuse", fake_langfuse)

    prompts.langfuse_prompt(name)

    assert fake_langfuse.get_prompt.called, (
        "langfuse_prompt() no llama a langfuse.get_prompt(): completa la función en "
        "nexus/llm/prompts.py."
    )
    kwargs = fake_langfuse.get_prompt.call_args.kwargs
    assert kwargs.get("label") == settings.environment, (
        f"{name}: el prompt debe pedirse por label (label=active_label(), que es "
        f"«{settings.environment}»); se ha pedido con label={kwargs.get('label')!r}."
    )
    assert kwargs.get("fallback") == PROMPTS_BY_NAME[name].messages, (
        f"{name}: si Langfuse no responde, Nexus se queda sin prompt. Pasa a get_prompt() "
        "fallback= con los mensajes del prompt del código (PROMPTS_BY_NAME[name].messages)."
    )


def _executor(label: str) -> Any:
    """La versión de nexus/executor que tiene ``label`` en Langfuse."""

    from nexus.llm.langfuse_client import langfuse

    try:
        return langfuse.get_prompt(
            "nexus/executor",
            label=label,
            type="chat",
            cache_ttl_seconds=0,
            max_retries=0,
            fetch_timeout_seconds=10,
        )
    except Exception as error:
        pytest.fail(
            f"No encuentro nexus/executor con el label {label} en Langfuse "
            f"({type(error).__name__}). ¿Responde Langfuse? ¿Has cargado el historial con "
            "uv run seed?"
        )


def _production() -> Any:
    """La versión de nexus/executor con el label production; falla si no hay ninguna."""

    from nexus.llm.langfuse_client import langfuse

    try:
        return langfuse.get_prompt(
            "nexus/executor",
            label="production",
            type="chat",
            cache_ttl_seconds=0,
            max_retries=0,
            fetch_timeout_seconds=10,
        )
    except Exception:
        pytest.fail("Ninguna versión de nexus/executor tiene el label production.")


def _numero(valor: object) -> str:
    return str(valor).replace(".", ",")


def test_production_del_executor() -> None:
    """La versión production de nexus/executor es de la prueba A/B y con temperatura baja"""

    de_la_prueba = sorted(_executor(label).version for label in ("marc", "jordi"))
    production = _production()
    temperature = ((production.config or {}).get("model") or {}).get("temperature")
    actual = f"production apunta a la versión {production.version}, " + (
        f"con temperatura {_numero(temperature)}."
        if temperature is not None
        else "sin temperatura en su config."
    )
    assert production.version in de_la_prueba, (
        f"{actual} No es ninguna de las de la prueba A/B (versiones "
        f"{' y '.join(map(str, de_la_prueba))})."
    )
    assert temperature is not None and float(temperature) <= MAX_TEMPERATURE, actual
