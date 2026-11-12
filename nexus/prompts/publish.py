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


def move_labels(langfuse: Any, name: str, version: int, labels: list[str]) -> list[str]:
    """Pone los labels a una versión que ya existe y devuelve los labels que le quedan.

    No crea ninguna versión: si el label estaba en otra, Langfuse se lo quita a esa.
    """

    prompt = langfuse.get_prompt(name, type="chat", version=version, cache_ttl_seconds=0)
    current = [label for label in prompt.labels if label != "latest"]
    new_labels = list(dict.fromkeys([*current, *labels]))
    langfuse.update_prompt(name=name, version=version, new_labels=new_labels)
    return new_labels


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="prompts",
        description=(
            "Publica una versión nueva de los prompts de Nexus, o con --version mueve "
            "labels a una versión que ya existe."
        ),
    )
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Label que se pone a la versión; se puede repetir (por defecto: development).",
    )
    parser.add_argument("--name", help="Solo este prompt, por ejemplo nexus/executor.")
    parser.add_argument(
        "--version",
        type=int,
        help="No publica nada: pone los labels a esta versión, que ya existe (requiere --name).",
    )
    parser.add_argument("--message", help="Mensaje de la versión (como un commit).")
    args = parser.parse_args(argv)
    if args.version is not None and not args.name:
        parser.error("--version necesita --name: las versiones son de cada prompt.")

    from nexus.llm.langfuse_client import langfuse

    labels = list(dict.fromkeys(args.label or ["development"]))
    if args.version is not None:
        try:
            current = move_labels(langfuse, args.name, args.version, labels)
        except Exception as error:
            raise SystemExit(
                f"No encuentro {args.name} versión {args.version} en Langfuse "
                f"({type(error).__name__}). Mira las versiones en Prompts → {args.name}."
            ) from error
        print(f"{args.name}: versión {args.version} con labels {', '.join(current)}")
        return

    definitions = [PROMPTS_BY_NAME[args.name]] if args.name else PROMPTS
    for definition in definitions:
        version = publish_prompt(langfuse, definition, labels, args.message)
        print(f"{definition.name}: versión {version} con labels {', '.join(labels)}")
    langfuse.flush()
