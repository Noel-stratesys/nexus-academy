"""La valoración 👍/👎 que deja el viajero simulado (score ``user_feedback``: 1 o 0).

No todos valoran: lo hace un 60 % de las conversaciones, y un 80 % cuando la experiencia
ha sido mala. La probabilidad de 👍 sale de la respuesta, como la juzgaría el viajero:

- vacía o «no puedo atender» → casi nunca;
- rechaza una consulta válida → rara vez; rechaza una que no lo era → a veces;
- en otro idioma que el del viajero → rara vez;
- el viajero rechazó la acción que le proponían → a medias;
- trae los datos que buscaba (``expected["menciona"]``) → casi siempre; si no, a medias,
  y menos si Nexus contestó de memoria, sin las herramientas que hacían falta (el viajero
  va al andén y el tren no está);
- un tono cercano la sube y una respuesta muy larga la baja un poco.

El viajero valora antes de comprobar si la respuesta era cierta: muchas respuestas
equivocadas se llevan un 👍. Es la diferencia entre la valoración y la evaluación.

Es determinista: el mismo escenario, la misma respuesta y la misma ``semilla`` (una por
conversación) dan siempre la misma valoración.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from nexus.simulation.scenarios import stable_fraction
from nexus.simulation.types import Scenario

# Las respuestas fijas del orquestador (``nexus.nodes.orchestrator``).
NO_DISPONIBLE = "Ahora mismo no puedo atender tu consulta"
RECHAZOS = (
    "Escribe tu consulta:",
    "No he entendido tu consulta",
    "Solo puedo ayudarte con temas de Metro de Vilaverda",
)

PALABRAS = {
    "es": {
        "los", "las", "y", "hay", "con", "pero", "está", "puedes", "día", "días", "hoy",
        "mañana", "tren", "último", "horas", "cuesta", "viajes", "una", "por", "para", "se",
        "tu", "te", "lo", "siento", "solo", "hacia", "pasa",
    },
    "ca": {
        "els", "i", "hi", "amb", "però", "és", "pots", "dia", "dies", "avui", "demà",
        "metro", "hores", "costa", "viatges", "per", "aquest", "aquesta", "et", "ho",
        "sento", "només", "cap", "passa", "l", "d", "t",
    },
    "en": {
        "the", "and", "is", "are", "you", "your", "at", "on", "to", "with", "there", "train",
        "every", "minutes", "can", "not", "of", "it", "for", "sorry", "only", "yes",
    },
}  # fmt: skip

CERCANO = re.compile(r"[😊🚇]|^(¡?hola|¡?buenas|hi|hey|hello|bon dia|ei)\b", re.IGNORECASE)


def _plano(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(char for char in normalizado if not unicodedata.combining(char))


def contiene(alternativas: str, texto: str) -> bool:
    """Si ``texto`` trae alguna de las ``alternativas`` (``"a|b"``), sin tildes ni mayúsculas.

    Las alternativas tienen que empezar una palabra, y las palabras cortas (``no``, ``sí``)
    tienen que ser palabras enteras: ``no`` no está en «normativa».
    """

    plano = _plano(texto)
    for opcion in alternativas.split("|"):
        buscada = _plano(opcion)
        fin = r"(?!\w)" if buscada.isalpha() and len(buscada) <= 3 else ""
        if re.search(rf"(?<!\w){re.escape(buscada)}{fin}", plano):
            return True
    return False


def idioma_de(texto: str) -> str | None:
    """El idioma en que está escrito ``texto`` (es, ca o en), o None si no está claro."""

    palabras = re.findall(r"\w+", texto.lower())
    cuentas = {
        idioma: sum(p in vocabulario for p in palabras) for idioma, vocabulario in PALABRAS.items()
    }
    mejor = max(cuentas, key=lambda idioma: cuentas[idioma])
    empatados = [idioma for idioma, n in cuentas.items() if n == cuentas[mejor]]
    return mejor if cuentas[mejor] >= 2 and len(empatados) == 1 else None


def probabilidad_de_pulgar_arriba(
    scenario: Scenario, answer: str, tool_calls: Sequence[dict[str, Any]] = ()
) -> float:
    """La probabilidad de que el viajero valore la respuesta con 👍."""

    texto = (answer or "").strip()
    if not texto or NO_DISPONIBLE in texto:
        return 0.05
    debia_rechazar = scenario.expected.get("verdict", "valid") != "valid"
    if any(rechazo in texto for rechazo in RECHAZOS):
        return 0.3 if debia_rechazar else 0.1
    if debia_rechazar:
        return 0.2
    idioma = idioma_de(texto)
    if idioma is not None and idioma != scenario.idioma:
        return 0.15
    if scenario.expected.get("quiere_accion") and scenario.approvals[:1] not in ((), ("approve",)):
        return 0.55
    menciona = scenario.expected.get("menciona") or []
    if menciona:
        acierta = all(contiene(dato, texto) for dato in menciona)
        usadas = {call["name"] for call in tool_calls}
        de_memoria = bool(scenario.expected.get("tools")) and not usadas
        probabilidad = 0.8 if acierta else (0.35 if de_memoria else 0.45)
    else:
        probabilidad = 0.75
    if CERCANO.search(texto):
        probabilidad += 0.15
    if len(texto) > 700:
        probabilidad -= 0.05
    return min(probabilidad, 0.95)


def feedback_for(
    scenario: Scenario,
    answer: str,
    tool_calls: Sequence[dict[str, Any]] = (),
    *,
    semilla: str = "",
) -> int | None:
    """La valoración del viajero: 1 (👍), 0 (👎) o None si no valora."""

    probabilidad = probabilidad_de_pulgar_arriba(scenario, answer, tool_calls)
    valora = 0.8 if probabilidad < 0.5 else 0.6
    if stable_fraction("valora", scenario.scenario_id, scenario.viajero, semilla) >= valora:
        return None
    return int(
        stable_fraction("pulgar", scenario.scenario_id, scenario.viajero, semilla) < probabilidad
    )
