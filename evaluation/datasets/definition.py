"""Datasets definidos en el código y cómo se suben a Langfuse.

Un dataset es una lista de casos. Cada caso tiene una entrada (lo que escribe el
viajero), lo que esperamos (``expected``) y metadata para analizar los resultados por
grupos: ``case_id`` y ``categoria``.
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class Case:
    case_id: str
    mensaje: str
    expected: dict[str, Any]
    categoria: str
    viajero: str = "1001"
    hoy: str = "2026-11-16"
    extra: dict[str, Any] = field(default_factory=dict)

    def input(self) -> dict[str, Any]:
        return {"mensaje": self.mensaje, "viajero": self.viajero, "hoy": self.hoy}

    def metadata(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "categoria": self.categoria,
            **self.extra,
        }


@dataclass(frozen=True)
class DatasetDefinition:
    name: str
    description: str
    # Qué parte de Nexus ejecuta un experimento sobre este dataset.
    target: Literal["orchestrator", "agent"]
    cases: list[Case]

    def item_id(self, case: Case) -> str:
        """Id estable por caso: volver a subir el dataset actualiza, no duplica."""

        return str(uuid5(NAMESPACE_URL, f"{self.name}/{case.case_id}"))


def upload(definition: DatasetDefinition, langfuse: Any) -> int:
    """Crea el dataset (o lo actualiza) con todos sus casos.

    Los casos que están en Langfuse pero ya no en el código se archivan: así el dataset
    de Langfuse tiene los mismos casos activos que el código.
    """

    langfuse.create_dataset(
        name=definition.name,
        description=definition.description,
        metadata={"target": definition.target, "casos": len(definition.cases)},
    )
    for case in definition.cases:
        langfuse.create_dataset_item(
            dataset_name=definition.name,
            id=definition.item_id(case),
            input=case.input(),
            expected_output=case.expected,
            metadata=case.metadata(),
        )
    _archive_removed(definition, langfuse)
    langfuse.flush()
    return len(definition.cases)


def _archive_removed(definition: DatasetDefinition, langfuse: Any) -> None:
    current = {definition.item_id(case) for case in definition.cases}
    page = 1
    while True:
        result = langfuse.api.dataset_items.list(dataset_name=definition.name, page=page, limit=50)
        for item in result.data:
            if item.id not in current and str(item.status).upper().endswith("ACTIVE"):
                langfuse.create_dataset_item(
                    dataset_name=definition.name,
                    id=item.id,
                    input=item.input,
                    expected_output=item.expected_output,
                    metadata=item.metadata,
                    status="ARCHIVED",
                )
        if page >= (result.meta.total_pages or 1):
            return
        page += 1
