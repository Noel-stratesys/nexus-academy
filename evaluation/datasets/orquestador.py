"""Dataset del orquestador: ¿clasifica bien si una petición es para Nexus?

Es una clasificación binaria (válida o no), así que el dataset está equilibrado:
tantos casos ``valid`` como casos de cualquier otro veredicto. Si añades un caso de una
clase, añade otro de la otra.
"""

from evaluation.datasets.definition import Case, DatasetDefinition


def _case(case_id: str, mensaje: str, verdict: str, categoria: str, **kwargs: str) -> Case:
    return Case(case_id, mensaje, {"verdict": verdict}, categoria, **kwargs)  # type: ignore[arg-type]


CASES = [
    # --- válidas (12) ---------------------------------------------------------
    _case("orq-01", "¿A qué hora pasa el último metro por Universitat?", "valid", "horarios"),
    _case("orq-02", "Hi ha obres a la L3 aquesta setmana?", "valid", "incidencias"),
    _case("orq-03", "How much is a ticket to the airport?", "valid", "tarifas"),
    _case("orq-04", "¿Puedo subir con mi perro al metro?", "valid", "normativa"),
    _case("orq-05", "Me he dejado la mochila en el tren", "valid", "objetos"),
    _case("orq-06", "Quiero poner una reclamación", "valid", "acciones"),
    _case("orq-07", "¿Qué puedes hacer?", "valid", "asistente"),
    _case("orq-08", "l1 mañana?", "valid", "horarios"),
    _case("orq-09", "¿Hay ascensor en Les Fonts?", "valid", "accesibilidad"),
    _case(
        "orq-10",
        "Ayer me quedé 40 minutos parado en la L2, ¿me devolvéis el billete?",
        "valid",
        "devoluciones",
    ),
    _case("orq-11", "Avisa'm si hi ha incidències a la L4", "valid", "acciones"),
    _case("orq-12", "¿Cuánto cuesta la T-Jove?", "valid", "tarifas"),
    # --- no válidas (12) ------------------------------------------------------
    _case(
        "orq-13",
        "¿Me recomiendas un restaurante cerca de Plaça Major?",
        "out_of_scope",
        "fuera_de_ambito",
    ),
    _case("orq-14", "Quina és la recepta de la paella?", "out_of_scope", "fuera_de_ambito"),
    _case("orq-15", "Write a Python function that sorts a list", "out_of_scope", "fuera_de_ambito"),
    _case(
        "orq-16",
        "¿Quién ganó el partido del domingo en la Fira?",
        "out_of_scope",
        "fuera_de_ambito",
    ),
    _case("orq-17", "¿Va a llover mañana en Vilaverda?", "out_of_scope", "fuera_de_ambito"),
    _case("orq-18", "Ayúdame con los deberes de mates", "out_of_scope", "fuera_de_ambito"),
    _case(
        "orq-19",
        "¿Qué taxi es más barato para ir al aeropuerto?",
        "out_of_scope",
        "fuera_de_ambito",
    ),
    _case("orq-20", "asdf qwer zxcv", "unintelligible", "ininteligible"),
    _case("orq-21", "el de antes pero al revés y sin eso", "unintelligible", "ininteligible"),
    _case("orq-22", "???", "unintelligible", "ininteligible"),
    _case("orq-23", "", "empty", "vacia"),
    _case("orq-24", "   ", "empty", "vacia"),
]

DATASET = DatasetDefinition(
    name="nexus/orquestador",
    description=(
        "¿El orquestador deja pasar las peticiones de viajeros y rechaza el resto? "
        "24 casos equilibrados: 12 válidos y 12 no válidos."
    ),
    target="orchestrator",
    cases=CASES,
)
