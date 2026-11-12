"""El dashboard «Nexus en producción» de Langfuse (lo crea ``uv run seed``).

Muestra el tráfico de producción (``environment = production``) por release: cuántas
conversaciones hay, cuántas se valoran con 👍, cuánto tardan, cuánto gastan y qué
herramientas usan. Es el panel de la prueba A/B de Marc y Jordi (release ``marc`` contra
``jordi``) y el de los despliegues (``blue`` contra ``green``).
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

DASHBOARD = "Nexus en producción"
COLUMNAS = 12


def _cualquiera(columna: str, valores: Sequence[str]) -> DashboardWidgetFilter:
    return DashboardWidgetFilter(
        column=columna, operator="any of", type="stringOptions", value=list(valores)
    )


CONVERSACIONES = _cualquiera("name", ["nexus-agent"])
VALORACIONES = _cualquiera("name", ["user_feedback"])


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
        "% 👍 por release",
        "Media de user_feedback (1 = 👍, 0 = 👎) por release: 0,8 es un 80 % de 👍.",
        "scores-numeric",
        ("traceRelease",),
        (("value", "avg"),),
        (VALORACIONES,),
        "VERTICAL_BAR",
    ),
    Widget(
        "Latencia p95 por release",
        "Lo que tarda el 95 % de los turnos, en segundos, por release.",
        "observations",
        ("release",),
        (("latency", "p95"),),
        (CONVERSACIONES,),
        "VERTICAL_BAR",
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
    """Crea el dashboard si no existe. Si ya existe (aunque lo hayas cambiado), no lo toca."""

    api = langfuse.api.unstable
    existentes = api.dashboards.list(limit=100).data
    if any(dashboard.name == DASHBOARD for dashboard in existentes):
        report(f"  Dashboard «{DASHBOARD}»: ya existía")
        return
    dashboard = api.dashboards.create(
        name=DASHBOARD,
        description="El tráfico de producción de Nexus, por release.",
        filters=[_cualquiera("environment", ["production"])],
    )
    creados: list[str] = []
    try:
        x = y = alto_fila = 0
        for widget in WIDGETS:
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
    report(f"  Dashboard «{DASHBOARD}»: creado con {len(WIDGETS)} paneles")
