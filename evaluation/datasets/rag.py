"""Dataset del RAG: 10 preguntas sobre la normativa, todas con respuesta en los documentos.

``docs`` son los documentos que contienen la respuesta (basta con recuperar uno) y
``menciona`` los datos que debe dar. Varias dependen de la edición de la normativa
(bicis, patinetes, perros, multas): ahí se nota si el buscador trae la norma derogada.

Las ejecuciones grabadas del capítulo 4 (``evaluation/experimentos_grabados``) se
hicieron sobre estos 10 casos: si cambian, hay que volver a grabarlas.
"""

from evaluation.datasets.definition import Case, DatasetDefinition

ACTUAL = "normativa-viajeros-2026"
GUIA_BICIS = "guia-bicicletas-y-patinetes"


def _answerable(
    case_id: str, pregunta: str, docs: list[str], menciona: list[str], **kwargs: str
) -> Case:
    expected = {"responde": True, "docs": docs, "menciona": menciona}
    return Case(case_id, pregunta, expected, "con_respuesta", **kwargs)  # type: ignore[arg-type]


CASES = [
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
        "rag-11",
        "¿Cuánto retraso tiene que haber para que me devuelvan el viaje?",
        ["devoluciones-y-reclamaciones"],
        ["30 minutos"],
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
]

DATASET = DatasetDefinition(
    name="nexus/rag",
    description=(
        "Preguntas de normativa con respuesta en los documentos. Mide si el buscador trae "
        "la norma vigente y si la respuesta da los datos que tiene que dar."
    ),
    target="agent",
    cases=CASES,
)
