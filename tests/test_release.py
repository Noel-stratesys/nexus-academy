"""Tests de los despliegues por fases (capítulo 5), sin modelo y sin Langfuse."""

import argparse
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import nexus.simulation
from evaluation import experiment
from nexus.prompts import EXECUTOR_PROMPT_NAME, ORCHESTRATOR_PROMPT_NAME, PROMPTS
from nexus.simulation.types import Assignment, Scenario, SimResult
from nexus.tools import tools_for
from nexus.tools.proximos import panel_tiempo_real, proximos
from release import cli, state
from release.cambios import CAMBIOS, CODE_TEXT, REGLA_D, TONO_A, CambioError, code_prompt_with_a
from release.gate import check_gate, format_gate, gate_passed
from release.router import assign, bucket, router
from release.state import Blue, Evento, Green, ReleaseState, dump_state, load_state, parse_state

# --- Dobles ------------------------------------------------------------------------


class FakeLangfuse:
    """Langfuse en memoria: versiones de prompt con labels únicos por prompt."""

    def __init__(self) -> None:
        self.versions: dict[str, list[dict[str, Any]]] = {
            prompt.name: [
                {
                    "version": 1,
                    "labels": {"production"},
                    "prompt": prompt.messages,
                    "config": prompt.config,
                }
            ]
            for prompt in PROMPTS
        }
        self.flushed = False

    def _move(self, name: str, labels: list[str], target: dict[str, Any]) -> None:
        for version in self.versions[name]:
            version["labels"] -= set(labels)
        target["labels"] |= set(labels)

    def get_prompt(self, name: str, *, label: str, **_: Any) -> SimpleNamespace:
        for version in self.versions[name]:
            if label in version["labels"]:
                return SimpleNamespace(**version)
        raise LookupError(f"{name} no tiene el label {label}")

    def create_prompt(self, *, name: str, prompt: Any, labels: list[str], **kwargs: Any) -> Any:
        created = {
            "version": len(self.versions[name]) + 1,
            "labels": set(),
            "prompt": prompt,
            "config": kwargs.get("config"),
        }
        self.versions[name].append(created)
        self._move(name, labels, created)
        return SimpleNamespace(**created)

    def update_prompt(self, *, name: str, version: int, new_labels: list[str]) -> None:
        self._move(name, new_labels, self.versions[name][version - 1])

    def labels(self, name: str) -> dict[int, set[str]]:
        return {item["version"]: item["labels"] for item in self.versions[name]}

    def flush(self) -> None:
        self.flushed = True


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "release.toml"
    monkeypatch.setattr(state, "STATE_FILE", path)
    return path


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch) -> FakeLangfuse:
    fake = FakeLangfuse()
    monkeypatch.setattr(cli, "_langfuse", lambda: fake)
    return fake


def _with_green(cambio: str = "A", traffic: int = 0, puerta: str = "superada") -> ReleaseState:
    return ReleaseState(green=Green(cambio=cambio, traffic=traffic, puerta=puerta))


# --- Router --------------------------------------------------------------------------


def test_router_sends_each_traveler_always_to_the_same_bucket() -> None:
    """El mismo viajero cae siempre en el mismo cubo, entre 0 y 99."""

    assert bucket("1001") == bucket("1001")
    assert all(0 <= bucket(str(user)) < 100 for user in range(500))


def test_router_splits_traffic_close_to_the_percentage() -> None:
    """Con un 30 % de tráfico, cerca del 30 % de los viajeros va a green."""

    current = _with_green(traffic=30)
    greens = sum(assign(f"u{user}", current).release == "green" for user in range(2000))
    assert 500 <= greens <= 700


def test_raising_traffic_keeps_green_travelers_in_green() -> None:
    """Al pasar del 10 % al 50 %, quien ya estaba en green sigue en green."""

    users = [f"u{user}" for user in range(300)]
    at_10 = {user for user in users if assign(user, _with_green(traffic=10)).release == "green"}
    at_50 = {user for user in users if assign(user, _with_green(traffic=50)).release == "green"}
    assert at_10 and at_10 <= at_50


def test_router_uses_labels_and_flags_of_each_release() -> None:
    """Blue lee production con sus flags y green, el label green con los suyos."""

    current = ReleaseState(
        blue=Blue(flags=frozenset({"a"})),
        green=Green(cambio="D", flags=frozenset({"a", "proximos_trenes"}), traffic=100),
    )
    assert assign("1001", current) == Assignment(
        "green", "green", frozenset({"a", "proximos_trenes"})
    )
    assert router(replace(current, green=Green()))("1001") == Assignment(
        "blue", "production", frozenset({"a"})
    )


def test_router_without_change_in_green_sends_everyone_to_blue() -> None:
    """Sin cambio en green, nadie va a green aunque el tráfico diga otra cosa."""

    current = ReleaseState(green=Green(cambio="", traffic=100))
    assert {assign(f"u{user}", current).release for user in range(50)} == {"blue"}


# --- Estado ------------------------------------------------------------------------------


def test_state_survives_a_round_trip_through_toml(state_file: Path) -> None:
    """Lo que se guarda en release.toml se lee igual, con tildes y comillas."""

    original = ReleaseState(
        blue=Blue(flags=frozenset({"proximos_trenes"}), cambios=("A", "C")),
        green=Green(cambio="D", flags=frozenset({"proximos_trenes"}), traffic=50, puerta="ok"),
        gate={"sin_errores": 0.95, "evita_tools_prohibidas": 1.0},
        historial=(Evento("2026-11-20T15:00:00", "rollback", "C", 'cae el 👍 en "ca"\ny en'),),
    )
    state.save_state(original)

    assert load_state() == original
    assert parse_state({}) == ReleaseState()


def test_missing_state_file_means_the_initial_state(state_file: Path) -> None:
    """Sin release.toml, todo el tráfico va a blue y no hay cambio en green."""

    assert load_state() == ReleaseState()
    assert "traffic = 0" in dump_state(ReleaseState())


def test_state_rejects_traffic_out_of_range() -> None:
    """Un tráfico fuera de 0-100 es un error al leer el estado."""

    with pytest.raises(ValueError):
        parse_state({"green": {"traffic": 120}})


# --- Puerta --------------------------------------------------------------------------------


def test_gate_passes_only_when_every_score_reaches_its_minimum() -> None:
    """La puerta pasa si todas las medias llegan al mínimo; un score sin datos no pasa."""

    thresholds = {"sin_errores": 0.95, "evita_tools_prohibidas": 1.0}

    assert gate_passed(check_gate({"sin_errores": 1.0, "evita_tools_prohibidas": 1.0}, thresholds))
    failing = check_gate({"sin_errores": 1.0, "evita_tools_prohibidas": 0.67}, thresholds)
    assert not gate_passed(failing)
    assert "✘ no pasa" in format_gate(failing)
    missing = check_gate({"sin_errores": 1.0}, thresholds)
    assert not gate_passed(missing)
    assert "sin datos" in format_gate(missing)


def test_experiment_gate_records_the_result_in_green(state_file: Path) -> None:
    """--gate sobre green guarda en release.toml si la puerta se superó."""

    state.save_state(_with_green("B", puerta=""))
    args = argparse.Namespace(release="green")

    passed = experiment.apply_gate(
        args,
        [{"sin_errores": 1, "evita_tools_prohibidas": 0.5}, {"sin_errores": 1}],
        load_state(),
    )

    assert not passed
    saved = load_state()
    assert saved.green.puerta == "fallida"
    assert saved.historial[-1].accion == "puerta"


def test_experiment_release_option_uses_label_and_flags_of_green(state_file: Path) -> None:
    """--release green prueba el label green con los flags de green."""

    state.save_state(ReleaseState(green=Green(cambio="D", flags=frozenset({"proximos_trenes"}))))
    args = experiment.parse_args(["agente", "--release", "green", "--flag", "otra"])

    label, flags, variant = experiment.release_settings(args)

    assert label == "green"
    assert flags == {"proximos_trenes", "otra"}
    assert variant == "green-D"


def test_experiment_main_exits_with_error_when_the_gate_fails(
    state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uv run experiment agente --release green --gate sale con error si no pasa."""

    state.save_state(_with_green("B", puerta=""))
    monkeypatch.setattr(experiment, "run", lambda args: [{"sin_errores": 0.5}])

    with pytest.raises(SystemExit) as exit_info:
        experiment.main(["agente", "--release", "green", "--gate"])

    assert exit_info.value.code == 1


# --- Cambios ---------------------------------------------------------------------------------


def test_every_change_keeps_the_prompt_variables() -> None:
    """Todos los cambios conservan {{viajero}}, {{hoy}} y {{tool_catalog}}."""

    with_a = code_prompt_with_a()
    for cambio in CAMBIOS.values():
        text = cambio.executor_prompt(CODE_TEXT if cambio.clave == "A" else with_a)
        assert all(var in text for var in ("{{viajero}}", "{{hoy}}", "{{tool_catalog}}"))


def test_changes_b_c_and_d_are_built_on_top_of_a() -> None:
    """B, C y D necesitan el tono de A en producción."""

    for clave in "BCD":
        with pytest.raises(CambioError):
            CAMBIOS[clave].executor_prompt(CODE_TEXT)
    assert TONO_A in code_prompt_with_a()


def test_change_b_drops_the_refund_policy_rule() -> None:
    """B quita la regla de tramitar devoluciones solo si la normativa lo permite."""

    text = CAMBIOS["B"].executor_prompt(code_prompt_with_a())
    assert "Solo se tramita una devolución si la normativa la permite" not in text
    assert "solicitar_devolucion enseguida" in text


def test_change_c_is_at_least_30_percent_shorter() -> None:
    """El prompt corto de C ocupa al menos un 30 % menos que el de A."""

    with_a = code_prompt_with_a()
    assert len(CAMBIOS["C"].executor_prompt(with_a)) <= 0.7 * len(with_a)


def test_change_d_adds_the_tool_rule_and_flag_without_undoing_c() -> None:
    """D añade su regla y su flag, también sobre el prompt corto de C."""

    short = CAMBIOS["C"].executor_prompt(code_prompt_with_a())
    with_d = CAMBIOS["D"].executor_prompt(short)
    assert REGLA_D in with_d and with_d.startswith(short.partition("\n\nHerramientas")[0])
    assert CAMBIOS["D"].flags == {"proximos_trenes"}
    assert REGLA_D in CAMBIOS["C"].executor_prompt(with_d)


# --- Herramienta proximos_trenes --------------------------------------------------------------


def test_proximos_trenes_only_exists_with_its_flag() -> None:
    """proximos_trenes solo está en el catálogo con el flag proximos_trenes."""

    assert "proximos_trenes" not in {tool.name for tool in tools_for()}
    assert "proximos_trenes" in {tool.name for tool in tools_for(frozenset({"proximos_trenes"}))}


def test_proximos_trenes_rejects_unknown_lines_and_stations() -> None:
    """Una línea que no existe o una estación fuera de la línea dan un error claro."""

    day = date(2026, 11, 16)
    assert "error" in proximos("L9", "Plaça Major", day)
    assert "error" in proximos("L2", "Plaça Major", day)


def test_realtime_panel_follows_the_timetable() -> None:
    """El panel de tiempo real suma el tiempo de viaje desde la cabecera."""

    panel = panel_tiempo_real("L1", date(2026, 11, 16))
    assert panel["pvi"][0] == 5 * 60
    assert panel["pma"][0] == 5 * 60 + 4


# --- CLI: release ------------------------------------------------------------------------------


def test_prepare_publishes_green_and_leaves_it_without_traffic(
    state_file: Path, fake_langfuse: FakeLangfuse
) -> None:
    """prepare A publica el prompt de A con el label green y green queda al 0 %."""

    cli.release(["prepare", "a"])

    saved = load_state()
    assert saved.green == Green(cambio="A", traffic=0)
    assert fake_langfuse.labels(EXECUTOR_PROMPT_NAME) == {1: {"production"}, 2: {"green"}}
    assert fake_langfuse.labels(ORCHESTRATOR_PROMPT_NAME) == {1: {"production", "green"}}
    published = fake_langfuse.versions[EXECUTOR_PROMPT_NAME][1]["prompt"][0]["content"]
    assert TONO_A in published
    assert fake_langfuse.flushed


def test_shift_requires_the_gate(state_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """shift no da tráfico a un cambio que no ha pasado la puerta (salvo --forzar)."""

    state.save_state(_with_green("B", puerta="fallida"))

    with pytest.raises(SystemExit):
        cli.release(["shift", "10"])
    assert load_state().green.traffic == 0

    cli.release(["shift", "10", "--forzar"])
    assert load_state().green.traffic == 10


def test_full_flow_shift_rollback_and_promote(
    state_file: Path, fake_langfuse: FakeLangfuse, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un cambio sube por fases, vuelve atrás y, corregido, se promociona."""

    cli.release(["prepare", "A"])
    state.save_state(replace(load_state(), green=replace(load_state().green, puerta="superada")))

    cli.release(["shift", "10"])
    assert load_state().green.traffic == 10
    with pytest.raises(SystemExit):
        cli.release(["prepare", "D"])  # green tiene tráfico: primero rollback o promote

    cli.release(["rollback", "--motivo", "cae la valoración"])
    after_rollback = load_state()
    assert after_rollback.green.traffic == 0 and after_rollback.green.cambio == "A"
    assert after_rollback.historial[-1].detalle == "cae la valoración"

    cli.release(["shift", "100"])
    cli.release(["promote", "--motivo", "todo en verde"])

    final = load_state()
    assert final.blue.cambios == ("A",)
    assert final.green == Green()
    assert fake_langfuse.labels(EXECUTOR_PROMPT_NAME) == {1: set(), 2: {"green", "production"}}
    assert [event.accion for event in final.historial] == [
        "prepare",
        "shift",
        "rollback",
        "shift",
        "promote",
    ]
    with pytest.raises(SystemExit):
        cli.release(["prepare", "A"])  # ya está en producción
    assert "Green queda libre" in capsys.readouterr().out


def test_prepare_d_after_a_adds_flags_to_green(
    state_file: Path, fake_langfuse: FakeLangfuse
) -> None:
    """prepare D, con A ya en producción, activa el flag proximos_trenes en green."""

    cli.release(["prepare", "A"])
    state.save_state(replace(load_state(), green=replace(load_state().green, puerta="superada")))
    cli.release(["promote"])

    cli.release(["prepare", "D"])

    assert load_state().green.flags == {"proximos_trenes"}
    published = fake_langfuse.versions[EXECUTOR_PROMPT_NAME][-1]["prompt"][0]["content"]
    assert TONO_A in published and REGLA_D in published


def test_prepare_b_before_a_explains_the_dependency(
    state_file: Path, fake_langfuse: FakeLangfuse
) -> None:
    """prepare B sin A en producción falla y explica por qué."""

    with pytest.raises(SystemExit) as exit_info:
        cli.release(["prepare", "B"])

    assert "promociona A" in str(exit_info.value.code)
    assert load_state().green.cambio == ""


def test_status_prints_blue_green_and_the_changes(
    state_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status muestra blue, green, los cuatro cambios y la puerta."""

    state.save_state(_with_green("C", traffic=10))

    cli.release(["status"])

    out = capsys.readouterr().out
    assert "cambio C (Laia)" in out
    assert "tráfico 10 %" in out
    assert "evita_tools_prohibidas ≥ 1" in out


def test_gate_runs_the_experiment_on_green(
    state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """release gate lanza el experimento del dataset agente sobre green con --gate."""

    state.save_state(_with_green("A", puerta=""))
    calls: list[list[str]] = []
    monkeypatch.setattr(experiment, "main", lambda argv: calls.append(argv))

    cli.release(["gate", "--repeat", "2"])

    assert calls == [["agente", "--release", "green", "--gate", "--repeat=2"]]


# --- CLI: simulate ------------------------------------------------------------------------------


def _result(release: str, feedback: int | None, latency: float, error: str | None = None) -> Any:
    scenario = Scenario("s", "horarios", "1001", "es", date(2026, 11, 16), "¿Hola?")
    return SimResult(
        scenario=scenario,
        assignment=Assignment(release=release),
        trace_id=None,
        answer="",
        tool_calls=[{"name": "consultar_horario"}],
        feedback=feedback,
        error=error,
        latency_s=latency,
    )


def test_summary_per_release_counts_feedback_latency_and_errors() -> None:
    """El resumen da, por release, conversaciones, % de 👍, latencias y errores."""

    rows = cli.summarize(
        [
            _result("green", 0, 9.0, "TimeoutError"),
            _result("blue", 1, 1.0),
            _result("blue", 0, 3.0),
            _result("blue", None, 2.0),
        ]
    )

    assert [row["release"] for row in rows] == ["blue", "green"]
    blue, green = rows
    assert blue["conversaciones"] == 3 and blue["valoradas"] == 2
    assert blue["pulgar_arriba"] == 50
    assert blue["latencia_media"] == 2.0 and blue["latencia_p95"] == 3.0
    assert green["errores"] == 1
    assert cli.p95([float(value) for value in range(1, 101)]) == 95


def test_simulate_routes_travelers_with_the_current_state(
    state_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """simulate reparte los viajeros con el router y marca el tráfico como producción."""

    state.save_state(_with_green("C", traffic=100))
    seen: dict[str, Any] = {}

    async def fake_run_traffic(
        n: int, *, assign: Callable[[str], Assignment], **kwargs: Any
    ) -> list[SimResult]:
        seen.update(n=n, **kwargs)
        return [_result(assign(f"u{user}").release, 1, 1.0) for user in range(n)]

    monkeypatch.setattr(nexus.simulation, "run_traffic", fake_run_traffic, raising=False)

    cli.simulate(["--n", "5", "--seed", "3"])

    assert seen["n"] == 5 and seen["seed"] == 3
    assert seen["environment"] == "production"
    assert seen["tags"] == ("simulacion", "canary-C")
    out = capsys.readouterr().out
    assert "green" in out and "Nexus en producción" in out
