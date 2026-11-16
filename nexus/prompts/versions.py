"""Las versiones de los prompts que vivieron en producción durante el historial de Nexus.

La primera semana del historial, la mitad de los viajeros habló con el prompt del
executor de Marc y la otra mitad con el de Jordi. Estas son las versiones canónicas que
``uv run seed`` deja en Langfuse, con los números que citan las trazas del historial:

==================  =======  =============================  ==========================
Prompt              Versión  Labels                         Qué es
==================  =======  =============================  ==========================
nexus/orchestrator  1        production, marc, jordi        El orquestador del código
nexus/executor      1        marc                           Marc: sobrio, temperatura 0,2
nexus/executor      2        jordi                          Jordi: cercano, temperatura 0,9
==================  =======  =============================  ==========================

Ninguna versión del executor lleva ``production``: elegir cuál lo lleva es la misión
del capítulo 1. Mientras tanto, Nexus usa el prompt del código (el fallback).

El orquestador también lleva los labels ``marc`` y ``jordi`` porque, durante el A/B, la
aplicación lee **todos** sus prompts con el label de la variante (``prompt_label_scope``).

El prompt de Jordi es más amable, pero no tiene dos reglas del de Marc: «consulta las
herramientas antes de dar horarios» y «si una herramienta no devuelve datos, dilo». Con
temperatura alta, eso basta para que se invente horarios.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from nexus.prompts.definition import PromptDefinition
from nexus.prompts.executor import PROMPT as EXECUTOR_PROMPT
from nexus.prompts.orchestrator import PROMPT as ORCHESTRATOR_PROMPT

EXECUTOR_MARC = PromptDefinition(
    name=EXECUTOR_PROMPT.name,
    node=EXECUTOR_PROMPT.node,
    tags=list(EXECUTOR_PROMPT.tags),
    config={"model": {"temperature": 0.2}},
    messages=[dict(message) for message in EXECUTOR_PROMPT.messages],
)

EXECUTOR_JORDI = PromptDefinition(
    name=EXECUTOR_PROMPT.name,
    node=EXECUTOR_PROMPT.node,
    tags=list(EXECUTOR_PROMPT.tags),
    config={"model": {"temperature": 0.9}},
    messages=[
        {
            "role": "system",
            "content": (
                "¡Hola! Eres Nexus, el compañero de viaje de quienes se mueven con Metro de "
                "Vilaverda (MdV). 🚇\n\n"
                "Hablas con: {{viajero}}\n"
                "Hoy es {{hoy}}.\n\n"
                "Tu estilo:\n"
                "- Trata al viajero con cercanía y buen humor, como alguien del equipo que "
                "conoce la red de memoria. Llámalo por su nombre.\n"
                "- Contesta siempre en el idioma en que te escribe.\n"
                "- Ve al grano y no dejes al viajero con dudas: si te pregunta una hora, "
                "dale una hora.\n"
                "- Para dudas de normas (bicicletas, mascotas, devoluciones...) apóyate en "
                "buscar_normativa y menciona el documento.\n"
                "- Si pide una reclamación, una devolución o avisos de una línea, llama a la "
                "herramienta sin más: el sistema le pedirá que lo apruebe.\n"
                "- Solo se tramita una devolución si la normativa la permite.\n"
                "- Respuestas cortas y con chispa, y despídete deseando un buen viaje.\n\n"
                "Herramientas disponibles:\n{{tool_catalog}}"
            ),
        },
    ],
)


@dataclass(frozen=True)
class CanonicalVersion:
    """Una versión de prompt con el número que tiene en el historial."""

    definition: PromptDefinition
    version: int
    labels: tuple[str, ...]
    message: str

    @property
    def name(self) -> str:
        return self.definition.name


# El orden importa: dentro de cada prompt, las versiones se crean de menor a mayor.
CANONICAL_VERSIONS: list[CanonicalVersion] = [
    CanonicalVersion(
        ORCHESTRATOR_PROMPT,
        1,
        ("production", "marc", "jordi"),
        "Orquestador inicial",
    ),
    CanonicalVersion(EXECUTOR_MARC, 1, ("marc",), "Executor de Marc: sobrio y fiel a las tools"),
    CanonicalVersion(EXECUTOR_JORDI, 2, ("jordi",), "Executor de Jordi: más cercano"),
]

# {(prompt, versión real en Langfuse): versión canónica del historial}
VersionMap = dict[tuple[str, int], int]


def normalize_messages(messages: Sequence[Any]) -> list[dict[str, str]]:
    """Los mensajes de un prompt de chat sin los campos que añade Langfuse."""

    normalized = []
    for message in messages:
        item = cast(Mapping[str, Any], message)
        if item.get("type") == "placeholder":
            normalized.append({"type": "placeholder", "name": str(item["name"])})
        else:
            normalized.append({"role": str(item["role"]), "content": str(item["content"])})
    return normalized


def same_content(prompt: Any, definition: PromptDefinition) -> bool:
    """Si una versión de Langfuse tiene los mensajes y la config de ``definition``."""

    return (
        normalize_messages(prompt.prompt) == normalize_messages(definition.messages)
        and (prompt.config or {}) == definition.config
    )


def _existing_versions(langfuse: Any, name: str) -> list[int]:
    response = langfuse.api.prompts.list(name=name, limit=50)
    for meta in response.data:
        if meta.name == name:
            return sorted(meta.versions)
    return []


def _get_version(langfuse: Any, name: str, version: int) -> Any:
    return langfuse.get_prompt(name, type="chat", version=version, cache_ttl_seconds=0)


def ensure_versions(
    langfuse: Any,
    versions: Sequence[CanonicalVersion] = CANONICAL_VERSIONS,
    *,
    report: Callable[[str], None] = print,
) -> VersionMap:
    """Deja en Langfuse las versiones canónicas, sin duplicarlas, y pone sus labels.

    Si ya existe una versión con el mismo contenido, la reutiliza y solo le añade los
    labels que falten; si no, la crea. Devuelve ``{(prompt, versión real): versión
    canónica}``, porque la versión real puede no coincidir con la del historial cuando el
    proyecto de Langfuse ya tenía otras versiones.
    """

    mapping: VersionMap = {}
    for canonical in versions:
        existing = _existing_versions(langfuse, canonical.name)
        found: Any = None
        used = {real for (name, real) in mapping if name == canonical.name}
        candidates = sorted(existing, key=lambda number: (number != canonical.version, number))
        for number in candidates:
            if number in used:
                continue
            prompt = _get_version(langfuse, canonical.name, number)
            if same_content(prompt, canonical.definition):
                found = prompt
                break
        if found is None:
            created = langfuse.create_prompt(
                name=canonical.name,
                prompt=cast(Any, canonical.definition.messages),
                type="chat",
                labels=list(canonical.labels),
                tags=canonical.definition.tags,
                config=canonical.definition.config,
                commit_message=canonical.message,
            )
            real = int(created.version)
            report(f"  {canonical.name}: creada la versión {real} ({', '.join(canonical.labels)})")
        else:
            real = int(found.version)
            current = [label for label in found.labels if label != "latest"]
            missing = [label for label in canonical.labels if label not in current]
            if missing:
                langfuse.update_prompt(
                    name=canonical.name, version=real, new_labels=[*current, *missing]
                )
                report(f"  {canonical.name}: versión {real}, labels añadidos {', '.join(missing)}")
            else:
                report(f"  {canonical.name}: versión {real} ya estaba lista")
        if real != canonical.version:
            report(
                f"  Aviso: {canonical.name} v{canonical.version} del historial es la versión "
                f"{real} en este Langfuse."
            )
        mapping[(canonical.name, real)] = canonical.version
    return mapping
