"""Misión 1 · Dos prompts y una discusión (``uv run check 1``).

Comprueba que Nexus sigue funcionando si Langfuse cae (el prompt tiene un fallback) y
que la versión ``production`` del executor no usa una temperatura alta.
"""

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


def test_production_del_executor_tiene_temperatura_baja() -> None:
    """La versión production de nexus/executor fija una temperatura de 0,3 o menos"""

    from nexus.llm.langfuse_client import langfuse

    try:
        prompt = langfuse.get_prompt(
            "nexus/executor",
            label="production",
            type="chat",
            cache_ttl_seconds=0,
            max_retries=0,
            fetch_timeout_seconds=10,
        )
    except Exception as error:
        pytest.fail(
            "No encuentro nexus/executor con el label production en Langfuse "
            f"({type(error).__name__}). ¿Responde Langfuse? Publica con: uv run prompts"
        )
    temperature = ((prompt.config or {}).get("model") or {}).get("temperature")
    assert temperature is not None, (
        f"La versión {prompt.version} (production) no fija config.model.temperature. "
        "Elige una versión que la fije y mueve a ella el label production."
    )
    assert float(temperature) <= MAX_TEMPERATURE, (
        f"production apunta a la versión {prompt.version}, con temperatura {temperature}. "
        "Una temperatura alta da variedad, no exactitud: mueve el label production a una "
        "versión con temperatura baja (desde la UI o con uv run prompts --label production)."
    )
