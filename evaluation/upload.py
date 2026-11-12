"""Sube los datasets a Langfuse (``uv run dataset``)."""

import argparse

from evaluation.datasets import DATASETS, upload


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dataset", description="Sube los datasets a Langfuse.")
    parser.add_argument(
        "nombres", nargs="*", help=f"Datasets a subir ({', '.join(DATASETS)}). Por defecto, todos."
    )
    args = parser.parse_args(argv)
    unknown = [name for name in args.nombres if name not in DATASETS]
    if unknown:
        parser.error(f"datasets desconocidos: {', '.join(unknown)}")

    from nexus.llm.langfuse_client import langfuse

    for name in args.nombres or sorted(DATASETS):
        definition = DATASETS[name]
        count = upload(definition, langfuse)
        print(f"{definition.name}: {count} casos")
