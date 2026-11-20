"""Comandos ``uv run release`` y ``uv run simulate``: desplegar un cambio por fases.

    uv run release status                 # qué hay en blue y en green
    uv run release prepare A              # publica el cambio A con el label green
    uv run release gate                   # la puerta: experimento sobre el dataset agente
    uv run release shift 10               # el 10 % de los viajeros va a green
    uv run simulate --n 40                # viajeros simulados contra blue y green
    uv run release rollback --motivo "…"  # green vuelve al 0 % (el cambio se queda)
    uv run release promote --motivo "…"   # green pasa a ser blue (production)
    uv run alarma --provocar              # extra: la alarma de tokens (release/alarma.py)

El estado está en ``release.toml``. Los prompts viven en Langfuse: blue lee los que
tienen el label ``production`` y green, los que tienen el label ``green``.

Ni la puerta ni el simulador llaman a un modelo de lenguaje: Nexus contesta con el modelo
con guion (``nexus.simulation.modelo``), que reacciona a los prompts y a las herramientas
como uno de verdad. Así cada paso tarda segundos y no gasta tokens.
"""

import argparse
import asyncio
import math
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

from nexus.data import viajeros
from nexus.prompts import EXECUTOR_PROMPT_NAME, PROMPTS, PROMPTS_BY_NAME
from nexus.simulation.types import SimResult
from release.cambios import CAMBIOS, CambioError
from release.router import bucket, router
from release.state import Green, ReleaseState, load_state, save_state

# Casos o conversaciones a la vez: sin proveedor de por medio, no hay límites que cuidar.
CONCURRENCIA = 8

# Las terminales de Windows no siempre escriben en UTF-8: tildes y "ç" se verían mal.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

DASHBOARD = "Nexus en producción"


def _langfuse() -> Any:
    """El cliente de Langfuse (se importa al usarlo para que ``status`` no lo necesite)."""

    from nexus.llm.langfuse_client import langfuse

    return langfuse


def _fail(message: str) -> NoReturn:
    sys.exit(f"✘ {message}")


def _flags(flags: frozenset[str]) -> str:
    return ", ".join(sorted(flags)) or "—"


def _green_share(traffic: int) -> str:
    """Cuántos viajeros conocidos caen en green con ese porcentaje."""

    ids = list(viajeros())
    inside = sum(1 for user_id in ids if bucket(user_id) < traffic)
    return f"{inside} de los {len(ids)} viajeros conocidos"


def _require_green(state: ReleaseState) -> str:
    if not state.green.cambio:
        _fail("No hay ningún cambio en green. Prepáralo con: uv run release prepare <cambio>")
    return state.green.cambio


# --- status --------------------------------------------------------------------


def _cambio_estado(state: ReleaseState, clave: str) -> str:
    if clave in state.blue.cambios:
        return "en producción"
    if state.green.cambio == clave:
        puerta = f", puerta {state.green.puerta}" if state.green.puerta else ""
        return f"en green al {state.green.traffic} %{puerta}"
    return "pendiente"


def status(state: ReleaseState) -> None:
    blue, green = state.blue, state.green
    print("Despliegues de Nexus (release.toml)\n")
    print(f"  blue   label {blue.label} · flags: {_flags(blue.flags)}")
    print(f"         cambios promocionados: {', '.join(blue.cambios) or 'ninguno'}")
    if green.cambio:
        cambio = CAMBIOS[green.cambio]
        print(f"  green  cambio {cambio.clave} ({cambio.autor}): {cambio.promesa}")
        print(
            f"         label {green.label} · flags: {_flags(green.flags)} · "
            f"tráfico {green.traffic} % ({_green_share(green.traffic)}) · "
            f"puerta: {green.puerta or 'sin pasar'}"
        )
    else:
        print("  green  sin cambio (todo el tráfico va a blue)")

    print("\nCambios:")
    for clave, cambio in CAMBIOS.items():
        print(f"  {clave}  {cambio.autor:<6} {cambio.promesa:<56} {_cambio_estado(state, clave)}")

    print("\nPuerta (media mínima en el dataset agente):")
    print("  " + ", ".join(f"{name} ≥ {value:g}" for name, value in state.gate.items()))

    if state.historial:
        print("\nÚltimos pasos:")
        for evento in state.historial[-6:]:
            detalle = f"  {evento.detalle}" if evento.detalle else ""
            print(f"  {evento.fecha}  {evento.accion:<8} {evento.cambio or '-'}{detalle}")


# --- prepare -------------------------------------------------------------------


def prepare(state: ReleaseState, clave: str, langfuse: Any) -> ReleaseState:
    """Publica el prompt del cambio con el label green y lo deja en green al 0 %."""

    clave = clave.upper()
    if clave not in CAMBIOS:
        _fail(f"No existe el cambio {clave}. Cambios: {', '.join(CAMBIOS)}.")
    cambio = CAMBIOS[clave]
    green = state.green
    if green.cambio and green.traffic > 0:
        _fail(
            f"Green tiene el {green.traffic} % del tráfico con el cambio {green.cambio}. "
            "Termina antes: uv run release rollback o uv run release promote."
        )
    if clave in state.blue.cambios:
        _fail(f"El cambio {clave} ya está en producción.")

    production = langfuse.get_prompt(
        EXECUTOR_PROMPT_NAME, type="chat", label=state.blue.label, cache_ttl_seconds=0
    )
    try:
        messages = cambio.messages(production.prompt[0]["content"])
    except CambioError as error:
        _fail(str(error))
    definition = PROMPTS_BY_NAME[EXECUTOR_PROMPT_NAME]
    created = langfuse.create_prompt(
        name=EXECUTOR_PROMPT_NAME,
        prompt=messages,
        type="chat",
        labels=[green.label],
        tags=definition.tags,
        config=production.config or definition.config,
        commit_message=f"Cambio {clave} ({cambio.autor}): {cambio.promesa}",
    )
    version = int(created.version)
    # El resto de prompts no cambia: green usa la misma versión que production.
    others = []
    for prompt in PROMPTS:
        if prompt.name == EXECUTOR_PROMPT_NAME:
            continue
        current = langfuse.get_prompt(
            prompt.name, type="chat", label=state.blue.label, cache_ttl_seconds=0
        )
        langfuse.update_prompt(
            name=prompt.name, version=int(current.version), new_labels=[green.label]
        )
        others.append(f"{prompt.name} v{current.version}")

    if green.cambio and green.cambio != clave:
        print(f"El cambio {green.cambio} sale de green (no tenía tráfico).")
    new_green = Green(
        cambio=clave, label=green.label, flags=state.blue.flags | cambio.flags, traffic=0
    )
    new_state = replace(state, green=new_green).with_event(
        "prepare", clave, f"{EXECUTOR_PROMPT_NAME} v{version}"
    )

    print(f"Cambio {clave} ({cambio.autor}): {cambio.promesa}")
    print(f"  {cambio.detalle}")
    print(f"  Publicado {EXECUTOR_PROMPT_NAME} v{version} con el label {green.label}.")
    if others:
        print(f"  Green usa también {', '.join(others)} (los mismos que production).")
    print(f"  Flags de green: {_flags(new_green.flags)} · tráfico 0 %")
    print("\nSiguiente paso, la puerta: uv run release gate")
    return new_state


# --- gate ----------------------------------------------------------------------


def gate(state: ReleaseState, extra: Sequence[str]) -> None:
    """Ejecuta el experimento de la puerta sobre green (sale con error si no pasa)."""

    clave = _require_green(state)
    from evaluation.experiment import main as experiment

    print(f"Puerta del cambio {clave}: experimento sobre el dataset agente.\n")
    experiment(["agente", "--release", "green", "--gate", "--sin-llm", *extra])


# --- shift, rollback y promote ---------------------------------------------------


def shift(state: ReleaseState, percent: int, *, forzar: bool = False) -> ReleaseState:
    clave = _require_green(state)
    green = state.green
    if not 0 <= percent <= 100:
        _fail("El porcentaje tiene que estar entre 0 y 100.")
    if percent > 0 and green.puerta != "superada" and not forzar:
        estado = "no ha superado" if green.puerta == "fallida" else "todavía no ha pasado"
        _fail(
            f"El cambio {clave} {estado} la puerta: uv run release gate. "
            "(--forzar lo sube igualmente, bajo tu responsabilidad.)"
        )
    new_state = replace(state, green=replace(green, traffic=percent)).with_event(
        "shift", clave, f"{green.traffic} % → {percent} %"
    )
    print(
        f"Green (cambio {clave}): {green.traffic} % → {percent} % del tráfico "
        f"({_green_share(percent)})."
    )
    if percent > 0:
        print("\nSiguiente paso: uv run simulate --n 40 y mira el dashboard, por release.")
    return new_state


def rollback(state: ReleaseState, motivo: str | None) -> ReleaseState:
    clave = _require_green(state)
    green = state.green
    new_state = replace(state, green=replace(green, traffic=0)).with_event(
        "rollback", clave, motivo or "(sin motivo)"
    )
    print(f"Rollback del cambio {clave}: green pasa del {green.traffic} % al 0 %.")
    print("Todo el tráfico vuelve a blue. El cambio sigue en green para que lo corrijas.")
    if not motivo:
        print('Apunta el motivo la próxima vez: uv run release rollback --motivo "…"')
    print(
        "\nAl corregirlo: si el arreglo está en el prompt, uv run release prepare "
        f"{clave}; si está en el código, vuelve a pasar la puerta (uv run release gate)."
    )
    return new_state


def promote(
    state: ReleaseState, motivo: str | None, langfuse: Any, *, forzar: bool = False
) -> ReleaseState:
    """Los prompts de green pasan a production y los flags de green, a blue."""

    clave = _require_green(state)
    green = state.green
    if green.puerta != "superada" and not forzar:
        _fail(
            f"El cambio {clave} no ha superado la puerta: uv run release gate. "
            "(--forzar lo promociona igualmente.)"
        )
    if green.traffic < 100:
        print(f"Aviso: promocionas el cambio {clave} con green al {green.traffic} %.")

    moved = []
    for prompt in PROMPTS:
        current = langfuse.get_prompt(
            prompt.name, type="chat", label=green.label, cache_ttl_seconds=0
        )
        langfuse.update_prompt(
            name=prompt.name, version=int(current.version), new_labels=[state.blue.label]
        )
        moved.append(f"{prompt.name} v{current.version}")

    blue = replace(state.blue, flags=green.flags, cambios=(*state.blue.cambios, clave))
    new_state = replace(state, blue=blue, green=Green(label=green.label)).with_event(
        "promote", clave, motivo or "(sin motivo)"
    )
    print(f"Cambio {clave} promocionado: ahora es blue.")
    print(f"  Label {state.blue.label} → {', '.join(moved)}")
    print(f"  Flags de blue: {_flags(blue.flags)}")
    print("  Green queda libre para el siguiente cambio.")
    return new_state


# --- Entrada de uv run release -------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release", description="Despliegue de Nexus por fases (blue/green con canary)."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")
    commands.add_parser("status", help="Qué hay en blue y en green.")
    prepare_cmd = commands.add_parser("prepare", help="Publica un cambio en green (al 0 %%).")
    prepare_cmd.add_argument("cambio", help=f"Uno de: {', '.join(CAMBIOS)}.")
    gate_cmd = commands.add_parser("gate", help="La puerta: experimento sobre green.")
    gate_cmd.add_argument("--repeat", type=int, help="Repite el experimento N veces.")
    gate_cmd.add_argument(
        "--concurrencia", type=int, default=CONCURRENCIA, help=f"Casos a la vez ({CONCURRENCIA})."
    )
    shift_cmd = commands.add_parser("shift", help="Porcentaje de viajeros que van a green.")
    shift_cmd.add_argument("percent", type=int, metavar="PORCENTAJE", help="De 0 a 100.")
    shift_cmd.add_argument("--forzar", action="store_true", help="Sin haber pasado la puerta.")
    rollback_cmd = commands.add_parser("rollback", help="Green vuelve al 0 %% del tráfico.")
    rollback_cmd.add_argument("--motivo", help="Por qué se vuelve atrás.")
    promote_cmd = commands.add_parser("promote", help="Green pasa a ser blue (production).")
    promote_cmd.add_argument("--motivo", help="Por qué se promociona.")
    promote_cmd.add_argument("--forzar", action="store_true", help="Sin haber pasado la puerta.")
    return parser


def release(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    state = load_state()
    match args.command:
        case "status":
            status(state)
        case "prepare":
            langfuse = _langfuse()
            save_state(prepare(state, args.cambio, langfuse))
            langfuse.flush()
        case "gate":
            extra = [
                f"--{name}={value}"
                for name in ("repeat", "concurrencia")
                if (value := getattr(args, name)) is not None
            ]
            gate(state, extra)
        case "shift":
            save_state(shift(state, args.percent, forzar=args.forzar))
        case "rollback":
            save_state(rollback(state, args.motivo))
        case "promote":
            langfuse = _langfuse()
            save_state(promote(state, args.motivo, langfuse, forzar=args.forzar))
            langfuse.flush()


# --- Entrada de uv run simulate ------------------------------------------------


def p95(values: Sequence[float]) -> float:
    """El percentil 95 por rango: el valor que deja por debajo al 95 % de los demás."""

    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else 0.0


def _release_order(name: str) -> tuple[int, str]:
    return ({"blue": 0, "green": 1}.get(name, 2), name)


def summarize(results: Sequence[SimResult]) -> list[dict[str, Any]]:
    """Una fila por release: conversaciones, valoración, latencia, errores y tools."""

    rows = []
    releases = sorted({result.assignment.release for result in results}, key=_release_order)
    for name in releases:
        group = [result for result in results if result.assignment.release == name]
        rated = [result.feedback for result in group if result.feedback is not None]
        latencies = [result.latency_s for result in group]
        rows.append(
            {
                "release": name,
                "conversaciones": len(group),
                "valoradas": len(rated),
                "pulgar_arriba": (100 * sum(rated) / len(rated)) if rated else None,
                "latencia_media": sum(latencies) / len(latencies),
                "latencia_p95": p95(latencies),
                "errores": sum(1 for result in group if result.error),
                "tools_por_conv": sum(len(result.tool_calls) for result in group) / len(group),
            }
        )
    return rows


def format_summary(rows: list[dict[str, Any]]) -> str:
    lines = [
        f"  {'release':<8} {'conv.':>5} {'valor.':>6} {'% 👍':>6} {'lat. media':>10} "
        f"{'lat. p95':>9} {'errores':>7} {'tools/conv.':>11}"
    ]
    for row in rows:
        thumbs = "—" if row["pulgar_arriba"] is None else f"{row['pulgar_arriba']:.0f} %"
        lines.append(
            f"  {row['release']:<8} {row['conversaciones']:>5} {row['valoradas']:>6} "
            f"{thumbs:>6} {row['latencia_media']:>8.1f} s {row['latencia_p95']:>7.1f} s "
            f"{row['errores']:>7} {row['tools_por_conv']:>11.1f}"
        )
    return "\n".join(lines)


def simulate(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="simulate", description="Viajeros simulados hablando con Nexus (blue y green)."
    )
    parser.add_argument("--n", type=int, default=40, help="Conversaciones (por defecto: 40).")
    parser.add_argument("--seed", type=int, default=0, help="Semilla: qué viajeros y peticiones.")
    parser.add_argument(
        "--concurrencia",
        type=int,
        default=CONCURRENCIA,
        help=f"Conversaciones a la vez (por defecto: {CONCURRENCIA}).",
    )
    args = parser.parse_args(argv)

    from nexus.simulation import run_traffic

    state = load_state()
    green = state.green
    tags = ["simulacion"]
    if green.cambio and green.traffic > 0:
        tags.append(f"canary-{green.cambio}")
        print(f"Green: cambio {green.cambio} al {green.traffic} % ({_green_share(green.traffic)}).")
    else:
        print("Green sin tráfico: todas las conversaciones van a blue.")
    print(f"Simulando {args.n} conversaciones (semilla {args.seed})…\n")

    results = asyncio.run(
        run_traffic(
            args.n,
            assign=router(state),
            seed=args.seed,
            concurrency=args.concurrencia,
            environment="production",
            tags=tuple(tags),
        )
    )
    print(format_summary(summarize(results)))
    host = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")
    print(
        f"\nCompara blue y green en Langfuse ({host or 'http://localhost:3100'}): "
        f"Dashboards → «{DASHBOARD}», por release."
    )
    print("Mira también por segmento (idioma, categoría): un fallo pequeño se esconde en la media.")


# --- Entrada de uv run alarma (extra) --------------------------------------------

# Minutos hacia atrás en que se buscan llamadas al modelo.
MINUTOS_ALARMA = 15
# Segundos que se espera a que Langfuse registre la conversación provocada.
ESPERA_ALARMA_S = 90


def _llamadas_recientes(langfuse: Any, desde: datetime, trace_id: str | None = None) -> list[Any]:
    """Las llamadas al modelo (generations) de producción desde ``desde``."""

    from release.alarma import Llamada

    llamadas, cursor = [], None
    while True:
        respuesta = langfuse.api.observations.get_many(
            type="GENERATION",
            environment="production",
            from_start_time=desde,
            trace_id=trace_id,
            fields="core,basic,usage,trace_context",
            limit=1000,
            cursor=cursor,
        )
        for observacion in respuesta.data:
            uso = observacion.usage_details or {}
            llamadas.append(
                Llamada(
                    trace_id=observacion.trace_id,
                    release=observacion.release or "",
                    tokens_entrada=int(uso.get("input", 0)),
                    tokens_salida=int(uso.get("output", 0)),
                    inicio=observacion.start_time,
                )
            )
        cursor = respuesta.meta.cursor
        if not respuesta.data or not cursor:
            return llamadas


def _provocar(state: ReleaseState, langfuse: Any) -> str | None:
    """Un viajero pega en el chat un texto enorme y pregunta: una llamada que se pasa."""

    from uuid import uuid4

    from nexus.graph import build_graph
    from nexus.rag.documents import DOCS_DIR
    from nexus.simulation.modelo import Guion, guion_scope, instalar
    from nexus.simulation.scenarios import scenarios
    from nexus.simulation.traffic import conversar

    instalar(latencia=True)
    base = next(s for s in scenarios(viajero="1001") if s.scenario_id == "nor-perro-es")
    # Unos 4 caracteres por token: el texto pegado pasa el umbral con holgura.
    caracteres = (int(state.alarma_tokens * 1.3) + 500) * 4
    normativa = (DOCS_DIR / "normativa-viajeros-2026.md").read_text(encoding="utf-8")
    pegado = ((normativa + "\n\n") * (caracteres // len(normativa) + 1))[:caracteres]
    mensaje = f"{pegado}\n\nLo he copiado de la web y no me aclaro. {base.mensaje}"
    scenario = replace(base, mensaje=mensaje)
    assignment = router(state)(scenario.viajero)
    thread_id = uuid4().hex
    with guion_scope(Guion(scenario, thread_id)):
        resultado = asyncio.run(
            conversar(
                build_graph(flags=assignment.flags),
                scenario,
                assignment,
                thread_id=thread_id,
                environment="production",
                tags=("alarma",),
            )
        )
    langfuse.flush()
    return resultado.trace_id


def _url_traza(langfuse: Any, trace_id: str) -> str:
    try:
        return str(langfuse.get_trace_url(trace_id=trace_id))
    except Exception:  # noqa: BLE001 - sin URL, basta con el id
        return trace_id


def alarma(argv: list[str] | None = None) -> None:
    """``uv run alarma``: el extra del capítulo 5, una alarma de tokens por llamada."""

    parser = argparse.ArgumentParser(
        prog="alarma", description="Alarma de tokens: llamadas al modelo que superan un umbral."
    )
    parser.add_argument(
        "--umbral", type=int, metavar="TOKENS", help="Guarda el umbral en release.toml y sale."
    )
    parser.add_argument(
        "--minutos",
        type=int,
        default=MINUTOS_ALARMA,
        help=f"Mira las llamadas de los últimos N minutos (por defecto: {MINUTOS_ALARMA}).",
    )
    parser.add_argument(
        "--provocar",
        action="store_true",
        help="Antes de mirar, un viajero pega un texto enorme: la alarma tiene que saltar.",
    )
    args = parser.parse_args(argv)
    state = load_state()

    if args.umbral is not None:
        if args.umbral < 0:
            _fail("El umbral es un número de tokens: 0 o más (0 apaga la alarma).")
        save_state(replace(state, alarma_tokens=args.umbral))
        apagada = " (alarma apagada)" if args.umbral == 0 else ""
        print(f"Umbral de la alarma: {args.umbral} tokens por llamada{apagada}.")
        print("Guardado en release.toml, sección [alarma].")
        return
    umbral = state.alarma_tokens
    if umbral <= 0:
        _fail(
            "La alarma no tiene umbral. Elígelo antes de mirar los datos: "
            "uv run alarma --umbral <tokens>"
        )

    from release.alarma import llamadas_en_alarma

    langfuse = _langfuse()
    desde = datetime.now(UTC) - timedelta(minutes=args.minutos)
    if args.provocar:
        print("Provocando la alarma: un viajero pega en el chat la normativa entera…")
        trace_id = _provocar(state, langfuse)
        if trace_id is None:
            _fail("La conversación provocada falló: mira el error en Langfuse.")
        print(f"  Conversación {trace_id}. Esperando a que Langfuse la registre…")
        limite = time.monotonic() + ESPERA_ALARMA_S
        while not _llamadas_recientes(langfuse, desde, trace_id):
            if time.monotonic() > limite:
                _fail("Langfuse aún no tiene la conversación: vuelve a probar con uv run alarma.")
            time.sleep(2)
        print()

    llamadas = _llamadas_recientes(langfuse, desde)
    try:
        en_alarma = llamadas_en_alarma(llamadas, umbral)
    except NotImplementedError as error:
        _fail(f"{error} Está en release/alarma.py.")
    print(
        f"Umbral: más de {umbral} tokens por llamada. Llamadas al modelo en los últimos "
        f"{args.minutos} minutos: {len(llamadas)}."
    )
    if not en_alarma:
        print("✔ Ninguna llamada supera el umbral.")
        return
    print(f"\n🚨 ALARMA: {len(en_alarma)} llamada(s) con más de {umbral} tokens.\n")
    print(f"  {'hora':<8} {'release':<8} {'tokens':>8}  traza")
    for llamada in en_alarma[:10]:
        hora = llamada.inicio.astimezone().strftime("%H:%M:%S")
        url = _url_traza(langfuse, llamada.trace_id)
        print(f"  {hora:<8} {llamada.release or '-':<8} {llamada.tokens:>8}  {url}")
    if len(en_alarma) > 10:
        print(f"  … y {len(en_alarma) - 10} más.")
    # Sale con error: así un cron o un pipeline puede avisar a alguien.
    sys.exit(1)
