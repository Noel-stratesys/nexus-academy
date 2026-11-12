"""El veredicto del orquestador: la primera puerta de cada petición.

``valid`` deja pasar la petición al executor; cualquier otro veredicto dice por qué se
rechaza. Los criterios viven aquí, en el código, y llegan al prompt por ``{{criteria}}``.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Verdict(StrEnum):
    VALID = "valid"
    EMPTY = "empty"
    UNINTELLIGIBLE = "unintelligible"
    OUT_OF_SCOPE = "out_of_scope"


# `empty` se decide en el código, sin llamar al modelo; el modelo elige entre estos.
VERDICT_CRITERIA: dict[Verdict, str] = {
    Verdict.VALID: (
        "La petición se entiende y está relacionada con el ámbito, aunque falten datos o "
        "Nexus no pueda resolverla del todo."
    ),
    Verdict.UNINTELLIGIBLE: (
        "No se entiende qué quiere el viajero ni teniendo en cuenta el diálogo previo."
    ),
    Verdict.OUT_OF_SCOPE: (
        "Se entiende, pero es ajena al ámbito: por ejemplo, restaurantes, el tiempo, "
        "deportes, deberes, programación o conversación general sin relación con viajar "
        "en Metro de Vilaverda."
    ),
}


def criteria_text() -> str:
    """Los criterios tal como los ve el prompt, un veredicto por línea."""

    return "\n".join(f"- {verdict.value}: {text}" for verdict, text in VERDICT_CRITERIA.items())


class OrchestratorDecision(BaseModel):
    verdict: Verdict

    @property
    def is_valid(self) -> bool:
        return self.verdict == Verdict.VALID


class ModelVerdict(BaseModel):
    """Lo que responde el modelo; `empty` no está porque lo decide el código."""

    verdict: Literal["valid", "unintelligible", "out_of_scope"] = Field(
        description="Veredicto sobre la petición actual."
    )

    def decision(self) -> OrchestratorDecision:
        return OrchestratorDecision(verdict=Verdict(self.verdict))


def empty_request_decision(request: str) -> OrchestratorDecision | None:
    """La decisión para una petición sin texto, que no necesita al modelo."""

    return None if request.strip() else OrchestratorDecision(verdict=Verdict.EMPTY)
