"""Crea el modelo de chat de un nodo a partir de su ModelConfig.

Es el único sitio que sabe de proveedores: el resto del código pide un modelo y lo usa.
"""

from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import ValidationError

from nexus.settings import ModelConfig, settings

# Los proveedores en la nube limitan las peticiones por minuto: se reintentan los 429.
CLOUD_MAX_RETRIES = 6

# Veces que se repite al momento una llamada en la que el modelo escribió mal su salida.
MALFORMED_OUTPUT_RETRIES = 2

# Códigos de error de Groq cuando el modelo escribe mal una llamada a herramienta
# (``tool_use_failed``) o un JSON que no cumple el esquema (``json_validate_failed``).
MALFORMED_OUTPUT_CODES = ("tool_use_failed", "json_validate_failed")


def is_malformed_output(error: BaseException) -> bool:
    """El modelo escribió mal la llamada a herramienta o el JSON que se le pedía.

    No es un fallo de la petición sino una errata del modelo: repetir la misma llamada
    suele salir bien, así que se reintenta al momento, sin esperar.
    """

    if isinstance(error, OutputParserException | ValidationError):
        return True
    return any(code in str(error) for code in MALFORMED_OUTPUT_CODES)


# Modelos de Groq que "piensan en voz alta" antes de responder. Su razonamiento no debe
# acabar en la respuesta al viajero ni confundir al orquestador.
GROQ_REASONING_FORMAT_MODELS = ("qwen3", "deepseek-r1")
GROQ_INCLUDE_REASONING_MODELS = ("gpt-oss",)


def _groq_parameters(name: str) -> dict[str, Any]:
    """Parámetros propios de ``ChatGroq`` para el modelo ``name``.

    Qwen3 y DeepSeek-R1 ocultan el razonamiento con ``reasoning_format="hidden"``. Los
    modelos gpt-oss no admiten ese parámetro: lo ocultan con ``include_reasoning=False``.
    """

    lowered = name.lower()
    parameters: dict[str, Any] = {"max_retries": CLOUD_MAX_RETRIES}
    if any(family in lowered for family in GROQ_REASONING_FORMAT_MODELS):
        parameters["reasoning_format"] = "hidden"
    elif any(family in lowered for family in GROQ_INCLUDE_REASONING_MODELS):
        parameters["model_kwargs"] = {"include_reasoning": False}
    return parameters


def chat_model(config: ModelConfig) -> BaseChatModel:
    """El modelo de LangChain descrito por ``config`` (``proveedor:nombre``).

    Proveedores: ``groq`` (el de la academy), ``openai`` (o cualquier servidor compatible
    con su API, vía ``OPENAI_BASE_URL``) y ``ollama`` (modelos en local).
    """

    parameters: dict[str, Any] = {"temperature": config.temperature}
    if config.provider == "ollama":
        parameters["base_url"] = settings.ollama_host
        parameters["reasoning"] = False
        if config.max_tokens is not None:
            parameters["num_predict"] = config.max_tokens
    elif config.max_tokens is not None:
        parameters["max_tokens"] = config.max_tokens
    if config.provider == "groq":
        parameters.update(_groq_parameters(config.name))
    elif config.provider == "openai":
        parameters["max_retries"] = CLOUD_MAX_RETRIES
    return cast(BaseChatModel, init_chat_model(config.model, **parameters))
