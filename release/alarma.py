"""Extra del capítulo 5: la alarma de tokens.

Una llamada al modelo que gasta muchos más tokens de lo normal suele ser un síntoma: un
viajero que pega un texto enorme, una herramienta que devuelve demasiado, un agente que
repite llamadas... ``uv run alarma`` lee de Langfuse las llamadas al modelo de los últimos
minutos y usa ``llamadas_en_alarma`` para decidir cuáles hacen saltar la alarma.

    uv run alarma --umbral 4000     # elige el umbral (se guarda en release.toml)
    uv run alarma                   # mira las llamadas de los últimos 15 minutos
    uv run alarma --provocar        # un viajero pega un texto enorme: la alarma tiene que saltar
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Llamada:
    """Una llamada al modelo tal como la guarda Langfuse: una observación de tipo generation."""

    trace_id: str
    release: str  # blue, green... (vacío si la traza no tiene release)
    tokens_entrada: int
    tokens_salida: int
    inicio: datetime

    @property
    def tokens(self) -> int:
        """Los tokens de la llamada: los de entrada más los de salida."""

        return self.tokens_entrada + self.tokens_salida


def llamadas_en_alarma(llamadas: Sequence[Llamada], umbral: int) -> list[Llamada]:
    """Las llamadas que hacen saltar la alarma, de la que más tokens gasta a la que menos.

    - Una llamada hace saltar la alarma si tiene **más** de ``umbral`` tokens (entrada más
      salida, ``llamada.tokens``). Una llamada con justo ``umbral`` tokens no la hace saltar.
    - Con ``umbral`` 0 o menos la alarma está apagada: devuelve una lista vacía.
    - Devuelve las llamadas ordenadas por tokens, de más a menos.

    Ejemplo, con umbral 4000:

        llamadas con 1800, 9000, 4000 y 5200 tokens
        # devuelve las de 9000 y 5200, en ese orden
    """

    raise NotImplementedError("Completa llamadas_en_alarma: es el extra del capítulo 5.")
