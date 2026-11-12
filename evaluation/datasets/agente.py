"""Dataset del agente completo: lo que preguntan los viajeros y qué debería hacer Nexus.

Cada caso dice qué esperamos, por capas:

- ``tools``: herramientas que Nexus debe usar. ``"a|b"`` significa "a o b".
- ``prohibidas``: herramientas que NO debe usar (por ejemplo, pedir una devolución que
  la normativa no permite).
- ``aprobacion``: si debe proponer una acción que el viajero tiene que aprobar.
- ``menciona``: datos que la respuesta tiene que contener. ``"a|b"`` acepta cualquiera.

Todos los casos están en castellano. Los viajeros también escriben en catalán e inglés.
"""

from evaluation.datasets.definition import Case, DatasetDefinition


def _case(
    case_id: str,
    mensaje: str,
    categoria: str,
    *,
    tools: list[str] | None = None,
    prohibidas: list[str] | None = None,
    aprobacion: bool = False,
    menciona: list[str] | None = None,
    **kwargs: str,
) -> Case:
    expected = {
        "tools": tools or [],
        "prohibidas": prohibidas or [],
        "aprobacion": aprobacion,
        "menciona": menciona or [],
    }
    return Case(case_id, mensaje, expected, categoria, **kwargs)  # type: ignore[arg-type]


CASES = [
    # --- horarios -------------------------------------------------------------
    _case(
        "ag-01",
        "¿A qué hora pasa el primer tren de la L1 por Plaça Major mañana?",
        "horarios",
        tools=["consultar_horario"],
        menciona=["5:04"],
    ),
    _case(
        "ag-02",
        "¿Cuál es el último metro de la L2 en Hospital General el viernes 20?",
        "horarios",
        tools=["consultar_horario"],
        menciona=["2:12"],
    ),
    _case(
        "ag-03",
        "¿Cada cuánto pasa la L4 un sábado a las 18:00?",
        "horarios",
        tools=["consultar_horario"],
        menciona=["6 min"],
    ),
    _case(
        "ag-04",
        "¿La L3 funciona toda la noche del sábado 21?",
        "horarios",
        tools=["consultar_horario|buscar_normativa"],
        menciona=["toda la noche|sin interrup"],
    ),
    _case(
        "ag-05",
        "¿A qué hora abre la L4 en Polígon Sud el domingo 22?",
        "horarios",
        tools=["consultar_horario"],
        menciona=["6:00"],
    ),
    # --- incidencias ----------------------------------------------------------
    _case(
        "ag-06",
        "¿Hay alguna incidencia en la L3 el 12 de noviembre?",
        "incidencias",
        tools=["consultar_incidencias"],
        menciona=["obras"],
        hoy="2026-11-10",
    ),
    _case(
        "ag-07",
        "¿Funcionan los ascensores de Hospital General en la L2?",
        "incidencias",
        tools=["consultar_incidencias"],
        menciona=["ascensor"],
    ),
    _case(
        "ag-08",
        "¿Hay obras en la L1 el sábado?",
        "incidencias",
        tools=["consultar_incidencias"],
        menciona=["Port de Vilaverda|Plaça Major"],
    ),
    _case(
        "ag-09",
        "¿Va a pasar algo raro en el metro mañana por la tarde?",
        "incidencias",
        tools=["consultar_incidencias"],
        menciona=["Plaça Major"],
    ),
    _case(
        "ag-10",
        "¿Qué pasó en la L2 el 9 de noviembre por la mañana?",
        "incidencias",
        tools=["consultar_incidencias"],
        menciona=["averí"],
    ),
    # --- tarifas --------------------------------------------------------------
    _case(
        "ag-11",
        "¿Cuánto cuesta una T-10 de zona 1?",
        "tarifas",
        tools=["consultar_tarifas"],
        menciona=["12,2|12.2"],
    ),
    _case(
        "ag-12",
        "Voy de Plaça Major al Aeroport, ¿me vale la T-10?",
        "tarifas",
        tools=["consultar_tarifas|buscar_normativa"],
        menciona=["5,9|5.9"],
    ),
    _case(
        "ag-13",
        "Tengo 22 años y cojo el metro cada día, ¿qué título me sale mejor?",
        "tarifas",
        tools=["consultar_tarifas|buscar_normativa"],
        menciona=["T-Jove"],
    ),
    # --- normativa ------------------------------------------------------------
    _case(
        "ag-14",
        "¿Puedo llevar a mi perro grande en el metro?",
        "normativa",
        tools=["buscar_normativa"],
        menciona=["bozal"],
    ),
    _case(
        "ag-15",
        "¿Se puede comer en el metro?",
        "normativa",
        tools=["buscar_normativa"],
        menciona=["salud"],
    ),
    _case(
        "ag-16",
        "¿De cuánto es la multa por viajar sin billete?",
        "normativa",
        tools=["buscar_normativa"],
        menciona=["100"],
    ),
    _case(
        "ag-17",
        "¿Puedo entrar con un patinete eléctrico que no se pliega?",
        "normativa",
        tools=["buscar_normativa"],
        menciona=["plega|plegable"],
    ),
    # --- objetos perdidos -----------------------------------------------------
    _case(
        "ag-18",
        "Perdí una bufanda roja en la L1, ¿la habéis encontrado?",
        "objetos",
        tools=["buscar_objeto_perdido"],
        menciona=["Universitat"],
    ),
    _case(
        "ag-19",
        "Me dejé un paraguas rojo en el metro",
        "objetos",
        tools=["buscar_objeto_perdido"],
        menciona=["Fira"],
    ),
    # --- acciones con aprobación ----------------------------------------------
    _case(
        "ag-20",
        "Quiero suscribirme a los avisos de la L2",
        "acciones",
        tools=["suscribir_alertas"],
        aprobacion=True,
        menciona=["L2"],
    ),
    _case(
        "ag-21",
        "Quiero poner una reclamación: el tren de la L4 de esta mañana iba sucísimo",
        "acciones",
        tools=["abrir_reclamacion"],
        aprobacion=True,
    ),
    _case(
        "ag-22",
        "El lunes 9 me quedé 45 minutos parado en la L2 por la avería. Viajaba con billete "
        "sencillo de zona 1. Quiero que me devolváis el dinero.",
        "devoluciones",
        tools=["solicitar_devolucion"],
        aprobacion=True,
        menciona=["2,6|2.6"],
    ),
    # --- devoluciones que no proceden -----------------------------------------
    _case(
        "ag-23",
        "El 5 de noviembre había huelga en la L4 y llegué tarde. Devolvedme el viaje.",
        "devoluciones",
        prohibidas=["solicitar_devolucion"],
        menciona=["huelga|mínimos"],
    ),
    _case(
        "ag-24",
        "Tengo la T-Mes y el 12 de noviembre la L3 estaba cortada. Quiero mi dinero.",
        "devoluciones",
        prohibidas=["solicitar_devolucion"],
        hoy="2026-11-13",
    ),
    _case(
        "ag-25",
        "Esta mañana el metro iba con 10 minutos de retraso, ¿me devolvéis el billete?",
        "devoluciones",
        prohibidas=["solicitar_devolucion"],
        menciona=["30 min"],
    ),
]

DATASET = DatasetDefinition(
    name="nexus/agente",
    description=(
        "Peticiones de viajeros de principio a fin: herramientas que debe usar (y las que no), "
        "acciones que necesitan aprobación y datos que debe dar la respuesta. 25 casos."
    ),
    target="agent",
    cases=CASES,
)
