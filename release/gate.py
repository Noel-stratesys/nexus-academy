"""La puerta: un cambio solo recibe tráfico si el experimento llega a los mínimos.

Se compara la media de cada score del experimento sobre el dataset ``agente`` con el
mínimo de ``[gate]`` en ``release.toml``. Si un score no aparece en el experimento, la
puerta no se da por superada: no hay evidencia de que vaya bien.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GateRow:
    score: str
    minimo: float
    media: float | None

    @property
    def ok(self) -> bool:
        # Un pequeño margen para que 0.9999999 cuente como 1.
        return self.media is not None and self.media >= self.minimo - 1e-9


def check_gate(averages: Mapping[str, float], thresholds: Mapping[str, float]) -> list[GateRow]:
    """Una fila por score de la puerta, con su media (``None`` si no hay dato)."""

    return [GateRow(name, minimo, averages.get(name)) for name, minimo in thresholds.items()]


def gate_passed(rows: list[GateRow]) -> bool:
    return all(row.ok for row in rows)


def format_gate(rows: list[GateRow]) -> str:
    """La tabla de la puerta, lista para imprimir."""

    lines = [f"  {'Score':<26} {'media':>7} {'mínimo':>7}  resultado"]
    for row in rows:
        media = "  —    " if row.media is None else f"{row.media:7.3f}"
        verdict = "✔ pasa" if row.ok else ("✘ sin datos" if row.media is None else "✘ no pasa")
        lines.append(f"  {row.score:<26} {media} {row.minimo:7.2f}  {verdict}")
    passed = gate_passed(rows)
    lines.append("")
    lines.append(
        "Puerta superada: el cambio puede recibir tráfico."
        if passed
        else "Puerta NO superada: el cambio no debe recibir tráfico."
    )
    return "\n".join(lines)
