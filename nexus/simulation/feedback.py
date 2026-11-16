"""La valoración 👍/👎 que deja el viajero simulado (score ``user_feedback``: 1 o 0).

No todos valoran: lo hace un 60 % de las conversaciones, y un 80 % cuando la experiencia
ha sido mala. La probabilidad de 👍 sale de la respuesta, como la juzgaría el viajero:

- vacía o «no puedo atender» → casi nunca;
- rechaza una consulta válida → rara vez; rechaza una que no lo era → a veces;
- en otro idioma que el del viajero → rara vez;
- el viajero rechazó la acción que le proponían → a medias;
- trae los datos que buscaba (``expected["menciona"]``) → casi siempre;
- trae un dato equivocado → rara vez: el viajero va al andén y el tren no está. Y menos
  aún si Nexus contestó de memoria, sin las herramientas que hacían falta;
- un tono cercano la sube y una respuesta muy larga la baja un poco.

El viajero valora después de usar la respuesta: si el dato era falso, se entera. Parte
de las valoraciones llevan un comentario (``comentario_for``), en el idioma del viajero,
que cuenta qué le gustó o qué falló. El viajero no sabe si Nexus consultó o no una
herramienta: eso solo se ve en la traza.

Es determinista: el mismo escenario, la misma respuesta y la misma ``semilla`` (una por
conversación) dan siempre la misma valoración y el mismo comentario.
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


def _juicio(
    scenario: Scenario, answer: str, tool_calls: Sequence[dict[str, Any]] = ()
) -> tuple[float, str]:
    """La probabilidad de 👍 y el motivo principal, tal como lo vive el viajero."""

    texto = (answer or "").strip()
    if not texto or NO_DISPONIBLE in texto:
        return 0.05, "no_atiende"
    debia_rechazar = scenario.expected.get("verdict", "valid") != "valid"
    if any(rechazo in texto for rechazo in RECHAZOS):
        return (0.3, "rechaza") if debia_rechazar else (0.1, "rechaza")
    if debia_rechazar:
        return 0.2, "otro_tema"
    idioma = idioma_de(texto)
    if idioma is not None and idioma != scenario.idioma:
        return 0.15, "idioma"
    if scenario.expected.get("quiere_accion") and scenario.approvals[:1] not in ((), ("approve",)):
        return 0.55, "neutro"
    motivo = "neutro"
    menciona = scenario.expected.get("menciona") or []
    if menciona:
        acierta = all(contiene(dato, texto) for dato in menciona)
        usadas = {call["name"] for call in tool_calls}
        de_memoria = bool(scenario.expected.get("tools")) and not usadas
        if acierta:
            probabilidad, motivo = 0.85, "acierta"
        else:
            probabilidad, motivo = (0.2 if de_memoria else 0.28), "dato_mal"
    else:
        probabilidad = 0.75
    cercano = bool(CERCANO.search(texto))
    if cercano:
        probabilidad += 0.1
        if motivo != "dato_mal":
            motivo = "cercano"
    if len(texto) > 700:
        probabilidad -= 0.05
        if motivo == "neutro":
            motivo = "larga"
    return min(probabilidad, 0.95), motivo


def probabilidad_de_pulgar_arriba(
    scenario: Scenario, answer: str, tool_calls: Sequence[dict[str, Any]] = ()
) -> float:
    """La probabilidad de que el viajero valore la respuesta con 👍."""

    return _juicio(scenario, answer, tool_calls)[0]


# Comentarios del viajero: {(👍 o 👎, motivo): {idioma: [comentarios]}}. Para un dato
# equivocado hay comentarios por categoría; si la categoría no tiene, se usa "dato_mal".
COMENTARIOS: dict[tuple[int, str], dict[str, list[str]]] = {
    (1, "cercano"): {
        "es": ["¡Muy amable! 😊", "Rápido y simpático, así da gusto.", "Me ha encantado el trato."],
        "ca": ["Molt amable! 😊", "Ràpid i simpàtic, així sí.", "M'ha agradat molt el tracte."],
        "en": ["Really friendly! 😊", "Quick and nice, great.", "Loved the tone."],
    },
    (1, "acierta"): {
        "es": ["Justo lo que necesitaba.", "Correcto, gracias.", "Dato exacto, perfecto."],
        "ca": ["Just el que necessitava.", "Correcte, gràcies.", "Dada exacta, perfecte."],
        "en": ["Exactly what I needed.", "Correct, thanks.", "Spot on."],
    },
    (1, "neutro"): {
        "es": ["Útil.", "Bien."],
        "ca": ["Útil.", "Bé."],
        "en": ["Useful.", "Fine."],
    },
    (0, "dato_mal/horarios"): {
        "es": [
            "Fui al andén a la hora que me dijo y el tren no pasaba.",
            "La hora que me dio no era la buena.",
            "Muy simpático, pero el horario estaba mal.",
            "Me dijo una hora y el tren pasó a otra. He perdido el tren.",
        ],
        "ca": [
            "Vaig anar a l'andana a l'hora que em va dir i el tren no passava.",
            "L'hora que em va donar no era la bona.",
            "Molt simpàtic, però l'horari estava malament.",
        ],
        "en": [
            "I went to the platform at the time it gave me and there was no train.",
            "The time it gave me was wrong.",
            "Very friendly, but the timetable was wrong.",
        ],
    },
    (0, "dato_mal/incidencias"): {
        "es": [
            "Me dijo que todo iba normal y la línea estaba cortada.",
            "No me avisó de la obra.",
        ],
        "ca": [
            "Em va dir que tot anava bé i la línia estava tallada.",
            "No em va avisar de l'obra.",
        ],
        "en": [
            "It said everything was fine and the line was closed.",
            "It didn't warn me about the works.",
        ],
    },
    (0, "dato_mal/tarifas"): {
        "es": ["El precio que me dijo no era ese."],
        "ca": ["El preu que em va dir no era aquest."],
        "en": ["The price it told me was wrong."],
    },
    (0, "dato_mal"): {
        "es": ["La información no era correcta.", "Lo que me dijo no era verdad."],
        "ca": ["La informació no era correcta.", "El que em va dir no era cert."],
        "en": ["The information was wrong.", "What it told me wasn't true."],
    },
    (0, "rechaza"): {
        "es": ["No ha entendido lo que le pedía."],
        "ca": ["No ha entès el que li demanava."],
        "en": ["It didn't understand my question."],
    },
    (0, "idioma"): {
        "es": ["Le escribo en castellano y me contesta en otro idioma."],
        "ca": ["Li escric en català i em contesta en un altre idioma."],
        "en": ["I write in English and it answers in another language."],
    },
    (0, "larga"): {
        "es": ["Demasiado largo para leerlo en el andén."],
        "ca": ["Massa llarg per llegir-ho a l'andana."],
        "en": ["Too long to read on the platform."],
    },
    (0, "no_atiende"): {
        "es": ["No me ha atendido."],
        "ca": ["No m'ha atès."],
        "en": ["It didn't help me at all."],
    },
}

# Qué parte de las valoraciones lleva comentario: más cuando la experiencia fue mala.
COMENTA = {0: 0.6, 1: 0.25}


def comentario_for(
    scenario: Scenario,
    answer: str,
    tool_calls: Sequence[dict[str, Any]] = (),
    feedback: int | None = None,
    *,
    semilla: str = "",
) -> str | None:
    """El comentario que deja el viajero con su valoración, o None si no comenta."""

    if feedback is None:
        return None
    if (
        stable_fraction("comenta", scenario.scenario_id, scenario.viajero, semilla)
        >= COMENTA[feedback]
    ):
        return None
    _, motivo = _juicio(scenario, answer, tool_calls)
    claves = [f"{motivo}/{scenario.categoria}", motivo] if motivo == "dato_mal" else [motivo]
    if feedback == 1 and motivo not in ("cercano", "acierta"):
        claves = ["neutro"]
    for clave in claves:
        textos = COMENTARIOS.get((feedback, clave), {})
        opciones = textos.get(scenario.idioma) or textos.get("es")
        if opciones:
            indice = stable_fraction("comentario", scenario.scenario_id, semilla) * len(opciones)
            return opciones[int(indice)]
    return None


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
