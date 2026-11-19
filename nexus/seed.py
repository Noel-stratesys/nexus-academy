"""Carga en Langfuse el historial de tres semanas de Nexus (``uv run seed``).

    uv run seed              # prompts, datasets, dashboard e historial (lo que falte)
    uv run seed --forzar     # borra el historial de Langfuse y lo vuelve a cargar entero
    uv run seed --resumen    # calcula el historial y enseña sus números, sin enviar nada

Deja en el proyecto de Langfuse:

1. Los prompts del historial: el orquestador (v1) y los dos executors de la prueba A/B,
   el de Marc (v1, label ``marc``) y el de Jordi (v2, label ``jordi``). Ninguna versión
   del executor lleva ``production``: elegirla es la misión del capítulo 1. Si un prompt
   ya tiene el label ``production`` en otra versión, no se lo quita.
2. Los datasets de evaluación (``evaluation/datasets``).
3. El dashboard «Nexus en producción» y las 10 trazas del capítulo 3 para calibrar los
   jueces (etiqueta ``cap3``), si faltan. ``--forzar`` no las toca, porque llevan las
   anotaciones del alumno; para reponerlas: ``uv run trazas-cap3 --forzar``.
4. Las conversaciones del 26 de octubre al 15 de noviembre de 2026, con las valoraciones
   de los viajeros (score ``user_feedback``).

El historial no llama a ningún modelo: ejecuta Nexus con un modelo con guion
(``nexus.simulation.modelo``) y reescribe cada traza en su fecha
(``nexus.simulation.trazas``). Sale siempre igual, así que se puede repetir: los días que
ya están en Langfuse no se vuelven a enviar, y un día que se quedó a medias se borra y se
envía de nuevo. Solo toca las trazas del historial, nunca las tuyas.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nexus.settings import initialize_environment

ENTORNO = "production"
FEEDBACK_SCORE = "user_feedback"
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _escribir(texto: str = "") -> None:
    print(texto, flush=True)


# --- prompts -------------------------------------------------------------------------


def _con_label(langfuse: Any, name: str, label: str) -> bool:
    response = langfuse.api.prompts.list(name=name, limit=50)
    return any(meta.name == name and label in meta.labels for meta in response.data)


def _prompts_en_langfuse(langfuse: Any) -> dict[str, dict[str, int]]:
    """Deja las versiones del historial en Langfuse y devuelve las de cada release."""

    from nexus.prompts.versions import CANONICAL_VERSIONS, ensure_versions
    from nexus.simulation.historial import VERSIONES

    ya_en_produccion = {
        name
        for name in {canonical.name for canonical in CANONICAL_VERSIONS}
        if _con_label(langfuse, name, "production")
    }
    versiones = [
        replace(
            canonical,
            labels=tuple(
                label
                for label in canonical.labels
                if label != "production" or canonical.name not in ya_en_produccion
            ),
        )
        for canonical in CANONICAL_VERSIONS
    ]
    reales = {
        (name, canonica): real
        for (name, real), canonica in ensure_versions(langfuse, versiones, report=_escribir).items()
    }
    return {
        release: {name: reales[(name, canonica)] for name, canonica in prompts.items()}
        for release, prompts in VERSIONES.items()
    }


def prompt_del_historial(name: str, *_: Any, version: int | None = None, **__: Any) -> Any:
    """Un ``get_prompt`` que sirve las versiones canónicas del historial desde el código."""

    from langfuse.api import Prompt_Chat
    from langfuse.model import ChatPromptClient

    from nexus.prompts.versions import CANONICAL_VERSIONS

    canonical = next(
        canonical
        for canonical in CANONICAL_VERSIONS
        if canonical.name == name and canonical.version == (version or 1)
    )
    prompt = Prompt_Chat(
        name=name,
        prompt=canonical.definition.messages,  # type: ignore[arg-type]
        type="chat",
        version=canonical.version,
        config=canonical.definition.config,
        labels=list(canonical.labels),
        tags=[],
    )
    return ChatPromptClient(prompt=prompt)


def _prompts_locales() -> dict[str, dict[str, int]]:
    """Para ``--resumen``: los prompts del historial salen del código, no de Langfuse."""

    from nexus.llm.langfuse_client import langfuse as cliente_de_nexus
    from nexus.simulation.historial import VERSIONES

    # get_client() devuelve otro objeto (con los mismos recursos): hay que cambiar el suyo.
    cliente_de_nexus.get_prompt = prompt_del_historial  # type: ignore[method-assign]
    return VERSIONES


# --- el historial --------------------------------------------------------------------


@dataclass
class Registro:
    """Lo que pasó en una conversación del historial, ya en su fecha."""

    conversacion: Any
    resultado: Any
    trace_id: str
    duracion_s: float
    tokens: int
    feedback: int | None
    derogada: bool


def _ya_cargada(langfuse: Any, trace_id: str) -> bool:
    respuesta = langfuse.api.observations.get_many(
        trace_id=trace_id, is_root_observation=True, fields="core", limit=1
    )
    return bool(respuesta.data)


def _cargadas(langfuse: Any, trace_ids: set[str]) -> int:
    """Cuántas de las trazas ``trace_ids`` del historial están en Langfuse."""

    from nexus.simulation.historial import CET, PRIMER_DIA, ULTIMO_DIA

    desde = datetime.combine(PRIMER_DIA, datetime.min.time(), CET)
    hasta = datetime.combine(ULTIMO_DIA + timedelta(days=1), datetime.min.time(), CET)
    cargadas, cursor = 0, None
    while True:
        respuesta = langfuse.api.observations.get_many(
            is_root_observation=True,
            fields="core",
            environment=ENTORNO,
            from_start_time=desde,
            to_start_time=hasta,
            limit=1000,
            cursor=cursor,
        )
        cargadas += sum(1 for observacion in respuesta.data if observacion.trace_id in trace_ids)
        cursor = respuesta.meta.cursor
        if not respuesta.data or not cursor:
            return cargadas


def _borrar(langfuse: Any, trace_ids: Sequence[str], espera_maxima_s: float = 600) -> None:
    """Borra de Langfuse esas trazas (con sus valoraciones) y espera a que no estén.

    Langfuse borra en segundo plano: lo que se enviara antes de que acabe se borraría también.
    """

    for inicio in range(0, len(trace_ids), 100):
        langfuse.api.trace.delete_multiple(trace_ids=list(trace_ids[inicio : inicio + 100]))
    muestra = trace_ids[:: max(1, len(trace_ids) // 10)]
    limite = time.monotonic() + espera_maxima_s
    while _cargadas(langfuse, set(trace_ids)) or any(
        langfuse.api.scores.get_many(trace_id=trace_id, limit=1).data for trace_id in muestra
    ):
        if time.monotonic() > limite:
            sys.exit(
                "✘ Langfuse no ha terminado de borrar el historial anterior. Espera unos "
                "minutos y vuelve a lanzar: uv run seed --forzar"
            )
        time.sleep(5)


def _tokens(spans: Sequence[Any]) -> int:
    total = 0
    for span in spans:
        uso = (span.attributes or {}).get("langfuse.observation.usage_details")
        if uso:
            total += int(json.loads(str(uso)).get("total", 0))
    return total


def _cita_derogada(tool_calls: Sequence[dict[str, Any]]) -> bool:
    """Si el primer fragmento que recuperó ``buscar_normativa`` es de normativa derogada."""

    from nexus.rag.documents import load_documents
    from nexus.simulation.modelo import leer_resultado

    vigentes = {document.doc_id: document.vigente for document in load_documents()}
    for call in tool_calls:
        if call["name"] == "buscar_normativa":
            fragmentos = leer_resultado(call.get("result")).get("fragmentos") or []
            if fragmentos and not vigentes.get(str(fragmentos[0]["id"]).split("#")[0], True):
                return True
    return False


def _calendario_cambia_el_dato(registro: Registro) -> bool:
    """Si la fecha equivocada cambió el dato que buscaba el viajero (hora o incidencias)."""

    from nexus.simulation.modelo import leer_resultado

    scenario = registro.conversacion.scenario
    verdad = scenario.expected["verdad"]
    resultados = [leer_resultado(call.get("result")) for call in registro.resultado.tool_calls]
    if scenario.categoria == "horarios":
        clave = "frecuencia_min" if verdad["dato"] == "frecuencia" else verdad["dato"]
        return resultados[0].get(clave) != verdad["horario"].get(clave)
    if scenario.categoria == "incidencias":
        vistas = {inc["id"] for datos in resultados for inc in datos.get("incidencias", [])}
        return vistas != set(verdad["incidencias"])
    return False


async def _historial(
    langfuse: Any, buffer: Any, versiones: dict[str, dict[str, int]], *, enviar: bool, forzar: bool
) -> list[Registro]:
    from nexus.graph import build_graph
    from nexus.settings import Models, RagSettings
    from nexus.simulation.feedback import comentario_for, feedback_for
    from nexus.simulation.historial import plan_historial
    from nexus.simulation.modelo import Guion, guion_scope, instalar
    from nexus.simulation.traffic import conversar
    from nexus.simulation.trazas import (
        agrupar_por_traza,
        exportador_langfuse,
        exportar,
        rehacer_traza,
        trace_id_de,
    )

    instalar()
    graph = build_graph()
    exportador = exportador_langfuse() if enviar else None
    plan = plan_historial()
    por_dia: dict[Any, list[Any]] = defaultdict(list)
    for conversacion in plan:
        por_dia[conversacion.dia].append(conversacion)

    if enviar and forzar:
        _escribir("  Borrando el historial que ya había (tarda un par de minutos)…")
        _borrar(langfuse, [trace_id_de(conversacion.clave) for conversacion in plan])

    registros: list[Registro] = []
    for dia, conversaciones in sorted(por_dia.items()):
        etiqueta = f"{DIAS_SEMANA[dia.weekday()]} {dia.day:>2}/{dia.month:02d}"
        del_dia = [trace_id_de(conversacion.clave) for conversacion in conversaciones]
        if enviar and not forzar:
            # La última conversación del día se envía la última: si está, está el día entero.
            if _ya_cargada(langfuse, del_dia[-1]):
                _escribir(f"  {etiqueta}: ya estaba ({len(conversaciones)} conversaciones)")
                continue
            if _ya_cargada(langfuse, del_dia[0]):
                _escribir(
                    f"  {etiqueta}: se quedó a medias; borro lo que llegó (tarda un par de "
                    "minutos)…"
                )
                _borrar(langfuse, del_dia)

        resultados = []
        for conversacion in conversaciones:
            guion = Guion(
                conversacion.scenario,
                conversacion.clave,
                inventa=conversacion.inventa,
                reintentos=conversacion.reintentos,
            )
            with guion_scope(guion):
                resultado = await conversar(
                    graph,
                    conversacion.scenario,
                    conversacion.assignment,
                    thread_id=conversacion.thread_id,
                    environment=ENTORNO,
                    versions=versiones[conversacion.assignment.release],
                    # El historial es el mismo para todos, con o sin cambios en el .env.
                    models=Models(),
                    rag=RagSettings(),
                )
            if resultado.error or not resultado.trace_id:
                raise RuntimeError(
                    f"La conversación {conversacion.clave} ({conversacion.scenario.scenario_id}) "
                    f"ha fallado: {resultado.error}"
                )
            resultados.append((conversacion, resultado))

        langfuse.flush()
        trazas = agrupar_por_traza(buffer.take())
        spans_del_dia = []
        for conversacion, resultado in resultados:
            trace_id, spans = rehacer_traza(
                trazas.pop(int(resultado.trace_id, 16)),
                semilla=conversacion.clave,
                inicio=conversacion.inicio,
            )
            # rehacer_traza pone inicio y fin a todos los spans.
            inicio = min(span.start_time or 0 for span in spans)
            fin = max(span.end_time or 0 for span in spans)
            if conversacion.historia:
                feedback, comentario = conversacion.valoracion, None
            else:
                feedback = feedback_for(
                    conversacion.scenario,
                    resultado.answer,
                    resultado.tool_calls,
                    semilla=conversacion.clave,
                )
                comentario = comentario_for(
                    conversacion.scenario,
                    resultado.answer,
                    resultado.tool_calls,
                    feedback,
                    semilla=conversacion.clave,
                )
            if enviar and feedback is not None:
                espera = 5 + int(trace_id[:4], 16) % 55
                langfuse.create_score(
                    name=FEEDBACK_SCORE,
                    value=feedback,
                    trace_id=trace_id,
                    score_id=str(uuid5(NAMESPACE_URL, f"nexus-historial/{conversacion.clave}")),
                    data_type="NUMERIC",
                    comment=comentario,
                    # Para filtrar los comentarios en la tabla Scores por categoría y versión.
                    metadata={
                        "categoria": conversacion.scenario.categoria,
                        "release": conversacion.assignment.release,
                    },
                    environment=ENTORNO,
                    timestamp=datetime.fromtimestamp(fin / 1e9, UTC) + timedelta(seconds=espera),
                )
            spans_del_dia.extend(spans)
            registros.append(
                Registro(
                    conversacion=conversacion,
                    resultado=resultado,
                    trace_id=trace_id,
                    duracion_s=(fin - inicio) / 1e9,
                    tokens=_tokens(spans),
                    feedback=feedback,
                    derogada=_cita_derogada(resultado.tool_calls),
                )
            )
        if enviar and exportador is not None:
            langfuse.flush()
            exportar(exportador, spans_del_dia)
        valoradas = [r.feedback for r in registros[-len(resultados) :] if r.feedback is not None]
        pulgar = f"{100 * sum(valoradas) / len(valoradas):.0f} % 👍" if valoradas else "—"
        accion = "enviado" if enviar else "calculado"
        _escribir(f"  {etiqueta}: {len(resultados)} conversaciones, {pulgar} · {accion}")
    if exportador is not None:
        exportador.shutdown()
    return registros


# --- el resumen ----------------------------------------------------------------------


def _pct(valores: Sequence[int]) -> str:
    return f"{100 * sum(valores) / len(valores):.0f} %" if valores else "—"


def _valoradas(registros: Sequence[Registro]) -> list[int]:
    return [r.feedback for r in registros if r.feedback is not None]


def _resumen(registros: Sequence[Registro]) -> None:
    from nexus.simulation.historial import BLUE, JORDI, MARC

    releases_ab = (MARC.release, JORDI.release)
    if not registros:
        return
    viajeros = {r.conversacion.scenario.viajero for r in registros}
    _escribir(
        f"\nHistorial: {len(registros)} conversaciones de {len(viajeros)} viajeros, "
        f"{len(_valoradas(registros))} valoradas, {_pct(_valoradas(registros))} 👍."
    )

    prueba = [r for r in registros if r.conversacion.assignment.release in releases_ab]
    if prueba:
        _escribir("\nPrueba A/B de la primera semana (% 👍 de las valoradas):")
        categorias = sorted({r.conversacion.scenario.categoria for r in prueba})
        cabecera = "  " + f"{'':<18}" + "".join(f"{release:>14}" for release in releases_ab)
        _escribir(cabecera)
        filas = [("total", None), *((categoria, categoria) for categoria in categorias)]
        for nombre, categoria in filas:
            celdas = []
            for release in releases_ab:
                grupo = [
                    r
                    for r in prueba
                    if r.conversacion.assignment.release == release
                    and (categoria is None or r.conversacion.scenario.categoria == categoria)
                ]
                valoradas = _valoradas(grupo)
                celdas.append(f"{_pct(valoradas)} ({len(valoradas)}/{len(grupo)})")
            _escribir("  " + f"{nombre:<18}" + "".join(f"{celda:>14}" for celda in celdas))
        tokens = {
            release: [r.tokens for r in prueba if r.conversacion.assignment.release == release]
            for release in releases_ab
        }
        _escribir(
            "  tokens por conversación: "
            + ", ".join(
                f"{release} {sum(valores) / len(valores):.0f}"
                for release, valores in tokens.items()
                if valores
            )
        )

    v2_horarios = [
        r
        for r in registros
        if r.conversacion.assignment.release in (JORDI.release, BLUE.release)
        and r.conversacion.scenario.categoria == "horarios"
    ]
    sin_tool = [r for r in v2_horarios if not r.resultado.tool_calls]
    _escribir(
        f"\nExecutor v2, horarios sin consultar la herramienta: {len(sin_tool)} de "
        f"{len(v2_horarios)}, {_pct(_valoradas(sin_tool))} 👍."
    )

    dia_de_la_semana = [
        r
        for r in registros
        if r.conversacion.scenario.expected.get("verdad", {}).get("afectado_por_calendario")
        and r.resultado.tool_calls
    ]
    cambiadas = [r for r in dia_de_la_semana if _calendario_cambia_el_dato(r)]
    _escribir(
        f"Fallo del calendario: {len(dia_de_la_semana)} conversaciones consultaron un día de "
        f"la semana con la fecha equivocada; en {len(cambiadas)}, de "
        f"{len({r.conversacion.scenario.viajero for r in cambiadas})} viajeros, el dato de "
        f"la respuesta era de otro día ({_pct(_valoradas(cambiadas))} 👍)."
    )
    derogadas = [r for r in registros if r.derogada]
    _escribir(
        f"Normativa derogada en el primer fragmento: {len(derogadas)} conversaciones de "
        f"{len({r.conversacion.scenario.viajero for r in derogadas})} viajeros."
    )
    lenta = max(registros, key=lambda r: r.duracion_s)
    _escribir(
        f"La traza más lenta: {lenta.duracion_s:.0f} s ({lenta.conversacion.clave}, "
        f"{len(lenta.resultado.tool_calls)} llamadas a herramientas), traza {lenta.trace_id}."
    )
    from nexus.simulation.historial import CET

    historia = {r.conversacion.historia: r for r in registros if r.conversacion.historia}
    for nombre in ("pere", "marta", "lenta"):
        if nombre in historia:
            registro = historia[nombre]
            momento = registro.conversacion.inicio.astimezone(CET)
            _escribir(f"  Caso {nombre}: traza {registro.trace_id} ({momento:%d/%m %H:%M})")


# --- entrada -------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed", description="Carga en Langfuse el historial de tres semanas de Nexus."
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Borra el historial de Langfuse y lo vuelve a cargar entero.",
    )
    parser.add_argument(
        "--resumen",
        action="store_true",
        help="Calcula el historial y enseña sus números, sin enviar nada a Langfuse.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    initialize_environment()
    from langfuse import Langfuse

    from nexus.simulation.trazas import SpanBuffer

    # Las trazas del historial se capturan en memoria para reescribirlas en su fecha. Este
    # cliente se crea antes que el de Nexus (nexus.llm.langfuse_client), que lo reutiliza.
    buffer = SpanBuffer()
    langfuse = Langfuse(span_exporter=buffer)
    enviar = not args.resumen

    if enviar:
        try:
            autenticado = langfuse.auth_check()
        except Exception as error:
            sys.exit(f"✘ Langfuse no responde ({type(error).__name__}). ¿Está levantado?")
        if not autenticado:
            sys.exit("✘ Langfuse no acepta las claves del .env (LANGFUSE_PUBLIC_KEY/SECRET_KEY).")

        from evaluation.datasets import DATASETS, upload
        from evaluation.experimentos_grabados import cargar as cargar_experimentos
        from evaluation.trazas_cap3 import cargar as cargar_trazas_cap3
        from nexus.dashboard import ensure_dashboard

        _escribir("Prompts del historial:")
        versiones = _prompts_en_langfuse(langfuse)
        _escribir("\nDatasets:")
        for nombre, definition in DATASETS.items():
            _escribir(f"  {nombre}: {upload(definition, langfuse)} casos")
        _escribir("\nDashboard:")
        ensure_dashboard(langfuse, report=_escribir)
        _escribir("\nTrazas del capítulo 3 (para calibrar los jueces):")
        cargar_trazas_cap3(langfuse, buffer=buffer, report=_escribir)
        _escribir("\nExperimentos del capítulo 4 (dataset nexus/rag):")
        cargar_experimentos(langfuse, report=_escribir)
        _escribir("\nHistorial (26 de octubre – 15 de noviembre de 2026):")
    else:
        versiones = _prompts_locales()
        _escribir("Historial (sin enviar nada a Langfuse):")

    registros = asyncio.run(
        _historial(langfuse, buffer, versiones, enviar=enviar, forzar=args.forzar)
    )
    langfuse.flush()
    from nexus.simulation.historial import plan_historial

    if len(registros) == len(plan_historial()):
        _resumen(registros)
    if enviar:
        _escribir("\n✔ Listo. Comprueba la instalación con: uv run check 0")
