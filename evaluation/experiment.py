"""Lanzar un experimento: una variante de Nexus sobre un dataset, con sus evaluadores.

    uv run experiment agente
    uv run experiment orquestador --label staging
    uv run experiment agente --repeat 3
    uv run experiment rag --rag-top-k 8 --rag-chunk-size 100 --rag-solo-vigentes
    uv run experiment agente --model executor=openai:otro-modelo
    uv run experiment agente --release green --gate

Con ``--release blue|green`` se prueba una de las dos versiones de ``release.toml`` (su
label y sus flags). Con ``--gate`` se comparan las medias con los mínimos de la puerta y
el comando termina con error si alguno no llega. Con ``--sin-llm`` Nexus usa el modelo con
guion en lugar de un modelo de lenguaje: es lo que hace ``uv run release gate``.

Cada ejecución queda en Langfuse como un *run* del dataset, con la configuración en su
metadata, y se puede comparar con otras en la pestaña del dataset.
"""

import argparse
import gc
import statistics
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from typing import Any

from evaluation.datasets import DATASETS
from evaluation.evaluators import EVALUATORS, averages
from evaluation.tasks import RunSettings, con_guion_de_caso, make_task
from nexus.prompts import PROMPTS
from nexus.settings import Models, settings
from release.gate import check_gate, format_gate, gate_passed
from release.state import ReleaseState, load_state, save_state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="experiment", description="Prueba una variante de Nexus sobre un dataset."
    )
    parser.add_argument("dataset", choices=sorted(DATASETS), help="Dataset sobre el que probar.")
    version = parser.add_mutually_exclusive_group()
    version.add_argument(
        "--label", default=None, help="Label de los prompts a probar (por defecto: production)."
    )
    version.add_argument(
        "--release",
        choices=("blue", "green"),
        help="Prueba esa versión de release.toml: su label y sus flags.",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Compara las medias con la puerta de release.toml; sale con error si no pasa.",
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
    parser.add_argument(
        "--sin-llm",
        action="store_true",
        help="Nexus con el modelo con guion: sin tokens ni proveedor (la puerta del capítulo 5).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        metavar="N",
        help="Solo los N primeros casos, por orden de case_id (para probar rápido).",
    )
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


def release_settings(args: argparse.Namespace) -> tuple[str, frozenset[str], str]:
    """Label, flags y nombre de la variante que pide la línea de comandos."""

    flags = frozenset(args.flag)
    if not getattr(args, "release", None):
        label = args.label or settings.environment
        return label, flags, args.nombre or label
    state = load_state()
    if args.release == "blue":
        return state.blue.label, state.blue.flags | flags, args.nombre or "blue"
    if not state.green.cambio:
        sys.exit("No hay ningún cambio en green. Prepáralo con: uv run release prepare <cambio>")
    variant = args.nombre or f"green-{state.green.cambio}"
    return state.green.label, state.green.flags | flags, variant


def mean_scores(scores_by_run: list[dict[str, float]]) -> dict[str, float]:
    """La media de cada score entre repeticiones."""

    names = {name for scores in scores_by_run for name in scores}
    return {
        name: statistics.mean(scores[name] for scores in scores_by_run if name in scores)
        for name in names
    }


def apply_gate(
    args: argparse.Namespace, scores_by_run: list[dict[str, float]], state: ReleaseState
) -> bool:
    """Imprime la tabla de la puerta y, si se probó green, guarda el resultado."""

    rows = check_gate(mean_scores(scores_by_run), state.gate)
    print("\nPuerta (release.toml, [gate]):")
    print(format_gate(rows))
    passed = gate_passed(rows)
    if getattr(args, "release", None) == "green" and state.green.cambio:
        resultado = "superada" if passed else "fallida"
        green = replace(state.green, puerta=resultado)
        detalle = ", ".join(
            f"{row.score} {'-' if row.media is None else f'{row.media:.2f}'}" for row in rows
        )
        save_state(
            replace(state, green=green).with_event(
                "puerta", state.green.cambio, f"{resultado}: {detalle}"
            )
        )
    return passed


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
    label, flags, variant = release_settings(args)
    sin_llm = bool(getattr(args, "sin_llm", False))
    if sin_llm:
        from nexus.simulation.modelo import instalar

        instalar(latencia=True)
    run_settings = RunSettings(
        prompt_versions=prompt_versions(langfuse, label),
        models=_models(args.model),
        rag=_rag(args),
        flags=flags,
    )
    dataset = langfuse.get_dataset(definition.name)
    # Solo los casos activos que siguen en el código (los demás están archivados).
    current = {definition.item_id(case) for case in definition.cases}
    items = [
        item
        for item in dataset.items
        if item.id in current and str(item.status).upper().endswith("ACTIVE")
    ]
    if not items:
        sys.exit(f"El dataset {definition.name} no tiene casos. Súbelo con: uv run dataset")
    if args.limite:
        items.sort(key=lambda item: (item.metadata or {}).get("case_id", ""))
        items = items[: args.limite]

    metadata = {
        "label": label,
        "release": getattr(args, "release", None) or "-",
        "prompts": ", ".join(f"{n} v{v}" for n, v in run_settings.prompt_versions.items()),
        "orchestrator": "modelo con guion" if sin_llm else run_settings.models.orchestrator.model,
        "executor": "modelo con guion" if sin_llm else run_settings.models.executor.model,
        "rag": run_settings.rag.model_dump_json(),
        "flags": ", ".join(sorted(run_settings.flags)) or "-",
    }
    print(f"Experimento sobre {definition.name}: {len(items)} casos.")
    for key, value in metadata.items():
        print(f"  {key}: {value}")

    task = make_task(definition.target, run_settings)
    if sin_llm:
        task = con_guion_de_caso(task)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    scores_by_run: list[dict[str, float]] = []
    categories: dict[str, Any] = {}
    for repetition in range(1, args.repeat + 1):
        suffix = f"-r{repetition}" if args.repeat > 1 else ""
        result = langfuse.run_experiment(
            name=definition.name,
            run_name=f"{variant}-{stamp}{suffix}",
            description=f"{variant} sobre {definition.name}",
            data=items,
            task=task,
            evaluators=EVALUATORS[args.dataset],
            run_evaluators=[averages],
            max_concurrency=args.concurrencia,
            metadata={**metadata, "repeticion": str(repetition)},
        )
        # Cada run_experiment usa su propio bucle de eventos y lo cierra al acabar. Los
        # clientes HTTP del modelo que quedan vivos intentarían cerrarse durante el run
        # siguiente, en un bucle que no es el suyo, y llenarían la salida de errores
        # «Event loop is closed». Liberarlos ahora, sin bucle activo, los cierra en silencio.
        gc.collect()
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
    args = parse_args(argv)
    scores_by_run = run(args)
    if args.gate and not apply_gate(args, scores_by_run, load_state()):
        sys.exit(1)
