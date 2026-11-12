"""Tipos compartidos del simulador de viajeros.

Los usan el historial que carga ``uv run seed`` (``nexus.simulation.historial``) y los
despliegues del capítulo 5 (``release`` y ``uv run simulate``). Este fichero es el
contrato entre esas piezas: cambiarlo afecta a todas.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Assignment:
    """A qué versión de Nexus va un viajero en una conversación.

    ``release`` es el nombre que verá Langfuse (``blue``, ``green``, ``marc``, ``jordi``...),
    ``label`` es el label de Langfuse con el que se leen los prompts y ``flags`` activa
    funcionalidades (por ejemplo, una herramienta nueva).
    """

    release: str = "blue"
    label: str = "production"
    flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Scenario:
    """Una petición de un viajero con la verdad que permite puntuarla sin modelo."""

    scenario_id: str
    categoria: str
    viajero: str
    idioma: str  # es, ca o en
    hoy: date
    mensaje: str
    # Lo que una buena respuesta tiene que hacer: herramientas, datos que menciona, etc.
    expected: dict[str, Any] = field(default_factory=dict)
    # Respuestas a las aprobaciones que pida Nexus: "approve" o el motivo del rechazo.
    approvals: tuple[str, ...] = ()


@dataclass
class SimResult:
    """Lo que ocurrió en una conversación simulada."""

    scenario: Scenario
    assignment: Assignment
    trace_id: str | None
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    feedback: int | None = None  # 1 = 👍, 0 = 👎, None = el viajero no valoró
    error: str | None = None
    latency_s: float = 0.0
