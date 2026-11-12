"""¿El juez coincide con las personas? (``uv run judge-agreement``)

Un LLM-as-a-judge es un evaluador más, y también se equivoca. Para fiarnos de él lo
comparamos con anotaciones humanas sobre las mismas trazas:

- **Concordancia**: en qué porcentaje de trazas el juez y la persona dicen lo mismo.
- **Kappa de Cohen**: la concordancia descontando la que saldría por azar. Por encima
  de 0,6 se considera buena; por debajo de 0,4, el juez todavía no es fiable.

Los dos scores se binarizan: un número es "bien" si llega al umbral; un booleano, si es
verdadero; una categoría, si está entre las etiquetas positivas.

    uv run judge-agreement --humano fidelidad_humana --juez fidelidad
"""

import argparse
import os
from collections import Counter
from typing import Any

import httpx

from nexus.settings import initialize_environment

POSITIVE_LABELS = {"correcto", "correcta", "fiel", "si", "sí", "yes", "true", "bien", "1"}


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


def _trace_id(score: dict[str, Any]) -> str | None:
    subject = score.get("subject") or {}
    if subject.get("kind") == "trace":
        return subject.get("id")
    return subject.get("traceId") or score.get("traceId")


def binarize(score: dict[str, Any], threshold: float) -> int:
    if score.get("dataType") == "CATEGORICAL":
        label = str(score.get("stringValue") or score.get("value") or "").strip().lower()
        return 1 if label in POSITIVE_LABELS else 0
    return 1 if float(score.get("value") or 0) >= threshold else 0


def cohen_kappa(pairs: list[tuple[int, int]]) -> float:
    """Kappa de Cohen para dos evaluadores con etiquetas 0/1."""

    total = len(pairs)
    observed = sum(1 for human, judge in pairs if human == judge) / total
    human_yes = sum(human for human, _ in pairs) / total
    judge_yes = sum(judge for _, judge in pairs) / total
    expected = human_yes * judge_yes + (1 - human_yes) * (1 - judge_yes)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="judge-agreement", description="¿El juez coincide con las personas?"
    )
    parser.add_argument("--humano", default="fidelidad_humana", help="Score de las personas.")
    parser.add_argument("--juez", default="fidelidad", help="Score del LLM-as-a-judge.")
    parser.add_argument("--umbral", type=float, default=0.5, help="Desde qué valor es 'bien'.")
    args = parser.parse_args(argv)

    with _client() as client:
        human = {_trace_id(s): binarize(s, args.umbral) for s in fetch_scores(client, args.humano)}
        judge = {_trace_id(s): binarize(s, args.umbral) for s in fetch_scores(client, args.juez)}
    common = sorted(key for key in human.keys() & judge.keys() if key)

    print(f"Scores humanos «{args.humano}»: {len(human)}  ·  del juez «{args.juez}»: {len(judge)}")
    if not common:
        print("No hay trazas con los dos scores. Anota trazas que el juez ya haya evaluado.")
        return
    pairs = [(human[key], judge[key]) for key in common]
    agreement = sum(1 for h, j in pairs if h == j) / len(pairs)
    table = Counter(pairs)
    print(f"Trazas con los dos scores: {len(pairs)}")
    print(f"Concordancia: {agreement:.0%}   Kappa de Cohen: {cohen_kappa(pairs):.2f}\n")
    print("                    juez: bien   juez: mal")
    print(f"  persona: bien     {table[(1, 1)]:>9}   {table[(1, 0)]:>9}")
    print(f"  persona: mal      {table[(0, 1)]:>9}   {table[(0, 0)]:>9}")
    disagreements = [key for key in common if human[key] != judge[key]]
    if disagreements:
        print("\nDesacuerdos (revisa estas trazas para mejorar la rúbrica):")
        base = os.environ["LANGFUSE_BASE_URL"]
        for key in disagreements:
            verdicts = (
                f"persona {'bien' if human[key] else 'mal'}, juez {'bien' if judge[key] else 'mal'}"
            )
            print(f"  {base}/project/nexus/traces/{key}  ({verdicts})")
