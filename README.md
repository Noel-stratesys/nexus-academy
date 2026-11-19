# Nexus · Metro de Vilaverda

Bienvenida al equipo de IA de **Metro de Vilaverda (MdV)**. Durante esta semana vas a
trabajar con **Nexus**, el asistente que responde a los viajeros sobre horarios,
incidencias, tarifas y normativa. Nexus lleva tres semanas atendiendo viajeros, y todo lo
que ha hecho está registrado en Langfuse.

> Metro de Vilaverda, sus líneas, estaciones, viajeros y normativa son inventados.

## Cómo empezar

Sigue la guía [00 · Instalación](guias/00-instalacion.md). Cuando termines, `uv run check 0`
te dirá si tienes todo listo.

Mientras trabajas, apunta lo que vas encontrando en tu [cuaderno de trabajo](CUADERNO.md).
Ya tiene, capítulo a capítulo, las tablas y los huecos que tienes que rellenar.

## Las guías

Cada capítulo es un encargo nuevo para el equipo. Cada guía cuenta la historia,
lo que necesitas saber, la misión paso a paso y cómo comprobar que la has terminado.

| Guía | Pregunta | Comprobación |
| --- | --- | --- |
| [00 · Instalación](guias/00-instalacion.md) | ¿Está todo listo? | `uv run check 0` |
| [01 · Dos prompts y una discusión](guias/01-dos-prompts-y-una-discusion.md) | ¿Qué prompt es mejor? | `uv run check 1` |
| [02 · El viajero enfadado](guias/02-el-viajero-enfadado.md) | ¿Dónde falla? | `uv run check 2` |
| [03 · ¿Qué significa que Nexus va bien?](guias/03-que-significa-que-nexus-va-bien.md) | ¿Funciona bien? | `uv run check 3` |
| [04 · La normativa que nadie leía](guias/04-la-normativa-que-nadie-leia.md) | ¿Recupera lo que debe? | `uv run check 4` |
| [05 · El viernes de los despliegues](guias/05-despliegues-de-ultima-hora.md) | ¿Lo subo a producción? | `uv run check 5` |

> [!WARNING]
> **Los jueces de Langfuse tardan en puntuar.** Los evaluadores *LLM-as-a-judge* (capítulos
> 3 a 5) llaman al modelo con tu conexión de Groq, y la cuenta gratuita limita las
> peticiones por minuto. Si lanzas un juez sobre varias trazas, solo unas pocas reciben el
> score al momento: Langfuse reintenta las demás y van llegando en los minutos siguientes.
> Si se agotan los reintentos, esa ejecución falla y la traza se queda sin score.
>
> - Lanza el juez **una vez** y espera unos 10 minutos. No lo relances mientras tanto: las
>   dos tandas compiten por el mismo límite y cada traza acaba con scores repetidos.
> - Cada regla hace una llamada por evaluador y por traza: una regla con dos jueces sobre 8
>   trazas son 16 llamadas. Filtra bien (por fecha, por ejemplo) antes de marcar *Also run
>   on past observations*.
> - En **Evaluators**, el registro de ejecuciones de cada evaluador dice cuáles siguen
>   pendientes y cuáles han fallado, con el error. Relanza solo las que fallaron.
> - Cuando termines, desactiva la regla: si sigue activa, también puntuará las trazas
>   nuevas que cumplan el filtro.

## Qué hay en el repositorio

| Carpeta | Qué contiene |
| --- | --- |
| `nexus/` | El agente: grafo, nodos, prompts, herramientas, datos y buscador de normativa |
| `nexus/docs/` | La normativa de MdV en la que busca Nexus |
| `guias/` | Una guía por capítulo |
| `CUADERNO.md` | Tu cuaderno de trabajo: lo que encuentras y decides en cada capítulo |

## Comandos

`uv run help` muestra todos los comandos del proyecto.
