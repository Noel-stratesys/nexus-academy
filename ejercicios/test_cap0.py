"""Misión 0 · Todo listo para empezar (``uv run check 0``).

Comprueba la instalación: el .env, Langfuse en Docker, los prompts publicados, el
proveedor del modelo y el historial de tres semanas de Nexus.

La comprobación del modelo hace una llamada real (y gasta tokens). Para saltarla:
``uv run check 0 -k "not modelo"``.
"""

import json
import os
from datetime import UTC, datetime

import pytest

from nexus.settings import PROJECT_ROOT, initialize_environment, settings

initialize_environment()

LANGFUSE_KEYS = ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
PROMPT_NAMES = ("nexus/orchestrator", "nexus/executor")
# Variable con la clave de cada proveedor (Ollama corre en local y no necesita clave).
PROVIDER_KEYS = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}

# El historial que carga ``uv run seed`` va del lunes 26 de octubre al domingo 15 de
# noviembre de 2026. Se mira la primera semana: las trazas que generes tú hoy caen en
# fechas reales y no deben hacer pasar esta comprobación por error.
HISTORY_FIRST_WEEK = (datetime(2026, 10, 26, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC))


def _langfuse_url() -> str:
    return os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3100")


def _count_traces(start: datetime, end: datetime) -> int:
    """Trazas (observations raíz) que empiezan entre ``start`` y ``end``."""

    from nexus.llm.langfuse_client import langfuse

    query = {
        "view": "observations",
        "metrics": [{"measure": "count", "aggregation": "count"}],
        "dimensions": [],
        "filters": [
            {"column": "isRootObservation", "operator": "=", "value": True, "type": "boolean"}
        ],
        "fromTimestamp": start.isoformat().replace("+00:00", "Z"),
        "toTimestamp": end.isoformat().replace("+00:00", "Z"),
    }
    rows = langfuse.api.metrics.metrics(query=json.dumps(query)).data
    return int(rows[0].get("count_count") or 0) if rows else 0


def test_existe_el_fichero_env() -> None:
    """Existe el fichero .env con tu configuración"""

    assert (PROJECT_ROOT / ".env").exists(), (
        "No hay fichero .env en la raíz del proyecto. Cópialo de la plantilla: "
        "copy .env.example .env (macOS/Linux: cp .env.example .env)."
    )


def test_claves_de_langfuse_configuradas() -> None:
    """Las claves de Langfuse están en el .env"""

    missing = [name for name in LANGFUSE_KEYS if not os.environ.get(name)]
    assert not missing, (
        f"Faltan variables en .env: {', '.join(missing)}. "
        "Cópialas de .env.example: ya funcionan con el docker-compose.yml."
    )


def test_langfuse_responde() -> None:
    """Langfuse responde en http://localhost:3100 y acepta tus claves"""

    from nexus.llm.langfuse_client import langfuse

    try:
        ok = langfuse.auth_check()
    except Exception as error:
        pytest.fail(
            f"Langfuse no responde en {_langfuse_url()} ({type(error).__name__}). "
            "¿Está Docker Desktop abierto? Arranca Langfuse con: docker compose up -d "
            "(tarda un par de minutos la primera vez)."
        )
    assert ok, "Langfuse responde pero no acepta las claves: revisa LANGFUSE_* en tu .env."


def test_prompts_publicados_en_production() -> None:
    """Los prompts nexus/orchestrator y nexus/executor están publicados con el label production"""

    from nexus.llm.langfuse_client import langfuse

    missing = []
    for name in PROMPT_NAMES:
        try:
            langfuse.get_prompt(
                name,
                label="production",
                type="chat",
                cache_ttl_seconds=0,
                max_retries=0,
                fetch_timeout_seconds=10,
            )
        except Exception:
            missing.append(name)
    assert not missing, (
        f"No encuentro en Langfuse con el label production: {', '.join(missing)}. "
        "Publícalos con: uv run prompts"
    )


def test_clave_del_proveedor_configurada() -> None:
    """La clave del proveedor del modelo está en el .env"""

    models = {settings.models.orchestrator.model, settings.models.executor.model}
    providers = {model.split(":", 1)[0] for model in models}
    missing = sorted(
        PROVIDER_KEYS[provider]
        for provider in providers
        if provider in PROVIDER_KEYS and not os.environ.get(PROVIDER_KEYS[provider])
    )
    assert not missing, (
        f"Falta {', '.join(missing)} en tu .env (modelos: {', '.join(sorted(models))}). "
        "Crea tu clave de Groq en https://console.groq.com/keys y pégala en GROQ_API_KEY."
    )


def test_el_modelo_responde() -> None:
    """El proveedor del modelo responde a una pregunta mínima"""

    from nexus.llm.models import chat_model

    configs = {
        config.model: config for config in (settings.models.orchestrator, settings.models.executor)
    }
    for model, config in configs.items():
        try:
            answer = chat_model(config).invoke("Responde solo con la palabra: listo")
        except Exception as error:
            detail = str(error).strip().splitlines()[0][:160] if str(error).strip() else ""
            pytest.fail(
                f"El modelo {model} no responde ({type(error).__name__}: {detail}). "
                "Revisa GROQ_API_KEY y MODELS__*__MODEL en tu .env. Si dice 429, espera "
                "un minuto: es el límite de peticiones del proveedor."
            )
        assert answer.text.strip(), f"El modelo {model} ha respondido un texto vacío."


def test_historial_cargado() -> None:
    """El historial de tres semanas de Nexus está cargado en Langfuse"""

    try:
        first_week = _count_traces(*HISTORY_FIRST_WEEK)
    except Exception as error:
        pytest.fail(
            f"No he podido consultar las trazas en Langfuse ({type(error).__name__}). "
            "Comprueba antes que Langfuse responde."
        )
    assert first_week > 0, (
        "No encuentro el historial de Nexus (sus trazas empiezan el 26 de octubre de 2026). "
        "Ejecuta uv run seed: si se corta, vuelve a lanzarlo, no duplica nada."
    )
