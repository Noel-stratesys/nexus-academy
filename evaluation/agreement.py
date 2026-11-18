"""¿Los jueces coinciden con las personas? (``uv run judge-agreement``)

Un LLM-as-a-judge es un evaluador más, y también se equivoca. Para fiarnos de él lo
comparamos con anotaciones humanas sobre las mismas trazas.

Las notas tienen tres niveles: **0**, **0,5** y **1**. Cada score se lleva a uno de ellos:

- un número, al nivel más cercano (0,8 → 1; 0,4 → 0,5);
- un booleano, a 1 si es verdadero y a 0 si no;
- una categoría, por su posición en la configuración del score (**Settings → Scores**):
  la primera categoría es 0; la del medio, 0,5; la última, 1. Así «brusco / seco /
  cercano» o «irrelevante / poco relevante / relevante» valen igual que «0 / 0.5 / 1».
  El juez no tiene configuración propia: se usan las etiquetas del score humano con el
  que se compara, así que **el juez tiene que devolver las mismas etiquetas**. Si no las
  encuentra, prueba con la etiqueta: «0», «0.5», «1», «Relevant», «Partially relevant»...

Y se mide:

- **Concordancia exacta**: en qué porcentaje de trazas el juez y la persona ponen el
  mismo nivel.
- **Kappa ponderada** (pesos lineales): la kappa de Cohen cuando los niveles tienen orden.
  Un 0 frente a un 0,5 cuenta como medio desacuerdo; un 0 frente a un 1, como uno entero.
  Por encima de 0,6 se considera buena; por debajo de 0,4, el juez todavía no es fiable.

Sin argumentos compara los dos jueces de la misión del capítulo 3::

    uv run judge-agreement
    uv run judge-agreement --humano tono_humano --juez tono   # solo un par
"""

import argparse
import os
import re
import sys
from collections import Counter
from typing import Any, NamedTuple

import httpx

from nexus.settings import initialize_environment

LEVELS = (0.0, 0.5, 1.0)

# (score humano, score del juez) de la misión del capítulo 3.
PAIRS = {
    "Tono (tu criterio)": ("tono_humano", "tono"),
    "Relevancia (plantilla de Langfuse)": ("relevancia_humana", "answer_relevance"),
}

# Etiquetas de las categorías: primero se mira si es parcial, luego negativa, luego positiva
# («Not relevant» contiene «relevant»; «Partially relevant», también).
PARTIAL_WORDS = ("partial", "parcial", "a medias", "somewhat", "mixed", "regular", "poco", "seco")
NEGATIVE_FIRST_WORDS = {"not", "no", "non", "nada", "mal", "false", "falso", "brusco"}
NEGATIVE_PREFIXES = (
    "irrelevant",
    "unrelated",
    "off topic",
    "inadecuad",
    "inapropiad",
    "incorrect",
    "ungrounded",
    "unsupported",
)
POSITIVE_FIRST_WORDS = {"sí", "si", "yes", "bien", "fiel", "true", "verdadero", "ok", "cercano"}
POSITIVE_PREFIXES = ("relevant", "adecuad", "apropiad", "correct", "grounded", "supported")


def _client() -> httpx.Client:
    initialize_environment()
    return httpx.Client(
        base_url=os.environ["LANGFUSE_BASE_URL"],
        auth=(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]),
        timeout=30,
    )


def fetch_scores(client: httpx.Client, name: str) -> list[dict[str, Any]]:
    """Todos los scores con ese nombre, página a página."""

    scores: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"name": name, "fields": "subject,details", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/public/v3/scores", params=params)
        response.raise_for_status()
        payload = response.json()
        scores.extend(payload["data"])
        cursor = payload.get("meta", {}).get("cursor")
        if not cursor:
            return scores


def trace_id(score: dict[str, Any]) -> str | None:
    subject = score.get("subject") or {}
    if subject.get("kind") == "trace":
        return subject.get("id")
    return subject.get("traceId") or score.get("traceId")


Labels = dict[str, float]  # etiqueta de una categoría (en minúsculas) → nivel


def fetch_configs(client: httpx.Client) -> tuple[dict[str, Labels], dict[str, Labels]]:
    """Las configuraciones de score categóricas: sus niveles por id y por nombre."""

    by_id: dict[str, Labels] = {}
    by_name: dict[str, Labels] = {}
    page = 1
    while True:
        response = client.get("/api/public/score-configs", params={"page": page, "limit": 100})
        response.raise_for_status()
        payload = response.json()
        for config in payload["data"]:
            if config.get("dataType") == "CATEGORICAL" and config.get("categories"):
                labels = category_levels(config["categories"])
                by_id[config["id"]] = labels
                if not config.get("isArchived"):
                    by_name[config["name"]] = labels
        if page >= payload.get("meta", {}).get("totalPages", 1):
            return by_id, by_name
        page += 1


def category_levels(categories: list[dict[str, Any]]) -> Labels:
    """La primera categoría (por valor) es 0; la última, 1; las de en medio, en proporción."""

    ordered = sorted(categories, key=lambda category: float(category["value"]))
    top = max(len(ordered) - 1, 1)
    return {
        str(category["label"]).strip().lower(): _nearest(index / top)
        for index, category in enumerate(ordered)
    }


def _nearest(value: float) -> float:
    return min(LEVELS, key=lambda level: abs(level - value))


def _label_level(label: str) -> float | None:
    text = re.sub(r"[_\-]+", " ", label.strip().lower())
    number = text.replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", number):
        return _nearest(float(number))
    first = text.split()[0] if text.split() else ""
    if any(word in text for word in PARTIAL_WORDS):
        return 0.5
    if first in NEGATIVE_FIRST_WORDS or text.startswith(NEGATIVE_PREFIXES):
        return 0.0
    if first in POSITIVE_FIRST_WORDS or text.startswith(POSITIVE_PREFIXES):
        return 1.0
    return None


def _label(score: dict[str, Any]) -> str:
    return str(score.get("stringValue") or score.get("value") or "")


def to_level(score: dict[str, Any], labels: Labels | None = None) -> float | None:
    """El nivel (0, 0,5 o 1) de un score de Langfuse, o ``None`` si no se entiende.

    ``labels`` son los niveles de las categorías de su configuración, si la tiene.
    """

    data_type = score.get("dataType")
    if data_type == "CATEGORICAL":
        label = _label(score)
        if labels and label.strip().lower() in labels:
            return labels[label.strip().lower()]
        return _label_level(label)
    if data_type == "BOOLEAN":
        return 1.0 if float(score.get("value") or 0) else 0.0
    value = score.get("value")
    if value is None:
        return None
    return _nearest(float(value))


def weighted_kappa(pairs: list[tuple[float, float]], levels: tuple[float, ...] = LEVELS) -> float:
    """Kappa de Cohen con pesos lineales para notas ordenadas (persona, juez).

    Con solo dos niveles (0 y 1) da lo mismo que la kappa de Cohen de siempre.
    """

    total = len(pairs)
    span = max(levels) - min(levels)
    human = Counter(h for h, _ in pairs)
    judge = Counter(j for _, j in pairs)
    observed = sum(abs(h - j) for h, j in pairs) / (total * span)
    expected = sum(human[a] * judge[b] * abs(a - b) for a in levels for b in levels) / (
        total * total * span
    )
    return 1.0 if expected == 0 else 1 - observed / expected


class Nota(NamedTuple):
    """La nota de una traza: su nivel, la etiqueta tal cual y el comentario (el del juez)."""

    level: float
    label: str
    comment: str


def collect_notes(
    client: httpx.Client,
    name: str,
    configs: dict[str, Labels] | None = None,
    labels: Labels | None = None,
) -> tuple[dict[str, Nota], list[str]]:
    """La nota de cada traza para el score ``name`` y las etiquetas que no se entienden.

    Cada score usa las categorías de su configuración (``configs``, por id); si no tiene,
    las de ``labels``. Si una traza tiene varias notas (has vuelto a lanzar el juez), cuenta
    la más reciente.
    """

    found: dict[str, Nota] = {}
    unknown: list[str] = []
    scores = sorted(fetch_scores(client, name), key=lambda s: s.get("timestamp") or "")
    for score in scores:
        key = trace_id(score)
        level = to_level(score, (configs or {}).get(score.get("configId") or "") or labels)
        if level is None:
            unknown.append(_label(score))
        elif key:
            comment = " ".join((score.get("comment") or "").split())
            found[key] = Nota(level, _label(score), comment)
    return found, unknown


def collect(
    client: httpx.Client,
    name: str,
    configs: dict[str, Labels] | None = None,
    labels: Labels | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Nivel de cada traza para el score ``name`` y las etiquetas que no se entienden."""

    notes, unknown = collect_notes(client, name, configs, labels)
    return {key: note.level for key, note in notes.items()}, unknown


def _collect_pair_notes(
    client: httpx.Client, human_name: str, judge_name: str
) -> tuple[dict[str, Nota], dict[str, Nota], list[str], list[str], Labels | None]:
    by_id, by_name = fetch_configs(client)
    human_labels = by_name.get(human_name)
    human, unknown_h = collect_notes(client, human_name, by_id, human_labels)
    judge, unknown_j = collect_notes(
        client, judge_name, by_id, by_name.get(judge_name) or human_labels
    )
    return human, judge, unknown_h, unknown_j, human_labels


def collect_pair(
    client: httpx.Client, human_name: str, judge_name: str
) -> tuple[dict[str, float], dict[str, float], list[str], list[str]]:
    """Niveles de la persona y del juez. El juez usa las etiquetas del score humano."""

    human, judge, unknown_h, unknown_j, _ = _collect_pair_notes(client, human_name, judge_name)
    return (
        {key: note.level for key, note in human.items()},
        {key: note.level for key, note in judge.items()},
        unknown_h,
        unknown_j,
    )


# ── Presentación ──────────────────────────────────────────────────────────────────────────

KAPPA_OK = 0.6
KAPPA_MEH = 0.4


def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _color() else text


def _bold(text: str) -> str:
    return _paint(text, "1")


def _dim(text: str) -> str:
    return _paint(text, "2")


def _fmt(level: float) -> str:
    return {0.0: "0", 0.5: "0,5", 1.0: "1"}[level]


def _fmt_num(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _verdict(kappa: float) -> str:
    goal = f"(objetivo: {_fmt_num(KAPPA_OK)})"
    if kappa >= KAPPA_OK:
        return _paint("✔ Fiable", "32")
    if kappa >= KAPPA_MEH:
        return _paint(f"~ Mejora la rúbrica {goal}", "33")
    return _paint(f"✘ No lo uses todavía {goal}", "31")


def _bar(kappa: float, width: int = 20) -> str:
    """Barra de 0 a 1 con una marca en el objetivo (0,6)."""

    filled = round(max(0.0, min(kappa, 1.0)) * width)
    cells = ["█" if i < filled else "░" for i in range(width)]
    cells.insert(round(KAPPA_OK * width), "│")
    return "".join(cells)


def _level_names(labels: Labels | None) -> dict[float, str]:
    """El nombre de cada nivel: la etiqueta de la categoría o, si no hay, el número."""

    names = {level: _fmt(level) for level in LEVELS}
    for label, level in (labels or {}).items():
        names[level] = label
    return names


def _trace_names() -> dict[str, tuple[str, str]]:
    """id de traza → (``cap3-XX``, pregunta), para las trazas del capítulo 3."""

    try:
        from langfuse import Langfuse

        from evaluation.trazas_cap3 import TRAZAS
    except ImportError:
        return {}
    return {
        Langfuse.create_trace_id(seed=f"nexus-academy-{t.id}"): (t.id, t.pregunta) for t in TRAZAS
    }


def _print_matrix(pairs: list[tuple[float, float]], labels: Labels | None) -> None:
    """Filas: tus notas; columnas: las del juez. La diagonal es donde coincidís."""

    names = _level_names(labels)
    width = max(7, *(len(names[level]) for level in LEVELS)) + 2
    head = 3 + max(len(names[level]) for level in LEVELS) + 1
    table = Counter(pairs)
    print()
    print("   " + " " * head + _dim("juez →".rjust(width)))
    print("   " + " " * head + "".join(names[j].rjust(width) for j in LEVELS))
    for i, h in enumerate(LEVELS):
        row = ("tú " if i == 0 else "   ") + names[h]
        cells = ""
        for j in LEVELS:
            count = table[(h, j)]
            cell = (str(count) if count else "·").rjust(width)
            if not count:
                cell = _dim(cell)
            elif h == j:
                cell = _paint(cell, "32;1")
            elif abs(h - j) == 1:
                cell = _paint(cell, "31;1")
            cells += cell
        print("   " + row.ljust(head) + cells)
    print(_dim("   La diagonal es donde coincidís; las esquinas, un punto entero de diferencia."))


def report(client: httpx.Client, title: str, human_name: str, judge_name: str) -> None:
    human, judge, unknown_h, unknown_j, labels = _collect_pair_notes(client, human_name, judge_name)
    common = sorted(human.keys() & judge.keys())

    print()
    print(_bold(f"━━ {title} " + "━" * max(3, 76 - len(title))))
    print(
        f"   Tú: «{human_name}» ({len(human)} trazas)  ·  "
        f"Juez: «{judge_name}» ({len(judge)} trazas)  ·  Con las dos notas: {len(common)}"
    )
    for name, unknown in ((human_name, unknown_h), (judge_name, unknown_j)):
        if unknown:
            warning = f"   ⚠ No sé a qué nivel corresponden estas etiquetas de «{name}»: "
            print(_paint(warning, "33") + ", ".join(sorted(set(unknown))))
    if not common:
        print("   No hay trazas con las dos notas. Anota trazas que el juez ya haya evaluado.")
        return

    pairs = [(human[key].level, judge[key].level) for key in common]
    kappa = weighted_kappa(pairs)
    matches = sum(1 for h, j in pairs if h == j)
    print()
    print(
        f"   Kappa ponderada  {_bold(_fmt_num(kappa).rjust(5))}  {_bar(kappa)}  {_verdict(kappa)}"
    )
    print(f"   Concordancia     {matches / len(pairs):>5.0%}  {matches} de {len(pairs)} trazas")
    _print_matrix(pairs, labels)

    disagreements = [key for key in common if human[key].level != judge[key].level]
    if not disagreements:
        print("\n   Sin desacuerdos.")
        return

    names = _trace_names()
    base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
    disagreements.sort(
        key=lambda k: (-abs(human[k].level - judge[k].level), names.get(k, (k, ""))[0])
    )
    print()
    print(
        _bold(f"   Desacuerdos ({len(disagreements)})")
        + _dim(" · empieza por los de un punto entero")
    )
    for key in disagreements:
        h, j = human[key], judge[key]
        name, question = names.get(key, (key[:8], ""))
        full = abs(h.level - j.level) == 1
        gap = _paint("un punto entero", "31") if full else _dim("medio punto")
        print()
        print(f"   {_bold(name)}  {_short(question, 66)}")
        print(
            f"      Tú: {h.label} ({_fmt(h.level)})  ·  Juez: {j.label} ({_fmt(j.level)})  ·  {gap}"
        )
        if j.comment:
            print(_dim(f"      Por qué, según el juez: «{_short(j.comment, 140)}»"))
        print(_dim(f"      {base}/project/nexus/traces/{key}"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="judge-agreement", description="¿Los jueces coinciden con las personas?"
    )
    parser.add_argument("--humano", help="Score de las personas (con --juez: solo ese par).")
    parser.add_argument("--juez", help="Score del LLM-as-a-judge.")
    args = parser.parse_args(argv)
    # Las terminales de Windows no siempre escriben en UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if bool(args.humano) != bool(args.juez):
        parser.error("--humano y --juez van juntos.")

    pairs = {"Tu par": (args.humano, args.juez)} if args.humano else PAIRS
    with _client() as client:
        for title, (human_name, judge_name) in pairs.items():
            report(client, title, human_name, judge_name)
