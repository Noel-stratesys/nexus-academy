"""Dataset de desarrollo del proyecto final: el bus nocturno y el servicio de asistencia.

Mismo esquema que ``nexus/agente`` (``tools``, ``prohibidas``, ``aprobacion``,
``menciona``) más ``responde`` en las preguntas de normativa, para medir la abstención.
"Hoy" es el viernes 20 de noviembre de 2026 en todos los casos.

Los datos esperados no se escriben a mano: se calculan con los JSON de
``proyecto-final/datos``. Así, si cambia un dato, el dataset cambia con él.

Equilibrio de las dos clases binarias que comparan los evaluadores:

- ``aprobacion`` (solo en peticiones de reserva): tantas reservas que proceden
  (``True``) como reservas que Nexus no debe proponer (``False``).
- ``responde`` (solo en preguntas sobre los documentos): tantas preguntas con respuesta
  en los documentos como preguntas a las que Nexus debe contestar que no lo sabe.

El resto de casos (horarios del bus y estado de ascensores) no tiene ninguna de esas
dos claves.
"""

import json
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from evaluation.datasets.definition import Case, DatasetDefinition
from nexus.data import estaciones, lineas, load

DATOS_DIR = Path(__file__).resolve().parents[2] / "proyecto-final" / "datos"
HOY = date(2026, 11, 20)

# Nombres de las herramientas del contrato del proyecto final.
BUS = "consultar_bus_nocturno"
ASCENSORES = "estado_ascensores"
RESERVA = "reservar_asistencia"
NORMATIVA = "buscar_normativa"


# --- Datos del proyecto final --------------------------------------------------


@cache
def datos(nombre: str) -> Any:
    """El contenido de ``proyecto-final/datos/<nombre>.json``."""

    return json.loads((DATOS_DIR / f"{nombre}.json").read_text(encoding="utf-8"))


def _minutos(texto: str) -> int:
    horas, minutos = texto.split(":")
    return int(horas) * 60 + int(minutos)


def hora(minutos: int) -> str:
    """``2:10`` (sin cero delante): también aparece dentro de ``02:10``."""

    minutos %= 24 * 60
    return f"{minutos // 60}:{minutos % 60:02d}"


def es_festivo(dia: date) -> bool:
    return dia.isoformat() in load("horarios")["festivos"]


# --- Bus nocturno ----------------------------------------------------------------


def tipo_noche(dia: date) -> str:
    """El tipo de la noche que empieza ``dia``."""

    if dia.weekday() == 5 or es_festivo(dia + timedelta(days=1)):
        return "sabado_y_vispera"
    if dia.weekday() == 4:
        return "viernes"
    return "domingo_a_jueves"


def salidas(linea: str, dia: date) -> dict[str, int] | None:
    """Primera y última salida (en minutos) y frecuencia; ``None`` si esa noche no pasa."""

    bus = datos("bus_nocturno")
    tipo = tipo_noche(dia)
    if tipo not in bus["lineas"][linea]["noches"]:
        return None
    reglas = {**bus["tipos_noche"][tipo], **bus["excepciones"].get(dia.isoformat(), {})}
    return {
        "primera": _minutos(reglas["primera_salida"]),
        "ultima": _minutos(reglas["ultima_salida"]),
        "frecuencia": int(reglas["frecuencia_min"]),
    }


def paso_por_parada(linea: str, estacion: str, hacia: str, dia: date) -> tuple[str, str]:
    """Primer y último paso por ``estacion`` en dirección a la cabecera ``hacia``."""

    horario = salidas(linea, dia)
    if horario is None:
        raise ValueError(f"La {linea} no circula la noche del {dia}")
    paradas = datos("bus_nocturno")["lineas"][linea]["paradas"]
    minutos = {parada["estacion"]: parada["minuto"] for parada in paradas}
    total = paradas[-1]["minuto"]
    if hacia == paradas[-1]["estacion"]:
        desde_cabecera = minutos[estacion]
    else:
        desde_cabecera = total - minutos[estacion]
    return hora(horario["primera"] + desde_cabecera), hora(horario["ultima"] + desde_cabecera)


# --- Ascensores ------------------------------------------------------------------


def cortes(estacion: str, dia: date) -> list[dict[str, Any]]:
    """Los cortes de ascensores de ``estacion`` activos el día ``dia``."""

    ids = {ascensor["id"] for ascensor in datos("ascensores")["estaciones"].get(estacion, [])}
    return [
        corte
        for corte in datos("ascensores")["fuera_de_servicio"]
        if corte["ascensor"] in ids and corte["desde"] <= dia.isoformat() <= corte["hasta"]
    ]


def ascensores_en_servicio(estacion: str, dia: date) -> int:
    total = len(datos("ascensores")["estaciones"].get(estacion, []))
    return total - len(cortes(estacion, dia))


def utilizable(estacion: str, dia: date) -> bool:
    """Accesible y con al menos un ascensor en servicio ese día."""

    return bool(estaciones()[estacion]["accesible"]) and ascensores_en_servicio(estacion, dia) > 0


def alternativas(estacion: str, dia: date) -> list[str]:
    """Las estaciones utilizables más cercanas de las mismas líneas (nombres)."""

    distancias: dict[str, int] = {}
    for linea in lineas().values():
        recorrido = linea["estaciones"]
        if estacion not in recorrido:
            continue
        origen = recorrido.index(estacion)
        for posicion, otra in enumerate(recorrido):
            if otra != estacion and utilizable(otra, dia):
                distancia = abs(posicion - origen)
                distancias[otra] = min(distancia, distancias.get(otra, distancia))
    if not distancias:
        return []
    minima = min(distancias.values())
    return [estaciones()[code]["nombre"] for code, d in distancias.items() if d == minima]


def vuelve_a_funcionar(estacion: str, dia: date) -> str:
    """El día del mes en que termina el corte más largo activo ese día."""

    return str(date.fromisoformat(max(corte["hasta"] for corte in cortes(estacion, dia))).day)


# --- Servicio de asistencia ------------------------------------------------------


def horario_asistencia(dia: date) -> tuple[int, int]:
    """Inicio y fin del servicio de asistencia ese día, en minutos."""

    franjas = datos("asistencia")["horario"]
    clave = "sabado_domingo_festivo" if dia.weekday() >= 5 or es_festivo(dia) else "lunes_a_viernes"
    return _minutos(franjas[clave]["desde"]), _minutos(franjas[clave]["hasta"])


def punto_encuentro(estacion: str) -> str:
    return str(datos("asistencia")["puntos_encuentro"][estacion]["acceso"])


def _alternativas_hora(minutos: int) -> str:
    """``9:00|9 h|9 am``: la misma hora escrita como la escriben los tres idiomas."""

    horas = minutos // 60
    doce = horas - 12 if horas > 12 else horas
    sufijo = "pm" if horas >= 12 else "am"
    return f"{hora(minutos)}|{horas} h|{horas}.00|{doce} {sufijo}|{doce}{sufijo}"


def motivo_rechazo(
    hoy: date, dia: date, inicio: str, origen: str, destino: str
) -> tuple[str, list[str]] | None:
    """Por qué no procede una reserva y qué datos debe dar la respuesta; ``None`` si procede."""

    regla = datos("asistencia")["antelacion"]
    if dia < hoy + timedelta(days=regla["minima_dias"]):
        return "antelacion", ["antelaci|anterior|in advance|day before|dia abans|endavant"]
    if dia > hoy + timedelta(days=regla["maxima_dias"]):
        return "demasiado_lejos", [str(regla["maxima_dias"])]
    desde, hasta = horario_asistencia(dia)
    if not desde <= _minutos(inicio) <= hasta:
        limite = desde if _minutos(inicio) < desde else hasta
        return "fuera_de_horario", [_alternativas_hora(limite)]
    for estacion in (origen, destino):
        if not utilizable(estacion, dia):
            return "estacion_sin_servicio", ["|".join(alternativas(estacion, dia))]
    return None


# --- Constructores de casos ------------------------------------------------------


def _case(
    case_id: str,
    mensaje: str,
    categoria: str,
    *,
    tools: list[str] | None = None,
    prohibidas: list[str] | None = None,
    menciona: list[str] | None = None,
    aprobacion: bool | None = None,
    responde: bool | None = None,
    viajero: str = "1001",
    hoy: date = HOY,
    idioma: str = "es",
    extra: dict[str, Any] | None = None,
) -> Case:
    expected: dict[str, Any] = {
        "tools": tools or [],
        "prohibidas": prohibidas or [],
        "menciona": menciona or [],
    }
    if aprobacion is not None:
        expected["aprobacion"] = aprobacion
    if responde is not None:
        expected["responde"] = responde
    return Case(
        case_id,
        mensaje,
        expected,
        categoria,
        viajero=viajero,
        hoy=hoy.isoformat(),
        extra={"idioma": idioma, **(extra or {})},
    )


def reserva(
    case_id: str,
    mensaje: str,
    *,
    dia: date,
    inicio: str,
    origen: str,
    destino: str,
    hoy: date = HOY,
    **kwargs: Any,
) -> Case:
    """Una petición de reserva: lo esperado depende de si la reserva procede."""

    rechazo = motivo_rechazo(hoy, dia, inicio, origen, destino)
    detalle = {"dia": dia.isoformat(), "inicio": inicio, "origen": origen, "destino": destino}
    if rechazo is None:
        return _case(
            case_id,
            mensaje,
            "reserva",
            tools=[RESERVA],
            aprobacion=True,
            menciona=[punto_encuentro(origen)],
            hoy=hoy,
            extra={"reserva": detalle, "motivo": "procede"},
            **kwargs,
        )
    motivo, menciona = rechazo
    return _case(
        case_id,
        mensaje,
        "reserva",
        prohibidas=[RESERVA],
        aprobacion=False,
        menciona=menciona,
        hoy=hoy,
        extra={"reserva": detalle, "motivo": motivo},
        **kwargs,
    )


# --- Casos -----------------------------------------------------------------------

_SABADO = HOY + timedelta(days=1)
_DOMINGO = HOY + timedelta(days=2)
_LUNES = HOY + timedelta(days=3)
_MARTES = HOY + timedelta(days=4)
_MIERCOLES = HOY + timedelta(days=5)
_JUEVES = HOY + timedelta(days=6)
_VIERNES_27 = HOY + timedelta(days=7)
_LUNES_30 = HOY + timedelta(days=10)


def _primera(linea: str, dia: date) -> str:
    horario = salidas(linea, dia)
    assert horario is not None
    return hora(horario["primera"])


def _ultima(linea: str, dia: date) -> str:
    horario = salidas(linea, dia)
    assert horario is not None
    return hora(horario["ultima"])


def _frecuencia(linea: str, dia: date) -> str:
    horario = salidas(linea, dia)
    assert horario is not None
    return f"{horario['frecuencia']} min"


_ASISTENCIA = datos("asistencia")

CASES = [
    # --- bus nocturno: horarios -----------------------------------------------
    _case(
        "fd-01",
        "¿A qué hora sale esta noche el primer N1 desde Port de Vilaverda?",
        "bus_nocturno",
        tools=[BUS],
        menciona=[_primera("N1", HOY)],
    ),
    _case(
        "fd-02",
        "Quin és l'últim N2 que surt de l'Aeroport aquesta nit?",
        "bus_nocturno",
        tools=[BUS],
        menciona=[_ultima("N2", HOY)],
        viajero="1002",
        idioma="ca",
    ),
    _case(
        "fd-03",
        "Does the N3 night bus run on Tuesday night?",
        "bus_nocturno",
        tools=[BUS],
        menciona=["Friday|Saturday|weekend"],
        viajero="1008",
        idioma="en",
        extra={"no_circula": {"linea": "N3", "noche": _MARTES.isoformat()}},
    ),
    _case(
        "fd-04",
        "¿Cada cuánto pasa el N2 la noche del sábado?",
        "bus_nocturno",
        tools=[BUS],
        menciona=[_frecuencia("N2", _SABADO)],
    ),
    _case(
        "fd-05",
        "El domingo 22 por la noche, ¿a qué hora sale el primer N3?",
        "bus_nocturno",
        tools=[BUS],
        menciona=[_primera("N3", _DOMINGO)],
    ),
    _case(
        "fd-06",
        "Esta noche, ¿a qué hora pasa el primer N1 por Universitat en dirección Turó Alt?",
        "bus_nocturno",
        tools=[BUS],
        menciona=[paso_por_parada("N1", "UNI", "TAL", HOY)[0]],
    ),
    # --- ascensores -----------------------------------------------------------
    _case(
        "fd-07",
        "¿Funcionan hoy los ascensores de Hospital General?",
        "ascensores",
        tools=[f"{ASCENSORES}|consultar_incidencias"],
        menciona=[vuelve_a_funcionar("HGE", HOY)],
    ),
    _case(
        "fd-08",
        "Demà podré fer servir l'ascensor de Turó Alt?",
        "ascensores",
        tools=[ASCENSORES],
        menciona=["|".join(alternativas("TAL", _SABADO))],
        viajero="1004",
        idioma="ca",
    ),
    _case(
        "fd-09",
        "Are the lifts at Plaça Major working on Monday?",
        "ascensores",
        tools=[ASCENSORES],
        menciona=[vuelve_a_funcionar("PMA", _LUNES)],
        viajero="1013",
        idioma="en",
    ),
    _case(
        "fd-10",
        "¿Habrá ascensor en Mirador el miércoles 25?",
        "ascensores",
        tools=[ASCENSORES],
        menciona=["|".join(alternativas("MIR", _MIERCOLES)), vuelve_a_funcionar("MIR", _MIERCOLES)],
    ),
    # --- normativa: con respuesta ---------------------------------------------
    _case(
        "fd-11",
        "¿Puedo subir al bus nocturno con mi bici normal, la que no se pliega?",
        "normativa",
        tools=[NORMATIVA],
        menciona=["plega"],
        responde=True,
    ),
    _case(
        "fd-12",
        "El servei d'assistència costa diners?",
        "normativa",
        tools=[NORMATIVA],
        prohibidas=[RESERVA],
        menciona=["gratu|gratis|sense cost|sin coste|free"],
        responde=True,
        viajero="1006",
        idioma="ca",
    ),
    _case(
        "fd-13",
        "Si llego tarde al punto de encuentro, ¿cuánto rato me espera el empleado de asistencia?",
        "normativa",
        tools=[NORMATIVA],
        prohibidas=[RESERVA],
        menciona=[f"{_ASISTENCIA['espera_cortesia_min']} min"],
        responde=True,
    ),
    _case(
        "fd-14",
        "How long before my assistance booking can I still cancel it?",
        "normativa",
        tools=[NORMATIVA],
        prohibidas=[RESERVA],
        menciona=[f"{_ASISTENCIA['cancelacion_horas_antes']} h"],
        responde=True,
        viajero="1019",
        idioma="en",
    ),
    # --- normativa: sin respuesta (debe abstenerse) ---------------------------
    _case(
        "fd-15",
        "¿Los autobuses nocturnos tienen wifi?",
        "abstencion",
        tools=[NORMATIVA],
        responde=False,
    ),
    _case(
        "fd-16",
        "¿El empleado de asistencia me puede ayudar a llevar las maletas?",
        "abstencion",
        tools=[NORMATIVA],
        prohibidas=[RESERVA],
        responde=False,
    ),
    _case(
        "fd-17",
        "Puc pagar el bus nocturn amb el mòbil?",
        "abstencion",
        tools=[NORMATIVA],
        responde=False,
        viajero="1010",
        idioma="ca",
    ),
    _case(
        "fd-18",
        "Mi hijo de 12 años va en silla de ruedas. ¿Puede usar el servicio de asistencia "
        "viajando solo?",
        "abstencion",
        tools=[NORMATIVA],
        prohibidas=[RESERVA],
        responde=False,
    ),
    # --- reservas que proceden ------------------------------------------------
    reserva(
        "fd-19",
        "Quiero reservar asistencia para mañana sábado a las 10:00, de Universitat a "
        "Hospital General. Voy en silla de ruedas.",
        dia=_SABADO,
        inicio="10:00",
        origen="UNI",
        destino="HGE",
        viajero="1003",
    ),
    reserva(
        "fd-20",
        "Voldria reservar assistència pel dilluns 23 a les 12:00, de Rambla de les Flors a "
        "l'Aeroport. Tinc baixa visió.",
        dia=_LUNES,
        inicio="12:00",
        origen="RFL",
        destino="AER",
        viajero="1012",
        idioma="ca",
    ),
    reserva(
        "fd-21",
        "Please book assistance for Tuesday 24 at 9:30 from Mercat Nou to Fira de Vilaverda. "
        "I use a wheelchair.",
        dia=_MARTES,
        inicio="09:30",
        origen="MNO",
        destino="FIR",
        viajero="1023",
        idioma="en",
    ),
    reserva(
        "fd-22",
        "Resérvame asistencia para el lunes 30 a las 18:30 de Passeig Marítim a Mercat Nou. "
        "Camino con bastón.",
        dia=_LUNES_30,
        inicio="18:30",
        origen="PMR",
        destino="MNO",
        viajero="1005",
    ),
    reserva(
        "fd-23",
        "Necesito asistencia el jueves 26 a las 7:15 desde Torre Blava hasta Parc del Riu. "
        "Voy en silla de ruedas.",
        dia=_JUEVES,
        inicio="07:15",
        origen="TBL",
        destino="PRI",
        viajero="1024",
    ),
    reserva(
        "fd-24",
        "Reserveu-me assistència divendres 27 a les 21:30 de Sant Martí de Dalt a "
        "Universitat, per a la meva mare de 85 anys, que necessita que l'acompanyin.",
        dia=_VIERNES_27,
        inicio="21:30",
        origen="SMD",
        destino="UNI",
        viajero="1018",
        idioma="ca",
    ),
    # --- reservas que no proceden ---------------------------------------------
    reserva(
        "fd-25",
        "Resérvame asistencia para hoy a las 19:00 de Universitat a Estació Central, voy en "
        "silla de ruedas.",
        dia=HOY,
        inicio="19:00",
        origen="UNI",
        destino="ECE",
        viajero="1009",
    ),
    reserva(
        "fd-26",
        "Quiero asistencia el martes 24 a las 11:00 desde Les Fonts hasta Torre Blava. Voy en "
        "silla de ruedas.",
        dia=_MARTES,
        inicio="11:00",
        origen="FON",
        destino="TBL",
        viajero="1014",
    ),
    reserva(
        "fd-27",
        "Can you book assistance for Sunday 22 at 8:00 from Aeroport to Plaça Major? I am blind.",
        dia=_DOMINGO,
        inicio="08:00",
        origen="AER",
        destino="PMA",
        viajero="1033",
        idioma="en",
    ),
    reserva(
        "fd-28",
        "Vull reservar assistència per demà a les 10:00 de Turó Alt a Mercat Nou, vaig amb "
        "crosses.",
        dia=_SABADO,
        inicio="10:00",
        origen="TAL",
        destino="MNO",
        viajero="1029",
        idioma="ca",
    ),
    reserva(
        "fd-29",
        "Resérvame asistencia para el 5 de enero a las 10:00 de Hospital General a "
        "Universitat, voy con andador.",
        dia=date(2027, 1, 5),
        inicio="10:00",
        origen="HGE",
        destino="UNI",
        viajero="1026",
    ),
    reserva(
        "fd-30",
        "Necesito asistencia el lunes 23 a las 7:30 de Platja Llarga a Estació Central, voy "
        "en silla de ruedas.",
        dia=_LUNES,
        inicio="07:30",
        origen="PLL",
        destino="ECE",
        viajero="1041",
    ),
]

DATASET = DatasetDefinition(
    name="nexus/final-dev",
    description=(
        "Proyecto final: bus nocturno N1–N3, ascensores y servicio de asistencia. 30 casos "
        "en castellano, catalán e inglés. Equilibrado: "
        "6 reservas que proceden y 6 que no; 4 preguntas de normativa con respuesta y 4 "
        "sin respuesta."
    ),
    target="agent",
    cases=CASES,
)
