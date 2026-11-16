"""Tests del historial de Nexus (``uv run seed``), sin modelo y sin Langfuse."""

import json
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

import nexus.llm.models as models
from nexus.context import Context
from nexus.data import viajero
from nexus.graph import build_graph
from nexus.llm import langfuse_client
from nexus.llm.prompts import prompt_version_scope
from nexus.prompts.versions import EXECUTOR_JORDI, EXECUTOR_MARC
from nexus.seed import prompt_del_historial
from nexus.settings import Models, RagSettings
from nexus.simulation.feedback import contiene, feedback_for, probabilidad_de_pulgar_arriba
from nexus.simulation.historial import CET, FIN_PRUEBA_AB, VERSIONES, plan_historial
from nexus.simulation.modelo import CLASES_DE_PROVEEDOR, Guion, ModeloConGuion, _pasos, guion_scope
from nexus.simulation.modelo import instalar as instalar_modelo_con_guion
from nexus.simulation.scenarios import scenarios, story_scenarios
from nexus.simulation.trazas import ENTRADA, PASO, TIPO, USO, SpanBuffer, rehacer_traza, trace_id_de
from nexus.state import answer_text

HOY = date(2026, 11, 10)


def _escenario(categoria: str, idioma: str = "es") -> Any:
    return next(s for s in scenarios(HOY, categorias=[categoria]) if s.idioma == idioma)


# --- La valoración del viajero ------------------------------------------------------------


def test_contiene_ignores_accents_and_needs_whole_short_words() -> None:
    """«no» no está en «normativa», pero sí en «No, ...»; las tildes dan igual."""

    assert not contiene("no", "Consulta la normativa")
    assert contiene("no", "No, a esa hora no se puede.")
    assert contiene("sí", "Si, claro")
    assert contiene("05:04|5:04", "El primer tren pasa a las 5:04.")
    assert contiene("3 min", "Pasa cada 3 minutos.")


def test_feedback_rewards_answers_with_the_data_and_punishes_inventions() -> None:
    """Acertar puntúa más que fallar, y fallar de memoria (sin herramientas) aún menos."""

    scenario = _escenario("horarios")
    dato = scenario.expected["menciona"][0].split("|")[0]
    llamada = [{"name": "consultar_horario"}]

    acierta = probabilidad_de_pulgar_arriba(scenario, f"Pasa a las {dato}.", llamada)
    falla = probabilidad_de_pulgar_arriba(scenario, "Pasa a las 23:59.", llamada)
    inventa = probabilidad_de_pulgar_arriba(scenario, "Pasa a las 23:59.", [])
    rechaza = probabilidad_de_pulgar_arriba(scenario, "No he entendido tu consulta.", [])

    assert acierta > falla > inventa > rechaza
    assert probabilidad_de_pulgar_arriba(scenario, "The train leaves at 23:59, sorry.") < falla


def test_feedback_is_reproducible_and_not_everyone_rates() -> None:
    """La misma semilla da la misma valoración; valoran entre el 60 y el 80 %."""

    scenario = _escenario("tarifas")
    answer = "La T-10 de 1 zona cuesta 12,15 €."
    valoraciones = [feedback_for(scenario, answer, semilla=str(n)) for n in range(1000)]

    assert valoraciones == [feedback_for(scenario, answer, semilla=str(n)) for n in range(1000)]
    valoradas = [v for v in valoraciones if v is not None]
    assert 0.5 < len(valoradas) / len(valoraciones) < 0.9
    assert set(valoradas) == {0, 1}


def test_comments_explain_the_rating_in_the_travellers_language() -> None:
    """Un horario inventado se comenta como horario equivocado, en el idioma del viajero."""

    from nexus.simulation.feedback import COMENTARIOS, comentario_for

    scenario = _escenario("horarios")
    comentarios = {
        comentario_for(scenario, "Pasa a las 23:59.", [], 0, semilla=str(n)) for n in range(200)
    }

    assert comentario_for(scenario, "Pasa a las 23:59.", [], None) is None
    assert None in comentarios  # no todos comentan
    textos = COMENTARIOS[(0, "dato_mal/horarios")][scenario.idioma]
    assert comentarios - {None} <= set(textos)


# --- El plan del historial --------------------------------------------------------------------


def test_history_plan_is_always_the_same() -> None:
    """Dos llamadas dan las mismas conversaciones, en el mismo orden."""

    primero, segundo = plan_historial(), plan_historial()

    assert primero == segundo
    assert len({conversacion.clave for conversacion in primero}) == len(primero) == 653
    assert all(
        date(2026, 10, 26) <= conversacion.dia <= date(2026, 11, 15) for conversacion in primero
    )


def test_history_runs_the_ab_test_the_first_week_and_blue_afterwards() -> None:
    """La primera semana se reparte entre v1-marc y v2-jordi; luego todo es blue."""

    plan = plan_historial()
    prueba = Counter(c.assignment.release for c in plan if c.dia <= FIN_PRUEBA_AB)
    despues = {c.assignment.release for c in plan if c.dia > FIN_PRUEBA_AB}

    assert set(prueba) == {"v1-marc", "v2-jordi"}
    assert 0.4 < prueba["v1-marc"] / sum(prueba.values()) < 0.6
    assert despues == {"blue"}
    assert all(c.scenario.categoria == "horarios" for c in plan if c.inventa)


def test_history_includes_the_story_cases_at_their_time() -> None:
    """Marta, Pere y la consulta lenta están en su día y su hora de Vilaverda."""

    historia = {c.historia: c for c in plan_historial() if c.historia}

    momentos = {nombre: c.inicio.astimezone(CET) for nombre, c in historia.items()}
    assert momentos["marta"].replace(tzinfo=None) == datetime(2026, 11, 3, 8, 3, 41)
    assert momentos["pere"].replace(tzinfo=None) == datetime(2026, 11, 10, 7, 52, 18)
    assert momentos["lenta"].replace(tzinfo=None) == datetime(2026, 11, 11, 7, 41, 6)
    assert historia["lenta"].reintentos == 8
    assert {c.valoracion for c in historia.values()} == {0, 1}


# --- El modelo con guion ----------------------------------------------------------------------


def test_scripted_model_names_its_generations_like_the_provider() -> None:
    """Las generaciones del historial se llaman como la clase del proveedor (ChatGroq)."""

    modelo = ModeloConGuion(model_name="llama-3.3-70b-versatile", proveedor="groq")

    assert modelo.to_json()["id"] == CLASES_DE_PROVEEDOR["groq"]
    assert modelo._get_ls_params()["ls_provider"] == "groq"


def test_only_a_prompt_without_the_tool_rule_lets_the_model_invent_timetables() -> None:
    """Con el prompt de Jordi da horarios de memoria; con el de Marc, consulta la herramienta."""

    guion = Guion(_escenario("horarios"), "semilla", inventa=True)
    marc = str(EXECUTOR_MARC.messages[0]["content"])
    jordi = str(EXECUTOR_JORDI.messages[0]["content"])

    assert _pasos(guion, jordi) == []
    assert [[name for name, _ in paso] for paso in _pasos(guion, marc)] == [["consultar_horario"]]


def test_scripted_model_without_a_script_fails_clearly() -> None:
    modelo = ModeloConGuion(model_name="llama")

    with pytest.raises(RuntimeError, match="guion_scope"):
        modelo.invoke([HumanMessage("Hola")])


@pytest.fixture
def nexus_con_guion(monkeypatch: pytest.MonkeyPatch) -> Any:
    """El grafo de Nexus con el modelo con guion y los prompts del historial del código."""

    monkeypatch.setattr(models, "init_chat_model", models.init_chat_model)
    instalar_modelo_con_guion()
    monkeypatch.setattr(langfuse_client.langfuse, "get_prompt", prompt_del_historial)
    return build_graph()


async def _conversar(graph: Any, scenario: Any, release: str) -> tuple[str, list[dict[str, Any]]]:
    context = Context(
        viajero=viajero(scenario.viajero),  # type: ignore[arg-type]
        hoy=scenario.hoy,
        models=Models(),
        rag=RagSettings(),
    )
    with guion_scope(Guion(scenario, "test")), prompt_version_scope(VERSIONES[release]):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(scenario.mensaje)]},
            config={"configurable": {"thread_id": uuid4().hex}},
            context=context,
        )
    messages: Sequence[Any] = result["messages"]
    resultados = {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}
    llamadas = [
        {**call, "result": resultados.get(call["id"] or "")}
        for m in messages
        if isinstance(m, AIMessage)
        for call in m.tool_calls
    ]
    return answer_text(messages), llamadas


async def test_pere_gets_the_wrong_day_because_the_tool_gets_it_wrong(nexus_con_guion: Any) -> None:
    """El modelo repite lo que devuelve la herramienta: el «jueves» de Pere sale miércoles."""

    pere = story_scenarios()["pere"]

    answer, llamadas = await _conversar(nexus_con_guion, pere, "blue")

    assert [(c["name"], c["args"]) for c in llamadas] == [
        ("consultar_incidencias", {"dia": "jueves", "linea": "L3"})
    ]
    assert "miércoles 11 de noviembre" in str(llamadas[0]["result"])
    assert "normalidad" in answer and "INC-0301" not in answer
    assert answer.startswith("¡") and "Pere" in answer  # el tono cercano de Jordi


async def test_marc_answers_the_same_question_soberly(nexus_con_guion: Any) -> None:
    """Con el prompt de Marc, la misma respuesta sin saludo ni emojis."""

    pere = story_scenarios()["pere"]

    answer, _ = await _conversar(nexus_con_guion, pere, "v1-marc")

    assert answer.startswith("El jueves la L3 funciona con normalidad")
    assert "Pere" not in answer


# --- Las trazas en su fecha ------------------------------------------------------------------


def _traza_de_prueba() -> list[ReadableSpan]:
    """Una traza como las de Nexus: el modelo pide dos herramientas a la vez y contesta."""

    buffer = SpanBuffer()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(buffer))
    tracer = provider.get_tracer("test")
    uso = json.dumps({"input": 900, "output": 40})
    with tracer.start_as_current_span("nexus-agent", attributes={TIPO: "agent"}):
        with tracer.start_as_current_span("LangGraph", attributes={TIPO: "chain"}):
            with tracer.start_as_current_span(
                "ChatGroq", attributes={TIPO: "generation", USO: uso}
            ):
                pass
            for linea in ("L1", "L2"):
                with tracer.start_as_current_span("tools", attributes={TIPO: "chain", PASO: 2}):
                    with tracer.start_as_current_span(
                        "consultar_incidencias", attributes={TIPO: "tool", ENTRADA: linea}
                    ):
                        pass
            with tracer.start_as_current_span(
                "ChatGroq", attributes={TIPO: "generation", USO: uso}
            ):
                pass
    provider.shutdown()
    return buffer.take()


def _forma(spans: Sequence[ReadableSpan]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            s.name,
            s.context.span_id if s.context else None,
            s.parent.span_id if s.parent else None,
            s.start_time,
            s.end_time,
        )
        for s in spans
    )


def test_rewritten_trace_is_reproducible_and_starts_at_its_time() -> None:
    """La misma conversación da siempre los mismos identificadores y horas."""

    spans = _traza_de_prueba()
    inicio = datetime(2026, 11, 10, 7, 52, 18, tzinfo=CET)

    trace_hex, nuevos = rehacer_traza(spans, semilla="conv-1", inicio=inicio)
    _, otra_vez = rehacer_traza(_traza_de_prueba(), semilla="conv-1", inicio=inicio)
    _, otra_conversacion = rehacer_traza(spans, semilla="conv-2", inicio=inicio)

    assert trace_hex == trace_id_de("conv-1")
    assert _forma(nuevos) == _forma(otra_vez)
    assert {s.context.span_id for s in nuevos if s.context}.isdisjoint(
        {s.context.span_id for s in otra_conversacion if s.context}
    )
    raiz = next(s for s in nuevos if s.parent is None)
    assert raiz.start_time == int(inicio.timestamp()) * 1_000_000_000


def test_rewritten_trace_keeps_the_structure_and_runs_parallel_tools_together() -> None:
    """Cada observación cuelga de la misma, dentro de su tiempo; las tools en paralelo, a la vez."""

    spans = _traza_de_prueba()
    _, nuevos = rehacer_traza(spans, semilla="conv-1", inicio=datetime(2026, 11, 10, tzinfo=CET))

    def arbol(lista: Sequence[ReadableSpan]) -> Counter[tuple[str, str | None]]:
        nombres = {s.context.span_id: s.name for s in lista if s.context}
        return Counter((s.name, nombres.get(s.parent.span_id) if s.parent else None) for s in lista)

    def inicio(span: ReadableSpan) -> int:
        assert span.start_time is not None
        return span.start_time

    def fin(span: ReadableSpan) -> int:
        assert span.end_time is not None
        return span.end_time

    assert arbol(nuevos) == arbol(spans)
    por_id = {s.context.span_id: s for s in nuevos if s.context}
    for span in nuevos:
        if span.parent is not None:
            padre = por_id[span.parent.span_id]
            assert inicio(padre) <= inicio(span) <= fin(span) <= fin(padre)
    herramientas = sorted((s for s in nuevos if s.name == "tools"), key=inicio)
    respuesta = max((s for s in nuevos if s.name == "ChatGroq"), key=inicio)
    assert inicio(herramientas[1]) - inicio(herramientas[0]) < 1_000_000  # < 1 ms
    assert inicio(respuesta) >= max(fin(s) for s in herramientas)
