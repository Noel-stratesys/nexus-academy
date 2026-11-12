"""Lanzar un experimento: una variante de Nexus sobre un dataset, con sus evaluadores.

    uv run experiment agente
    uv run experiment orquestador --label staging
    uv run experiment agente --repeat 3
    uv run experiment rag --rag-top-k 8 --rag-chunk-size 100 --rag-solo-vigentes
    uv run experiment agente --model executor=openai:otro-modelo

Cada ejecución queda en Langfuse como un *run* del dataset, con la configuración en su
metadata, y se puede comparar con otras en la pestaña del dataset.
"""

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any

from evaluation.datasets import DATASETS
from evaluation.evaluators import EVALUATORS, averages
from evaluation.tasks import RunSettings, make_task
from nexus.prompts import PROMPTS
from nexus.settings import Models, settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="experiment", description="Prueba una variante de Nexus sobre un dataset."
    )
    parser.add_argument("dataset", choices=sorted(DATASETS), help="Dataset sobre el que probar.")
    parser.add_argument(
        "--label", default=None, help="Label de los prompts a probar (por defecto: production)."
    )
    parser.add_argument(
        "--particion",
        choices=("development", "holdout", "todas"),
        default="development",
        help="Qué casos usar. El holdout se reserva para la comprobación final.",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="Repite el experimento N veces para ver el ruido."
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="NODO=PROVEEDOR:MODELO",
        help="Cambia el modelo de un nodo (orchestrator o executor).",
    )
    parser.add_argument("--rag-top-k", type=int)
    parser.add_argument("--rag-chunk-size", type=int, choices=(100, 250, 800))
    parser.add_argument("--rag-estrategia", choices=("bm25", "embeddings"))
    parser.add_argument("--rag-solo-vigentes", action="store_true")
    parser.add_argument("--flag", action="append", default=[], help="Activa una funcionalidad.")
    parser.add_argument("--nombre", help="Nombre corto de la variante, para reconocer el run.")
    parser.add_argument(
        "--concurrencia", type=int, default=1, help="Casos a la vez (cuidado con los límites)."
    )
    parser.add_argument("--detalle", action="store_true", help="Muestra el resultado de cada caso.")
    return parser.parse_args(argv)


def _models(overrides: list[str]) -> Models:
    models = settings.models
    for override in overrides:
        node, _, model = override.partition("=")
        if node not in ("orchestrator", "executor") or ":" not in model:
            sys.exit(f"--model espera NODO=PROVEEDOR:MODELO, no {override!r}")
        current = getattr(models, node)
        models = models.model_copy(update={node: current.model_copy(update={"model": model})})
    return models


def _rag(args: argparse.Namespace) -> Any:
    updates: dict[str, Any] = {}
    if args.rag_top_k:
        updates["top_k"] = args.rag_top_k
    if args.rag_chunk_size:
        updates["chunk_size"] = args.rag_chunk_size
    if args.rag_estrategia:
        updates["strategy"] = args.rag_estrategia
    if args.rag_solo_vigentes:
        updates["only_current"] = True
    return settings.rag.model_copy(update=updates)


def prompt_versions(langfuse: Any, label: str) -> dict[str, int]:
    """La versión a la que apunta ``label`` en cada prompt, fijada para todo el run."""

    return {
        prompt.name: int(langfuse.get_prompt(prompt.name, type="chat", label=label).version)
        for prompt in PROMPTS
    }


def _category_table(item_results: list[Any]) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for result in item_results:
        category = (getattr(result.item, "metadata", None) or {}).get("categoria", "?")
        for evaluation in result.evaluations:
            table[evaluation.name][category].append(float(evaluation.value))
    return {
        name: {category: sum(values) / len(values) for category, values in by_category.items()}
        for name, by_category in table.items()
    }


def _print_summary(scores_by_run: list[dict[str, float]], categories: dict[str, Any]) -> None:
    names = sorted({name for scores in scores_by_run for name in scores})
    print("\nScore                          media", end="")
    print("   ± desv. (entre repeticiones)" if len(scores_by_run) > 1 else "")
    for name in names:
        values = [scores[name] for scores in scores_by_run if name in scores]
        mean = statistics.mean(values)
        spread = f"   ± {statistics.stdev(values):.3f}" if len(values) > 1 else ""
        print(f"  {name:<28} {mean:6.3f}{spread}")
    print("\nPor categoría (último run):")
    for name, by_category in sorted(categories.items()):
        cells = ", ".join(f"{cat} {value:.2f}" for cat, value in sorted(by_category.items()))
        print(f"  {name}: {cells}")


def run(args: argparse.Namespace) -> list[dict[str, float]]:
    from nexus.llm.langfuse_client import langfuse

    definition = DATASETS[args.dataset]
    label = args.label or settings.environment
    run_settings = RunSettings(
        prompt_versions=prompt_versions(langfuse, label),
        models=_models(args.model),
        rag=_rag(args),
        flags=frozenset(args.flag),
    )
    dataset = langfuse.get_dataset(definition.name)
    items = [
        item
        for item in dataset.items
        if args.particion == "todas" or (item.metadata or {}).get("particion") == args.particion
    ]
    if not items:
        sys.exit(f"No hay casos en {definition.name} para la partición {args.particion}.")

    metadata = {
        "label": label,
        "prompts": ", ".join(f"{n} v{v}" for n, v in run_settings.prompt_versions.items()),
        "orchestrator": run_settings.models.orchestrator.model,
        "executor": run_settings.models.executor.model,
        "rag": run_settings.rag.model_dump_json(),
        "flags": ", ".join(sorted(run_settings.flags)) or "-",
        "particion": args.particion,
    }
    print(f"Experimento sobre {definition.name}: {len(items)} casos ({args.particion}).")
    for key, value in metadata.items():
        print(f"  {key}: {value}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    variant = args.nombre or label
    scores_by_run: list[dict[str, float]] = []
    categories: dict[str, Any] = {}
    for repetition in range(1, args.repeat + 1):
        suffix = f"-r{repetition}" if args.repeat > 1 else ""
        result = langfuse.run_experiment(
            name=definition.name,
            run_name=f"{variant}-{stamp}{suffix}",
            description=f"{variant} sobre {definition.name}",
            data=items,
            task=make_task(definition.target, run_settings),
            evaluators=EVALUATORS[args.dataset],
            run_evaluators=[averages],
            max_concurrency=args.concurrencia,
            metadata={**metadata, "repeticion": str(repetition)},
        )
        if args.detalle:
            print(result.format(include_item_results=True))
        scores = {
            evaluation.name.removeprefix("media_"): float(evaluation.value)
            for evaluation in result.run_evaluations
        }
        scores_by_run.append(scores)
        categories = _category_table(result.item_results)
        print(f"\nRun {repetition}/{args.repeat}: {result.run_name}")
        if result.experiment_url:
            print(f"  {result.experiment_url}")
    _print_summary(scores_by_run, categories)
    langfuse.flush()
    return scores_by_run


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))
