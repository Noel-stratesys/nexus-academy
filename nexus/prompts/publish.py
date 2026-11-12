"""Publica en Langfuse los prompts definidos en el código (``uv run prompts``)."""

import argparse
from typing import Any, cast

from nexus.prompts import PROMPTS, PROMPTS_BY_NAME, PromptDefinition


def publish_prompt(
    langfuse: Any, definition: PromptDefinition, labels: list[str], message: str | None = None
) -> int:
    """Crea una versión nueva del prompt con esos labels y devuelve su número."""

    prompt = langfuse.create_prompt(
        name=definition.name,
        prompt=cast(Any, definition.messages),
        type="chat",
        labels=labels,
        tags=definition.tags,
        config=definition.config,
        commit_message=message or f"Prompt del nodo {definition.node} desde el código",
    )
    return int(prompt.version)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="prompts", description="Publica una versión nueva de los prompts de Nexus."
    )
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Label de la versión creada; se puede repetir (por defecto: development).",
    )
    parser.add_argument("--name", help="Publica solo este prompt, por ejemplo nexus/executor.")
    parser.add_argument("--message", help="Mensaje de la versión (como un commit).")
    args = parser.parse_args(argv)

    from nexus.llm.langfuse_client import langfuse

    labels = list(dict.fromkeys(args.label or ["development"]))
    definitions = [PROMPTS_BY_NAME[args.name]] if args.name else PROMPTS
    for definition in definitions:
        version = publish_prompt(langfuse, definition, labels, args.message)
        print(f"{definition.name}: versión {version} con labels {', '.join(labels)}")
    langfuse.flush()
