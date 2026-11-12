"""Fechas para las herramientas: de "jueves" o "mañana" a una fecha concreta."""

import unicodedata
from datetime import date, timedelta

DIAS_SEMANA: dict[str, int] = {}
for index, names in enumerate(
    [
        ("lunes", "dilluns", "monday"),
        ("martes", "dimarts", "tuesday"),
        ("miercoles", "dimecres", "wednesday"),
        ("jueves", "dijous", "thursday"),
        ("viernes", "divendres", "friday"),
        ("sabado", "dissabte", "saturday"),
        ("domingo", "diumenge", "sunday"),
    ]
):
    for name in names:
        DIAS_SEMANA[name] = index

NOMBRES_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

RELATIVOS = {
    "hoy": 0,
    "avui": 0,
    "today": 0,
    "manana": 1,
    "dema": 1,
    "tomorrow": 1,
    "pasado manana": 2,
    "dema passat": 2,
}


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(char for char in stripped if not unicodedata.combining(char))


def resolve_day(dia: str, hoy: date) -> date:
    """La fecha a la que se refiere ``dia`` visto desde ``hoy``.

    Acepta una fecha ISO (``2026-11-12``), ``hoy``/``mañana``/``pasado mañana`` y los días
    de la semana en castellano, catalán o inglés. Un día de la semana es el próximo con
    ese nombre; si es el mismo día de hoy, es hoy.
    """

    text = _normalize(dia)
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    if text in RELATIVOS:
        return hoy + timedelta(days=RELATIVOS[text])
    if text in DIAS_SEMANA:
        target = DIAS_SEMANA[text]
        offset = (target - hoy.isoweekday()) % 7
        return hoy + timedelta(days=offset)
    raise ValueError(
        f"No entiendo el día {dia!r}. Usa una fecha (AAAA-MM-DD), 'hoy', 'mañana' "
        "o un día de la semana."
    )


def describe(day: date) -> str:
    """``jueves 12 de noviembre de 2026``, para los prompts y las respuestas."""

    meses = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return f"{NOMBRES_DIA[day.weekday()]} {day.day} de {meses[day.month - 1]} de {day.year}"
