"""Tests de los datos y las herramientas que no dependen del modelo."""

from datetime import date

from nexus.calendar import resolve_day
from nexus.data import find_station, normalize_line, viajero
from nexus.tools.horarios import day_type, schedule
from nexus.tools.incidencias import incidents_on
from nexus.tools.tarifas import consultar_tarifas


def test_resolve_day_accepts_iso_dates_and_relative_days() -> None:
    hoy = date(2026, 11, 10)

    assert resolve_day("2026-11-12", hoy) == date(2026, 11, 12)
    assert resolve_day("mañana", hoy) == date(2026, 11, 11)
    assert resolve_day("avui", hoy) == hoy


def test_day_type_follows_the_calendar() -> None:
    assert day_type(date(2026, 11, 10)) == "laborable"
    assert day_type(date(2026, 11, 13)) == "viernes"
    assert day_type(date(2026, 11, 14)) == "sabado"
    assert day_type(date(2026, 11, 23)) == "domingo_festivo"  # Festa Major, lunes
    assert day_type(date(2026, 12, 7)) == "viernes"  # lunes, víspera del festivo del 8


def test_schedule_adds_the_travel_time_from_the_first_station() -> None:
    result = schedule("L1", "PMA", date(2026, 11, 10), "08:00")

    assert result["primer_tren"] == "05:04"
    assert result["ultimo_tren"] == "00:04"
    assert result["frecuencia_min"] == 3


def test_saturday_night_service_runs_all_night_on_l1_and_l3() -> None:
    assert "toda la noche" in schedule("L3", "UNI", date(2026, 11, 14))["ultimo_tren"]
    assert schedule("L2", "ECE", date(2026, 11, 14), "03:30")["trenes_en_esa_hora"] == []


def test_incidents_on_finds_the_l3_works_only_on_their_day() -> None:
    assert [item["id"] for item in incidents_on(date(2026, 11, 12), "L3")] == ["INC-0301"]
    assert incidents_on(date(2026, 11, 11), "L3") == []


def test_lookups_accept_names_and_codes() -> None:
    assert find_station("plaça major") == "PMA"
    assert find_station("Placa Major") == "PMA"
    assert normalize_line("línea 3") == "L3"
    assert viajero("1042") is not None


def test_consultar_tarifas_understands_common_names() -> None:
    assert "t10" in consultar_tarifas.invoke({"titulo": "T-10"})
    assert "error" in consultar_tarifas.invoke({"titulo": "abono anual"})
