"""Crea el modelo de chat de un nodo a partir de su ModelConfig.

Es el único sitio que sabe de proveedores: el resto del código pide un modelo y lo usa.
"""

from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from nexus.settings import ModelConfig, settings


def chat_model(config: ModelConfig) -> BaseChatModel:
    """El modelo de LangChain descrito por ``config`` (``proveedor:nombre``)."""

    parameters: dict[str, Any] = {"temperature": config.temperature}
    if config.provider == "ollama":
        parameters["base_url"] = settings.ollama_host
        parameters["reasoning"] = False
        if config.max_tokens is not None:
            parameters["num_predict"] = config.max_tokens
    elif config.max_tokens is not None:
        parameters["max_tokens"] = config.max_tokens
    if config.provider == "openai":
        # Los servidores compartidos limitan las peticiones por minuto: reintenta los 429.
        parameters["max_retries"] = 6
    return cast(BaseChatModel, init_chat_model(config.model, **parameters))
