"""Tests del dataset ``nexus/final-dev`` y de los datos y documentos del proyecto final."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from evaluation.datasets import DATASETS
from evaluation.datasets import final_dev as fd
from nexus.data import estaciones, load
from nexus.rag.documents import load_documents
from nexus.tools import BASE_TOOLS

DOCS_DIR = Path(fd.DATOS_DIR).parent / "docs"
CONTRATO = {fd.BUS, fd.ASCENSORES, fd.RESERVA}
CASES = DATASETS["final-dev"].cases


def _names(options: list[str]) -> set[str]:
    return {name for alternatives in options for name in alternatives.split("|")}


# --- el dataset ----------------------------------------------------------------


def test_final_dev_is_registered_with_its_langfuse_name() -> None:
    definition = DATASETS["final-dev"]

    assert definition.name == "nexus/final-dev"
    assert definition.target == "agent"
    assert len(definition.cases) == 30


def test_case_ids_are_unique() -> None:
    ids = [case.case_id for case in CASES]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("particion", [None, "development"])
def test_binary_classes_are_balanced(particion: str | None) -> None:
    cases = [case for case in CASES if particion is None or case.particion == particion]
    approvals = Counter(case.expected.get("aprobacion") for case in cases)
    answers = Counter(case.expected.get("responde") for case in cases)

    assert approvals[True] == approvals[False] > 0
    assert answers[True] == answers[False] > 0


def test_every_case_is_in_the_story_today_and_has_a_language() -> None:
    assert {case.hoy for case in CASES} == {fd.HOY.isoformat()}
    assert {case.metadata()["idioma"] for case in CASES} == {"es", "ca", "en"}


def test_tool_names_are_the_contract_or_existing_tools() -> None:
    existing = {tool.name for tool in BASE_TOOLS}
    used = set()
    for case in CASES:
        used |= _names(case.expected["tools"]) | set(case.expected["prohibidas"])

    assert used <= CONTRATO | existing
    assert CONTRATO <= used


def test_bookings_follow_the_assistance_rules() -> None:
    motivos: Counter[str] = Counter()
    for case in (case for case in CASES if case.categoria == "reserva"):
        reserva = case.metadata()["reserva"]
        rechazo = fd.motivo_rechazo(
            fd.HOY,
            date.fromisoformat(reserva["dia"]),
            reserva["inicio"],
            reserva["origen"],
            reserva["destino"],
        )
        if case.expected["aprobacion"]:
            assert rechazo is None, case.case_id
            assert case.expected["tools"] == [fd.RESERVA]
        else:
            assert rechazo is not None, case.case_id
            assert fd.RESERVA in case.expected["prohibidas"]
            motivos[rechazo[0]] += 1

    assert set(motivos) == {
        "antelacion",
        "demasiado_lejos",
        "fuera_de_horario",
        "estacion_sin_servicio",
    }


# --- los hechos esperados ------------------------------------------------------


def test_night_types_follow_the_calendar() -> None:
    assert fd.tipo_noche(date(2026, 11, 20)) == "viernes"
    assert fd.tipo_noche(date(2026, 11, 21)) == "sabado_y_vispera"
    assert fd.tipo_noche(date(2026, 11, 22)) == "sabado_y_vispera"  # víspera de la Festa Major
    assert fd.tipo_noche(date(2026, 11, 24)) == "domingo_a_jueves"


def test_night_bus_facts() -> None:
    assert fd.salidas("N3", date(2026, 11, 24)) is None
    assert fd.hora(fd.salidas("N1", fd.HOY)["primera"]) == "2:10"  # type: ignore[index]
    assert fd.hora(fd.salidas("N3", date(2026, 11, 22))["primera"]) == "3:10"  # type: ignore[index]
    assert fd.paso_por_parada("N1", "UNI", "TAL", fd.HOY) == ("2:30", "5:10")
    assert fd.paso_por_parada("N1", "UNI", "PVI", fd.HOY) == ("2:21", "5:01")


def test_elevator_facts() -> None:
    assert fd.ascensores_en_servicio("HGE", fd.HOY) == 1
    assert not fd.utilizable("TAL", date(2026, 11, 21))
    assert fd.alternativas("TAL", date(2026, 11, 21)) == ["Universitat"]
    assert fd.alternativas("FON", date(2026, 11, 24)) == ["Universitat"]  # Mirador, sin ascensor


def test_no_answer_case_is_derived_from_the_data() -> None:
    case = next(case for case in CASES if case.case_id == "fd-03")
    no_circula = case.metadata()["no_circula"]

    assert fd.salidas(no_circula["linea"], date.fromisoformat(no_circula["noche"])) is None


# --- coherencia de los datos ---------------------------------------------------


def test_night_bus_stops_are_metro_stations_in_travel_order() -> None:
    for linea in fd.datos("bus_nocturno")["lineas"].values():
        minutos = [parada["minuto"] for parada in linea["paradas"]]
        assert all(parada["estacion"] in estaciones() for parada in linea["paradas"])
        assert minutos[0] == 0 and minutos == sorted(minutos)


def test_elevators_match_the_network() -> None:
    ascensores = fd.datos("ascensores")["estaciones"]
    ids = {ascensor["id"] for lista in ascensores.values() for ascensor in lista}

    for code, station in estaciones().items():
        assert len(ascensores.get(code, [])) == station["ascensores"], code
    assert {corte["ascensor"] for corte in fd.datos("ascensores")["fuera_de_servicio"]} <= ids


def test_elevator_outages_match_their_incidents() -> None:
    incidents = {incident["id"]: incident for incident in load("incidencias")}
    for corte in fd.datos("ascensores")["fuera_de_servicio"]:
        if "incidencia" not in corte:
            continue
        incident = incidents[corte["incidencia"]]
        assert incident["tipo"] == "accesibilidad"
        assert incident["desde"][:10] == corte["desde"] and incident["hasta"][:10] == corte["hasta"]


def test_meeting_points_exist_for_accessible_stations_only() -> None:
    accessible = {code for code, station in estaciones().items() if station["accesible"]}

    assert set(fd.datos("asistencia")["puntos_encuentro"]) == accessible


# --- los documentos ------------------------------------------------------------


def test_documents_have_the_rag_header() -> None:
    documents = {document.doc_id: document for document in load_documents(DOCS_DIR)}

    assert set(documents) == {"reglamento-bus-nocturno", "protocolo-asistencia"}
    assert all(document.vigente for document in documents.values())


def test_documents_agree_with_the_data() -> None:
    reglamento = (DOCS_DIR / "reglamento-bus-nocturno.md").read_text(encoding="utf-8")
    protocolo = (DOCS_DIR / "protocolo-asistencia.md").read_text(encoding="utf-8")
    bus = fd.datos("bus_nocturno")
    asistencia = fd.datos("asistencia")

    for tipo in bus["tipos_noche"].values():
        for clave in ("primera_salida", "ultima_salida"):
            assert fd.hora(fd._minutos(tipo[clave])) in reglamento
        assert f"cada {tipo['frecuencia_min']} minutos" in reglamento
    assert fd.hora(fd._minutos(bus["excepciones"]["2026-11-22"]["primera_salida"])) in reglamento
    for franja in asistencia["horario"].values():
        assert fd.hora(fd._minutos(franja["desde"])) in protocolo
        assert fd.hora(fd._minutos(franja["hasta"])) in protocolo
    assert f"{asistencia['espera_cortesia_min']} minutos" in protocolo
    assert f"{asistencia['cancelacion_horas_antes']} horas" in protocolo
    assert f"{asistencia['antelacion']['maxima_dias']} días" in protocolo
