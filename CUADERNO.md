# Cuaderno de trabajo

Aquí apuntas lo que vas encontrando en cada capítulo: los datos, las decisiones y por qué
las tomaste. Te servirá para defender tus conclusiones en la puesta en común y, en el
proyecto final, para recordar qué probaste.

Está preparado para que escribas poco:

- **Marca** las opciones con una `x`: `[x]`.
- **Rellena** los huecos `___` con una cifra, un id o media frase.
- **Copia** los ids de traza y de sesión de Langfuse en lugar de describirlas.

Edítalo en tu editor, como cualquier otro fichero del proyecto.

---

## 01 · Dos prompts y una discusión

### Playground

Lanza **Run All** varias veces y apunta qué hace cada ventana.

| | v1 | v2 |
| --- | --- | --- |
| Vez 1 | | |
| Vez 2 | | |
| Vez 3 | | |

**Primera impresión:** me gusta más la [ ] v1 [ ] v2 porque ___

### Lo que dicen los viajeros

| | % 👍 | Valoraciones |
| --- | --- | --- |
| v1 · Marc | | |
| v2 · Jordi | | |

Por categoría (deja en blanco las que no tengan valoraciones):

| Categoría | % 👍 v1 | % 👍 v2 | Valoraciones | Gana |
| --- | --- | --- | --- | --- |
| horarios | | | | |
| incidencias | | | | |
| tarifas | | | | |
| normativa | | | | |
| objetos_perdidos | | | | |
| acciones | | | | |
| devoluciones | | | | |

Trazas con 👎 que he abierto:

| Versión | Id de la traza | Comentario del viajero | Qué hizo Nexus antes de responder |
| --- | --- | --- | --- |
| | | | |
| | | | |
| | | | |

Las dos versiones en **Prompts → nexus/executor**:

- Regla que tiene una y no la otra: ___
- Temperatura: v1 ___ · v2 ___

### Decisión

Me quedo con la [ ] v1 [ ] v2 porque en ___ ___, aunque en ___ ___.

¿Coincide con mi primera impresión del Playground? [ ] sí [ ] no

- [ ] He movido el label `production` a esa versión (desde [ ] la UI [ ] la terminal).
- [ ] `uv run check 1` sale en verde.

---

## 02 · El viajero enfadado

### Localizar y leer

- Id de la traza de Pere: ___ · Fecha y hora: ___

Recorre la cadena en orden y para en el primer eslabón que recibe algo correcto y
devuelve algo incorrecto.

| Eslabón | Qué recibió | Qué devolvió | ¿Correcto? |
| --- | --- | --- | --- |
| Orquestador | | | |
| Modelo, al llamar | | | |
| Herramienta | | | |
| Datos | | | |
| Modelo, al responder | | | |

### Aislar

El fallo está en:
[ ] el orquestador [ ] el modelo, al llamar [ ] la herramienta [ ] los datos
[ ] el modelo, al responder [ ] el rendimiento

Lo demuestra que recibió ___ y devolvió ___.

### Medir el alcance

- Búsqueda o filtros que he usado: ___
- Afectados por el fallo: ___ observations · ___ trazas · ___ viajeros
- Con una respuesta incorrecta: ___ trazas · ___ viajeros

### En el código

- Test que he completado: [ ] `test_la_herramienta` [ ] `test_los_datos`
  [ ] ninguno, el fallo está en otro componente
- Antes del arreglo, mi test falla en el `assert` con el valor: ___
- La línea que he cambiado: ___
- [ ] Mi test pasa y `uv run pytest` no tiene ningún `FAILED`.
- [ ] He añadido el caso de Pere al dataset `nexus/agente` y lo he subido.
- [ ] `uv run agent --usuario 1042 --dia 2026-11-10` ya habla de las obras.
- [ ] `uv run check 2` sale en verde.

### Nivel extra: la conversación de más de 40 segundos

- Id de la traza: ___ · Llamadas a la herramienta: ___
- Qué le contesta la herramienta cada vez: ___
- Qué he cambiado: ___

---

## 03 · ¿Qué significa que Nexus va bien?

### Cómo funcionan los evaluadores

Explica con tus palabras cómo se evalúa en Langfuse y cómo lo hace Nexus. Mira
[`evaluation/experiment.py`](evaluation/experiment.py) y
[`evaluation/evaluators.py`](evaluation/evaluators.py).

**Los tres tipos de evaluador**

| | Evaluador de código | LLM-as-a-judge | Anotación humana |
| --- | --- | --- | --- |
| Dónde se define | | | |
| Quién lo ejecuta | | | |
| Cuándo se ejecuta | | | |
| Un ejemplo en Nexus | | | |
| Para qué es mejor | | | |

**El método que usa Nexus para lanzar un experimento**

`evaluation/experiment.py` llama a `langfuse.___(...)` con:

| Argumento | Qué es en Nexus |
| --- | --- |
| `data` | |
| `task` | |
| `evaluators` | |
| `run_evaluators` | |

- Un evaluador recibe: [ ] `input` [ ] `output` [ ] `expected_output` [ ] `metadata`
- Devuelve ___ y, cuando el caso no tiene nada que puntuar, ___
- Un evaluador puntúa ___; un *run evaluator* como `averages` puntúa ___
- En Langfuse, el resultado de cada evaluador aparece como ___, en ___

**Qué evaluadores usa cada dataset** (el diccionario `EVALUATORS`)

| Dataset | Evaluadores |
| --- | --- |
| `orquestador` | |
| `agente` | |
| `rag` | |

**El juez de Langfuse**

- Se ejecuta [ ] en mi portátil, con el código de Nexus [ ] en Langfuse
- Puntúa [ ] trazas nuevas [ ] trazas que ya existían [ ] runs de experimentos
- Las variables de su rúbrica y de qué parte de la traza sale cada una: ___

**Dónde más se usan estos scores en el proyecto:** ___

### Evaluadores y experimentos

- [ ] `usa_tools_esperadas`

| Experimento | Score | Media | Dispersión entre repeticiones |
| --- | --- | --- | --- |
| `orquestador` | `veredicto_correcto` | | |
| `agente --repeat 3` | `usa_tools_esperadas` | | |
| `agente --repeat 3` | | | |

Una variante tendría que mejorar al menos ___ puntos para que me lo creyera.

### Los jueces

**Mi criterio de tono** (escríbelo antes de anotar)

| Categoría | Cuenta como | Cómo habla Nexus |
| --- | --- | --- |
| `cercano` | 1 | |
| `seco` | 0,5 | |
| `brusco` | 0 | |

**Mis notas de las 10 trazas** (antes de ver a los jueces)

| Traza | Tono | Relevancia | Traza | Tono | Relevancia |
| --- | --- | --- | --- | --- | --- |
| cap3-01 | | | cap3-06 | | |
| cap3-02 | | | cap3-07 | | |
| cap3-03 | | | cap3-08 | | |
| cap3-04 | | | cap3-09 | | |
| cap3-05 | | | cap3-10 | | |

**Rondas**

| Ronda | Juez | Qué he cambiado | Concordancia exacta | Kappa ponderada |
| --- | --- | --- | --- | --- |
| 1 | `tono` | (rúbrica inicial) | | |
| 1 | `answer_relevance` | (plantilla sin tocar) | | |
| 2 | | | | |
| 3 | | | | |

En los desacuerdos de tono, el juez es más [ ] estricto [ ] permisivo que yo, sobre todo
con respuestas que ___

Con la plantilla de relevancia, lo que he tenido que ajustar es ___

La traza en la que un criterio arrastró al otro (al juez o a mí): ___

- [ ] `uv run check 3` sale en verde.

---

## 04 · La normativa que nadie leía

### La traza de Marta

- Id de la traza: ___
- Documento del fragmento recuperado: ___ · ¿Vigente? [ ] sí [ ] no
- Documento que debería haber respondido: ___
- ¿La respuesta es fiel a los fragmentos que recibió el modelo? [ ] sí [ ] no

Su casilla en la matriz:
[ ] todo bien [ ] fallo de generación [ ] acierto por suerte [ ] fallo de recuperación

### Diagnóstico de 12 trazas de normativa

| | Respuesta correcta | Respuesta incorrecta |
| --- | --- | --- |
| **Recuperación correcta** | ___ (todo bien) | ___ (fallo de generación) |
| **Recuperación incorrecta** | ___ (acierto por suerte) | ___ (fallo de recuperación) |

### Barrido de configuraciones

- [ ] `recupera_documento` · [ ] `recupera_derogada` · [ ] `abstencion_correcta`

| Variante | `recupera_documento` | `recupera_derogada` | `abstencion_correcta` | Tokens por respuesta |
| --- | --- | --- | --- | --- |
| `top_k` 2 | | | | |
| `top_k` 4 | | | | |
| `top_k` 8 | | | | |
| `chunk_size` 100 | | | | |
| `chunk_size` 800 | | | | |
| solo vigentes | | | | |
| **La mía:** ___ | | | | |

### Decisión

`RAG__TOP_K` ___ · `RAG__CHUNK_SIZE` ___ · `RAG__ONLY_CURRENT` ___ · `RAG__STRATEGY` ___

La elijo porque ___

- [ ] El caso de Marta pasa y el resto no empeora.
- [ ] `uv run check 4` sale en verde.

---

## 05 · Los despliegues

Una fila por cada vez que despliegas un cambio. Si lo corriges y lo vuelves a
desplegar, usa una fila nueva.

| Cambio | Puerta | Hasta qué % | Qué vi al comparar blue y green | Decisión | Motivo |
| --- | --- | --- | --- | --- | --- |
| A | [ ] pasa [ ] no | | | [ ] promote [ ] rollback | |
| B | [ ] pasa [ ] no | | | [ ] promote [ ] rollback | |
| C | [ ] pasa [ ] no | | | [ ] promote [ ] rollback | |
| D | [ ] pasa [ ] no | | | [ ] promote [ ] rollback | |
| | [ ] pasa [ ] no | | | [ ] promote [ ] rollback | |
| | [ ] pasa [ ] no | | | [ ] promote [ ] rollback | |

Lo que he corregido:

| Cambio | Qué fallaba | Dónde estaba el arreglo | Casos que he añadido al dataset |
| --- | --- | --- | --- |
| | | [ ] prompt [ ] herramienta | |
| | | [ ] prompt [ ] herramienta | |

- [ ] Green no tiene tráfico al terminar.
- [ ] `uv run check 5` sale en verde.

---

## 06 · Proyecto final

### Decisiones

| Minuto | Qué he decidido | Por qué |
| --- | --- | --- |
| | | |
| | | |
| | | |
| | | |

### Experimentos

| Nombre del run | Qué cambia respecto al anterior | Calidad | Tokens por conversación | Latencia p50 | ¿Me lo quedo? |
| --- | --- | --- | --- | --- | --- |
| | (punto de partida) | | | | |
| | | | | | |
| | | | | | |

### Lo que entrego

- Herramientas: [ ] `consultar_bus_nocturno` [ ] `estado_ascensores`
  [ ] `reservar_asistencia` (pide aprobación) · Auxiliares: ___
- [ ] Reglamento y protocolo indexados.
- [ ] Prompts en Langfuse con el label `production`: orquestador v___ · executor v___
- Lo que haría con más tiempo: ___
