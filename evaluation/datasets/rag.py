"""Dataset del RAG: preguntas sobre la normativa, con y sin respuesta en los documentos.

- Con respuesta: ``docs`` son los documentos que contienen la respuesta (basta con
  recuperar uno) y ``menciona`` los datos que debe dar.
- Sin respuesta: la normativa no dice nada. Lo correcto es decir que no consta, no
  inventar. ``responde`` es ``False``.

Hay tantas preguntas con respuesta como sin ella: así un buscador que "siempre
responde algo" no saca buena nota.
"""

from evaluation.datasets.definition import Case, DatasetDefinition

ACTUAL = "normativa-viajeros-2026"
GUIA_BICIS = "guia-bicicletas-y-patinetes"


def _answerable(
    case_id: str, pregunta: str, docs: list[str], menciona: list[str], **kwargs: str
) -> Case:
    expected = {"responde": True, "docs": docs, "menciona": menciona}
    return Case(case_id, pregunta, expected, "con_respuesta", **kwargs)  # type: ignore[arg-type]


def _unanswerable(case_id: str, pregunta: str, **kwargs: str) -> Case:
    expected = {"responde": False, "docs": [], "menciona": []}
    return Case(case_id, pregunta, expected, "sin_respuesta", **kwargs)  # type: ignore[arg-type]


CASES = [
    # --- con respuesta en la normativa (15) -----------------------------------
    _answerable(
        "rag-01",
        "¿Puedo subir con la bici al metro un martes a las 8:15?",
        [ACTUAL, GUIA_BICIS],
        ["9:30|no puedes|no se puede|no está permitid|no se admite|no podrás"],
        viajero="1017",
        hoy="2026-11-03",
    ),
    _answerable(
        "rag-02",
        "¿Puedo llevar una bicicleta plegada en hora punta?",
        [ACTUAL, GUIA_BICIS],
        ["plegada"],
    ),
    _answerable(
        "rag-03",
        "¿Dónde puedo dejar aparcada la bici en una estación?",
        [GUIA_BICIS],
        ["Estació Central|Plaça Major|Universitat|Parc del Riu"],
    ),
    _answerable(
        "rag-04",
        "¿Puedo cargar mi patinete eléctrico en un enchufe de la estación?",
        [ACTUAL, GUIA_BICIS],
        ["no"],
    ),
    _answerable(
        "rag-05",
        "¿Qué necesito para llevar a mi perro grande en el metro?",
        [ACTUAL, "viajar-con-mascotas"],
        ["bozal"],
    ),
    _answerable(
        "rag-06",
        "¿Qué medidas tiene que tener el transportín del gato?",
        [ACTUAL, "viajar-con-mascotas"],
        ["45"],
    ),
    _answerable(
        "rag-07",
        "¿Hasta qué edad viajan gratis los niños?",
        [ACTUAL, "tarifas-y-titulos"],
        ["4 años"],
    ),
    _answerable(
        "rag-08",
        "¿Cuál es la multa por viajar sin billete?",
        [ACTUAL],
        ["100"],
    ),
    _answerable(
        "rag-09",
        "¿Cuántos minutos tengo para hacer transbordo con el billete sencillo?",
        ["tarifas-y-titulos"],
        ["75"],
    ),
    _answerable(
        "rag-10",
        "¿Podemos viajar dos personas con la misma T-10?",
        ["tarifas-y-titulos"],
        ["multipersonal|sí"],
    ),
    _answerable(
        "rag-11",
        "¿Cuánto retraso tiene que haber para que me devuelvan el viaje?",
        ["devoluciones-y-reclamaciones"],
        ["30 minutos"],
    ),
    _answerable(
        "rag-12",
        "¿Cuántos días tengo para pedir una devolución?",
        ["devoluciones-y-reclamaciones"],
        ["30 días"],
    ),
    _answerable(
        "rag-13", "¿Cuánto tiempo guardáis los objetos perdidos?", ["objetos-perdidos"], ["30 días"]
    ),
    _answerable(
        "rag-14",
        "¿Qué estaciones no tienen acceso sin escaleras?",
        ["accesibilidad"],
        ["Drassanes Velles"],
    ),
    _answerable(
        "rag-15",
        "¿Hasta qué hora hay metro la noche de la Festa Major?",
        ["servicio-nocturno-y-eventos"],
        ["3:00"],
    ),
    # --- sin respuesta en la normativa (15) -----------------------------------
    _unanswerable("rag-16", "¿Cuánto cuesta el parking del Aeroport?"),
    _unanswerable("rag-17", "¿Hay descuento para familias numerosas?"),
    _unanswerable("rag-18", "¿Puedo llevar un dron en el metro?"),
    _unanswerable("rag-19", "¿Cuál es el teléfono de atención al cliente?"),
    _unanswerable("rag-20", "¿Se pueden reservar vagones para una excursión del colegio?"),
    _unanswerable("rag-21", "¿Hay consignas para dejar maletas en las estaciones?"),
    _unanswerable("rag-22", "¿Puedo pagar el billete con bitcoin?"),
    _unanswerable("rag-23", "¿Se puede celebrar un cumpleaños en un vagón?"),
    _unanswerable("rag-24", "¿Cuántos trenes tiene Metro de Vilaverda?"),
    _unanswerable("rag-25", "¿Hay descuento para jubilados?"),
    _unanswerable("rag-26", "Si pierdo la T-Mes, ¿me dan un duplicado?"),
    _unanswerable("rag-27", "¿Hay descuento para universitarios de más de 26 años?"),
    _unanswerable("rag-28", "¿Las mascotas pagan en el autobús nocturno?"),
    _unanswerable("rag-29", "¿A qué temperatura está el aire acondicionado de los trenes?"),
    _unanswerable("rag-30", "¿Hay cajeros automáticos en las estaciones?"),
]

DATASET = DatasetDefinition(
    name="nexus/rag",
    description=(
        "Preguntas de normativa: 15 con respuesta en los documentos y 15 sin ella. "
        "Mide si se recupera el documento correcto y si Nexus se abstiene cuando no hay respuesta."
    ),
    target="agent",
    cases=CASES,
)
