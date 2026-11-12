"""El historial de Nexus: tres semanas de producción, del 26 de octubre al 15 de noviembre.

``plan_historial()`` decide, siempre igual, qué pasó: quién escribió, cuándo, qué preguntó
y qué versión de Nexus le atendió. ``uv run seed`` lo ejecuta y lo carga en Langfuse.

- Semana 1 (26 oct – 1 nov): prueba A/B entre el executor de Marc (release ``marc``,
  executor v1) y el de Jordi (release ``jordi``, executor v2). Cada conversación va a una
  de las dos al azar, mitad y mitad.
- Semanas 2 y 3 (2 – 15 nov): el de Jordi ganó y es producción (release ``blue``).
- Los casos de la historia: Marta pregunta por la bici (martes 3, 8:03), Pere por la L3
  (martes 10, 7:52) y una consulta de incidencias tarda más de 40 s (miércoles 11, 7:41).

Las horas son de Vilaverda (CET: el cambio de hora fue el 25 de octubre).
"""

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

from nexus.data import viajeros
from nexus.prompts import EXECUTOR_PROMPT_NAME
from nexus.prompts.orchestrator import ORCHESTRATOR_PROMPT_NAME
from nexus.simulation.scenarios import pick_scenario, scenarios, stable_fraction, story_scenarios
from nexus.simulation.types import Assignment, Scenario

CET = timezone(timedelta(hours=1), "CET")
PRIMER_DIA = date(2026, 10, 26)
ULTIMO_DIA = date(2026, 11, 15)
FIN_PRUEBA_AB = date(2026, 11, 1)

MARC = Assignment(release="marc", label="marc")
JORDI = Assignment(release="jordi", label="jordi")
BLUE = Assignment(release="blue", label="production")

# Versión canónica (la del historial) de cada prompt que usa cada release.
VERSIONES = {
    "marc": {ORCHESTRATOR_PROMPT_NAME: 1, EXECUTOR_PROMPT_NAME: 1},
    "jordi": {ORCHESTRATOR_PROMPT_NAME: 1, EXECUTOR_PROMPT_NAME: 2},
    "blue": {ORCHESTRATOR_PROMPT_NAME: 1, EXECUTOR_PROMPT_NAME: 2},
}

# Conversaciones por día de la semana (lunes = 0). La semana de la prueba A/B hubo más.
VOLUMEN = {0: 30, 1: 30, 2: 30, 3: 30, 4: 32, 5: 18, 6: 14}
VOLUMEN_PRUEBA_AB = {0: 46, 1: 46, 2: 46, 3: 46, 4: 48, 5: 28, 6: 22}

# Peso de cada hora del día: en laborable, las puntas de ir y volver del trabajo.
HORAS_LABORABLE = [
    0.3, 0.1, 0.05, 0.05, 0.1, 0.6, 2.0, 5.5, 6.5, 4.0, 2.5, 2.2,
    2.3, 2.6, 2.4, 2.2, 2.8, 4.5, 5.0, 3.8, 2.6, 1.8, 1.2, 0.7,
]  # fmt: skip
HORAS_FESTIVO = [
    0.8, 0.6, 0.3, 0.1, 0.1, 0.2, 0.4, 0.8, 1.5, 2.5, 3.5, 3.8,
    3.6, 3.2, 2.8, 3.0, 3.3, 3.5, 3.4, 3.0, 2.5, 2.0, 1.6, 1.2,
]  # fmt: skip

# Sin la regla de consultar las herramientas, cuántas veces da el horario de memoria.
PROBABILIDAD_INVENTA = 0.65


@dataclass(frozen=True)
class Conversacion:
    """Una conversación del historial.

    ``inventa`` y ``reintentos`` van al guion del modelo (``nexus.simulation.modelo``);
    ``valoracion`` fija la del viajero en los casos de la historia (si es None, la decide
    ``feedback_for``).
    """

    clave: str
    inicio: datetime  # en UTC
    scenario: Scenario
    assignment: Assignment
    inventa: bool = False
    reintentos: int = 0
    historia: str | None = None
    valoracion: int | None = None

    @property
    def dia(self) -> date:
        return self.inicio.astimezone(CET).date()

    @property
    def thread_id(self) -> str:
        return hashlib.sha256(f"sesion|{self.clave}".encode()).hexdigest()[:32]

    @property
    def versiones(self) -> dict[str, int]:
        return VERSIONES[self.assignment.release]


def dias_del_historial() -> list[date]:
    return [PRIMER_DIA + timedelta(days=n) for n in range((ULTIMO_DIA - PRIMER_DIA).days + 1)]


def _momento(dia: date, hora: int, minuto: int, segundo: int = 0) -> datetime:
    return datetime.combine(dia, time(hora, minuto, segundo), CET).astimezone(UTC)


def _version(dia: date, clave: str) -> Assignment:
    if dia <= FIN_PRUEBA_AB:
        return MARC if stable_fraction("prueba-ab", clave) < 0.5 else JORDI
    return BLUE


def _casos_de_la_historia() -> list[Conversacion]:
    historia = story_scenarios()
    pere, marta = historia["pere"], historia["marta"]
    lenta_dia = date(2026, 11, 11)
    lenta = next(
        scenario
        for scenario in scenarios(lenta_dia, viajero="1001", categorias=["incidencias"])
        if scenario.scenario_id == "inc-manana-sin-linea-es"
    )
    return [
        Conversacion(
            "historia-marta", _momento(marta.hoy, 8, 3, 41), marta, BLUE,
            historia="marta", valoracion=1,
        ),
        Conversacion(
            "historia-pere", _momento(pere.hoy, 7, 52, 18), pere, BLUE,
            historia="pere", valoracion=1,
        ),
        Conversacion(
            "historia-lenta", _momento(lenta_dia, 7, 41, 6), lenta, BLUE,
            reintentos=8, historia="lenta", valoracion=0,
        ),
    ]  # fmt: skip


def plan_historial() -> list[Conversacion]:
    """Todas las conversaciones del historial, en orden. Siempre las mismas."""

    rng = random.Random("nexus-historial")
    ids = sorted(viajeros())
    # Unos viajeros escriben mucho más que otros.
    pesos = [0.3 + 2.7 * rng.random() ** 2 for _ in ids]
    conversaciones = []
    for dia in dias_del_historial():
        volumen = VOLUMEN_PRUEBA_AB if dia <= FIN_PRUEBA_AB else VOLUMEN
        laborable = dia.weekday() < 5 and dia != date(2026, 11, 1)
        horas = HORAS_LABORABLE if laborable else HORAS_FESTIVO
        momentos = sorted(
            _momento(dia, rng.choices(range(24), weights=horas)[0], rng.randrange(60),
                     rng.randrange(60))
            for _ in range(volumen[dia.weekday()])
        )  # fmt: skip
        for numero, inicio in enumerate(momentos):
            quien = rng.choices(ids, weights=pesos)[0]
            scenario = pick_scenario(rng, dia, quien)
            inventa = rng.random() < PROBABILIDAD_INVENTA
            reintentos = rng.randint(1, 3)
            sin_linea = scenario.expected.get("verdad", {}).get("sin_linea", False)
            clave = f"{dia.isoformat()}-{numero:03d}"
            conversaciones.append(
                Conversacion(
                    clave=clave,
                    inicio=inicio,
                    scenario=scenario,
                    assignment=_version(dia, clave),
                    inventa=inventa and scenario.categoria == "horarios",
                    reintentos=reintentos if sin_linea else 0,
                )
            )
    conversaciones.extend(_casos_de_la_historia())
    return sorted(conversaciones, key=lambda conversacion: conversacion.inicio)
