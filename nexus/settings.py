"""Configuración de Nexus: se lee de variables de entorno y del fichero .env.

Cada nodo tiene su modelo (``MODELS__<NODO>__MODEL=proveedor:nombre``). La temperatura
por defecto está aquí, pero un prompt de Langfuse puede fijar la suya en su ``config``.
"""

import os
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@cache
def initialize_environment() -> None:
    """Carga el .env una sola vez, sin pisar las variables que ya existan."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    os.environ.setdefault("LANGFUSE_TIMEOUT", "30")


initialize_environment()


class ModelConfig(BaseModel):
    """Modelo de un nodo; ``model`` tiene el formato ``proveedor:nombre``."""

    model: str
    temperature: float = 0
    max_tokens: int | None = None

    @property
    def provider(self) -> str:
        return self.model.split(":", 1)[0]

    @property
    def name(self) -> str:
        return self.model.split(":", 1)[1]


class OrchestratorModel(ModelConfig):
    model: str = "ollama:qwen3:4b-instruct"
    max_tokens: int | None = 256


class ExecutorModel(ModelConfig):
    model: str = "ollama:qwen3:4b-instruct"
    temperature: float = 0.2
    max_tokens: int | None = 2048


class Models(BaseModel):
    orchestrator: OrchestratorModel = OrchestratorModel()
    executor: ExecutorModel = ExecutorModel()


class RagSettings(BaseModel):
    """Cómo busca Nexus en la normativa."""

    strategy: Literal["bm25", "embeddings"] = "bm25"
    chunk_size: int = 250
    top_k: int = Field(default=4, ge=1, le=20)
    only_current: bool = False
    embedding_model: str = "ollama:nomic-embed-text-v2-moe"

    @field_validator("chunk_size")
    @classmethod
    def _known_chunk_size(cls, value: int) -> int:
        if value not in (100, 250, 800):
            raise ValueError("chunk_size debe ser 100, 250 u 800")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_nested_delimiter="__")

    # Label de Langfuse que usa la aplicación para leer sus prompts.
    environment: str = "production"
    # "Hoy" en la historia del academy. Los datos y las fechas relativas parten de aquí.
    nexus_today: date = date(2026, 11, 16)
    ollama_host: str = "http://localhost:11434"
    models: Models = Models()
    rag: RagSettings = RagSettings()
    llm_call_timeout_seconds: float = Field(default=120, gt=0)
    executor_tool_max_retries: int = Field(default=0, ge=0)


settings = Settings()
