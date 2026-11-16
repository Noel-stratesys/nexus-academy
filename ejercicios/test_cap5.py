"""Misión 5 · El viernes de los despliegues (``uv run check 5``).

Cuatro cambios esperaban despliegue. Comprueba que ninguno se ha quedado a medias, que
lo inseguro no ha llegado a producción, que producción conserva el tono de Marc y las
reglas del prompt original, que el dataset agente cubre lo que falló en el canary, y que
la herramienta de próximos trenes funciona.
"""

from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from evaluation.datasets.agente import CASES, DATASET
from nexus.data import viajero
from nexus.prompts import EXECUTOR_PROMPT_NAME
from nexus.tools.proximos import proximos
from release.cambios import CAMBIOS, TONO_A
from release.state import load_state

FINALES = ("promote", "rollback")


def _idioma(case_extra: dict[str, Any], viajero_id: str | None) -> str:
    """El idioma de un caso: ``idioma`` en su metadata o, si no, el de su viajero."""

    if case_extra.get("idioma"):
        return str(case_extra["idioma"])
    found = viajero(viajero_id) if viajero_id else None
    return found.idioma if found else "es"


def _faltan(idiomas: set[str]) -> list[str]:
    return [nombre for code, nombre in (("ca", "catalán"), ("en", "inglés")) if code not in idiomas]


def test_ningun_cambio_se_queda_a_medias() -> None:
    """Ningún cambio se queda a medias: green no recibe tráfico al terminar"""

    green = load_state().green
    assert green.traffic == 0, (
        f"El cambio {green.cambio} sigue en green con el {green.traffic} % del tráfico. "
        "Termínalo: uv run release promote si es seguro, o uv run release rollback si no."
    )


def test_cada_cambio_acaba_en_promote_o_rollback_con_motivo() -> None:
    """Cada cambio acaba en promote o en rollback, con su motivo"""

    historial = load_state().historial
    pendientes = []
    for clave in CAMBIOS:
        finales = [e for e in historial if e.cambio == clave and e.accion in FINALES]
        if not finales:
            pendientes.append(f"{clave} (sin promote ni rollback)")
        elif finales[-1].detalle in ("", "(sin motivo)"):
            pendientes.append(f"{clave} ({finales[-1].accion} sin motivo)")
    assert not pendientes, (
        f"Cambios sin cerrar: {', '.join(pendientes)}. Cierra cada uno con "
        'uv run release promote --motivo "…" o uv run release rollback --motivo "…".'
    )


def test_el_tono_de_marc_esta_en_produccion() -> None:
    """El cambio A (tono más cercano) está en producción"""

    cambios = load_state().blue.cambios
    assert "A" in cambios, (
        f"Cambios promocionados: {', '.join(cambios) or 'ninguno'}. Los demás cambios "
        "se construyen sobre A: tiene que estar en producción."
    )


def test_las_devoluciones_sin_normativa_no_llegan_a_produccion() -> None:
    """Producción no tramita devoluciones que la normativa no permite"""

    assert "B" not in load_state().blue.cambios, (
        "Hay en producción un cambio con el que Nexus tramita devoluciones que la "
        "normativa no permite. ¿Qué tendría que haberlo parado antes de llegar a los viajeros?"
    )


def test_produccion_conserva_el_tono_y_la_regla_del_idioma(langfuse_http: httpx.Client) -> None:
    """Producción tiene el tono de Marc y conserva las reglas del prompt original"""

    response = langfuse_http.get(
        f"/api/public/v2/prompts/{quote(EXECUTOR_PROMPT_NAME, safe='')}",
        params={"label": "production"},
    )
    assert response.status_code == 200, (
        f"No se puede leer {EXECUTOR_PROMPT_NAME} con el label production "
        f"(HTTP {response.status_code}). ¿Está Langfuse en marcha?"
    )
    text = "\n".join(message.get("content", "") for message in response.json()["prompt"])
    assert TONO_A in text, (
        f"El prompt de producción no tiene el tono de Marc («{TONO_A}…»). Promociona el "
        "cambio A (o un cambio construido sobre A)."
    )
    assert "idioma" in text.lower(), (
        "Al prompt de producción le falta una regla que tenía el original. Compara los "
        "dos prompts: ¿a qué viajeros afecta lo que se ha perdido?"
    )


def test_el_dataset_agente_tiene_casos_en_catalan_y_en_ingles() -> None:
    """El dataset agente tiene casos que habrían detectado lo que falló en el canary"""

    idiomas = {_idioma(case.extra, case.viajero) for case in CASES}
    faltan = _faltan(idiomas)
    assert not faltan, (
        "A evaluation/datasets/agente.py le faltan casos de algún grupo de viajeros. "
        "¿Qué grupo falló en el canary sin que la puerta lo viera? La misión explica cómo "
        "asignar un caso a un viajero."
    )


def test_el_dataset_subido_a_langfuse_tiene_esos_casos(langfuse_http: httpx.Client) -> None:
    """El dataset agente de Langfuse también tiene esos casos"""

    response = langfuse_http.get(
        "/api/public/dataset-items", params={"datasetName": DATASET.name, "limit": 100}
    )
    assert response.status_code == 200, (
        f"No se pueden leer los casos de {DATASET.name} (HTTP {response.status_code}). "
        "¿Está Langfuse en marcha? ¿Has subido el dataset con uv run dataset?"
    )
    idiomas = {
        _idioma(item.get("metadata") or {}, (item.get("input") or {}).get("viajero"))
        for item in response.json()["data"]
    }
    faltan = _faltan(idiomas)
    assert not faltan, (
        "En Langfuse faltan los casos nuevos del dataset agente. Súbelos con "
        "uv run dataset agente: la puerta solo ve los casos que están en Langfuse."
    )


def test_proximos_trenes_encuentra_trenes_en_una_estacion_normal() -> None:
    """La herramienta de próximos trenes da los trenes de la L1 en Plaça Major"""

    result = proximos("L1", "Plaça Major", date(2026, 11, 16), "08:00")
    assert "error" not in result, f"La herramienta devuelve un error: {result['error']}"
    assert result.get("proximos_trenes"), (
        f"Para la L1 en Plaça Major a las 08:00 la herramienta responde {result}. Mira en "
        "las trazas del canary qué devolvía a cada llamada y reprodúcelo sin pasar por el "
        "modelo."
    )
    assert result["proximos_trenes"][0]["hora"] == "08:01", (
        f"El primer tren después de las 08:00 en Plaça Major (L1) pasa a las 08:01, no a "
        f"las {result['proximos_trenes'][0]['hora']}."
    )
