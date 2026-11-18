"""Cuando el modelo escribe mal su salida, la llamada se repite al momento (sin red)."""

from typing import Any

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from nexus.context import Context
from nexus.decisions import ModelVerdict, Verdict
from nexus.llm import models
from nexus.nodes import orchestrator

TOOL_USE_FAILED = (
    "Error code: 400 - {'error': {'message': \"tool call validation failed\", "
    "'type': 'invalid_request_error', 'code': 'tool_use_failed'}}"
)
JSON_VALIDATE_FAILED = (
    "Error code: 400 - {'error': {'message': 'Generated JSON does not match the expected "
    "schema', 'type': 'invalid_request_error', 'code': 'json_validate_failed'}}"
)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(TOOL_USE_FAILED),
        RuntimeError(JSON_VALIDATE_FAILED),
        OutputParserException("no es JSON"),
    ],
)
def test_detecta_una_salida_mal_escrita(error: Exception) -> None:
    assert models.is_malformed_output(error)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Error code: 429 - rate limit reached"),
        TimeoutError("La llamada al modelo superó 120 segundos."),
        ValueError("otra cosa"),
    ],
)
def test_no_confunde_otros_errores_con_una_salida_mal_escrita(error: Exception) -> None:
    assert not models.is_malformed_output(error)


class FakeModel:
    """Un modelo que falla con ``errors`` en orden y después responde ``valid``."""

    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        self.calls = 0
        self.method: str | None = None

    def with_structured_output(self, schema: type, *, method: str) -> Any:
        self.method = method

        def answer(_: Any) -> ModelVerdict:
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            return ModelVerdict(verdict="valid")

        return RunnableLambda(answer)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Sustituye el prompt y el modelo del orquestador por versiones sin red."""

    def install(errors: list[Exception]) -> FakeModel:
        model = FakeModel(errors)
        monkeypatch.setattr(orchestrator, "langfuse_prompt", lambda name: object())
        monkeypatch.setattr(orchestrator, "model_for", lambda prompt, base: base)
        monkeypatch.setattr(orchestrator, "chat_model", lambda config: model)
        passthrough = RunnableLambda(lambda inputs: inputs)
        monkeypatch.setattr(orchestrator, "chat_template", lambda prompt: passthrough)
        return model

    return install


async def _classify() -> Verdict:
    decision = await orchestrator.classify_request(
        [HumanMessage(content="¿Hay obras en la L3?")], context=Context()
    )
    return decision.verdict


async def test_el_orquestador_pide_json_con_esquema(fake_model: Any) -> None:
    model = fake_model([])

    assert await _classify() == Verdict.VALID
    assert model.method == "json_schema"
    assert model.calls == 1


async def test_el_orquestador_repite_al_momento_si_el_modelo_escribe_mal(fake_model: Any) -> None:
    model = fake_model([RuntimeError(JSON_VALIDATE_FAILED), OutputParserException("roto")])

    assert await _classify() == Verdict.VALID
    assert model.calls == 3


async def test_el_orquestador_se_rinde_tras_los_reintentos(fake_model: Any) -> None:
    errors = [RuntimeError(TOOL_USE_FAILED)] * (models.MALFORMED_OUTPUT_RETRIES + 1)
    model = fake_model(list(errors))

    with pytest.raises(RuntimeError, match="tool_use_failed"):
        await _classify()
    assert model.calls == models.MALFORMED_OUTPUT_RETRIES + 1


async def test_el_orquestador_no_repite_otros_errores(fake_model: Any) -> None:
    model = fake_model([RuntimeError("Error code: 429 - rate limit reached")])

    with pytest.raises(RuntimeError, match="429"):
        await _classify()
    assert model.calls == 1
