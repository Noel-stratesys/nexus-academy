"""Prompts de Nexus tal como están en el código. ``uv run prompts`` los publica en Langfuse."""

from nexus.prompts.definition import PromptDefinition
from nexus.prompts.executor import EXECUTOR_PROMPT_NAME
from nexus.prompts.executor import PROMPT as EXECUTOR_PROMPT
from nexus.prompts.orchestrator import ORCHESTRATOR_PROMPT_NAME
from nexus.prompts.orchestrator import PROMPT as ORCHESTRATOR_PROMPT

PROMPTS: list[PromptDefinition] = [ORCHESTRATOR_PROMPT, EXECUTOR_PROMPT]
PROMPTS_BY_NAME = {prompt.name: prompt for prompt in PROMPTS}

__all__ = [
    "EXECUTOR_PROMPT_NAME",
    "ORCHESTRATOR_PROMPT_NAME",
    "PROMPTS",
    "PROMPTS_BY_NAME",
    "PromptDefinition",
]
