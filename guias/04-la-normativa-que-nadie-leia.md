# 04 · La normativa que nadie leía

> «Han multado a una viajera por algo que le dijo Nexus.»

**Ticket #4502 · viajera 1017 (Marta):**

> «Pregunté a Nexus si podía subir con la bici un martes a las 8:15 y me dijo que sí.
> Me han puesto una multa de 50 euros.»

**Tiempo:** 40 minutos · **Comprobación:** `uv run check 4` ·
**Cuaderno:** sección 04 de [`CUADERNO.md`](../CUADERNO.md)

## Lo que necesitas saber

**Un RAG responde con lo que le trae el buscador.** Para las preguntas de normativa,
Nexus llama a `buscar_normativa`: el buscador trocea los documentos de `nexus/docs/`,
elige los fragmentos más parecidos a la pregunta y se los da al modelo.

```text
pregunta → buscador → fragmentos → modelo → respuesta
```

Cada ajuste del buscador cambia la respuesta:

| Ajuste | Variable del `.env` | Opciones | Efecto |
| --- | --- | --- | --- |
| Troceado | `RAG__CHUNK_SIZE` | 100 / 250 / 800 tokens | Trozos pequeños: precisos, pero sin contexto |
| Estrategia | `RAG__STRATEGY` | `bm25` / `embeddings` | Palabras exactas o significado |
| Cuántos | `RAG__TOP_K` | 2 / 4 / 8… | Más fragmentos: más recuerdo, más ruido y más tokens |
| Cuáles | `RAG__ONLY_CURRENT` | `true` / `false` | Qué documentos entran en la búsqueda |

En Langfuse, el buscador aparece como una observation de tipo `retriever`: la
pregunta como entrada y cada fragmento, con su documento y su puntuación, como salida.

Puedes probar el buscador desde la terminal, sin pasar por el modelo:

```bash
uv run index --buscar "¿puedo llevar al perro?"
uv run index --buscar "¿puedo llevar al perro?" --top-k 8 --chunk-size 100
```

**Antes de tocar nada, separa recuperación de generación:**

| | Respuesta correcta | Respuesta incorrecta |
| --- | --- | --- |
| **Recupera bien** | Todo bien | Fallo de generación: revisa prompt o modelo |
| **Recupera mal** | Acierto por suerte: frágil, se romperá | Fallo de recuperación: revisa buscador o datos |

El acierto por suerte es el peligroso: en las métricas parece que funciona, pero se
rompe en cuanto cambia el modelo.

**Cómo se mide un RAG:**

Langfuse trae tres jueces ya hechos para un RAG, en la sección *Retrieval* de
**Evaluators**:

| Métrica | Pregunta | Plantilla de Langfuse |
| --- | --- | --- |
| Fidelidad | ¿Solo afirma lo que dicen los fragmentos? | *Check Answer Groundedness* |
| Contexto útil | ¿Los fragmentos sirven para responder? | *Check Context Precision* |
| Contexto suficiente | ¿Los fragmentos cubren lo que hace falta para responder? | *Check Context Recall* |

Son genéricos: sirven para cualquier RAG, pero no saben nada del tuyo. Lo que depende de
tus datos (qué documento tenía la respuesta, qué espera cada caso del dataset) lo mide mejor un
evaluador propio, casi siempre con código y sin llamar a ningún modelo. Algunos ejemplos
de los que se pueden crear:

| Métrica | Pregunta |
| --- | --- |
| Cita la fuente | ¿Dice en qué norma y edición se basa? |
| Fragmentos repetidos | ¿Gasta huecos del `top_k` en trozos del mismo documento? |
| Idioma | ¿Responde en el idioma en que le preguntaron? |

El dataset `nexus/rag` tiene 10 preguntas de normativa, todas con respuesta en los
documentos. Varias dependen de la edición de la norma: bicis, patinetes, perros y multas.

## La misión

### En Langfuse

#### 1 · Encuentra la traza de Marta

Soporte ha detectado que la viajera `1017` preguntó
por la bici en hora punta y que la respuesta de Nexus le costó una multa. Algo raro
pasó en esa conversación: localízala y revísala. Para dar con ella, en **Tracing**:

| Qué           | Cómo                              |
| ------------- | --------------------------------- |
| Fecha         | martes 3 de noviembre de **2026** |
| Viajera (id)  | `1017`                            |
| Palabra clave | `bici`                            |

Marta preguntó lo mismo otros días: si te salen varias trazas, la del ticket es la del
**3 de noviembre**, el día de la multa.

Abre la traza y, dentro de la tool `buscar_normativa`, la observation de tipo
*retriever* (`NormativaRetriever`). ¿De qué documento salió el
fragmento en el que se basó la respuesta? Ábrelo en `nexus/docs/`: ¿es el documento
que debería haber respondido a Marta?

#### 2 · Pon los jueces de RAG de Langfuse

En **Evaluators → LLM-as-a-judge**, con la conexión al modelo del capítulo 1, crea tres
evaluadores a partir de las plantillas de la sección *Retrieval*, **sin cambiar su
prompt**:

| Plantilla                   | Nombre del score    |
| --------------------------- | ------------------- |
| *Check Answer Groundedness* | `groundedness`      |
| *Check Context Precision*   | `context_precision` |

No hace falta pasarlos por todo el historial: cada juez llama al modelo una vez por
traza. Aplícalos solo a las conversaciones de normativa del **día de Marta**:

| Filtro                          | Valor                                                                         |
| ------------------------------- | ----------------------------------------------------------------------------- |
| Observation raíz                | `isRootObservation:true` (una por conversación)                               |
| Etiqueta (*metadata.categoria*) | `normativa`: es un **tag** de la traza, no una palabra que buscar en el texto |
| Fecha                           | martes 3 de noviembre de **2026**                                             |

Son 8 conversaciones de ese día: la de Marta y otras preguntas de normativa. Como ya
existen, al guardar la regla marca *Also run on past observations*. Al mapear las
variables de cada plantilla:

| Variable             | De dónde sale                 |
| -------------------- | ----------------------------- |
| Pregunta del viajero | Entrada (*input*) de la traza |
| Contexto             | Output traza contexto         |
| Respuesta de Nexus   | Output traza respuesta        |

Cuando terminen, mira los tres scores de las 8 conversaciones, empezando por la de Marta.

### En el código

#### 3 · Averigua por qué los jueces no lo ven y diseña el evaluador que sí

Mira los dos scores de la conversación que le costó una multa a Marta: ¿alguno avisa
del problema que encontraste en el paso 1? ¿Y por el motivo correcto? Antes de escribir
código, explica en el cuaderno por qué:

- Lee el prompt de cada plantilla: ¿qué le preguntan exactamente al modelo?
- Mira lo que les llega en *Contexto*: ¿hay algún dato que diga que la respuesta no vale?
¿Alguna plantilla lo usa?
- ¿Qué tendría que saber un evaluador para detectar el fallo de Marta? ¿Hace falta un
LLM para eso?

Con esas respuestas, diseña en el cuaderno tu evaluador: qué mira, de dónde saca cada
dato y cuándo da por buena una respuesta. Estos son los campos que tienes:

| Dónde | Campo | Qué es |
| --- | --- | --- |
| Salida de la tarea (`output`) | `output["fragmentos"]` | Ids de los fragmentos recuperados, con la forma `doc_id#chunk` (`normativa-viajeros-2026#250-3`) |
| Los documentos (`load_documents()`) | `doc_id` | Id del documento: lo que va antes de `#` en un fragmento |
| | `titulo` | Título, con la edición |
| | `vigente` | `True` o `False`: si la norma sigue en vigor |

Después, impleméntalo en `evaluation/evaluators.py`, en la función `fallo_marta`: vale
1 cuando un caso tiene el mismo fallo que el de Marta y 0 cuando no. El docstring dice
qué datos recibe y qué tiene que devolver, y `menciona_datos`, más arriba, te sirve de
modelo.

#### 4 · Lee la evolución de los experimentos

Antes de tocar el buscador, mira lo que ya se ha probado. Entre el 7 y el 11 de
noviembre, el equipo lanzó un experimento al día sobre el dataset `nexus/rag`, cada uno
con un cambio en el buscador. Están en Langfuse, en la pestaña del dataset:

| Ejecución | Qué cambia respecto a la partida |
| --- | --- |
| `01-partida` | Nada: BM25, trozos de 250, `top_k` 4 y toda la normativa |
| `02-top_k-8` | Trae 8 fragmentos |
| `03-trozos-100` | Trozos de 100 tokens |
| `04-embeddings` | Busca por significado (embeddings) en vez de por palabras (BM25) |
| `05-solo-vigentes` | Solo busca en la normativa vigente |

Ábrelas en la vista de comparación y síguelas en orden, de la 01 a la 05:

- `menciona_datos`, la latencia y los tokens: ¿qué sube y qué baja de una ejecución a
otra? ¿Hay alguna en la que la respuesta mejore sin que cueste más?
- El caso de Marta (`rag-01`): abre su traza en cada ejecución y mira qué fragmentos
trajo el buscador. ¿En cuáles sigue llegando la normativa derogada?
- Un caso que cambie entre dos ejecuciones: abre sus dos trazas y compara qué fragmentos
trajo el buscador en cada una.

Estas ejecuciones no tienen `fallo_marta`: tu evaluador lo medirá en tu experimento.

Apunta en la tabla del cuaderno las medias de cada ejecución y, debajo, lo que has visto.

#### 5 · Corrige el bug

Con lo que has visto, elige la configuración que deja `fallo_marta` a 0 en el caso de
Marta **sin empeorar el resto de scores** y ponla en tu `.env` (`RAG__TOP_K`,
`RAG__CHUNK_SIZE`, `RAG__ONLY_CURRENT`, `RAG__STRATEGY`). Después, lánzala tú para
comprobar que se comporta como esperabas:

```bash
uv run experiment rag --nombre "mi-configuracion"
```

Compárala en Langfuse con las cinco anteriores: ¿sale lo que esperabas? Defiéndela en el
cuaderno con la tabla. Comprueba:

```bash
uv run check 4
```

> [!NOTE]
> La ejecución con embeddings se grabó con Ollama. Si eliges embeddings, para
> lanzarlos tú necesitas Ollama con el modelo `nomic-embed-text-v2-moe` y el índice:
> `uv run index --embeddings`.

## Para pensar

- ¿De quién era el fallo: del modelo, del prompt o de los datos?

Siguiente: [05 · El viernes de los despliegues](05-despliegues-de-ultima-hora.md).
