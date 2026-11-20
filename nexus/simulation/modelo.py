"""El modelo con guion que reproduce el historial de Nexus (``uv run seed``).

El historial no se genera con un modelo de lenguaje: ``uv run seed`` ejecuta el grafo de
Nexus de verdad (orquestador, executor, herramientas y buscador de normativa) y solo
sustituye el modelo por este, que sigue un guion. Así el historial es el mismo para todo
el mundo, no gasta tokens y las trazas tienen la forma de las de producción.

El guion de cada conversación (``Guion``) dice qué pide el viajero y cómo se comporta esa
versión de Nexus. A partir de ahí, el modelo decide con lo que ve, como uno de verdad:

- Llama a las herramientas de ``expected["llamadas"]`` con los argumentos tal como los
  dice el viajero (``"jueves"``, no la fecha).
- Redacta la respuesta con lo que **devuelven** las herramientas, no con la verdad del
  escenario: si una herramienta se equivoca, la respuesta repite el error.
- El tono sale del prompt que recibe: cercano si el prompt pide cercanía (el de Jordi, o el
  cambio A), sobrio si no. Si el prompt no le obliga a consultar las herramientas antes de
  dar horarios y el guion dice ``inventa``, da la hora sin consultarla.

Los despliegues del capítulo 5 (``uv run release gate`` y ``uv run simulate``) usan el
mismo modelo, así que tampoco gastan tokens. Ahí el modelo también reacciona a los
prompts y a las herramientas de cada despliegue, como lo haría uno de verdad.

En la puerta, cada caso del dataset ``agente`` hace de guion (``guion_de_caso``): el modelo
usa las herramientas que espera el caso y da los datos que pide. Con ``instalar(latencia=True)``
cada llamada tarda lo que tardaría la de un modelo de verdad con esos tokens.
"""

import ast
import asyncio
import hashlib
import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from nexus.data import estaciones, lineas, load
from nexus.data import viajero as buscar_viajero
from nexus.rag.documents import load_documents
from nexus.simulation.types import Scenario

ACCIONES = ("abrir_reclamacion", "solicitar_devolucion", "suscribir_alertas")

# Lo que tarda una llamada simulada: un mínimo, más lo que cuesta leer la entrada y
# escribir la salida (segundos por token). Del orden de un modelo de 70B en la nube.
LATENCIA_BASE_S = 0.2
LATENCIA_ENTRADA_S = 1 / 15000
LATENCIA_SALIDA_S = 1 / 150

# Si las llamadas tardan lo que tardaría un modelo de verdad (``instalar(latencia=True)``).
_latencia = {"activa": False}


def latencia_simulada(entrada: int, salida: int) -> float:
    """Los segundos que tarda una llamada con ``entrada`` y ``salida`` tokens."""

    return LATENCIA_BASE_S + entrada * LATENCIA_ENTRADA_S + salida * LATENCIA_SALIDA_S


@dataclass(frozen=True)
class Guion:
    """Cómo transcurre una conversación del historial.

    ``semilla`` hace reproducibles los detalles (identificadores, frases); ``inventa``
    deja que una versión sin la regla de consultar las herramientas responda horarios de
    memoria; ``reintentos`` son las veces que Nexus repite una consulta al sistema central
    de incidencias antes de preguntar línea a línea.
    """

    scenario: Scenario
    semilla: str
    inventa: bool = False
    reintentos: int = 0


_GUION: ContextVar[Guion | None] = ContextVar("guion_historial", default=None)


@contextmanager
def guion_scope(guion: Guion) -> Iterator[None]:
    """El guion que sigue el modelo mientras dure el bloque."""

    token = _GUION.set(guion)
    try:
        yield
    finally:
        _GUION.reset(token)


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def _fraccion(*parts: object) -> float:
    return int(_hash(*parts)[:16], 16) / 16**16


def _elige(opciones: Sequence[Any], *parts: object) -> Any:
    return opciones[int(_fraccion(*parts) * len(opciones))]


def _tokens(texto: str) -> int:
    return round(len(texto) / 3.6)


# La clase de LangChain de cada proveedor: las generaciones del historial llevan su nombre,
# como las de producción.
CLASES_DE_PROVEEDOR = {
    "groq": ["langchain_groq", "chat_models", "ChatGroq"],
    "openai": ["langchain_openai", "chat_models", "base", "ChatOpenAI"],
    "ollama": ["langchain_ollama", "chat_models", "ChatOllama"],
}


class ModeloConGuion(BaseChatModel):
    """Modelo de chat determinista que sigue el ``Guion`` activo (``guion_scope``)."""

    model_name: str
    proveedor: str = "groq"
    temperature: float = 0.0
    max_tokens: int | None = None
    herramientas: list[dict[str, Any]] = []

    @property
    def _llm_type(self) -> str:
        return f"{self.proveedor}-chat"

    def to_json(self) -> Any:
        clase = CLASES_DE_PROVEEDOR.get(self.proveedor, CLASES_DE_PROVEEDOR["groq"])
        return {"lc": 1, "type": "not_implemented", "id": clase, "repr": clase[-1]}

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> Any:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = self.proveedor
        return params

    @property
    def _identifying_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.herramientas:
            params["tools"] = self.herramientas
        return params

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ModeloConGuion":
        return self.model_copy(
            update={"herramientas": [convert_to_openai_tool(tool) for tool in tools]}
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._responder(messages)
        if _latencia["activa"]:
            time.sleep(_segundos(message))
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._responder(messages)
        if _latencia["activa"]:
            await asyncio.sleep(_segundos(message))
        return ChatResult(generations=[ChatGeneration(message=message)])

    # --- decisiones -------------------------------------------------------------------

    def _responder(self, messages: list[BaseMessage]) -> AIMessage:
        guion = _GUION.get()
        if guion is None:
            raise RuntimeError("ModeloConGuion necesita un guion: usa guion_scope().")
        nombres = [tool["function"]["name"] for tool in self.herramientas]
        if nombres == ["ModelVerdict"]:
            verdict = guion.scenario.expected.get("verdict", "valid")
            return self._mensaje(messages, "", [("ModelVerdict", {"verdict": verdict})], guion)

        sistema = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
        ultima = max(i for i, message in enumerate(messages) if isinstance(message, HumanMessage))
        turno = messages[ultima + 1 :]
        paso = sum(1 for m in turno if isinstance(m, AIMessage) and m.tool_calls)
        # Si una herramienta pidió volver a consultar, el modelo la vuelve a llamar.
        repetir = _pendientes(turno)
        if repetir:
            return self._mensaje(messages, "", repetir, guion, paso)
        es_caso = bool(guion.scenario.expected.get("caso"))
        pasos = _pasos_caso(guion, sistema, nombres) if es_caso else _pasos(guion, sistema, nombres)
        if paso < len(pasos):
            return self._mensaje(messages, "", pasos[paso], guion, paso)
        resultados = _resultados(turno)
        texto = (
            redactar_caso(guion, sistema, resultados)
            if es_caso
            else redactar(guion, sistema, resultados)
        )
        return self._mensaje(messages, texto, [], guion, paso)

    def _mensaje(
        self,
        messages: list[BaseMessage],
        texto: str,
        llamadas: Sequence[tuple[str, dict[str, Any]]],
        guion: Guion,
        paso: int = 0,
    ) -> AIMessage:
        tool_calls = [
            {
                "name": name,
                "args": args,
                "id": "call_" + _hash(guion.semilla, paso, index, name)[:24],
                "type": "tool_call",
            }
            for index, (name, args) in enumerate(llamadas)
        ]
        entrada = sum(_tokens(_contenido(message)) + 4 for message in messages) + _tokens(
            json.dumps(self.herramientas, ensure_ascii=False)
        )
        salida = max(
            1,
            _tokens(texto)
            + _tokens(json.dumps([[name, args] for name, args in llamadas], ensure_ascii=False)),
        )
        return AIMessage(
            content=texto,
            tool_calls=tool_calls,
            usage_metadata={
                "input_tokens": entrada,
                "output_tokens": salida,
                "total_tokens": entrada + salida,
            },
            response_metadata={
                "model_name": self.model_name,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            },
        )


def _segundos(message: AIMessage) -> float:
    uso = message.usage_metadata or {}
    return latencia_simulada(int(uso.get("input_tokens", 0)), int(uso.get("output_tokens", 0)))


def instalar(*, latencia: bool = False) -> None:
    """Hace que ``nexus.llm.models.chat_model`` cree modelos con guion en vez de los reales.

    Con ``latencia``, cada llamada tarda lo que tardaría la de un modelo de verdad (el
    historial no lo necesita: reescribe las horas de sus trazas).
    """

    import nexus.llm.models as models

    _latencia["activa"] = latencia

    def crear(model: str, **parametros: Any) -> ModeloConGuion:
        proveedor, _, nombre = model.partition(":")
        return ModeloConGuion(
            model_name=nombre or proveedor,
            proveedor=proveedor if nombre else "groq",
            temperature=parametros.get("temperature", 0.0),
            max_tokens=parametros.get("max_tokens"),
        )

    models.init_chat_model = crear  # type: ignore[attr-defined]


def _contenido(message: BaseMessage) -> str:
    texto = str(message.content)
    if isinstance(message, AIMessage) and message.tool_calls:
        texto += json.dumps([call["args"] for call in message.tool_calls], ensure_ascii=False)
    return texto


def _obliga_a_consultar(sistema: str) -> bool:
    """Si el prompt exige consultar las herramientas antes de dar horarios."""

    bajo = sistema.lower()
    return "consulta las herramientas antes" in bajo or "consulta siempre las herramientas" in bajo


def _es_cercano(sistema: str) -> bool:
    return "cercanía" in sistema.lower()


def _responde_en_su_idioma(sistema: str) -> bool:
    """Si el prompt tiene alguna regla sobre el idioma de la respuesta.

    Sin ella, el modelo contesta en el idioma del prompt: en castellano.
    """

    return "idioma" in sistema.lower()


def _devoluciones_agiles(sistema: str) -> bool:
    """Si el prompt pide tramitar las devoluciones sin consultar antes la normativa."""

    return "devoluciones ágiles" in sistema.lower()


def _idioma_respuesta(guion: Guion, sistema: str) -> Guion:
    """El guion con el idioma en que contestará el modelo con este prompt."""

    if _responde_en_su_idioma(sistema) or guion.scenario.idioma == "es":
        return guion
    return replace(guion, scenario=replace(guion.scenario, idioma="es"))


def _pendientes(turno: Sequence[BaseMessage]) -> list[tuple[str, dict[str, Any]]]:
    """Las llamadas de la última vuelta cuya herramienta pidió volver a consultar."""

    ultima = next((m for m in reversed(turno) if isinstance(m, AIMessage) and m.tool_calls), None)
    if ultima is None:
        return []
    ids = {call["id"] for call in ultima.tool_calls}
    calculando = {
        message.tool_call_id
        for message in turno
        if isinstance(message, ToolMessage)
        and message.tool_call_id in ids
        and leer_resultado(message.content).get("estado") == "calculando"
    }
    return [
        (call["name"], dict(call["args"])) for call in ultima.tool_calls if call["id"] in calculando
    ]


def _args_devolucion(scenario: Scenario) -> dict[str, Any]:
    """La devolución que pide el modelo cuando no consulta antes la normativa."""

    llamadas = scenario.expected.get("llamadas", [])
    pedida = next((c["args"] for c in llamadas if c["name"] == "solicitar_devolucion"), None)
    if pedida is not None:
        return dict(pedida)
    verdad = scenario.expected.get("verdad", {})
    return {
        "titulo": verdad.get("titulo", "senzill"),
        "importe": verdad.get("importe_viaje") or _precio_senzill(),
        "motivo": "retraso",
        "incidencia_id": verdad.get("incidencia"),
    }


def _precio_senzill() -> float:
    return float(load("tarifas")["titulos"]["senzill"]["precios"]["1"])


def _pasos(
    guion: Guion, sistema: str, disponibles: Sequence[str] = ()
) -> list[list[tuple[str, dict[str, Any]]]]:
    """Las llamadas a herramientas de cada vuelta del agente, en orden."""

    scenario = guion.scenario
    llamadas = [
        (call["name"], dict(call["args"])) for call in scenario.expected.get("llamadas", [])
    ]
    if scenario.categoria == "devoluciones" and _devoluciones_agiles(sistema):
        return [[("solicitar_devolucion", _args_devolucion(scenario))]]
    if scenario.expected.get("verdad", {}).get("dato") == "proximos":
        args = dict(llamadas[0][1])
        if "proximos_trenes" in disponibles:
            return [[("proximos_trenes", args)]]
        # Sin la herramienta nueva, lo más parecido: la frecuencia de ahora.
        hora = args.get("hora", "08:00")
        horario = {"linea": args["linea"], "estacion": args["estacion"], "dia": "hoy", "hora": hora}
        return [[("consultar_horario", horario)]]
    if scenario.categoria == "horarios" and guion.inventa and not _obliga_a_consultar(sistema):
        return []
    if scenario.categoria == "incidencias" and scenario.expected["verdad"].get("sin_linea"):
        dia = llamadas[0][1]["dia"]
        central = [[("consultar_incidencias", {"dia": dia})] for _ in range(guion.reintentos + 1)]
        por_linea = [
            ("consultar_incidencias", {"dia": dia, "linea": code}) for code in sorted(lineas())
        ]
        return [*central, por_linea]
    consultas = [call for call in llamadas if call[0] not in ACCIONES]
    acciones = [call for call in llamadas if call[0] in ACCIONES]
    return [paso for paso in (consultas, acciones) if paso]


@dataclass(frozen=True)
class Resultado:
    nombre: str
    args: dict[str, Any]
    datos: dict[str, Any]


def leer_resultado(contenido: Any) -> dict[str, Any]:
    """El dict que devolvió una herramienta (LangChain lo guarda como texto)."""

    if isinstance(contenido, dict):
        return contenido
    texto = str(contenido)
    for parser in (json.loads, ast.literal_eval):
        try:
            value = parser(texto)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict):
            return value
    return {"texto": texto}


def _resultados(turno: Sequence[BaseMessage]) -> list[Resultado]:
    pedidas = {
        call["id"]: call
        for message in turno
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    resultados = []
    for message in turno:
        if isinstance(message, ToolMessage) and message.tool_call_id in pedidas:
            call = pedidas[message.tool_call_id]
            resultados.append(
                Resultado(call["name"], call["args"], leer_resultado(message.content))
            )
    return resultados


# --- redacción ---------------------------------------------------------------------------

MESES = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
    "ca": ["gener", "febrer", "març", "abril", "maig", "juny", "juliol", "agost", "setembre",
           "octubre", "novembre", "desembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
}  # fmt: skip

DIA_TEXTO = {
    "es": {
        "hoy": "hoy", "mañana": "mañana", "lunes": "el lunes", "martes": "el martes",
        "miércoles": "el miércoles", "jueves": "el jueves", "viernes": "el viernes",
        "sábado": "el sábado", "domingo": "el domingo",
    },
    "ca": {"avui": "avui", "demà": "demà"},
    "en": {
        "today": "today", "tomorrow": "tomorrow", "monday": "on Monday",
        "tuesday": "on Tuesday", "wednesday": "on Wednesday", "thursday": "on Thursday",
        "friday": "on Friday", "saturday": "on Saturday", "sunday": "on Sunday",
    },
}  # fmt: skip

# Las incidencias en catalán e inglés: (descripción, alternativa).
INCIDENCIAS_TRADUCIDAS: dict[str, dict[str, tuple[str, str | None]]] = {
    "INC-0291": {
        "ca": (
            "Avaria d'un tren entre Sant Martí de Dalt i Hospital General, amb retards de "
            "fins a 45 minuts",
            "Autobús 22 entre Parc del Riu i Hospital General",
        ),
        "en": (
            "A train has broken down between Sant Martí de Dalt and Hospital General, with "
            "delays of up to 45 minutes",
            "Bus 22 between Parc del Riu and Hospital General",
        ),
    },
    "INC-0294": {
        "ca": (
            "Un dels dos ascensors d'Hospital General està fora de servei per substitució; "
            "l'altre funciona amb normalitat",
            None,
        ),
        "en": (
            "One of the two lifts at Hospital General is out of service while it is "
            "replaced; the other one works normally",
            None,
        ),
    },
    "INC-0297": {
        "ca": (
            "Vaga parcial, amb serveis mínims del 60 % en hora punta i del 40 % la resta del dia",
            None,
        ),
        "en": (
            "Partial strike, with minimum services of 60% at peak times and 40% the rest of "
            "the day",
            None,
        ),
    },
    "INC-0301": {
        "ca": (
            "Obres de renovació de via: sense servei entre Rambla de les Flors i Les Fonts "
            "tot el dia",
            "Autobús llançadora L3 cada 6 minuts entre Rambla de les Flors i Les Fonts, amb "
            "parada a Universitat",
        ),
        "en": (
            "Track renewal works: no service between Rambla de les Flors and Les Fonts all day",
            "L3 shuttle bus every 6 minutes between Rambla de les Flors and Les Fonts, "
            "stopping at Universitat",
        ),
    },
    "INC-0305": {
        "ca": (
            "Tancament anticipat a les 22:00 entre Can Riera i Turó Alt per manteniment de "
            "la catenària",
            "Autobús N1 des d'Universitat",
        ),
        "en": (
            "Early closure at 22:00 between Can Riera and Turó Alt for overhead line maintenance",
            "Night bus N1 from Universitat",
        ),
    },
    "INC-0308": {
        "ca": (
            "L'estació Plaça Major està tancada per una concentració autoritzada; els trens "
            "hi passen sense parar",
            "Feu servir Rambla de les Flors o Passeig Marítim",
        ),
        "en": (
            "Plaça Major station is closed for an authorised demonstration; trains pass "
            "through without stopping",
            "Use Rambla de les Flors or Passeig Marítim",
        ),
    },
    "INC-0311": {
        "ca": (
            "Cap de setmana sense servei entre Port de Vilaverda i Plaça Major per obres "
            "d'impermeabilització",
            "Autobús llançadora L1 entre Port de Vilaverda i Plaça Major",
        ),
        "en": (
            "No service between Port de Vilaverda and Plaça Major all weekend due to "
            "waterproofing works",
            "L1 shuttle bus between Port de Vilaverda and Plaça Major",
        ),
    },
}  # fmt: skip

TITULOS = {
    "senzill": {"es": "el billete sencillo", "ca": "el bitllet senzill", "en": "a single ticket"},
    "t10": {"es": "la T-10", "ca": "la T-10", "en": "the T-10"},
    "tmes": {"es": "la T-Mes", "ca": "la T-Mes", "en": "the T-Mes"},
    "tjove": {"es": "la T-Jove", "ca": "la T-Jove", "en": "the T-Jove"},
    "tturista": {"es": "la T-Turista", "ca": "la T-Turista", "en": "the T-Turista"},
    "aeroport": {"es": "el billete Aeroport", "ca": "el bitllet Aeroport",
                 "en": "the Aeroport ticket"},
}  # fmt: skip

NOTAS_TITULO = {
    "senzill": {
        "es": "Vale para un viaje, con transbordos durante 75 minutos.",
        "ca": "Val per a un viatge, amb transbordaments durant 75 minuts.",
        "en": "It covers one journey, with transfers for 75 minutes.",
    },
    "t10": {
        "es": "Son 10 viajes, multipersonal, con transbordos durante 75 minutos.",
        "ca": "Són 10 viatges, multipersonal, amb transbordaments durant 75 minuts.",
        "en": "It gives you 10 journeys, can be shared, with transfers for 75 minutes.",
    },
    "tmes": {
        "es": "Viajes ilimitados durante 30 días naturales; es personal.",
        "ca": "Viatges il·limitats durant 30 dies naturals; és personal.",
        "en": "Unlimited journeys for 30 days; it is personal.",
    },
    "tjove": {
        "es": "Viajes ilimitados durante 90 días para menores de 26 años.",
        "ca": "Viatges il·limitats durant 90 dies per a menors de 26 anys.",
        "en": "Unlimited journeys for 90 days for under-26s.",
    },
    "tturista": {
        "es": "Viajes ilimitados en todas las zonas, incluido el Aeroport.",
        "ca": "Viatges il·limitats a totes les zones, inclòs l'Aeroport.",
        "en": "Unlimited journeys in all zones, including the Aeroport.",
    },
    "aeroport": {
        "es": "La T-10 y la T-Mes no son válidas en Aeroport.",
        "ca": "La T-10 i la T-Mes no són vàlides a l'Aeroport.",
        "en": "Your T-10 is not valid at Aeroport: you need this ticket.",
    },
}

OBJETOS_TRADUCIDOS = {
    "OBJ-5521": {"es": "un paraguas negro plegable", "ca": "un paraigua negre plegable",
                 "en": "a black folding umbrella"},
    "OBJ-5530": {"es": "una mochila azul con un portátil",
                 "ca": "una motxilla blava amb un portàtil",
                 "en": "a blue backpack with a laptop"},
    "OBJ-5560": {"es": "unas llaves con un llavero de un faro",
                 "ca": "unes claus amb un clauer d'un far",
                 "en": "a set of keys with a lighthouse keyring"},
}  # fmt: skip


def _t(idioma: str, es: str, ca: str, en: str) -> str:
    return {"es": es, "ca": ca, "en": en}[idioma]


def _mayuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


def _sin_punto(texto: str) -> str:
    return texto.rstrip().rstrip(".")


def _dia(palabra: str, idioma: str) -> str:
    return DIA_TEXTO[idioma].get(palabra, palabra)


def _fecha(texto_o_fecha: str | date, idioma: str) -> str:
    """``2026-11-02`` o ``lunes 2 de noviembre de 2026`` → ``2 de noviembre`` (o similar)."""

    if isinstance(texto_o_fecha, date):
        dia = texto_o_fecha
    else:
        match = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", texto_o_fecha)
        if match:
            mes = MESES["es"].index(match.group(2)) + 1
            dia = date(int(match.group(3)), mes, int(match.group(1)))
        else:
            dia = date.fromisoformat(texto_o_fecha[:10])
    mes = MESES[idioma][dia.month - 1]
    return _t(idioma, f"{dia.day} de {mes}", f"{dia.day} de {mes}", f"{dia.day} {mes}")


def _euros(importe: float, idioma: str) -> str:
    coma = f"{importe:.2f}".replace(".", ",")
    return _t(idioma, f"{coma} €", f"{coma} €", f"€{importe:.2f}")


def _incidencia(incidencia: dict[str, Any], idioma: str) -> str:
    traducida = INCIDENCIAS_TRADUCIDAS.get(incidencia["id"], {}).get(idioma)
    descripcion, alternativa = traducida or (incidencia["descripcion"], incidencia["alternativa"])
    texto = f"{_sin_punto(descripcion)} ({incidencia['id']})."
    if alternativa:
        texto += " " + _t(idioma, "Alternativa", "Alternativa", "Alternative") + ": "
        texto += _sin_punto(alternativa) + "."
    return texto


def redactar(guion: Guion, sistema: str, resultados: Sequence[Resultado]) -> str:
    """La respuesta final al viajero, con lo que devolvieron las herramientas."""

    guion = _idioma_respuesta(guion, sistema)
    scenario = guion.scenario
    if scenario.expected.get("verdad", {}).get("dato") == "proximos":
        texto = _proximos(guion, resultados)
        return _con_cercania(texto, guion) if _es_cercano(sistema) else texto
    redactores = {
        "horarios": _horarios,
        "incidencias": _incidencias,
        "tarifas": _tarifas,
        "normativa": _normativa,
        "objetos_perdidos": _objetos,
        "acciones": _acciones,
        "devoluciones": _devoluciones,
    }
    texto = redactores[scenario.categoria](guion, resultados)
    return _con_cercania(texto, guion) if _es_cercano(sistema) else texto


def _con_cercania(texto: str, guion: Guion) -> str:
    scenario = guion.scenario
    persona = buscar_viajero(scenario.viajero)
    nombre = persona.nombre if persona else ""
    saludos = {
        "es": [f"¡Hola, {nombre}! ", f"¡Hola {nombre}! 😊 ", f"¡Buenas, {nombre}! "],
        "ca": [f"Hola, {nombre}! ", f"Bon dia, {nombre}! 😊 ", f"Ei, {nombre}! "],
        "en": [f"Hi {nombre}! ", f"Hey {nombre}! 😊 ", f"Hello {nombre}! "],
    }[scenario.idioma]
    despedidas = {
        "es": ["¡Buen viaje! 🚇", "¡Que tengas buen viaje! 🚇", "¡Feliz viaje! 😊"],
        "ca": ["Bon viatge! 🚇", "Que tinguis bon viatge! 🚇", "Bon trajecte! 😊"],
        "en": ["Have a great trip! 🚇", "Enjoy your ride! 🚇", "Safe travels! 😊"],
    }[scenario.idioma]
    saludo = _elige(saludos, guion.semilla, "saludo")
    despedida = _elige(despedidas, guion.semilla, "despedida")
    return f"{saludo}{texto} {despedida}"


# Horarios ---------------------------------------------------------------------------------


def _inventado(dato: str, verdad: dict[str, Any], semilla: str) -> str | int:
    """Lo que contesta de memoria una versión que no consulta la herramienta."""

    horario = verdad["horario"]
    if dato == "frecuencia":
        real = horario.get("frecuencia_min")
        opciones = [n for n in (4, 5, 6, 7, 10) if n != real] if real else [15, 20]
        return _elige(opciones, semilla, "inventa")
    real = horario[dato]
    opciones = {
        "primer_tren": ["05:15", "05:30", "05:45", "06:00"],
        "ultimo_tren": ["23:30", "00:00", "00:30", "01:00"],
    }[dato]
    return _elige([hora for hora in opciones if hora != real], semilla, "inventa")


def _horarios(guion: Guion, resultados: Sequence[Resultado]) -> str:
    scenario = guion.scenario
    idioma = scenario.idioma
    args = scenario.expected["llamadas"][0]["args"]
    linea, estacion, hora = args["linea"], args["estacion"], args.get("hora")
    dia = _dia(args["dia"], idioma)
    dato = scenario.expected["verdad"]["dato"]
    datos = resultados[0].datos if resultados else None
    if datos is not None and "error" in datos:
        return _t(
            idioma,
            f"No he podido consultar ese horario: {datos['error']}",
            f"No he pogut consultar aquest horari: {datos['error']}",
            f"I couldn't check that timetable: {datos['error']}",
        )
    valor: Any
    if datos is None:
        valor = _inventado(dato, scenario.expected["verdad"], guion.semilla)
    elif dato == "frecuencia":
        valor = datos.get("frecuencia_min")
    else:
        valor = datos[dato]

    if dato == "frecuencia" and valor is None:
        primer = datos["primer_tren"] if datos else "05:00"
        return _t(
            idioma,
            f"A las {hora} no hay servicio en la {linea}. El primer tren pasa por {estacion} "
            f"a las {primer}.",
            f"A les {hora} no hi ha servei a la {linea}. El primer metro passa per {estacion} "
            f"a les {primer}.",
            f"No service on the {linea} at {hora} {dia}. The first train stops at {estacion} "
            f"at {primer}.",
        )
    if dato == "frecuencia":
        return _t(
            idioma,
            f"{_mayuscula(dia)} hacia las {hora}, la {linea} pasa por {estacion} cada "
            f"{valor} minutos.",
            f"{_mayuscula(dia)} cap a les {hora}, la {linea} passa per {estacion} cada "
            f"{valor} minuts.",
            f"Around {hora} {dia}, the {linea} stops at {estacion} every {valor} minutes.",
        )
    if "toda la noche" in str(valor):
        return _t(
            idioma,
            f"Sí: la noche del sábado al domingo la {linea} circula sin interrupción por "
            f"{estacion}, con un tren cada 15 minutos.",
            f"Sí: la nit de dissabte a diumenge la {linea} circula tota la nit per {estacion}, "
            "amb un tren cada 15 minuts.",
            f"Yes: on Saturday night the {linea} runs all night at {estacion}, with a train "
            "every 15 minutes.",
        )
    if dato == "ultimo_tren" and scenario.scenario_id == "hor-nocturno-es":
        return (
            f"No, la {linea} no funciona toda la noche: el último tren pasa por {estacion} "
            f"a las {valor}."
        )
    if dato == "primer_tren":
        return _t(
            idioma,
            f"El primer tren de la {linea} pasa por {estacion} {dia} a las {valor}.",
            f"El primer metro de la {linea} passa per {estacion} {dia} a les {valor}.",
            f"The first {linea} train stops at {estacion} {dia} at {valor}.",
        )
    return _t(
        idioma,
        f"El último tren de la {linea} pasa por {estacion} {dia} a las {valor}.",
        f"L'últim metro de la {linea} passa per {estacion} {dia} a les {valor}.",
        f"The last {linea} train leaves {estacion} {dia} at {valor}.",
    )


# Próximos trenes --------------------------------------------------------------------------


def _todavia_calculando(idioma: str) -> str:
    return _t(
        idioma,
        "Todavía estoy calculando los próximos trenes. Vuelve a preguntarme en unos segundos.",
        "Encara estic calculant els propers metros. Torna-m'ho a preguntar d'aquí a uns segons.",
        "I'm still working out the next trains. Please ask me again in a few seconds.",
    )


def _proximos(guion: Guion, resultados: Sequence[Resultado]) -> str:
    scenario = guion.scenario
    idioma = scenario.idioma
    args = scenario.expected["llamadas"][0]["args"]
    linea, estacion = args["linea"], args["estacion"]
    datos = resultados[-1].datos if resultados else {}
    if datos.get("estado") == "calculando":
        return _todavia_calculando(idioma)
    if "error" in datos:
        return _t(
            idioma,
            f"No he podido consultar los próximos trenes: {datos['error']}",
            f"No he pogut consultar els propers metros: {datos['error']}",
            f"I couldn't check the next trains: {datos['error']}",
        )
    trenes = [tren["hora"] for tren in datos.get("proximos_trenes", [])]
    if trenes:
        primeros, ultimo = ", ".join(trenes[:-1]), trenes[-1]
        lista = _t(idioma, f"{primeros} y {ultimo}", f"{primeros} i {ultimo}",
                   f"{primeros} and {ultimo}") if primeros else ultimo  # fmt: skip
        return _t(
            idioma,
            f"Los próximos trenes de la {linea} pasan por {estacion} a las {lista}.",
            f"Els propers metros de la {linea} passen per {estacion} a les {lista}.",
            f"The next {linea} trains stop at {estacion} at {lista}.",
        )
    frecuencia = datos.get("frecuencia_min")
    if frecuencia:
        return _t(
            idioma,
            f"No tengo los trenes en tiempo real, pero ahora la {linea} pasa por {estacion} "
            f"cada {frecuencia} minutos.",
            f"No tinc els metros en temps real, però ara la {linea} passa per {estacion} cada "
            f"{frecuencia} minuts.",
            f"I don't have real-time trains, but the {linea} stops at {estacion} every "
            f"{frecuencia} minutes right now.",
        )
    return _t(
        idioma,
        f"Ahora no pasan más trenes de la {linea} por {estacion}.",
        f"Ara no passen més metros de la {linea} per {estacion}.",
        f"There are no more {linea} trains at {estacion} now.",
    )


# Incidencias ------------------------------------------------------------------------------


def _incidencias(guion: Guion, resultados: Sequence[Resultado]) -> str:
    scenario = guion.scenario
    idioma = scenario.idioma
    por_linea = [r for r in resultados if r.args.get("linea") and "incidencias" in r.datos]

    if scenario.scenario_id.startswith("inc-ascensor"):
        encontradas = [
            incidencia
            for r in por_linea
            for incidencia in r.datos["incidencias"]
            if incidencia["tipo"] == "accesibilidad" and "Hospital General" in incidencia["tramo"]
        ]
        if encontradas:
            return _t(idioma, "Hoy: ", "Avui: ", "Today: ") + _incidencia(encontradas[0], idioma)
        return _t(
            idioma,
            "Hoy los ascensores de Hospital General funcionan con normalidad.",
            "Avui els ascensors d'Hospital General funcionen amb normalitat.",
            "Today the lifts at Hospital General are working normally.",
        )

    if scenario.expected["verdad"].get("sin_linea"):
        dia = _dia(resultados[0].args["dia"], idioma) if resultados else ""
        if not por_linea:
            return _t(
                idioma,
                "Ahora mismo el sistema de incidencias no responde. Prueba en unos minutos.",
                "Ara mateix el sistema d'incidències no respon. Torna-ho a provar d'aquí a una "
                "estona.",
                "The incident system is not responding right now. Please try again shortly.",
            )
        vistas: dict[str, tuple[str, dict[str, Any]]] = {}
        for r in por_linea:
            for incidencia in r.datos["incidencias"]:
                vistas.setdefault(incidencia["id"], (r.datos["linea"], incidencia))
        if not vistas:
            return _t(
                idioma,
                f"{_mayuscula(dia)} no hay incidencias previstas en ninguna línea: toda la red "
                "funciona con normalidad.",
                f"{_mayuscula(dia)} no hi ha cap incidència prevista a cap línia: tota la xarxa "
                "funciona amb normalitat.",
                f"There are no incidents planned on any line {dia}: the whole network is "
                "running normally.",
            )
        lineas_txt = " ".join(
            f"{linea}: {_incidencia(incidencia, idioma)}" for linea, incidencia in vistas.values()
        )
        return _t(
            idioma,
            f"{_mayuscula(dia)} hay incidencias en la red. {lineas_txt} El resto de líneas "
            "funciona con normalidad.",
            f"{_mayuscula(dia)} hi ha incidències a la xarxa. {lineas_txt} La resta de línies "
            "funciona amb normalitat.",
            f"There are incidents on the network {dia}. {lineas_txt} All other lines are "
            "running normally.",
        )

    frases = []
    for r in por_linea:
        dia = _dia(r.args["dia"], idioma)
        linea = r.datos["linea"]
        if r.datos["incidencias"]:
            detalle = " ".join(
                _incidencia(incidencia, idioma) for incidencia in r.datos["incidencias"]
            )
            frases.append(
                _t(
                    idioma,
                    f"{_mayuscula(dia)} hay incidencias en la {linea}: {detalle}",
                    f"{_mayuscula(dia)} hi ha incidències a la {linea}: {detalle}",
                    f"There are incidents on the {linea} {dia}: {detalle}",
                )
            )
        else:
            frases.append(
                _t(
                    idioma,
                    f"{_mayuscula(dia)} la {linea} funciona con normalidad: no hay incidencias "
                    "previstas.",
                    f"{_mayuscula(dia)} la {linea} funciona amb normalitat: no hi ha cap "
                    "incidència prevista.",
                    f"The {linea} is running normally {dia}: no incidents are planned.",
                )
            )
    return " ".join(frases)


# Tarifas ----------------------------------------------------------------------------------


def _tarifas(guion: Guion, resultados: Sequence[Resultado]) -> str:
    scenario = guion.scenario
    idioma = scenario.idioma
    verdad = scenario.expected["verdad"]
    datos = resultados[0].datos
    clave = next(key for key in datos if key not in ("moneda", "titulos", "error"))
    importe = datos[clave]["precios"][verdad["precio"]]
    precio = verdad["precio"]
    if precio.isdigit():
        n = int(precio)
        cuanto = _t(
            idioma,
            f" de {n} zona{'s' if n > 1 else ''}",
            f" de {n} zona{'es' if n > 1 else ''}",
            f" for {n} zone{'s' if n > 1 else ''}",
        )
    elif precio.endswith("h"):
        cuanto = _t(idioma, f" de {precio[:-1]} horas", f" de {precio[:-1]} hores",
                    f" for {precio[:-1]} hours")  # fmt: skip
    else:
        cuanto = ""
    titulo = _mayuscula(TITULOS[clave][idioma])
    euros = _euros(importe, idioma)
    frase = _t(
        idioma,
        f"{titulo}{cuanto} cuesta {euros}.",
        f"{titulo}{cuanto} costa {euros}.",
        f"{titulo}{cuanto} costs {euros}.",
    )
    return f"{frase} {NOTAS_TITULO[clave][idioma]}"


# Normativa --------------------------------------------------------------------------------


def _documento_vigente(doc_id: str) -> bool:
    return next((doc.vigente for doc in load_documents() if doc.doc_id == doc_id), True)


def _normativa(guion: Guion, resultados: Sequence[Resultado]) -> str:
    scenario = guion.scenario
    verdad = scenario.expected["verdad"]
    fragmentos = resultados[0].datos.get("fragmentos", []) if resultados else []
    primero = fragmentos[0] if fragmentos else {"id": "", "documento": ""}
    derogada = not _documento_vigente(str(primero["id"]).split("#")[0])
    sid = scenario.scenario_id

    if sid.startswith("nor-bici") or sid == "historia-marta":
        if derogada:
            return _t(
                scenario.idioma,
                "Sí, puedes subir con la bici al metro a cualquier hora y cualquier día, "
                "también en hora punta. Tiene que ir en el último coche y tú con ella. Lo dice "
                f"la {primero['documento']}.",
                "Sí, pots pujar al metro amb la bici a qualsevol hora i qualsevol dia, també en "
                "hora punta. Ha d'anar a l'últim cotxe i l'has d'acompanyar. Ho diu la "
                f"{primero['documento']}.",
                "Yes, you can take your bike on the metro at any time on any day, even at peak "
                "times. It must go in the last carriage and you must stay with it, according "
                f"to the {primero['documento']}.",
            )
        if verdad["permitido"]:
            return _t(
                scenario.idioma,
                "Sí: a esa hora se admiten bicicletas no plegables, en el primer o el último "
                "coche (Normativa de viajeros, edición 2026).",
                "Sí: a aquella hora s'admeten bicicletes no plegables, al primer o a l'últim "
                "cotxe (Normativa de viatgers, edició 2026).",
                "Yes: non-folding bikes are allowed at that time, in the first or last "
                "carriage (Passenger rules, 2026 edition).",
            )
        return _t(
            scenario.idioma,
            "No: los días laborables no se puede entrar con una bicicleta no plegable de "
            "7:00 a 9:30 ni de 17:00 a 20:00. Si es plegable, sí (Normativa de viajeros, "
            "edición 2026).",
            "No: els dies feiners no es pot entrar amb una bicicleta no plegable de 7:00 a "
            "9:30 ni de 17:00 a 20:00. Si és plegable, sí (Normativa de viatgers, edició 2026).",
            "No: on weekdays non-folding bikes are not allowed from 7:00 to 9:30 or from 17:00 "
            "to 20:00. Folding bikes are fine (Passenger rules, 2026 edition).",
        )
    if sid.startswith("nor-patinete"):
        if derogada:
            return (
                "Yes, you can bring a scooter, electric or not, as long as it is folded "
                f"(source: {primero['documento']})."
            )
        return (
            "Only if it is a foldable electric scooter, and it must stay folded and switched "
            "off in stations and trains (Passenger rules, 2026 edition)."
        )
    if sid.startswith("nor-perro"):
        return (
            "Sí. Un perro grande puede viajar con correa de 1,5 metros como máximo y con bozal, "
            "fuera de las franjas de máxima afluencia de los días laborables, y solo un perro "
            "por persona (Viajar con animales de compañía)."
        )
    if sid.startswith("nor-accesible"):
        if verdad["accesible"]:
            return (
                "Sí, Les Fonts tiene acceso sin escalones hasta el andén (Guía de accesibilidad)."
            )
        return (
            "No. Les Fonts es una de las cuatro estaciones sin acceso sin escalones: al andén "
            "solo se llega por escaleras. Te recomiendo usar la estación accesible más cercana "
            "de la L3 (Guía de accesibilidad)."
        )
    if sid.startswith("nor-vapear"):
        return (
            "No, no es pot vapejar en cap espai de MdV, tampoc a l'andana. La multa és de "
            f"{verdad['sancion_euros']} euros (Normativa de viatgers de Metro de Vilaverda, "
            "edició 2026)."
        )
    raise ValueError(f"No sé redactar la normativa de {sid}")


# Objetos perdidos -------------------------------------------------------------------------


def _objetos(guion: Guion, resultados: Sequence[Resultado]) -> str:
    idioma = guion.scenario.idioma
    encontrados = resultados[0].datos.get("encontrados", []) if resultados else []
    if not encontrados:
        return _t(
            idioma,
            "No consta ningún objeto que encaje con tu descripción. Si aparece, lo llevarán a "
            "la oficina de objetos perdidos de Estació Central.",
            "No consta cap objecte que encaixi amb la teva descripció. Si apareix, el portaran "
            "a l'oficina d'objectes perduts d'Estació Central.",
            "Nothing matching your description has been found yet. If it turns up, it will be "
            "taken to the lost property office at Estació Central.",
        )
    objeto = encontrados[0]
    que = OBJETOS_TRADUCIDOS.get(objeto["id"], {}).get(idioma, objeto["descripcion"].lower())
    cuando = _fecha(objeto["fecha"], idioma)
    return _t(
        idioma,
        f"Sí: el {cuando} se encontró {que} en {objeto['estacion']} (referencia "
        f"{objeto['id']}). Puedes recogerlo en la oficina de objetos perdidos de Estació "
        "Central, de 8:00 a 20:00, con tu DNI.",
        f"Sí: el {cuando} es va trobar {que} a {objeto['estacion']} (referència "
        f"{objeto['id']}). El pots recollir a l'oficina d'objectes perduts d'Estació Central, "
        "de 8:00 a 20:00, amb el DNI.",
        f"Yes: {que} was found at {objeto['estacion']} on {cuando} (reference {objeto['id']}). "
        "You can collect it at the lost property office in Estació Central, from 8:00 to "
        "20:00, with your ID.",
    )


# Acciones ---------------------------------------------------------------------------------


def _acciones(guion: Guion, resultados: Sequence[Resultado]) -> str:
    idioma = guion.scenario.idioma
    accion = next(r for r in resultados if r.nombre in ACCIONES)
    referencia = accion.datos.get("referencia")
    if accion.nombre == "suscribir_alertas":
        linea = accion.args["linea"]
        if referencia:
            return _t(
                idioma,
                f"Hecho: te he suscrito a los avisos de incidencias de la {linea} (referencia "
                f"{referencia}).",
                f"Fet: t'he subscrit als avisos d'incidències de la {linea} (referència "
                f"{referencia}).",
                f"Done: you are now subscribed to {linea} incident alerts (reference "
                f"{referencia}).",
            )
        return _t(
            idioma,
            f"De acuerdo, no te he suscrito a los avisos de la {linea}.",
            f"D'acord, no t'he subscrit als avisos de la {linea}.",
            f"OK, I haven't subscribed you to the {linea} alerts.",
        )
    if referencia:
        return _t(
            idioma,
            f"He registrado tu reclamación (referencia {referencia}). Te responderán en un "
            "plazo de 15 días hábiles.",
            f"He registrat la teva reclamació (referència {referencia}). Et respondran en un "
            "termini de 15 dies hàbils.",
            f"I've registered your complaint (reference {referencia}). You'll get an answer "
            "within 15 working days.",
        )
    return _t(
        idioma,
        "De acuerdo, no he abierto la reclamación. Si cambias de opinión, dímelo y la registro.",
        "D'acord, no he obert la reclamació. Si canvies d'opinió, digues-m'ho i la registro.",
        "OK, I haven't opened the complaint. If you change your mind, just tell me.",
    )


# Devoluciones -----------------------------------------------------------------------------


def _devoluciones(guion: Guion, resultados: Sequence[Resultado]) -> str:
    scenario = guion.scenario
    idioma = scenario.idioma
    verdad = scenario.expected["verdad"]
    incidencia = verdad.get("incidencia")
    solicitud = next((r for r in resultados if r.nombre == "solicitar_devolucion"), None)
    if solicitud is not None and solicitud.datos.get("referencia"):
        euros = _euros(float(solicitud.args["importe"]), idioma)
        referencia = solicitud.datos["referencia"]
        return _t(
            idioma,
            f"He solicitado la devolución de {euros} por la incidencia {incidencia} "
            f"(referencia {referencia}). El abono se hace en 10 días hábiles.",
            f"He sol·licitat la devolució de {euros} per la incidència {incidencia} "
            f"(referència {referencia}). L'abonament es fa en 10 dies hàbils.",
            f"I've requested a refund of {euros} for incident {incidencia} (reference "
            f"{referencia}). It will be paid within 10 working days.",
        )
    if solicitud is not None:
        return _t(
            idioma,
            "De acuerdo, no he pedido la devolución.",
            "D'acord, no he demanat la devolució.",
            "OK, I haven't requested the refund.",
        )
    motivo = verdad["motivo"]
    if motivo == "título ilimitado":
        return _t(
            idioma,
            "Lo siento, pero con un título ilimitado como la T-Mes no hay devolución por "
            "retrasos, según la Política de devoluciones y reclamaciones.",
            "Ho sento, però amb un títol il·limitat com la T-Mes no hi ha devolució per "
            "retards, segons la Política de devolucions i reclamacions.",
            "Sorry, unlimited tickets like the T-Mes are not refunded for delays, according to "
            "the refunds and complaints policy.",
        )
    if motivo.startswith("huelga"):
        return _t(
            idioma,
            f"Lo siento, pero la huelga ({incidencia}) tenía servicios mínimos anunciados y, "
            "en ese caso, la Política de devoluciones y reclamaciones no prevé devolver el "
            "importe.",
            f"Ho sento, però la vaga ({incidencia}) tenia serveis mínims anunciats i, en aquest "
            "cas, la Política de devolucions i reclamacions no preveu retornar l'import.",
            f"Sorry, the strike ({incidencia}) had announced minimum services, and in that case "
            "the refunds and complaints policy does not cover a refund.",
        )
    if motivo.startswith("obras"):
        return _t(
            idioma,
            f"Lo siento, pero las obras ({incidencia}) estaban anunciadas y había servicio "
            "alternativo, así que la Política de devoluciones no prevé devolver el importe.",
            f"Ho sento, però les obres ({incidencia}) estaven anunciades i hi havia servei "
            "alternatiu, així que la Política de devolucions no preveu retornar l'import.",
            f"Sorry, the works ({incidencia}) were announced in advance and there was a "
            "replacement service, so the refunds policy does not cover a refund.",
        )
    return _t(
        idioma,
        "Lo siento, solo se devuelve el viaje si el retraso supera los 30 minutos por una "
        "incidencia de MdV registrada.",
        "Ho sento, només es retorna el viatge si el retard supera els 30 minuts per una "
        "incidència de MdV registrada.",
        "Sorry, journeys are only refunded for delays of more than 30 minutes caused by a "
        "registered MdV incident.",
    )


# --- La puerta: cada caso del dataset agente hace de guion ---------------------------------

MESES_CASO = {
    **{mes: numero for numero, mes in enumerate(MESES["es"], start=1)},
    **{mes: numero for numero, mes in enumerate(MESES["ca"], start=1)},
    **{mes.lower(): numero for numero, mes in enumerate(MESES["en"], start=1)},
}
DIAS_SEMANA_CASO = (
    "lunes|martes|miércoles|jueves|viernes|sábado|domingo|"
    "dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|"
    "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
)


def guion_de_caso(
    entrada: Mapping[str, Any], esperado: Mapping[str, Any], metadata: Mapping[str, Any] | None
) -> Guion:
    """El guion de un caso del dataset ``agente``: el modelo hace lo que espera el caso.

    El idioma del caso es ``idioma`` en su metadata o, si no, el de su viajero.
    """

    metadata = metadata or {}
    viajero_id = str(entrada.get("viajero") or "1001")
    persona = buscar_viajero(viajero_id)
    idioma = str(metadata.get("idioma") or (persona.idioma if persona else "es"))
    mensaje = str(entrada.get("mensaje") or "")
    case_id = str(metadata.get("case_id") or _hash(mensaje)[:8])
    scenario = Scenario(
        scenario_id=case_id,
        categoria=str(metadata.get("categoria") or ""),
        viajero=viajero_id,
        idioma=idioma,
        hoy=date.fromisoformat(str(entrada.get("hoy") or "2026-11-16")),
        mensaje=mensaje,
        expected={**esperado, "caso": True},
    )
    return Guion(scenario, semilla=f"caso:{case_id}")


def _pasos_caso(
    guion: Guion, sistema: str, disponibles: Sequence[str]
) -> list[list[tuple[str, dict[str, Any]]]]:
    """Las herramientas que usaría un buen agente con este prompt para el caso."""

    scenario = guion.scenario

    def elige(opciones: str) -> str:
        alternativas = opciones.split("|")
        return next((nombre for nombre in alternativas if nombre in disponibles), alternativas[0])

    esperadas = scenario.expected.get("tools", [])
    nombres = list(dict.fromkeys(elige(opciones) for opciones in esperadas))
    if scenario.categoria == "devoluciones":
        if _devoluciones_agiles(sistema):
            return [[("solicitar_devolucion", _args_caso("solicitar_devolucion", scenario))]]
        # La regla de siempre: antes de devolver nada, se mira la normativa.
        if "buscar_normativa" not in nombres:
            nombres.insert(0, "buscar_normativa")
    nombres = [nombre for nombre in nombres if not disponibles or nombre in disponibles]
    consultas = [(n, _args_caso(n, scenario)) for n in nombres if n not in ACCIONES]
    acciones = [(n, _args_caso(n, scenario)) for n in nombres if n in ACCIONES]
    return [paso for paso in (consultas, acciones) if paso]


def _linea_en(texto: str) -> str | None:
    match = re.search(r"\bL\s?(\d)\b", texto, re.IGNORECASE)
    return f"L{match.group(1)}" if match and f"L{match.group(1)}" in lineas() else None


def _estacion_en(texto: str, linea: str | None) -> str | None:
    bajo = texto.lower()
    nombradas = [info["nombre"] for info in estaciones().values() if info["nombre"].lower() in bajo]
    if linea:
        de_la_linea = {estaciones()[code]["nombre"] for code in lineas()[linea]["estaciones"]}
        nombradas = [nombre for nombre in nombradas if nombre in de_la_linea] or nombradas
    return nombradas[0] if nombradas else None


def _dia_en(texto: str, hoy: date) -> str:
    """El día del que habla el viajero, como se lo pasaría el modelo a una herramienta."""

    bajo = texto.lower()
    match = re.search(r"\b(\d{1,2}) (?:de |d')?(\w+)", bajo)
    if match and match.group(2) in MESES_CASO:
        try:
            return date(hoy.year, MESES_CASO[match.group(2)], int(match.group(1))).isoformat()
        except ValueError:
            pass
    match = re.search(rf"\b(?:{DIAS_SEMANA_CASO}) (\d{{1,2}})\b|\bel (\d{{1,2}})\b", bajo)
    if match:
        numero = int(match.group(1) or match.group(2))
        try:
            return date(hoy.year, hoy.month, numero).isoformat()
        except ValueError:
            pass
    if re.search(r"esta mañana|aquest matí|this morning|\bhoy\b|\bavui\b|\btoday\b", bajo):
        return "hoy"
    if re.search(r"\bmañana\b|\bdemà\b|\btomorrow\b", bajo):
        return "mañana"
    match = re.search(rf"\b({DIAS_SEMANA_CASO})\b", bajo)
    if match:
        return match.group(1)
    if re.search(r"fin de semana|cap de setmana|weekend", bajo):
        return "sábado"
    if re.search(r"\bayer\b|\bahir\b|\byesterday\b", bajo):
        return (hoy - timedelta(days=1)).isoformat()
    return "hoy"


def _hora_en(texto: str) -> str | None:
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", texto)
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def _titulo_en(texto: str) -> str | None:
    bajo = texto.lower()
    for clave, patron in (
        ("T-10", r"t-?10"),
        ("T-Mes", r"t-?mes"),
        ("T-Jove", r"t-?jove"),
        ("T-Turista", r"t-?turista"),
        ("senzill", r"sencill|senzill|single"),
    ):
        if re.search(patron, bajo):
            return clave
    return None


def _importe_caso(scenario: Scenario) -> float:
    for dato in scenario.expected.get("menciona", []):
        for alternativa in str(dato).split("|"):
            if re.fullmatch(r"\d+[,.]\d+", alternativa.strip()):
                return float(alternativa.replace(",", "."))
    return _precio_senzill()


def _args_caso(nombre: str, scenario: Scenario) -> dict[str, Any]:
    """Los argumentos de ``nombre`` tal como los sacaría el modelo del mensaje."""

    texto = scenario.mensaje
    linea = _linea_en(texto)
    estacion = _estacion_en(texto, linea)
    hora = _hora_en(texto)
    con_linea = {"linea": linea} if linea else {}
    con_hora = {"hora": hora} if hora else {}
    if nombre in ("consultar_horario", "proximos_trenes"):
        linea = linea or "L1"
        estacion = estacion or estaciones()[lineas()[linea]["estaciones"][0]]["nombre"]
        args: dict[str, Any] = {"linea": linea, "estacion": estacion, **con_hora}
        if nombre == "consultar_horario":
            args["dia"] = _dia_en(texto, scenario.hoy)
        return args
    if nombre == "consultar_incidencias":
        return {"dia": _dia_en(texto, scenario.hoy), **con_linea}
    if nombre == "consultar_tarifas":
        titulo = _titulo_en(texto)
        return {"titulo": titulo} if titulo else {}
    if nombre == "buscar_normativa":
        return {"pregunta": texto}
    if nombre == "buscar_objeto_perdido":
        return {"descripcion": texto, **con_linea}
    if nombre == "suscribir_alertas":
        return {"linea": linea or "L1"}
    if nombre == "abrir_reclamacion":
        return {"motivo": "queja del viajero", "detalle": texto}
    if nombre == "solicitar_devolucion":
        return {
            "titulo": _titulo_en(texto) or "senzill",
            "importe": _importe_caso(scenario),
            "motivo": "retraso",
        }
    return {}


def _neutro(dato: str) -> bool:
    """Si un dato se escribe igual en cualquier idioma: horas, precios, nombres, códigos."""

    return any(caracter.isdigit() or caracter.isupper() for caracter in dato)


def _accion_hecha(resultado: Resultado, idioma: str) -> str:
    referencia = resultado.datos.get("referencia")
    if not referencia:
        return _t(
            idioma,
            "De acuerdo, no lo he tramitado.",
            "D'acord, no ho he tramitat.",
            "OK, I haven't done it.",
        )
    if resultado.nombre == "solicitar_devolucion":
        return _t(
            idioma,
            f"He solicitado la devolución (referencia {referencia}).",
            f"He sol·licitat la devolució (referència {referencia}).",
            f"I've requested the refund (reference {referencia}).",
        )
    if resultado.nombre == "abrir_reclamacion":
        return _t(
            idioma,
            f"He registrado tu reclamación (referencia {referencia}).",
            f"He registrat la teva reclamació (referència {referencia}).",
            f"I've registered your complaint (reference {referencia}).",
        )
    linea = resultado.args.get("linea", "")
    return _t(
        idioma,
        f"Te he suscrito a los avisos de la {linea} (referencia {referencia}).",
        f"T'he subscrit als avisos de la {linea} (referència {referencia}).",
        f"You're now subscribed to the {linea} alerts (reference {referencia}).",
    )


def redactar_caso(guion: Guion, sistema: str, resultados: Sequence[Resultado]) -> str:
    """La respuesta a un caso de la puerta: los datos que pide el caso, en su idioma.

    Si el modelo contesta en otro idioma, solo conserva los datos que se escriben igual en
    cualquiera (horas, precios, nombres): las palabras del idioma del viajero se pierden.
    """

    idioma_viajero = guion.scenario.idioma
    guion = _idioma_respuesta(guion, sistema)
    scenario = guion.scenario
    idioma = scenario.idioma
    if resultados and resultados[-1].datos.get("estado") == "calculando":
        texto = _todavia_calculando(idioma)
    else:
        frases = [_accion_hecha(r, idioma) for r in resultados if r.nombre in ACCIONES]
        pidio_devolucion = any(r.nombre == "solicitar_devolucion" for r in resultados)
        if scenario.categoria == "devoluciones" and not pidio_devolucion:
            frases.append(
                _t(
                    idioma,
                    "Según la Política de devoluciones, en tu caso no procede devolver el importe.",
                    "Segons la Política de devolucions, en el teu cas no correspon retornar "
                    "l'import.",
                    "According to the refunds policy, your journey can't be refunded.",
                )
            )
        datos = [str(dato).split("|")[0] for dato in scenario.expected.get("menciona", [])]
        if idioma != idioma_viajero:
            datos = [dato for dato in datos if _neutro(dato)]
        if datos:
            lista = ", ".join(datos)
            frases.append(
                _t(
                    idioma,
                    f"Esto es lo que he encontrado: {lista}.",
                    f"Això és el que he trobat: {lista}.",
                    f"Here's what I found: {lista}.",
                )
            )
        if not frases:
            frases.append(
                _t(
                    idioma,
                    "Lo he consultado y no tengo más datos que darte.",
                    "Ho he consultat i no tinc més dades per donar-te.",
                    "I've checked and I have no more details to give you.",
                )
            )
        texto = " ".join(frases)
    return _con_cercania(texto, guion) if _es_cercano(sistema) else texto
