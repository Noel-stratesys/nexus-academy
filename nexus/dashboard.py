"""Los dashboards de Nexus en Langfuse (los crea ``uv run seed``).

- «Nexus en producción»: el tráfico de producción (``environment = production``) por
  release: cuántas conversaciones hay, cuántas se valoran con 👍, cuánto tardan, cuánto
  gastan y qué herramientas usan. Es el panel de los despliegues (``blue`` contra
  ``green``).
- «Prueba A/B del executor»: solo la semana de la prueba A/B, ``v1-marc`` contra
  ``v2-jordi``, ordenado como las preguntas del capítulo 1: cuál gusta más, en qué, por
  qué y a qué coste. No dice qué significa cada número: eso lo concluye quien lo mira.

Las medias no van en barras: el gráfico de barras de Langfuse ajusta el eje a los datos
(empieza en 0,64, por ejemplo) y hace que 0,73 frente a 0,65 parezca el triple. Van en
quesitos (la proporción de 👍 y 👎, que no depende de ningún eje), en líneas por día (que
además enseñan cuánto varía de un día a otro) o en tablas con el número exacto.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langfuse.api.unstable.dashboard_widgets import (
    DashboardWidgetChartType,
    DashboardWidgetDimension,
    DashboardWidgetFilter,
    DashboardWidgetMetric,
    DashboardWidgetMetricAggregation,
    DashboardWidgetView,
)
from langfuse.api.unstable.dashboards import CreateDashboardPlacementRequest_Widget

from nexus.simulation.historial import JORDI, MARC

DASHBOARD = "Nexus en producción"
DASHBOARD_AB = "Prueba A/B del executor"
COLUMNAS = 12


def _cualquiera(columna: str, valores: Sequence[str]) -> DashboardWidgetFilter:
    return DashboardWidgetFilter(
        column=columna, operator="any of", type="stringOptions", value=list(valores)
    )


CONVERSACIONES = _cualquiera("name", ["nexus-agent"])
VALORACIONES = _cualquiera("name", ["user_feedback"])
HERRAMIENTAS = _cualquiera("type", ["TOOL"])
GENERACIONES = _cualquiera("type", ["GENERATION"])
RELEASES_AB = (MARC.release, JORDI.release)
# Las observaciones llevan el release en «release»; las valoraciones, en «traceRelease».
SOLO_AB = _cualquiera("release", RELEASES_AB)
VALORACIONES_AB = _cualquiera("traceRelease", RELEASES_AB)


@dataclass(frozen=True)
class Widget:
    nombre: str
    descripcion: str
    vista: str
    dimensiones: tuple[str, ...]
    metricas: tuple[tuple[str, str], ...]
    filtros: tuple[DashboardWidgetFilter, ...]
    grafico: str
    ancho: int = 6
    alto: int = 6


@dataclass(frozen=True)
class Panel:
    nombre: str
    descripcion: str
    widgets: tuple[Widget, ...]


WIDGETS = [
    Widget(
        "Conversaciones por día",
        "Turnos de conversación (trazas nexus-agent) por día y release.",
        "observations",
        ("release",),
        (("count", "count"),),
        (CONVERSACIONES,),
        "BAR_TIME_SERIES",
        ancho=12,
    ),
    Widget(
        "% 👍 por día y release",
        "Media diaria de user_feedback (1 = 👍, 0 = 👎) por release: 0,8 es un 80 % de 👍.",
        "scores-numeric",
        ("traceRelease",),
        (("value", "avg"),),
        (VALORACIONES,),
        "LINE_TIME_SERIES",
    ),
    Widget(
        "Latencia p95 por día y release",
        "Lo que tarda el 95 % de los turnos, en segundos, cada día y por release.",
        "observations",
        ("release",),
        (("latency", "p95"),),
        (CONVERSACIONES,),
        "LINE_TIME_SERIES",
    ),
    Widget(
        "👍 por categoría y release",
        "Media de user_feedback y valoraciones por categoría de la petición (etiqueta) y "
        "release. Un fallo en una categoría se esconde en la media global.",
        "scores-numeric",
        ("tags", "traceRelease"),
        (("value", "avg"), ("count", "count")),
        (VALORACIONES,),
        "PIVOT_TABLE",
        ancho=12,
        alto=8,
    ),
    Widget(
        "Tokens y conversaciones por release",
        "Tokens de todas las llamadas al modelo y turnos con alguna llamada, por release.",
        "observations",
        ("release",),
        (("totalTokens", "sum"), ("traceId", "uniq")),
        (_cualquiera("type", ["GENERATION"]),),
        "PIVOT_TABLE",
    ),
    Widget(
        "Herramientas más llamadas",
        "Llamadas a cada herramienta. Muchas llamadas a la misma en una conversación suelen "
        "ser un bucle.",
        "observations",
        ("name",),
        (("count", "count"),),
        (_cualquiera("type", ["TOOL"]),),
        "HORIZONTAL_BAR",
    ),
]


# Un quesito por versión: cuántas valoraciones son 👍 (1) y cuántas 👎 (0).
QUESITOS_AB = tuple(
    Widget(
        f"👍 y 👎 · {release}",
        "Valoraciones de los viajeros: 1 = 👍, 0 = 👎.",
        "scores-numeric",
        ("value",),
        (("count", "count"),),
        (VALORACIONES, _cualquiera("traceRelease", [release])),
        "PIE",
        ancho=3,
    )
    for release in RELEASES_AB
)

WIDGETS_AB = [
    # ¿Cuál gusta más?
    *QUESITOS_AB,
    Widget(
        "Valoraciones por versión",
        "Cuántas conversaciones de cada versión valoraron los viajeros, y su media.",
        "scores-numeric",
        ("traceRelease",),
        (("count", "count"), ("value", "avg")),
        (VALORACIONES, VALORACIONES_AB),
        "PIVOT_TABLE",
    ),
    Widget(
        "% 👍 por día y versión",
        "Media diaria de user_feedback (1 = 👍, 0 = 👎) de cada versión. Mira cuánto cambia "
        "de un día a otro antes de sacar conclusiones de la diferencia entre versiones.",
        "scores-numeric",
        ("traceRelease",),
        (("value", "avg"),),
        (VALORACIONES, VALORACIONES_AB),
        "LINE_TIME_SERIES",
        ancho=12,
    ),
    # ¿En qué?
    Widget(
        "% 👍 por categoría y versión",
        "Media de user_feedback y número de valoraciones, por categoría de la petición "
        "(etiqueta) y versión.",
        "scores-numeric",
        ("tags", "traceRelease"),
        (("value", "avg"), ("count", "count")),
        (VALORACIONES, VALORACIONES_AB),
        "PIVOT_TABLE",
        ancho=12,
        alto=8,
    ),
    # ¿Por qué?
    Widget(
        "Conversaciones por categoría y versión",
        "Turnos de conversación (trazas nexus-agent), por categoría y versión.",
        "observations",
        ("tags", "release"),
        (("count", "count"),),
        (CONVERSACIONES, SOLO_AB),
        "PIVOT_TABLE",
        alto=8,
    ),
    Widget(
        "Conversaciones que consultan alguna herramienta, por categoría y versión",
        "Turnos de conversación con al menos una llamada a una herramienta, por categoría "
        "y versión.",
        "observations",
        ("tags", "release"),
        (("traceId", "uniq"),),
        (HERRAMIENTAS, SOLO_AB),
        "PIVOT_TABLE",
        alto=8,
    ),
    Widget(
        "Herramientas llamadas, por versión",
        "Llamadas a cada herramienta, por versión.",
        "observations",
        ("name", "release"),
        (("count", "count"),),
        (HERRAMIENTAS, SOLO_AB),
        "PIVOT_TABLE",
        ancho=12,
    ),
    # ¿A qué coste?
    Widget(
        "Tokens por versión",
        "Tokens de todas las llamadas al modelo y turnos con alguna llamada, por versión: "
        "divide para tener los tokens por conversación.",
        "observations",
        ("release",),
        (("totalTokens", "sum"), ("traceId", "uniq")),
        (GENERACIONES, SOLO_AB),
        "PIVOT_TABLE",
    ),
    Widget(
        "Latencia p95 por día y versión",
        "Lo que tarda el 95 % de los turnos, en segundos, cada día y por versión.",
        "observations",
        ("release",),
        (("latency", "p95"),),
        (CONVERSACIONES, SOLO_AB),
        "LINE_TIME_SERIES",
    ),
]

PANELES = [
    Panel(DASHBOARD, "El tráfico de producción de Nexus, por release.", tuple(WIDGETS)),
    Panel(
        DASHBOARD_AB,
        f"La prueba A/B de la primera semana: {MARC.release} (executor v1) contra "
        f"{JORDI.release} (executor v2).",
        tuple(WIDGETS_AB),
    ),
]


def _crear_widget(api: Any, widget: Widget) -> str:
    creado = api.dashboard_widgets.create(
        name=widget.nombre,
        description=widget.descripcion,
        view=DashboardWidgetView(widget.vista),
        dimensions=[DashboardWidgetDimension(field=campo) for campo in widget.dimensiones],
        metrics=[
            DashboardWidgetMetric(measure=medida, agg=DashboardWidgetMetricAggregation(agg))
            for medida, agg in widget.metricas
        ],
        filters=list(widget.filtros),
        chart_type=DashboardWidgetChartType(widget.grafico),
    )
    return str(creado.id)


def ensure_dashboard(langfuse: Any, *, report: Callable[[str], None] = print) -> None:
    """Crea los dashboards que falten. Si uno ya existe (aunque lo hayas cambiado), no lo toca."""

    api = langfuse.api.unstable
    existentes = {dashboard.name for dashboard in api.dashboards.list(limit=100).data}
    for panel in PANELES:
        if panel.nombre in existentes:
            report(f"  Dashboard «{panel.nombre}»: ya existía")
        else:
            _crear_panel(api, panel)
            report(f"  Dashboard «{panel.nombre}»: creado con {len(panel.widgets)} paneles")


def _crear_panel(api: Any, panel: Panel) -> None:
    dashboard = api.dashboards.create(
        name=panel.nombre,
        description=panel.descripcion,
        filters=[_cualquiera("environment", ["production"])],
    )
    creados: list[str] = []
    try:
        x = y = alto_fila = 0
        for widget in panel.widgets:
            if x + widget.ancho > COLUMNAS:
                x, y, alto_fila = 0, y + alto_fila, 0
            creados.append(_crear_widget(api, widget))
            api.dashboards.add_placement(
                dashboard.id,
                request=CreateDashboardPlacementRequest_Widget(
                    widget_id=creados[-1], x=x, y=y, width=widget.ancho, height=widget.alto
                ),
            )
            x += widget.ancho
            alto_fila = max(alto_fila, widget.alto)
    except Exception:
        api.dashboards.delete(dashboard.id)
        for widget_id in creados:
            api.dashboard_widgets.delete(widget_id)
        raise
