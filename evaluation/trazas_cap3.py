"""Las 10 trazas del capítulo 3, para calibrar los jueces.

``uv run seed`` las sube en la instalación. Este comando sirve para reponerlas:

    uv run trazas-cap3            # sube las que falten
    uv run trazas-cap3 --forzar   # las borra (con sus scores) y las vuelve a subir

Son conversaciones de Nexus escritas a mano: una pregunta de un viajero, las herramientas
que consultó Nexus con lo que devolvieron y la respuesta. Todas las respuestas son fieles
a lo que dijeron las herramientas; lo que cambia de una a otra es **el tono** y **si
responden a lo que se preguntó**. Sobre ellas se calibran los dos jueces de la misión:

- ``tono``: el criterio que escribes tú.
- ``answer_relevance``: la plantilla *Check Answer Relevance* de Langfuse.

Cada traza tiene la etiqueta ``cap3`` y el entorno ``cap3``, para que los jueces y la
annotation queue se apliquen solo a ellas y no se mezclen con el tráfico de producción.
Los identificadores son siempre los mismos: volver a lanzar el comando no las duplica.
"""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nexus.settings import initialize_environment

ETIQUETA = "cap3"
ENTORNO = "cap3"
NOMBRE = "nexus-agent"


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    argumentos: dict[str, Any]
    salida: dict[str, Any]


@dataclass(frozen=True)
class Traza:
    id: str
    viajero: str
    pregunta: str
    respuesta: str
    herramientas: list[Herramienta] = field(default_factory=list)


_T10 = {
    "nombre": "T-10",
    "descripcion": "10 viajes, multipersonal, con transbordos durante 75 minutos.",
    "precios": {"1": 12.2, "2": 23.1, "3": 31.4},
}
_DEVOLUCIONES = "devoluciones-y-reclamaciones"

TRAZAS: list[Traza] = [
    Traza(
        id="cap3-01",
        viajero="2101",
        pregunta="¿Cuánto cuesta una T-10 de zona 1?",
        herramientas=[
            Herramienta("consultar_tarifas", {"titulo": "T-10"}, {"moneda": "EUR", "t10": _T10})
        ],
        respuesta=(
            "La T-10 de zona 1 cuesta 12,20 €. Son 10 viajes, la podéis compartir varias "
            "personas y permite hacer transbordos durante 75 minutos desde que la validas. "
            "¡Buen viaje!"
        ),
    ),
    Traza(
        id="cap3-02",
        viajero="2102",
        pregunta=(
            "El lunes 9 por la mañana me quedé 40 minutos parado en la L2 y llegué tarde a una "
            "cita en el médico. ¿Esto se puede reclamar?"
        ),
        herramientas=[
            Herramienta(
                "consultar_incidencias",
                {"dia": "2026-11-09", "linea": "L2"},
                {
                    "fecha": "lunes 9 de noviembre de 2026",
                    "linea": "L2",
                    "incidencias": [
                        {
                            "id": "INC-0291",
                            "tipo": "averia",
                            "desde": "2026-11-09T08:10",
                            "hasta": "2026-11-09T08:55",
                            "descripcion": (
                                "Avería de un tren entre Sant Martí de Dalt y Hospital General. "
                                "Retrasos de hasta 45 minutos."
                            ),
                        }
                    ],
                    "estado": "con incidencias",
                },
            ),
            Herramienta(
                "buscar_normativa",
                {"pregunta": "devolución por retraso de una avería"},
                {
                    "fragmentos": [
                        {
                            "documento": "Política de devoluciones y reclamaciones",
                            "seccion": "Cuándo se devuelve el importe de un viaje",
                            "texto": (
                                "MdV devuelve el importe del viaje en estos casos: 1. Un retraso "
                                "de más de 30 minutos causado por una incidencia del servicio de "
                                "MdV (por ejemplo, una avería de un tren), registrada en el "
                                "sistema de incidencias."
                            ),
                        },
                        {
                            "documento": "Política de devoluciones y reclamaciones",
                            "seccion": "Plazo y forma",
                            "texto": (
                                "La devolución se pide en los 30 días siguientes al viaje, con el "
                                "número de la incidencia si se conoce. El abono se hace en 10 "
                                "días hábiles."
                            ),
                        },
                    ]
                },
            ),
        ],
        respuesta=(
            "Siento mucho que llegaras tarde a tu cita, entiendo que es un mal trago. Ese día "
            "hubo una avería de un tren entre Sant Martí de Dalt y Hospital General, de 8:10 a "
            "8:55, con retrasos de hasta 45 minutos (incidencia INC-0291).\n\n"
            "Como el retraso fue de más de 30 minutos por una avería de MdV, tienes derecho a "
            "la devolución del viaje. Puedes pedirla en los 30 días siguientes y el abono llega "
            "en 10 días hábiles. Si quieres, la solicito yo ahora con el número de la incidencia."
        ),
    ),
    Traza(
        id="cap3-03",
        viajero="2103",
        pregunta="Mañana vuelo. ¿Puedo ir al aeropuerto con mi T-10? ¿Y cuánto cuesta el billete?",
        herramientas=[
            Herramienta(
                "consultar_tarifas",
                {"titulo": "aeroport"},
                {
                    "moneda": "EUR",
                    "aeroport": {
                        "nombre": "Billete Aeroport",
                        "descripcion": (
                            "Un viaje con origen o destino Aeroport desde cualquier zona. Los "
                            "títulos T-10 y T-Mes no son válidos en Aeroport."
                        ),
                        "precios": {"unico": 5.9},
                    },
                },
            )
        ],
        respuesta=(
            "¡Qué bien, buen viaje! El Billete Aeroport cuesta 5,90 € y vale para un viaje "
            "desde cualquier zona de la red hasta el aeropuerto. Lo encontrarás en las máquinas "
            "de cualquier estación. ¡Que tengas muy buen vuelo!"
        ),
    ),
    Traza(
        id="cap3-04",
        viajero="2104",
        pregunta="Ayer me dejé una mochila azul en la L2. ¿La habéis encontrado?",
        herramientas=[
            Herramienta(
                "buscar_objeto_perdido",
                {"descripcion": "mochila azul", "linea": "L2"},
                {
                    "encontrados": [
                        {
                            "id": "OBJ-5530",
                            "descripcion": "Mochila azul con portátil",
                            "linea": "L2",
                            "estacion": "Hospital General",
                            "fecha": "2026-11-04",
                        }
                    ],
                    "como_recoger": (
                        "Oficina de objetos perdidos de Estació Central, de 8:00 a 20:00, con DNI."
                    ),
                },
            ),
            Herramienta(
                "consultar_incidencias",
                {"dia": "hoy", "linea": "L2"},
                {
                    "fecha": "miércoles 18 de noviembre de 2026",
                    "linea": "L2",
                    "incidencias": [
                        {
                            "id": "INC-0294",
                            "tipo": "accesibilidad",
                            "desde": "2026-11-02T05:00",
                            "hasta": "2026-11-27T24:00",
                            "descripcion": (
                                "Uno de los dos ascensores de Hospital General está fuera de "
                                "servicio por sustitución. El otro funciona con normalidad."
                            ),
                        }
                    ],
                    "estado": "con incidencias",
                },
            ),
        ],
        respuesta=(
            "¡Hola! Muchas gracias por escribirnos, es un placer ayudarte. Te cuento cómo está "
            "hoy la L2: uno de los dos ascensores de Hospital General está fuera de servicio por "
            "sustitución hasta el 27 de noviembre, aunque el otro funciona con normalidad. Si te "
            "va bien, puedo suscribirte a los avisos de la L2 para que te enteres al momento de "
            "cualquier novedad. ¡Que tengas un día estupendo!"
        ),
    ),
    Traza(
        id="cap3-05",
        viajero="2105",
        pregunta="¿Cuánto cuesta la T-Jove y hasta qué edad se puede usar?",
        herramientas=[
            Herramienta(
                "consultar_tarifas",
                {"titulo": "T-Jove"},
                {
                    "moneda": "EUR",
                    "tjove": {
                        "nombre": "T-Jove",
                        "descripcion": (
                            "Viajes ilimitados durante 90 días para menores de 26 años. Personal."
                        ),
                        "precios": {"1": 45.0, "2": 45.0, "3": 45.0},
                    },
                },
            )
        ],
        respuesta="T-Jove: 45,00 €. Todas las zonas. 90 días ilimitados. Menores de 26. Personal.",
    ),
    Traza(
        id="cap3-06",
        viajero="2106",
        pregunta=(
            "Al comprar la T-Mes en la máquina me la han cobrado dos veces. ¿Cómo pido que me "
            "devuelvan el dinero y cuánto tardáis en devolverlo?"
        ),
        herramientas=[
            Herramienta(
                "buscar_normativa",
                {"pregunta": "devolución por cobro duplicado de un título"},
                {
                    "fragmentos": [
                        {
                            "documento": "Política de devoluciones y reclamaciones",
                            "seccion": "Cuándo se devuelve el importe de un viaje",
                            "texto": (
                                "MdV devuelve el importe del viaje en estos casos: [...] 2. Un "
                                "cobro duplicado al comprar un título."
                            ),
                        },
                        {
                            "documento": "Política de devoluciones y reclamaciones",
                            "seccion": "Plazo y forma",
                            "texto": (
                                "La devolución se pide en los 30 días siguientes al viaje, con el "
                                "número de la incidencia si se conoce. El abono se hace en 10 "
                                "días hábiles."
                            ),
                        },
                    ]
                },
            )
        ],
        respuesta=(
            "Según la política de devoluciones vigente, los cobros duplicados en la compra de "
            "títulos son objeto de devolución. La solicitud debe realizarse dentro de los 30 "
            "días siguientes. Proceda a tramitarla."
        ),
    ),
    Traza(
        id="cap3-07",
        viajero="2107",
        pregunta="¿A qué hora pasa el último metro de la L1 por Universitat este sábado?",
        herramientas=[
            Herramienta(
                "consultar_incidencias",
                {"dia": "sábado", "linea": "L3"},
                {
                    "fecha": "sábado 21 de noviembre de 2026",
                    "linea": "L3",
                    "incidencias": [],
                    "estado": "servicio normal",
                },
            )
        ],
        respuesta=(
            "Consulta realizada. Línea L3, sábado 21 de noviembre de 2026: servicio normal. No "
            "constan incidencias."
        ),
    ),
    Traza(
        id="cap3-08",
        viajero="2108",
        pregunta="¿Puedo subir al metro con mi patinete eléctrico?",
        herramientas=[
            Herramienta(
                "buscar_normativa",
                {"pregunta": "patinete eléctrico en el metro"},
                {
                    "fragmentos": [
                        {
                            "documento": "Normativa de viajeros 2026",
                            "seccion": "3. Patinetes y otros vehículos de movilidad personal",
                            "texto": (
                                "Los patinetes eléctricos solo pueden entrar si son plegables, "
                                "van plegados y apagados durante todo el recorrido por la "
                                "estación y el tren. No se pueden cargar en las instalaciones de "
                                "MdV. Los patinetes eléctricos no plegables, los monociclos "
                                "eléctricos y los segways no están permitidos."
                            ),
                        },
                        {
                            "documento": "Normativa de viajeros 2026",
                            "seccion": "Sanciones",
                            "texto": (
                                "Acceder con un patinete eléctrico no permitido o cargarlo en la "
                                "instalación: 60 euros."
                            ),
                        },
                    ]
                },
            )
        ],
        respuesta=(
            "A ver, que tampoco es tan difícil: solo si es plegable, y lo llevas plegado y "
            "apagado todo el rato. Si no se pliega, ni lo intentes, que son 60 euros de multa. "
            "Y ni se te ocurra cargarlo en un enchufe de la estación. Está todo en la normativa; "
            "la próxima vez léetela antes de preguntar."
        ),
    ),
    Traza(
        id="cap3-09",
        viajero="2109",
        pregunta=(
            "Mi T-10 no pasa por el torno de Plaça Major, da error todo el rato. ¿Qué hago con "
            "ella? ¿Y cómo entro ahora? Tengo prisa."
        ),
        herramientas=[
            Herramienta(
                "buscar_normativa",
                {"pregunta": "título que no se puede validar"},
                {
                    "fragmentos": [
                        {
                            "documento": "Política de devoluciones y reclamaciones",
                            "seccion": "Cuándo se devuelve el importe de un viaje",
                            "texto": (
                                "MdV devuelve el importe del viaje en estos casos: [...] 3. Un "
                                "título defectuoso que no se puede validar, siempre que se "
                                "entregue en una oficina de atención."
                            ),
                        }
                    ]
                },
            )
        ],
        respuesta=(
            "Lo más probable es que la estés pasando mal, eso pasa mucho. Si de verdad está "
            "estropeada, llévala a una oficina de atención y ya te devolverán lo que toque."
        ),
    ),
    Traza(
        id="cap3-10",
        viajero="2110",
        pregunta="¿Hay huelga el jueves 5 en la L4? Tengo que ir a trabajar.",
        herramientas=[
            Herramienta("consultar_tarifas", {"titulo": "T-10"}, {"moneda": "EUR", "t10": _T10})
        ],
        respuesta=(
            "Eso pregúntalo en otro sitio, yo estoy para lo que estoy. Lo que sí te digo es que "
            "la T-10 de zona 1 sale a 12,20 €, ¿vale?"
        ),
    ),
]


def trace_id(langfuse: Any, traza: Traza) -> str:
    """El id de la traza: sale de su nombre, así que siempre es el mismo."""

    return langfuse.create_trace_id(seed=f"nexus-academy-{traza.id}")


def subir(langfuse: Any, traza: Traza) -> None:
    """Escribe la traza con la misma forma que una de Nexus: agente, herramientas, respuesta."""

    from langfuse import propagate_attributes

    with propagate_attributes(
        trace_name=NOMBRE,
        session_id=traza.id,
        user_id=traza.viajero,
        tags=[ETIQUETA],
        metadata={"caso": traza.id, "idioma": "es"},
        environment=ENTORNO,
    ):
        with langfuse.start_as_current_observation(
            trace_context={"trace_id": trace_id(langfuse, traza)},
            name=NOMBRE,
            as_type="agent",
            input={"mensaje": traza.pregunta},
        ) as root:
            for herramienta in traza.herramientas:
                with langfuse.start_as_current_observation(
                    name=herramienta.nombre, as_type="tool", input=herramienta.argumentos
                ) as tool:
                    tool.update(output=herramienta.salida)
            root.update(output={"respuesta": traza.respuesta})


def _existe(langfuse: Any, trace_id_: str) -> bool:
    respuesta = langfuse.api.observations.get_many(
        trace_id=trace_id_, is_root_observation=True, fields="core", limit=1
    )
    return bool(respuesta.data)


def _borrar(langfuse: Any, ids: list[str], espera_maxima_s: float = 300) -> None:
    """Borra esas trazas (y sus scores) y espera a que Langfuse termine de borrarlas."""

    langfuse.api.trace.delete_multiple(trace_ids=ids)
    limite = time.monotonic() + espera_maxima_s
    while any(_existe(langfuse, id_) for id_ in ids):
        if time.monotonic() > limite:
            sys.exit("✘ Langfuse todavía no ha borrado las trazas. Espera un poco y repite.")
        time.sleep(5)


def cargar(
    langfuse: Any,
    *,
    forzar: bool = False,
    buffer: Any = None,
    report: Callable[[str], None] = print,
) -> int:
    """Sube las trazas que falten (todas, con ``forzar``) y devuelve cuántas ha subido.

    ``uv run seed`` pasa su ``buffer``: su cliente de Langfuse guarda los spans en memoria en
    vez de mandarlos, así que aquí se mandan a mano.
    """

    ids = {traza.id: trace_id(langfuse, traza) for traza in TRAZAS}
    if forzar:
        report("  Borrando las trazas del capítulo 3 y sus scores…")
        _borrar(langfuse, list(ids.values()))

    pendientes = [t for t in TRAZAS if forzar or not _existe(langfuse, ids[t.id])]
    for traza in pendientes:
        subir(langfuse, traza)
    langfuse.flush()
    if buffer is not None and pendientes:
        from nexus.simulation.trazas import exportador_langfuse, exportar

        exportador = exportador_langfuse()
        try:
            exportar(exportador, buffer.take())
        finally:
            exportador.shutdown()

    report(
        f"  {len(pendientes)} subidas, {len(TRAZAS) - len(pendientes)} ya estaban "
        f"(etiqueta «{ETIQUETA}», entorno «{ENTORNO}»)"
    )
    return len(pendientes)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="trazas-cap3",
        description="Sube a Langfuse las 10 trazas del capítulo 3 (uv run seed ya lo hace).",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Borra las trazas (y los scores que tengan) y las vuelve a subir.",
    )
    args = parser.parse_args(argv)
    # Las terminales de Windows no siempre escriben en UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    initialize_environment()
    from langfuse import get_client

    print("Trazas del capítulo 3:")
    cargar(get_client(), forzar=args.forzar)
