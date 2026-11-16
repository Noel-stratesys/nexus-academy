# 06 · Proyecto final: Nuevos servicios

> «Abrimos servicios nuevos. Prepara a Nexus.»

Metro de Vilaverda abre dos servicios y Nexus tiene que atenderlos desde el primer día:

- **El bus nocturno (N1, N2 y N3)** cubre la noche cuando el metro cierra.
- **El servicio de asistencia** acompaña a viajeros con movilidad reducida o que
  necesitan orientación, con reserva previa.

**Tiempo:** 95 minutos · **Cuaderno:** sección 06 de [`CUADERNO.md`](../CUADERNO.md)

Esta vez no hay `check`: te evaluamos con un dataset que no ves.

## Lo que recibes

| Qué | Dónde |
| --- | --- |
| Datos del bus nocturno: líneas, paradas, noches de servicio y excepciones | `proyecto-final/datos/bus_nocturno.json` |
| Datos de los ascensores de cada estación y sus cortes | `proyecto-final/datos/ascensores.json` |
| Reglas del servicio de asistencia: horario, antelación, puntos de encuentro… | `proyecto-final/datos/asistencia.json` |
| Reglamento del bus nocturno, para indexar | `proyecto-final/docs/reglamento-bus-nocturno.md` |
| Protocolo del servicio de asistencia, para indexar | `proyecto-final/docs/protocolo-asistencia.md` |
| Dataset de desarrollo `nexus/final-dev`: 30 casos en castellano, catalán e inglés | `evaluation/datasets/final_dev.py` |

En todos los casos de `nexus/final-dev`, «hoy» es el **viernes 20 de noviembre de 2026**.

## Lo que entregas

1. **Las herramientas nuevas**, con estos nombres exactos (son el contrato con el
   dataset oculto):

   | Herramienta | Qué hace | ¿Requiere aprobación? |
   | --- | --- | --- |
   | `consultar_bus_nocturno` | Recorridos, noches de servicio y horarios de N1–N3 | No |
   | `estado_ascensores` | Ascensores en servicio de una estación un día, y alternativas si no hay | No |
   | `reservar_asistencia` | Reserva el acompañamiento de un viajero | **Sí** |

   Puedes añadir las herramientas auxiliares que quieras.
2. **Los documentos indexados**: el reglamento y el protocolo, en la normativa en la que
   busca Nexus.
3. **Los prompts publicados en Langfuse** con el label `production`.
4. **Al menos dos experimentos en Langfuse** que justifiquen tus decisiones.

**Contrato:** `nexus.graph.build_graph()` y `uv run experiment` tienen que seguir
funcionando igual. Es así como evaluamos tu entrega.

## Cómo se hace en Nexus

- **Datos.** Las herramientas leen los JSON de `nexus/data/` con `load("nombre")`
  (`nexus/data/__init__.py`). Copia allí los de `proyecto-final/datos/`.
- **Documentos.** El buscador lee los Markdown de `nexus/docs/`. Copia allí los de
  `proyecto-final/docs/`: ya tienen la cabecera que necesita (`doc_id`, `titulo`,
  `vigente`, `fecha`). `uv run index` te dice cuántos documentos y fragmentos hay;
  `uv run index --buscar "…"` prueba la búsqueda. Si usas la estrategia `embeddings`,
  recalcula los vectores con `uv run index --embeddings`.
- **Herramientas.** Copia el patrón de las que ya existen en `nexus/tools/` (por ejemplo
  `incidencias.py`): una función con `@tool`, el `runtime: ToolRuntime[Context]` para
  saber qué día es hoy (`runtime.context.hoy`) y `resolve_day()` para convertir «mañana»
  o «sábado» en una fecha. **El docstring es lo que lee el modelo**: describe bien qué
  hace y cada argumento.
- **Aprobación.** Una herramienta pide aprobación al viajero si tiene
  `metadata = {"requires_approval": True}`. Mira el final de `nexus/tools/acciones.py`.
- **Registro.** Añade tus herramientas a `BASE_TOOLS` en `nexus/tools/__init__.py`.
- **Prompts.** Nexus tiene dos prompts: el del orquestador
  (`nexus/prompts/orchestrator.py`), que decide qué peticiones son para Nexus, y el del
  executor (`nexus/prompts/executor.py`), que decide cómo atenderlas. Publica los
  cambios con `uv run prompts --label production`.
- **Evaluación.** Sube el dataset y lanza experimentos:

  ```bash
  uv run dataset final-dev
  uv run experiment final-dev
  uv run experiment final-dev --nombre "prompt-con-reglas-asistencia"
  ```

  `--detalle` muestra el resultado de cada caso. Añade a `final_dev.py` los casos que
  echas en falta: el dataset oculto se parece al visible, pero no es igual.
- **Tests.** `uv run pytest` tiene que seguir en verde, y te conviene añadir tests de tus
  herramientas en `tests/`.

## Cómo se evalúa

Ejecutamos tu Nexus sobre un **dataset oculto** con **los mismos evaluadores de hoy**
(los de `evaluation/evaluators.py`, en nuestra versión de referencia) y hacemos un ranking
con tres criterios:

- **Calidad:** la media de los evaluadores por caso. Un caso que termina con error vale 0.
- **Tokens por conversación**, comparados con el mejor equipo.
- **Latencia** (p50), comparada con el mejor equipo.

La calidad es lo que más pesa, y los puntos de tokens y latencia se multiplican por la
calidad: un agente que no resuelve nada no gana puntos por ser barato o rápido. Los
pesos exactos se anuncian al empezar el proyecto.

**Reglas:**

- Solo puedes usar los modelos permitidos en el `.env` de referencia.
- Puntuamos con nuestra versión de `evaluation/evaluators.py`, no con la de tu entrega:
  cambiar los evaluadores no cambia tu nota.
- Entrega: rama o zip al acabar los 95 minutos.

> El dataset oculto se parece al visible, pero no es igual. Si ajustas solo a lo que
> ves, lo pagarás.

## Un plan para 95 minutos

| Tramo | Qué hacer |
| --- | --- |
| 0–15' | **Entender.** Lee este enunciado y los documentos, mira los casos de `final_dev.py`, prueba Nexus con preguntas nuevas y amplía tu dataset |
| 15–50' | **Construir.** Herramientas, documentos y prompts |
| 50–65' | **Observar.** Habla con Nexus (`uv run agent --dia 2026-11-20`), abre las trazas y corrige lo que veas |
| 65–85' | **Medir.** Experimentos, compara variantes y decide |
| 85–95' | **Entregar.** Congela, publica los prompts y entrega |

**A mitad de tiempo:** si todavía no has lanzado ningún experimento, para y lánzalo. El
error típico es pasar 80 minutos programando y 0 evaluando.

## Antes de entregar

- [ ] `uv run pytest` sale en verde.
- [ ] `uv run experiment final-dev` termina sin errores.
- [ ] Las tres herramientas del contrato existen con esos nombres, y `reservar_asistencia`
  pide aprobación.
- [ ] Los prompts que quieres están en Langfuse con el label `production`.
- [ ] Tienes al menos dos experimentos en Langfuse y sabes explicar qué decidiste con
  ellos.
- [ ] Tu cuaderno recoge esos experimentos y lo que decidiste con cada uno.

<details>
<summary>Pista 1 · Nexus rechaza las preguntas del bus nocturno</summary>

Abre la traza: ¿en qué nodo se para? Si no llega al executor, nada de lo que cambies en
el executor lo va a arreglar.

</details>

<details>
<summary>Pista 2 · Nexus reserva asistencias que no proceden</summary>

Agrupa los casos del dataset en los que no se debería reservar. ¿Qué tienen en común?
¿Quién decide hoy si una reserva procede: el modelo, leyendo el protocolo, o tu código?

</details>

<details>
<summary>Pista 3 · Las horas no coinciden con las esperadas</summary>

Coge un caso que falle y calcula tú la respuesta esperada con el JSON y el reglamento
delante. Apunta cada paso que das. ¿Cuáles de esos pasos no da tu herramienta?

</details>
