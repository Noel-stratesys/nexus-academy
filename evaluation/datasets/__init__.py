"""Los datasets de Nexus. ``uv run dataset`` los sube a Langfuse."""

from evaluation.datasets.agente import DATASET as AGENTE
from evaluation.datasets.definition import Case, DatasetDefinition, upload
from evaluation.datasets.final_dev import DATASET as FINAL_DEV
from evaluation.datasets.orquestador import DATASET as ORQUESTADOR
from evaluation.datasets.rag import DATASET as RAG

DATASETS: dict[str, DatasetDefinition] = {
    "orquestador": ORQUESTADOR,
    "agente": AGENTE,
    "rag": RAG,
    "final-dev": FINAL_DEV,
}

__all__ = ["DATASETS", "Case", "DatasetDefinition", "upload"]
