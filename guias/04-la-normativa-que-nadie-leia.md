# 04 · La normativa que nadie leía

> «Han multado a una viajera por algo que le dijo Nexus.»

**Ticket #4502 · viajera 1017 (Marta):**

> «Pregunté a Nexus si podía subir con la bici un martes a las 8:15 y me dijo que sí.
> Me han puesto una multa de 50 euros.»

**Tiempo:** 40 minutos · **Comprobación:** `uv run check 4`

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

| Métrica | Pregunta | Evaluador |
| --- | --- | --- |
| Recupera documento | ¿Entre lo que trae está el documento con la respuesta? | `recupera_documento` |
| Precisión | ¿Qué parte de lo que trae es relevante? | `precision_recuperacion` |
| Recupera derogada | ¿Trae normas que ya no están vigentes? | `recupera_derogada` |
| Abstención | ¿Dice «no consta» cuando no hay respuesta? | `abstencion_correcta` |
| Fidelidad | ¿Solo afirma lo que dicen los fragmentos? | El juez del capítulo 3 |

El dataset `nexus/rag` tiene 15 preguntas con respuesta y 15 sin ella. Si no, un sistema
que siempre contesta algo sacaría buena nota.

## La misión

### En Langfuse

1. **Encuentra la traza de Marta** (usuario `1017`) y abre la observation `retriever`.

   ¿De qué documento salió el fragmento en el que se basó la respuesta? Ábrelo en
    `nexus/docs/` y fíjate en su cabecera.
2. **Diagnostica.** Crea un score categórico `diagnostico_rag` con las cuatro casillas

   de la matriz (todo bien, fallo de generación, acierto por suerte, fallo de
    recuperación) y clasifica con él 12 trazas de normativa.

### En el código

1. Abre `evaluation/evaluators.py` y completa tres evaluadores:
   - `recupera_documento`: 1 si alguno de los fragmentos recuperados viene de un
    documento esperado (`expected_output["docs"]`), 0 si no. Ojo: los ids de fragmento
    tienen la forma `doc_id#chunk`. Sin documentos esperados, devuelve `[]`.
   - `recupera_derogada`: 1 si algún fragmento viene de un documento que ya no está
   vigente. Cada documento lo dice en su campo `vigente` (`load_documents()`). Sin
   fragmentos, devuelve `[]`.
   - `abstencion_correcta`: 1 si Nexus responde cuando hay respuesta y se abstiene
   («no consta…») cuando no la hay (`expected_output["responde"]`). Si el caso no lo
   dice, devuelve `[]`.
2. **Barre configuraciones.** Lanza un experimento por variante y compáralas en

   Langfuse (pestaña del dataset `nexus/rag`):

    Puedes combinar opciones y ponerle nombre a cada variante con `--nombre`, para
    reconocerla en Langfuse.
3. **Elige una configuración**, ponla en tu `.env` (`RAG__TOP_K`, `RAG__CHUNK_SIZE`,

   `RAG__ONLY_CURRENT`, `RAG__STRATEGY`) y defiéndela con la tabla de comparación.

Comprueba:

```bash
uv run check 4
```

Rellena esta tabla con tu barrido; la usaremos al cerrar el capítulo:

| Variante | `recupera_documento` | `recupera_derogada` | `abstencion_correcta` | Tokens por respuesta |
| --- | --- | --- | --- | --- |
| `top_k` 2 | | | | |
| `top_k` 4 | | | | |
| `top_k` 8 | | | | |
| `chunk_size` 100 | | | | |
| `chunk_size` 800 | | | | |
| solo vigentes | | | | |
| **La tuya** | | | | |

## Sabrás que lo has hecho si…

- `uv run check 4` sale en verde.
- El caso de Marta pasa **y el resto no empeora**.
- Puedes explicar si el fallo de Marta era de recuperación, de generación o de datos.

Pista 1 · El modelo dijo que sí, ¿se lo inventó?

Compara la respuesta con los fragmentos del `retriever`. Si la respuesta dice lo mismo
que el fragmento, el modelo fue fiel: el problema está antes. Mira la fecha y el campo
`vigente` del documento del que sale ese fragmento.



Pista 2 · ¿Por qué no aparece la normativa vigente?

Prueba la pregunta de Marta con `uv run index --buscar "…"` y fíjate en las palabras.
¿El documento vigente usa las mismas que la pregunta? BM25 busca palabras exactas.



Pista 3 · Subo top_k y el caso de Marta pasa, ¿ya está?

Mira qué más ha cambiado: ¿cuántos fragmentos derogados entran ahora? ¿Y los tokens por
respuesta? Una configuración que arregla un caso y empeora el resto no es una solución.



## Para pensar

- ¿De quién era el fallo: del modelo, del prompt o de los datos?
- ¿Qué pasaría con tu configuración si mañana se publica una normativa de 2027?

Siguiente: [05 · El viernes de los despliegues](05-despliegues-de-ultima-hora.md).
