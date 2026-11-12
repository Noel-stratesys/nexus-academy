"""Los cuatro cambios que esperan despliegue el viernes.

Cada cambio dice cómo queda el prompt del executor y qué flags activa. El prompt se
construye **sobre el que está en producción** en el momento de prepararlo (el de
``nexus/prompts/executor.py`` mientras no se haya promocionado nada): así, si se
promociona primero D y después C, o al revés, ninguno borra lo que añadió el otro.

B, C y D están hechos sobre A: A tiene que estar en producción antes de prepararlos.

``uv run release prepare <cambio>`` publica el prompt del cambio con el label ``green``.
"""

from collections.abc import Callable
from dataclasses import dataclass

from nexus.prompts import EXECUTOR_PROMPT_NAME, PROMPTS_BY_NAME
from nexus.prompts.definition import ChatMessage
from release.prompt_corto import PROMPT_CORTO

# El prompt del executor tal como está en el código.
CODE_TEXT = PROMPTS_BY_NAME[EXECUTOR_PROMPT_NAME].messages[0]["content"]

# Frase del tono de Marc (cambio A). La lleva todo lo que se construye sobre A.
TONO_A = "Habla con cercanía"

# Regla de Jordi (cambio B) que sustituye a la de comprobar la normativa.
REGLA_B = (
    "Devoluciones ágiles: si el viajero pide que le devuelvan el dinero, llama a "
    "solicitar_devolucion enseguida. No hace falta consultar antes la normativa ni las "
    "incidencias: queremos menos fricción con el viajero."
)

# Regla que añade D para que el modelo use la herramienta nueva.
REGLA_D = "Para saber cuándo pasan los próximos trenes por una estación, usa proximos_trenes."

VARIABLES = ("{{viajero}}", "{{hoy}}", "{{tool_catalog}}")


class CambioError(ValueError):
    """El cambio no se puede construir sobre el prompt que hay en producción."""


def _replace(text: str, old: str, new: str) -> str:
    """``text`` con ``old`` cambiado por ``new``; falla si ``old`` no está."""

    if old not in text:
        raise CambioError(f"El prompt de producción no contiene {old!r}.")
    return text.replace(old, new, 1)


def _before_tools(text: str, line: str) -> str:
    """``text`` con ``line`` justo antes de la lista de herramientas."""

    head, separator, tail = text.rpartition("\n\nHerramientas")
    if not separator:
        raise CambioError("El prompt de producción no tiene la lista de herramientas.")
    return f"{head}\n{line}{separator}{tail}"


def _cambio_a(production: str) -> str:
    return _replace(
        production,
        "7. Sé breve y concreto: dos o tres frases, con los datos útiles.\n",
        f"7. {TONO_A}: saluda al viajero por su nombre y háblale de tú. Si hay una "
        "incidencia o un aviso que afecta a su viaje, empieza por él, en una frase clara.\n"
        "8. Sé breve y concreto: dos o tres frases, con los datos útiles.\n",
    )


def _cambio_b(production: str) -> str:
    text = production.replace(
        "(bicicletas, mascotas, devoluciones...)", "(bicicletas, mascotas...)"
    )
    regla = "6. Solo se tramita una devolución si la normativa la permite.\n"
    if regla in text:
        return text.replace(regla, f"6. {REGLA_B}\n")
    text = text.replace(" Devolución solo si la normativa la permite.", "")
    return _before_tools(text, f"- {REGLA_B}")


def _cambio_c(production: str) -> str:
    # El prompt corto sustituye al de producción, pero conserva la regla de D si ya está.
    return _before_tools(PROMPT_CORTO, f"- {REGLA_D}") if REGLA_D in production else PROMPT_CORTO


def _cambio_d(production: str) -> str:
    if REGLA_D in production:
        return production
    # En el prompt largo las reglas van numeradas; en el corto, con guiones.
    numbered = "\n8. " in production
    return _before_tools(production, f"9. {REGLA_D}" if numbered else f"- {REGLA_D}")


@dataclass(frozen=True)
class Cambio:
    clave: str
    autor: str
    promesa: str
    detalle: str
    build: Callable[[str], str]
    flags: frozenset[str] = frozenset()
    # Frase que tiene que estar en producción antes de preparar este cambio.
    requiere: str | None = None

    def executor_prompt(self, production: str = CODE_TEXT) -> str:
        """El prompt del executor de este cambio, construido sobre ``production``."""

        if self.requiere and self.requiere not in production:
            raise CambioError(
                f"El cambio {self.clave} está hecho sobre A: promociona A antes de prepararlo."
            )
        text = self.build(production)
        missing = [variable for variable in VARIABLES if variable not in text]
        if missing:
            raise CambioError(f"Al prompt del cambio {self.clave} le faltan {', '.join(missing)}")
        return text

    def messages(self, production: str = CODE_TEXT) -> list[ChatMessage]:
        return [{"role": "system", "content": self.executor_prompt(production)}]


CAMBIOS: dict[str, Cambio] = {
    cambio.clave: cambio
    for cambio in [
        Cambio(
            clave="A",
            autor="Marc",
            promesa="Tono más cercano y avisos más claros",
            detalle="Saluda por el nombre y empieza por el aviso que afecta al viajero.",
            build=_cambio_a,
        ),
        Cambio(
            clave="B",
            autor="Jordi",
            promesa="Devoluciones más ágiles: menos fricción con el viajero",
            detalle="Pide la devolución en cuanto el viajero la reclama.",
            build=_cambio_b,
            requiere=TONO_A,
        ),
        Cambio(
            clave="C",
            autor="Laia",
            promesa="Prompt más corto: −30 % de tokens",
            detalle="Sustituye el prompt del executor por uno compacto (release/prompt_corto.py).",
            build=_cambio_c,
            requiere=TONO_A,
        ),
        Cambio(
            clave="D",
            autor="Jordi",
            promesa="Herramienta nueva: próximos trenes en tiempo real",
            detalle="Activa la herramienta proximos_trenes (flag proximos_trenes).",
            build=_cambio_d,
            flags=frozenset({"proximos_trenes"}),
            requiere=TONO_A,
        ),
    ]
}


def code_prompt_with_a() -> str:
    """El prompt del código con A aplicado: la base habitual de B, C y D."""

    return CAMBIOS["A"].executor_prompt(CODE_TEXT)
