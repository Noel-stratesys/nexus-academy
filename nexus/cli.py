"""Comandos del proyecto (``uv run <comando>``). ``uv run help`` los lista."""

import argparse
import asyncio
import json
import sys
from datetime import date
from typing import Any
from uuid import uuid4

# Las terminales de Windows no siempre escriben en UTF-8: tildes y "ç" se verían mal.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

COMMANDS = {
    "agent": "Habla con Nexus en la terminal como un viajero (--usuario, --dia).",
    "prompts": "Publica en Langfuse una versión nueva de los prompts del código.",
    "index": "Muestra los chunks de la normativa y prueba el buscador (--buscar).",
    "dataset": "Sube a Langfuse los datasets definidos en evaluation/datasets.",
    "experiment": "Ejecuta Nexus sobre un dataset y puntúa cada caso (--repeat, --label...).",
    "judge-agreement": "Compara las notas del LLM-as-a-judge con las anotaciones humanas.",
    "seed": "Carga en Langfuse el historial de tres semanas de Nexus.",
    "check": "Comprueba una misión: uv run check 0 … uv run check 5.",
    "release": "Despliegue por fases: status, prepare, shift, rollback, promote.",
    "simulate": "Simula viajeros hablando con Nexus (tráfico de producción).",
    "help": "Esta ayuda.",
}


def show_help() -> None:
    print("Comandos disponibles (ejecútalos con `uv run <comando>`):\n")
    for name, text in COMMANDS.items():
        print(f"  {name:<12} {text}")


async def _ask_approval(actions: list[dict[str, Any]]) -> list[str]:
    replies = []
    for action in actions:
        print(f"\nNexus quiere ejecutar {action['name']}:")
        print(json.dumps(action["args"], ensure_ascii=False, indent=2))
        reply = (await asyncio.to_thread(input, "«sí» para aprobar, o di por qué no> ")).strip()
        replies.append("approve" if reply.lower() in {"si", "sí", "s", "yes"} else reply or "No")
    return replies


async def _chat(args: argparse.Namespace) -> None:
    from nexus.context import Context
    from nexus.graph import build_graph
    from nexus.llm.langfuse_client import langfuse
    from nexus.runner import run_turn

    hoy = date.fromisoformat(args.dia) if args.dia else None
    context = Context.for_user(args.usuario, **({"hoy": hoy} if hoy else {}))
    graph = build_graph()
    thread_id = uuid4().hex
    print(f"Hablas con Nexus como {context.viajero.describe()}. Hoy es {context.hoy}.")
    print("Escribe «salir» para terminar.")
    try:
        while True:
            text = (await asyncio.to_thread(input, "\nTú> ")).strip()
            if text.lower() in {"salir", "exit", "quit"}:
                break
            if not text:
                continue
            turn = await run_turn(
                graph,
                text,
                context=context,
                thread_id=thread_id,
                approver=_ask_approval,
                tags=["chat"],
            )
            print(f"Nexus> {turn.answer or '(sin respuesta)'}")
    finally:
        langfuse.flush()


def agent() -> None:
    parser = argparse.ArgumentParser(prog="agent", description=COMMANDS["agent"])
    parser.add_argument("--usuario", default="1001", help="Id del viajero (ver nexus/data).")
    parser.add_argument("--dia", help="Fecha de 'hoy' en la historia, AAAA-MM-DD.")
    asyncio.run(_chat(parser.parse_args()))


def prompts() -> None:
    from nexus.prompts.publish import main

    main()


def index() -> None:
    parser = argparse.ArgumentParser(prog="index", description=COMMANDS["index"])
    parser.add_argument("--chunk-size", type=int, choices=(100, 250, 800))
    parser.add_argument(
        "--embeddings",
        action="store_true",
        help="Calcula y guarda los vectores de todos los tamaños de chunk.",
    )
    parser.add_argument("--buscar", help="Prueba una búsqueda con la configuración actual.")
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--estrategia", choices=("bm25", "embeddings"))
    parser.add_argument("--solo-vigentes", action="store_true")
    args = parser.parse_args()

    from nexus.rag.documents import CHUNK_SIZES, chunks_for, load_documents
    from nexus.settings import settings

    if args.embeddings:
        from nexus.rag.embeddings import build_index

        for size in CHUNK_SIZES:
            path = build_index(chunks_for(size), size, settings.rag.embedding_model)
            print(f"Chunks de {size}: {len(chunks_for(size))} vectores en {path.name}")
        return

    if args.buscar:
        from nexus.rag.retriever import retriever

        overrides: dict[str, Any] = {}
        if args.chunk_size:
            overrides["chunk_size"] = args.chunk_size
        if args.top_k:
            overrides["top_k"] = args.top_k
        if args.estrategia:
            overrides["strategy"] = args.estrategia
        if args.solo_vigentes:
            overrides["only_current"] = True
        for document in retriever(**overrides).invoke(args.buscar):
            meta = document.metadata
            vigente = "" if meta["vigente"] else "  [NO VIGENTE]"
            print(f"{meta['rank']}. {meta['score']:.3f}  {meta['chunk_id']}{vigente}")
            print(f"   {', '.join(meta['secciones'])}")
        return

    print(f"{len(load_documents())} documentos")
    for size in [args.chunk_size] if args.chunk_size else CHUNK_SIZES:
        print(f"Chunks de {size} tokens: {len(chunks_for(size))}")
