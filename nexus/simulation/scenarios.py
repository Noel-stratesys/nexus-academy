"""El catálogo de peticiones de los viajeros simulados, con la verdad de cada una.

Cada plantilla es una petición típica (en castellano, catalán o inglés) y sabe calcular,
para un día concreto, qué debería hacer Nexus y qué datos son correctos. La verdad sale
siempre de los datos y de las funciones de las herramientas, nunca de números escritos a
mano: si cambian los datos, cambia la verdad.

``expected`` sigue el formato de ``evaluation/datasets/agente.py`` y añade algunas claves:

- ``verdict``: el veredicto correcto del orquestador.
- ``tools``, ``prohibidas``, ``aprobacion`` y ``menciona``: como en los datasets.
- ``llamadas``: las llamadas a herramientas que haría un buen agente, con argumentos.
- ``quiere_accion``: la acción que pide el viajero (``suscribir_alertas``...), si pide una.
- ``verdad``: los hechos que permiten comprobar la respuesta (fechas, horas, precios...).
- ``historia``: ``pere`` o ``marta`` en los casos de los tickets de la historia.

Las fechas de la semana se calculan bien aquí, aunque ``nexus.calendar`` tenga un fallo:
``verdad["fecha_segun_nexus"]`` dice qué día entendería Nexus, y
``verdad["afectado_por_calendario"]`` si los dos días no coinciden.
"""

import hashlib
import random
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from typing import Any

from nexus.calendar import describe, resolve_day
from nexus.data import estaciones, find_station, load, viajeros
from nexus.data import viajero as buscar_viajero
from nexus.rag.documents import DOCS_DIR
from nexus.simulation.types import Scenario
from nexus.tools.horarios import _clock, _hour_minutes, _minutes, day_type, schedule
from nexus.tools.incidencias import incidents_on
from nexus.tools.proximos import HORA_POR_DEFECTO, panel_tiempo_real

CATEGORIAS = (
    "horarios",
    "incidencias",
    "tarifas",
    "normativa",
    "objetos_perdidos",
    "acciones",
    "devoluciones",
    "fuera_de_ambito",
    "ininteligible",
)

# Cuánto pregunta la gente de cada cosa: los pesos para elegir plantillas al azar.
PESOS_CATEGORIA = {
    "horarios": 26,
    "incidencias": 18,
    "tarifas": 12,
    "normativa": 15,
    "objetos_perdidos": 6,
    "acciones": 8,
    "devoluciones": 7,
    "fuera_de_ambito": 5,
    "ininteligible": 3,
}

# Las preguntas por el próximo tren (capítulo 5) son de las más habituales.
PESO_PROXIMOS = 30

# Viajero que usa cada plantilla cuando no se pide uno concreto.
VIAJERO_POR_IDIOMA = {"es": "1001", "ca": "1002", "en": "1008"}

DIAS = {
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "ca": ["dilluns", "dimarts", "dimecres", "dijous", "divendres", "dissabte", "diumenge"],
    "en": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
}

ACCIONES = ("abrir_reclamacion", "solicitar_devolucion", "suscribir_alertas")

# Lo que dice una buena respuesta cuando no hay trenes, en los tres idiomas.
SIN_SERVICIO = (
    "no hay|sin servicio|no circula|cerrad|no hi ha|sense servei|tancat|no service|no trains|closed"
)
SERVICIO_NORMAL = (
    "normal|sin incidencias|no hay incidencias|amb normalitat|cap incidència|"
    "no incidents|no disruptions"
)


# --- utilidades de la verdad ---------------------------------------------------------


def proximo_dia(indice: int, hoy: date) -> date:
    """El próximo día de la semana ``indice`` (lunes = 0) visto desde ``hoy``; hoy si coincide."""

    return hoy + timedelta(days=(indice - hoy.weekday()) % 7)


def _hora(texto: str) -> str:
    """``05:04`` → ``05:04|5:04``: las dos formas en que una respuesta puede escribirla."""

    corta = texto.lstrip("0") if not texto.startswith("00") else texto[1:]
    return texto if corta == texto else f"{texto}|{corta}"


def _euros(importe: float) -> str:
    """``12.2`` → ``12,20|12.20|12,2|12.2``."""

    return "|".join(
        dict.fromkeys(
            [
                f"{importe:.2f}".replace(".", ","),
                f"{importe:.2f}",
                f"{importe:g}".replace(".", ","),
                f"{importe:g}",
            ]
        )
    )


@cache
def _documento(doc_id: str) -> str:
    return (DOCS_DIR / f"{doc_id}.md").read_text(encoding="utf-8")


def _dato_documento(doc_id: str, patron: str) -> str:
    """El primer grupo de ``patron`` en el documento ``doc_id`` (falla si no está)."""

    match = re.search(patron, _documento(doc_id))
    if match is None:
        raise ValueError(f"No encuentro {patron!r} en {doc_id}")
    return match.group(1)


@cache
def franjas_sin_bici() -> list[tuple[str, str]]:
    """Las franjas de los laborables sin bicicletas no plegables (normativa de 2026)."""

    parrafo = next(
        linea
        for linea in _documento("normativa-viajeros-2026").splitlines()
        if "no plegable" in linea and "de lunes a viernes" in linea
    )
    return re.findall(r"de (\d{1,2}:\d{2}) a (\d{1,2}:\d{2})", parrafo)


def bici_permitida(dia: date, hora: str) -> bool:
    """Si la normativa vigente deja entrar con una bicicleta no plegable ese día y hora."""

    if dia.weekday() >= 5 or dia.isoformat() in load("horarios")["festivos"]:
        return True
    minutos = _minutos(hora)
    return not any(
        _minutos(desde) <= minutos < _minutos(hasta) for desde, hasta in franjas_sin_bici()
    )


def _minutos(hora: str) -> int:
    horas, minutos = hora.split(":")
    return int(horas) * 60 + int(minutos)


def _retraso_minimo_devolucion() -> int:
    return int(_dato_documento("devoluciones-y-reclamaciones", r"retraso de más de (\d+) minutos"))


def _incidencia(incidencia_id: str) -> dict[str, Any]:
    return next(item for item in load("incidencias") if item["id"] == incidencia_id)


def _duracion_minutos(incidencia: dict[str, Any]) -> int:
    desde = datetime.fromisoformat(incidencia["desde"])
    hasta_texto = incidencia["hasta"].replace("T24:00", "T23:59")
    return int((datetime.fromisoformat(hasta_texto) - desde).total_seconds() // 60)


def devolucion_procedente(
    *, titulo: str, retraso_min: int, incidencia_id: str | None
) -> tuple[bool, str]:
    """Si la política de devoluciones permite devolver el viaje, y por qué.

    Las reglas son las de ``nexus/docs/devoluciones-y-reclamaciones.md``.
    """

    descripcion = load("tarifas")["titulos"][titulo]["descripcion"].lower()
    if "ilimitados" in descripcion:
        return False, "título ilimitado"
    if incidencia_id is None:
        return False, "sin incidencia registrada"
    incidencia = _incidencia(incidencia_id)
    if incidencia["tipo"] == "huelga":
        return False, "huelga con servicios mínimos"
    if incidencia["tipo"] == "obras" and incidencia["alternativa"]:
        return False, "obras programadas con servicio alternativo"
    if retraso_min <= _retraso_minimo_devolucion():
        return False, f"retraso de {retraso_min} minutos"
    return True, f"{incidencia['tipo']} de MdV con retraso de {retraso_min} minutos"


# --- plantillas ------------------------------------------------------------------------

Constructor = Callable[[date, str], dict[str, Any]]


@dataclass(frozen=True)
class Plantilla:
    """Una petición típica. ``construir(hoy, viajero)`` devuelve su ``expected``."""

    plantilla_id: str
    categoria: str
    idioma: str
    mensaje: str
    construir: Constructor
    approvals: tuple[str, ...] = ()
    disponible_desde: date | None = None
    # Solo los casos de la historia fijan viajero y día.
    viajero: str | None = None
    hoy: date | None = None

    def disponible(self, hoy: date) -> bool:
        return self.disponible_desde is None or hoy >= self.disponible_desde

    def scenario(self, hoy: date, viajero_id: str | None = None) -> Scenario:
        dia = self.hoy or hoy
        quien = self.viajero or viajero_id or VIAJERO_POR_IDIOMA[self.idioma]
        return Scenario(
            scenario_id=self.plantilla_id,
            categoria=self.categoria,
            viajero=quien,
            idioma=self.idioma,
            hoy=dia,
            mensaje=self.mensaje,
            expected=self.construir(dia, quien),
            approvals=self.approvals,
        )


def _expected(
    *,
    llamadas: list[dict[str, Any]] | None = None,
    tools: list[str] | None = None,
    prohibidas: list[str] | None = None,
    menciona: list[str] | None = None,
    verdad: dict[str, Any] | None = None,
    verdict: str = "valid",
    quiere_accion: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    llamadas = llamadas or []
    return {
        "verdict": verdict,
        "tools": tools if tools is not None else list(dict.fromkeys(c["name"] for c in llamadas)),
        "prohibidas": prohibidas or [],
        "aprobacion": quiere_accion is not None,
        "menciona": menciona or [],
        "llamadas": llamadas,
        "quiere_accion": quiere_accion,
        "verdad": verdad or {},
        **extra,
    }


def _dia(palabra: str, idioma: str, hoy: date) -> date:
    """El día correcto al que se refiere ``palabra`` (``mañana``, ``jueves``...)."""

    relativos = {"hoy": 0, "avui": 0, "today": 0, "mañana": 1, "demà": 1, "tomorrow": 1}
    if palabra in relativos:
        return hoy + timedelta(days=relativos[palabra])
    return proximo_dia(DIAS[idioma].index(palabra), hoy)


def _fechas(palabra: str, idioma: str, hoy: date) -> dict[str, Any]:
    correcta = _dia(palabra, idioma, hoy)
    try:
        segun_nexus = resolve_day(palabra, hoy)
    except ValueError:
        segun_nexus = None
    return {
        "fecha": correcta.isoformat(),
        "fecha_texto": describe(correcta),
        "fecha_segun_nexus": segun_nexus.isoformat() if segun_nexus else None,
        "afectado_por_calendario": segun_nexus is not None and segun_nexus != correcta,
    }


def horario(
    plantilla_id: str,
    idioma: str,
    mensaje: str,
    *,
    linea: str,
    estacion: str,
    dia: str,
    dato: str,
    hora: str | None = None,
) -> Plantilla:
    """Una pregunta de horario. ``dato``: primer_tren, ultimo_tren o frecuencia."""

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        fechas = _fechas(dia, idioma, hoy)
        codigo = find_station(estacion)
        assert codigo is not None, estacion
        resultado = schedule(linea, codigo, date.fromisoformat(fechas["fecha"]), hora)
        if dato == "frecuencia":
            if "frecuencia_min" in resultado:
                menciona = [f"{resultado['frecuencia_min']} min"]
            else:
                menciona = [SIN_SERVICIO]
        elif "toda la noche" in resultado[dato]:
            menciona = ["toda la noche|sin interrup|tota la nit|all night"]
        else:
            menciona = [_hora(resultado[dato])]
        args: dict[str, Any] = {"linea": linea, "estacion": estacion, "dia": dia}
        if hora:
            args["hora"] = hora
        return _expected(
            llamadas=[{"name": "consultar_horario", "args": args}],
            menciona=menciona,
            verdad={**fechas, "dato": dato, "horario": resultado},
        )

    return Plantilla(plantilla_id, "horarios", idioma, mensaje, construir)


def incidencias(
    plantilla_id: str,
    idioma: str,
    mensaje: str,
    *,
    dias: list[str],
    linea: str | None,
    tipo: str | None = None,
    estacion: str | None = None,
    **kwargs: Any,
) -> Plantilla:
    """Una pregunta de incidencias de una línea (o de toda la red si ``linea`` es None)."""

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        lineas = [linea] if linea else sorted(load("red")["lineas"])
        encontradas: list[dict[str, Any]] = []
        fechas = [_fechas(dia, idioma, hoy) for dia in dias]
        for item in fechas:
            for code in lineas:
                encontradas += incidents_on(date.fromisoformat(item["fecha"]), code)
        if tipo:
            encontradas = [inc for inc in encontradas if inc["tipo"] == tipo]
        if estacion:
            nombre = estaciones()[estacion]["nombre"]
            encontradas = [inc for inc in encontradas if nombre in inc["tramo"]]
        ids = list(dict.fromkeys(inc["id"] for inc in encontradas))
        llamadas = [
            {
                "name": "consultar_incidencias",
                "args": {"dia": dia, **({"linea": linea} if linea else {})},
            }
            for dia in dias
        ]
        return _expected(
            llamadas=llamadas,
            menciona=ids or [SERVICIO_NORMAL],
            verdad={
                "fechas": fechas,
                "incidencias": ids,
                "sin_linea": linea is None,
                "afectado_por_calendario": any(item["afectado_por_calendario"] for item in fechas),
            },
        )

    return Plantilla(plantilla_id, "incidencias", idioma, mensaje, construir, **kwargs)


def tarifa(
    plantilla_id: str, idioma: str, mensaje: str, *, titulo: str, precio: str, consulta: str
) -> Plantilla:
    """Una pregunta de precio: ``precio`` es la clave en ``tarifas.json`` (zona o duración)."""

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        importe = load("tarifas")["titulos"][titulo]["precios"][precio]
        return _expected(
            llamadas=[{"name": "consultar_tarifas", "args": {"titulo": consulta}}],
            menciona=[_euros(importe)],
            verdad={"titulo": titulo, "precio": precio, "importe": importe},
        )

    return Plantilla(plantilla_id, "tarifas", idioma, mensaje, construir)


def normativa(
    plantilla_id: str,
    idioma: str,
    mensaje: str,
    *,
    documento: str,
    verdad: Callable[[date], dict[str, Any]],
    menciona: Callable[[date], list[str]] = lambda _hoy: [],
    **kwargs: Any,
) -> Plantilla:
    """Una pregunta de normativa: se responde con ``buscar_normativa``."""

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        return _expected(
            llamadas=[{"name": "buscar_normativa", "args": {"pregunta": mensaje}}],
            menciona=menciona(hoy),
            verdad={"documento": documento, **verdad(hoy)},
        )

    return Plantilla(plantilla_id, "normativa", idioma, mensaje, construir, **kwargs)


def _bici(dia_semana: str, idioma: str, hora: str) -> Callable[[date], dict[str, Any]]:
    def verdad(hoy: date) -> dict[str, Any]:
        dia = _dia(dia_semana, idioma, hoy)
        return {
            "fecha": dia.isoformat(),
            "hora": hora,
            "permitido": bici_permitida(dia, hora),
            "documento_derogado": "normativa-viajeros-2024",
        }

    return verdad


def objeto(
    plantilla_id: str, idioma: str, mensaje: str, *, descripcion: str, linea: str | None
) -> Plantilla:
    """Un objeto perdido. Solo aparece a partir del día en que se encontró."""

    from nexus.tools.objetos import buscar_objeto_perdido

    args = {"descripcion": descripcion, **({"linea": linea} if linea else {})}
    encontrados = buscar_objeto_perdido.invoke(args)["encontrados"]
    desde = max((date.fromisoformat(item["fecha"]) for item in encontrados), default=None)

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        ids = [item["id"] for item in encontrados]
        return _expected(
            llamadas=[{"name": "buscar_objeto_perdido", "args": args}],
            menciona=ids,
            verdad={"encontrados": ids},
        )

    return Plantilla(
        plantilla_id, "objetos_perdidos", idioma, mensaje, construir, disponible_desde=desde
    )


def accion(
    plantilla_id: str,
    idioma: str,
    mensaje: str,
    *,
    tool: str,
    args: dict[str, Any],
    approvals: tuple[str, ...] = ("approve",),
) -> Plantilla:
    """Una petición de acción, que Nexus ejecuta tras la aprobación del viajero."""

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        aprobada = approvals[:1] == ("approve",)
        prefijo = {"suscribir_alertas": "ALR-", "abrir_reclamacion": "REC-"}[tool]
        return _expected(
            llamadas=[{"name": tool, "args": args}],
            quiere_accion=tool,
            menciona=[prefijo] if aprobada else [],
            verdad={"aprobada": aprobada},
        )

    return Plantilla(plantilla_id, "acciones", idioma, mensaje, construir, approvals=approvals)


def devolucion(
    plantilla_id: str,
    idioma: str,
    mensaje: str,
    *,
    titulo: str,
    retraso_min: int,
    incidencia_id: str | None,
    fecha_viaje: date | None = None,
) -> Plantilla:
    """Una petición de devolución, procedente o no según la política de devoluciones."""

    procedente, motivo = devolucion_procedente(
        titulo=titulo, retraso_min=retraso_min, incidencia_id=incidencia_id
    )
    if fecha_viaje is None and incidencia_id is not None:
        fecha_viaje = date.fromisoformat(_incidencia(incidencia_id)["desde"][:10])
    zona = "1"
    importe = load("tarifas")["titulos"][titulo]["precios"].get(zona, 0.0)
    if titulo == "t10":
        importe = round(importe / 10, 2)

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        llamadas: list[dict[str, Any]] = [
            {"name": "buscar_normativa", "args": {"pregunta": "devolución por retraso"}}
        ]
        if incidencia_id and fecha_viaje:
            linea = _incidencia(incidencia_id)["linea"]
            llamadas.append(
                {
                    "name": "consultar_incidencias",
                    "args": {"dia": fecha_viaje.isoformat(), "linea": linea},
                }
            )
        if procedente:
            llamadas.append(
                {
                    "name": "solicitar_devolucion",
                    "args": {
                        "titulo": load("tarifas")["titulos"][titulo]["nombre"],
                        "importe": importe,
                        "motivo": motivo,
                        "incidencia_id": incidencia_id,
                    },
                }
            )
        return _expected(
            llamadas=llamadas,
            tools=["buscar_normativa", *(["solicitar_devolucion"] if procedente else [])],
            prohibidas=[] if procedente else ["solicitar_devolucion"],
            quiere_accion="solicitar_devolucion",
            menciona=[_euros(importe)] if procedente else [],
            verdad={
                "procedente": procedente,
                "motivo": motivo,
                "importe": importe if procedente else 0.0,
                "incidencia": incidencia_id,
                "titulo": load("tarifas")["titulos"][titulo]["nombre"],
                "importe_viaje": importe,
            },
        )

    return Plantilla(
        plantilla_id,
        "devoluciones",
        idioma,
        mensaje,
        construir,
        approvals=("approve",),
        disponible_desde=fecha_viaje + timedelta(days=1) if fecha_viaje else None,
    )


def proximos_trenes(
    plantilla_id: str, idioma: str, mensaje: str, *, linea: str, estacion: str
) -> Plantilla:
    """Una pregunta por los próximos trenes: la responde la herramienta del cambio D.

    La verdad sale del panel de tiempo real, no de la herramienta.
    """

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        codigo = find_station(estacion)
        assert codigo is not None, estacion
        apertura = _minutes(load("horarios")["tipos_dia"][day_type(hoy)]["apertura"])
        desde = _hour_minutes(HORA_POR_DEFECTO, apertura)
        llegadas = panel_tiempo_real(linea, hoy)[codigo.lower()]
        siguientes = [_clock(minuto) for minuto in llegadas if minuto >= desde][:3]
        return _expected(
            llamadas=[{"name": "proximos_trenes", "args": {"linea": linea, "estacion": estacion}}],
            tools=["proximos_trenes"],
            menciona=[_hora(siguientes[0])] if siguientes else [SIN_SERVICIO],
            verdad={"dato": "proximos", "proximos": siguientes},
            peso=PESO_PROXIMOS,
        )

    return Plantilla(plantilla_id, "horarios", idioma, mensaje, construir)


def _proximos() -> list[Plantilla]:
    """Las preguntas por el próximo tren. Solo las hace el simulador del capítulo 5."""

    return [
        proximos_trenes(
            "prox-pma-es",
            "es",
            "¿Cuándo pasa el próximo tren de la L1 por Plaça Major?",
            linea="L1",
            estacion="Plaça Major",
        ),
        proximos_trenes(
            "prox-hge-ca",
            "ca",
            "Quan passa el proper metro de la L4 per Hospital General?",
            linea="L4",
            estacion="Hospital General",
        ),
        proximos_trenes(
            "prox-pll-en",
            "en",
            "When is the next L3 train at Platja Llarga?",
            linea="L3",
            estacion="Platja Llarga",
        ),
    ]


def rechazo(plantilla_id: str, idioma: str, mensaje: str, *, verdict: str) -> Plantilla:
    """Una petición que el orquestador debe rechazar."""

    categoria = "fuera_de_ambito" if verdict == "out_of_scope" else "ininteligible"

    def construir(hoy: date, _viajero: str) -> dict[str, Any]:
        return _expected(verdict=verdict, tools=[], prohibidas=list(ACCIONES))

    return Plantilla(plantilla_id, categoria, idioma, mensaje, construir)


# --- el catálogo -----------------------------------------------------------------------


def _catalogo() -> list[Plantilla]:
    sancion_vapear = _dato_documento("normativa-viajeros-2026", r"Fumar o vapear: (\d+) euros")
    return [
        # horarios
        horario(
            "hor-primer-tren-es",
            "es",
            "¿A qué hora pasa el primer tren de la L1 por Plaça Major mañana?",
            linea="L1",
            estacion="Plaça Major",
            dia="mañana",
            dato="primer_tren",
        ),
        horario(
            "hor-ultimo-tren-ca",
            "ca",
            "A quina hora passa l'últim metro de la L2 per Hospital General avui?",
            linea="L2",
            estacion="Hospital General",
            dia="avui",
            dato="ultimo_tren",
        ),
        horario(
            "hor-frecuencia-en",
            "en",
            "How often does the L4 stop at Fira de Vilaverda tomorrow around 18:00?",
            linea="L4",
            estacion="Fira de Vilaverda",
            dia="tomorrow",
            dato="frecuencia",
            hora="18:00",
        ),
        horario(
            "hor-frecuencia-sabado-es",
            "es",
            "¿Cada cuánto pasa la L3 por Universitat el sábado a las 11:00?",
            linea="L3",
            estacion="Universitat",
            dia="sábado",
            dato="frecuencia",
            hora="11:00",
        ),
        horario(
            "hor-sin-servicio-es",
            "es",
            "Tengo que coger la L2 en Estació Central hoy a las 3:30 de la madrugada, "
            "¿cada cuánto pasa?",
            linea="L2",
            estacion="Estació Central",
            dia="hoy",
            dato="frecuencia",
            hora="03:30",
        ),
        horario(
            "hor-sin-servicio-en",
            "en",
            "Is there any L4 train at Torre Blava tomorrow at 4:15 in the morning?",
            linea="L4",
            estacion="Torre Blava",
            dia="tomorrow",
            dato="frecuencia",
            hora="04:15",
        ),
        horario(
            "hor-ultimo-divendres-ca",
            "ca",
            "Quin és l'últim tren de la L1 a Universitat divendres?",
            linea="L1",
            estacion="Universitat",
            dia="divendres",
            dato="ultimo_tren",
        ),
        horario(
            "hor-primer-domingo-en",
            "en",
            "What time is the first L3 train at Platja Llarga on Sunday?",
            linea="L3",
            estacion="Platja Llarga",
            dia="sunday",
            dato="primer_tren",
        ),
        horario(
            "hor-nocturno-es",
            "es",
            "¿La L3 funciona toda la noche del sábado en Rambla de les Flors?",
            linea="L3",
            estacion="Rambla de les Flors",
            dia="sábado",
            dato="ultimo_tren",
        ),
        horario(
            "hor-aeroport-en",
            "en",
            "When does the last L2 train leave from Aeroport today?",
            linea="L2",
            estacion="Aeroport",
            dia="today",
            dato="ultimo_tren",
        ),
        horario(
            "hor-primer-dilluns-ca",
            "ca",
            "A quina hora surt el primer metro de la L4 de Polígon Sud dilluns?",
            linea="L4",
            estacion="Polígon Sud",
            dia="dilluns",
            dato="primer_tren",
        ),
        # incidencias
        incidencias(
            "inc-l3-jueves-es",
            "es",
            "¿La L3 funciona con normalidad el jueves?",
            dias=["jueves"],
            linea="L3",
        ),
        incidencias(
            "inc-l2-dimarts-ca",
            "ca",
            "Hi haurà algun problema a la L2 dimarts?",
            dias=["dimarts"],
            linea="L2",
        ),
        incidencias(
            "inc-l4-thursday-en",
            "en",
            "Is the L4 running normally on Thursday?",
            dias=["thursday"],
            linea="L4",
        ),
        incidencias(
            "inc-manana-sin-linea-es",
            "es",
            "¿Pasa algo mañana en el metro?",
            dias=["mañana"],
            linea=None,
        ),
        incidencias(
            "inc-dema-sense-linia-ca",
            "ca",
            "Hi ha alguna incidència al metro demà?",
            dias=["demà"],
            linea=None,
        ),
        incidencias(
            "inc-l2-hoy-es",
            "es",
            "¿Hay alguna incidencia hoy en la L2?",
            dias=["hoy"],
            linea="L2",
        ),
        incidencias(
            "inc-l1-finde-es",
            "es",
            "¿Hay obras en la L1 este fin de semana?",
            dias=["sábado", "domingo"],
            linea="L1",
        ),
        incidencias(
            "inc-ascensor-hge-ca",
            "ca",
            "Funcionen els ascensors de l'Hospital General avui?",
            dias=["avui"],
            linea="L2",
            tipo="accesibilidad",
            estacion="HGE",
        ),
        # tarifas
        tarifa(
            "tar-t10-es",
            "es",
            "¿Cuánto cuesta la T-10 de una zona?",
            titulo="t10",
            precio="1",
            consulta="T-10",
        ),
        tarifa(
            "tar-tmes-ca",
            "ca",
            "Quant val la T-Mes de dues zones?",
            titulo="tmes",
            precio="2",
            consulta="T-Mes",
        ),
        tarifa(
            "tar-aeroport-en",
            "en",
            "How much is a ticket to the airport? Can I use my T-10?",
            titulo="aeroport",
            precio="unico",
            consulta="aeroport",
        ),
        tarifa(
            "tar-tjove-es",
            "es",
            "¿Qué precio tiene la T-Jove?",
            titulo="tjove",
            precio="1",
            consulta="T-Jove",
        ),
        tarifa(
            "tar-turista-en",
            "en",
            "How much is the T-Turista for 72 hours?",
            titulo="tturista",
            precio="72h",
            consulta="T-Turista",
        ),
        tarifa(
            "tar-senzill-ca",
            "ca",
            "Quant costa un bitllet senzill per a tres zones?",
            titulo="senzill",
            precio="3",
            consulta="senzill",
        ),
        # normativa
        normativa(
            "nor-bici-martes-es",
            "es",
            "¿Puedo subir con la bici al metro un martes a las 8:15?",
            documento="normativa-viajeros-2026",
            verdad=_bici("martes", "es", "8:15"),
            menciona=lambda hoy: ["no"],
        ),
        normativa(
            "nor-bici-dissabte-ca",
            "ca",
            "Puc pujar al metro amb la bici dissabte a les 10?",
            documento="normativa-viajeros-2026",
            verdad=_bici("dissabte", "ca", "10:00"),
            menciona=lambda hoy: ["sí|si|pots"],
        ),
        normativa(
            "nor-perro-es",
            "es",
            "¿Puedo llevar a mi perro grande en el metro?",
            documento="viajar-con-mascotas",
            verdad=lambda hoy: {"condiciones": ["correa", "bozal"]},
            menciona=lambda hoy: ["bozal"],
        ),
        normativa(
            "nor-patinete-en",
            "en",
            "Can I bring my electric scooter on the metro?",
            documento="normativa-viajeros-2026",
            verdad=lambda hoy: {"permitido": "solo plegable, plegado y apagado"},
            menciona=lambda hoy: ["fold"],
        ),
        normativa(
            "nor-accesible-es",
            "es",
            "¿La estación de Les Fonts es accesible en silla de ruedas?",
            documento="accesibilidad",
            verdad=lambda hoy: {"accesible": estaciones()["FON"]["accesible"]},
            menciona=lambda hoy: ["no" if not estaciones()["FON"]["accesible"] else "sí"],
        ),
        normativa(
            "nor-vapear-ca",
            "ca",
            "Es pot vapejar a l'andana? Quina multa hi ha?",
            documento="normativa-viajeros-2026",
            verdad=lambda hoy: {"permitido": False, "sancion_euros": int(sancion_vapear)},
            menciona=lambda hoy: [sancion_vapear],
        ),
        # objetos perdidos
        objeto(
            "obj-paraguas-es",
            "es",
            "Perdí un paraguas negro en la L1, ¿lo habéis encontrado?",
            descripcion="paraguas negro",
            linea="L1",
        ),
        objeto(
            "obj-motxilla-ca",
            "ca",
            "He perdut una motxilla blava a la L2. L'heu trobat?",
            descripcion="mochila azul",
            linea="L2",
        ),
        objeto(
            "obj-keys-en",
            "en",
            "I lost my keys at the airport station. Has anyone found them?",
            descripcion="llaves",
            linea="L2",
        ),
        # acciones
        accion(
            "acc-alertas-l3-es",
            "es",
            "Quiero recibir avisos de las incidencias de la L3.",
            tool="suscribir_alertas",
            args={"linea": "L3"},
        ),
        accion(
            "acc-alertas-l2-en",
            "en",
            "Please subscribe me to the L2 alerts.",
            tool="suscribir_alertas",
            args={"linea": "L2"},
        ),
        accion(
            "acc-reclamacion-ca",
            "ca",
            "Vull posar una reclamació: ahir un empleat de la L1 em va tractar molt malament.",
            tool="abrir_reclamacion",
            args={
                "motivo": "trato recibido",
                "detalle": "Trato incorrecto de un empleado en la L1.",
            },
        ),
        accion(
            "acc-reclamacion-rechazada-es",
            "es",
            "Quiero poner una reclamación porque esta mañana el tren de la L4 iba lleno.",
            tool="abrir_reclamacion",
            args={"motivo": "aglomeración", "detalle": "Tren de la L4 lleno por la mañana."},
            approvals=("No, déjalo, prefiero no hacerlo ahora.",),
        ),
        # devoluciones
        devolucion(
            "dev-averia-l2-es",
            "es",
            "El lunes 9 me quedé 45 minutos parado en la L2 por una avería. Viajaba con la "
            "T-10. ¿Me devolvéis el viaje?",
            titulo="t10",
            retraso_min=45,
            incidencia_id="INC-0291",
        ),
        devolucion(
            "dev-huelga-l4-ca",
            "ca",
            "Dijous 5 hi va haver vaga a la L4 i vaig arribar tard. Em torneu els diners del "
            "bitllet senzill?",
            titulo="senzill",
            retraso_min=40,
            incidencia_id="INC-0297",
        ),
        devolucion(
            "dev-tmes-retraso-es",
            "es",
            "Tengo la T-Mes y hoy el tren se ha retrasado 10 minutos. Quiero que me devolváis "
            "el dinero.",
            titulo="tmes",
            retraso_min=10,
            incidencia_id=None,
        ),
        devolucion(
            "dev-obras-l3-en",
            "en",
            "The L3 was closed for works on the 12th and I had to take the shuttle bus. I paid "
            "a single ticket and I want a refund.",
            titulo="senzill",
            retraso_min=20,
            incidencia_id="INC-0301",
        ),
        # fuera de ámbito
        rechazo(
            "fue-restaurante-es",
            "es",
            "¿Me recomiendas un restaurante cerca de Plaça Major?",
            verdict="out_of_scope",
        ),
        rechazo(
            "fue-futbol-ca",
            "ca",
            "Qui va guanyar el partit del Vilaverda ahir?",
            verdict="out_of_scope",
        ),
        rechazo(
            "fue-poema-en",
            "en",
            "Write me a short poem about the sea.",
            verdict="out_of_scope",
        ),
        # ininteligible
        rechazo("inint-es", "es", "eso de la cosa del otro día???", verdict="unintelligible"),
        rechazo("inint-ca", "ca", "allò d'abans, ja saps, el de la", verdict="unintelligible"),
        rechazo("inint-en", "en", "the thing with the stuff again??", verdict="unintelligible"),
    ]


def _historia() -> list[Plantilla]:
    """Los dos tickets de la historia, con su viajero y su día exactos."""

    pere = incidencias(
        "historia-pere",
        "es",
        "Hola, ¿la L3 funciona con normalidad el jueves? Tengo que ir a trabajar.",
        dias=["jueves"],
        linea="L3",
        viajero="1042",
        hoy=date(2026, 11, 10),
    )
    marta = normativa(
        "historia-marta",
        "es",
        "¿Puedo subir al metro con la bici un martes a las 8:15?",
        documento="normativa-viajeros-2026",
        verdad=_bici("martes", "es", "8:15"),
        menciona=lambda hoy: ["no"],
        viajero="1017",
        hoy=date(2026, 11, 3),
    )
    return [_con_historia(pere, "pere"), _con_historia(marta, "marta")]


def _con_historia(plantilla: Plantilla, nombre: str) -> Plantilla:
    construir = plantilla.construir

    def con_historia(hoy: date, quien: str) -> dict[str, Any]:
        return {**construir(hoy, quien), "historia": nombre}

    return Plantilla(
        plantilla.plantilla_id,
        plantilla.categoria,
        plantilla.idioma,
        plantilla.mensaje,
        con_historia,
        plantilla.approvals,
        plantilla.disponible_desde,
        plantilla.viajero,
        plantilla.hoy,
    )


@cache
def plantillas() -> tuple[Plantilla, ...]:
    """Todas las plantillas: el catálogo general y, al final, los casos de la historia."""

    return (*_catalogo(), *_historia())


def scenarios(
    hoy: date | None = None,
    *,
    viajero: str | None = None,
    categorias: Iterable[str] | None = None,
    idiomas: Iterable[str] | None = None,
    historia: bool = False,
    proximos: bool = False,
) -> list[Scenario]:
    """Las peticiones del catálogo para ``hoy``, con su verdad calculada ese día.

    Con ``viajero``, solo las de su idioma y a su nombre. Los casos de la historia (Pere
    y Marta) tienen día y viajero fijos y solo se incluyen con ``historia=True``. Las
    preguntas por el próximo tren (capítulo 5) solo se incluyen con ``proximos=True``.
    """

    from nexus.settings import settings

    dia = hoy or settings.nexus_today
    persona = buscar_viajero(viajero) if viajero else None
    if viajero and persona is None:
        raise ValueError(f"No existe el viajero {viajero}")
    wanted_cats = set(categorias) if categorias is not None else None
    wanted_langs = set(idiomas) if idiomas is not None else None
    if persona is not None:
        wanted_langs = {persona.idioma} & (wanted_langs or {persona.idioma})
    result = []
    for plantilla in (*plantillas(), *(_proximos() if proximos else ())):
        es_historia = plantilla.hoy is not None
        if es_historia and not historia:
            continue
        if wanted_cats is not None and plantilla.categoria not in wanted_cats:
            continue
        if wanted_langs is not None and plantilla.idioma not in wanted_langs:
            continue
        if not es_historia and not plantilla.disponible(dia):
            continue
        result.append(plantilla.scenario(dia, None if es_historia else viajero))
    return result


def story_scenarios() -> dict[str, Scenario]:
    """Los casos de la historia por nombre: ``pere`` y ``marta``."""

    return {
        str(scenario.expected["historia"]): scenario
        for scenario in scenarios(historia=True)
        if "historia" in scenario.expected
    }


def pick_scenario(
    rng: random.Random, hoy: date, viajero_id: str | None = None, *, proximos: bool = False
) -> Scenario:
    """Una petición al azar para ``hoy``, de un viajero al azar si no se indica."""

    quien = viajero_id or rng.choice(sorted(viajeros()))
    catalogo = scenarios(hoy, viajero=quien, proximos=proximos)
    pesos = [
        scenario.expected.get("peso", PESOS_CATEGORIA[scenario.categoria]) for scenario in catalogo
    ]
    return rng.choices(catalogo, weights=pesos, k=1)[0]


def stable_fraction(*parts: object) -> float:
    """Un número en [0, 1) que depende solo de ``parts``: azar reproducible."""

    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64
