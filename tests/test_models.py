"""Tests de ``chat_model``: qué modelo y con qué parámetros se crea, sin llamar a la red."""

import pytest
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from nexus.llm.models import CLOUD_MAX_RETRIES, chat_model
from nexus.settings import ExecutorModel, ModelConfig, OrchestratorModel


@pytest.fixture(autouse=True)
def fake_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Crear el cliente no llama a la red, pero exige una clave: nunca se usa la del .env.
    monkeypatch.setenv("GROQ_API_KEY", "gsk-clave-de-prueba")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-clave-de-prueba")


def test_default_models_use_groq() -> None:
    assert OrchestratorModel().model == "groq:llama-3.3-70b-versatile"
    assert ExecutorModel().model == "groq:llama-3.3-70b-versatile"


def test_groq_model_retries_rate_limits_and_keeps_its_parameters() -> None:
    model = chat_model(
        ModelConfig(model="groq:llama-3.3-70b-versatile", temperature=0.2, max_tokens=256)
    )

    assert isinstance(model, ChatGroq)
    assert model.model_name == "llama-3.3-70b-versatile"
    assert model.temperature == 0.2
    assert model.max_tokens == 256
    assert model.max_retries == CLOUD_MAX_RETRIES
    assert model.reasoning_format is None
    assert model.model_kwargs == {}


@pytest.mark.parametrize("name", ["qwen/qwen3-32b", "deepseek-r1-distill-llama-70b"])
def test_groq_reasoning_models_hide_their_reasoning(name: str) -> None:
    model = chat_model(ModelConfig(model=f"groq:{name}"))

    assert isinstance(model, ChatGroq)
    assert model.reasoning_format == "hidden"


def test_groq_gpt_oss_hides_reasoning_without_reasoning_format() -> None:
    model = chat_model(ModelConfig(model="groq:openai/gpt-oss-120b"))

    assert isinstance(model, ChatGroq)
    assert model.model_name == "openai/gpt-oss-120b"
    assert model.reasoning_format is None
    assert model.model_kwargs == {"include_reasoning": False}


def test_openai_compatible_model_retries_rate_limits() -> None:
    model = chat_model(ModelConfig(model="openai:mi-modelo", max_tokens=128))

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "mi-modelo"
    assert model.max_retries == CLOUD_MAX_RETRIES
    assert model.max_tokens == 128


def test_ollama_model_uses_the_configured_host() -> None:
    model = chat_model(ModelConfig(model="ollama:qwen3:4b-instruct", max_tokens=64))

    assert isinstance(model, ChatOllama)
    assert model.model == "qwen3:4b-instruct"
    assert model.num_predict == 64
    assert model.reasoning is False
