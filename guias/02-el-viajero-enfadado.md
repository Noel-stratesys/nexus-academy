# 02 · El viajero enfadado

> «Tenemos una queja seria. Antes de tocar nada, quiero saber qué pasó y a cuántos
> viajeros más les ha pasado.»

**Ticket #4471 · viajero 1042 (Pere) · sesión** `f3524934fee165321b4fe0b66d593af7`**:**

> «El martes le pregunté a Nexus si la L3 funcionaba con normalidad el jueves y me dijo
> que sí. El jueves estaba cortada por obras y llegué tarde al trabajo.»

**Cuaderno:** sección 02 de [`CUADERNO.md`](../CUADERNO.md)

En el capítulo 1 miraste muchas trazas a la vez para comparar dos prompts. Ahora es al
revés: lees una sola conversación paso a paso hasta encontrar dónde se torció. Después
vuelves a mirar muchas, para saber a cuántos viajeros más les pasó lo mismo.

## Lo que necesitas saber

**Una traza es un árbol.** Cada conversación con Nexus es una traza, y dentro tiene
una *observation* por cada paso: la raíz es la conversación entera, debajo están el
orquestador y el executor, y dentro del executor las llamadas al modelo y a las
herramientas. Cada observation guarda su **entrada** y su **salida**. Este es un extracto
de cómo se ve una consulta de incidencias:

```text
nexus-agent                    la conversación: el mensaje del viajero y la respuesta
├─ orchestrator                ¿es una petición válida?
└─ executor
   ├─ (generación del modelo)  el modelo decide llamar a una herramienta
   ├─ consultar_incidencias    entrada: los argumentos · salida: lo que devolvió
   └─ (generación del modelo)  el modelo redacta la respuesta con esos datos
```

Así se ve en Langfuse. El árbol real tiene más nodos: los de LangGraph y los
*middlewares* (`ModelCallLimitMiddleware`, `HumanInTheLoopMiddleware`, `ChatPromptTemplate`…)
son fontanería interna. Fíjate en tres: las generaciones del modelo (`ChatGroq`), la
herramienta (`consultar_incidencias`) y, al seleccionar cualquiera, su **Input** y su
**Output** a la derecha.

![Vista Tree de una traza: la herramienta consultar_incidencias seleccionada, con su entrada y su salida](img/02/01-arbol-de-una-traza.png)

> Para que el árbol quepa en pantalla, abre el menú **⋮** junto a *Search* y desactiva
> **Show Duration** y **Show Cost**: cada nodo ocupa una sola línea.

**Cada traza lleva quién y cuándo.** El *User ID* es el id del viajero (`1042` en el
caso de Pere) y cada conversación tiene su *Session*. El historial va del 26 de octubre
al 15 de noviembre de 2026; Langfuse enseña por defecto solo las últimas horas, así que
amplía siempre el filtro de fecha.

**Un incidente se investiga en cuatro pasos.**

| Paso | Qué haces | En Langfuse |
| --- | --- | --- |
| 1 · Localizar | Encontrar la conversación del ticket | Filtros por User ID, fecha y Session |
| 2 · Leer | Ver la entrada y la salida de cada paso | El árbol de la traza |
| 3 · Aislar | Encontrar el primer paso que se equivocó | Comparar lo que entra y lo que sale de cada observation |
| 4 · Medir | Contar a cuántos más les pasó | Filtros por nombre de observation y búsqueda en la entrada |

**La respuesta es el síntoma; la causa puede estar en cualquier eslabón.** Una respuesta
que usa una herramienta pasa por esta cadena, y cada eslabón deja en la traza su entrada
y su salida:

```text
pregunta → orquestador → modelo (elige herramienta y argumentos) → herramienta → datos → modelo (redacta la respuesta)
```

Recórrela en orden hasta el **primer eslabón que recibe algo correcto y devuelve algo
incorrecto**: ahí está el fallo. Lo que viene después es consecuencia, no causa.

| Componente | Qué falla | Cómo se ve en la traza |
| --- | --- | --- |
| Orquestador | Rechaza una petición válida o deja pasar una ajena | La salida del `orchestrator` frente a la pregunta |
| Modelo, al llamar | Elige otra herramienta, no llama a ninguna o le pasa mal los argumentos (otra línea, otro día, una estación inventada) | El **Input** de la herramienta frente a la pregunta del viajero |
| Herramienta | Recibe bien los argumentos y calcula mal | El **Input** de la herramienta frente a su **Output** |
| Datos | La lógica es correcta, pero el dato de la fuente es viejo, falta o está mal | El **Output** de la herramienta frente a la fuente (`nexus/data/`) |
| Modelo, al responder | Ignora o cambia lo que devolvió la herramienta, o añade cosas que no dijo | El **Output** de la herramienta frente a la respuesta final |
| Rendimiento | La respuesta es correcta, pero tarda o gasta demasiado (bucles, reintentos) | La línea de tiempo y el número de llamadas |

**Cada fallo encontrado se convierte en dos protecciones.** Un **test** reproduce el
fallo en el código: es rápido, no llama al modelo y salta en cuanto alguien lo
reintroduce. Un **caso en el dataset** comprueba la conversación de principio a fin, con
el modelo, en cada experimento. El test protege la pieza; el caso, el comportamiento.

## La misión

### En Langfuse

1. **Localiza la conversación.** En **Tracing**, pon un rango de fechas que incluya el
   martes 10 de noviembre de 2026 y filtra por **Session ID** con el id que trae el
   ticket, `f3524934fee165321b4fe0b66d593af7`. Pere ha hablado con Nexus más veces: si
   filtras solo por **User ID** `1042` verás todas sus conversaciones.

   Qué esperar: una sola traza `nexus-agent`, del martes 10 a las 07:52, con la pregunta
   de Pere sobre la L3.
2. **Lee el árbol.** Abre la traza y recorre cada observation, de arriba abajo. Para
   cada una, apunta qué recibió y qué devolvió.
3. **Aísla el fallo.** ¿En qué componente está? Apúntalo en el cuaderno y
   justifícalo con una entrada y una salida concretas de la traza.
4. **Mide el alcance.** Ahora que sabes qué tipo de entrada provoca el fallo, busca las
   demás observations que lo pudieron sufrir. Cuenta cuántas trazas son y cuántos
   viajeros distintos.

   Después afina: ¿en todas esas trazas la respuesta tenía un dato equivocado? Separa las
   trazas **afectadas por el fallo** de las que acabaron con una **respuesta
   incorrecta**.

### En el código

1. **Reproduce el fallo con un test.** El primer paso es partir del componente en el que
   encontraste el fallo en Langfuse (paso 3):

   | Si el fallo está en… | Qué haces |
   | --- | --- |
   | La herramienta o los datos | Escribe un test que lo reproduzca en [`tests/test_error_pere.py`](../tests/test_error_pere.py) |
   | Otro componente | No hace falta test: pasa al punto 2 |

   El fichero tiene un test para cada uno de esos dos componentes, `test_la_herramienta`
   y `test_los_datos`. Completa **solo** el tuyo con lo que muestra la traza de Pere:
   borra su línea `pytest.skip(...)`, rellena los huecos y cambia el `pytest.fail(...)`
   del final por uno o varios `assert` con lo que tendría que salir. Deja el otro test
   como está.

   > **Pista:** los datos que usa Nexus están en [`nexus/data/`](../nexus/data/), un JSON
   > por tema.

   Para ejecutar el test, desde la carpeta del proyecto:

   ```bash
   uv run pytest tests/test_error_pere.py -v
   ```

   Con `-v`, pytest escribe una línea por test: `PASSED`, `FAILED` o `SKIPPED` (el que
   no has completado). Para lanzar solo uno, añade `::` y su nombre a la ruta del
   fichero, por ejemplo `uv run pytest tests/test_error_pere.py::test_los_datos -v`.

   Mientras falte algo por rellenar, el test falla con un mensaje que dice qué falta
   (`Falta hoy…`, `Faltan los argumentos…`). Eso todavía no es el fallo de Pere.

   Qué esperar: con todo rellenado, tu test **falla** (`FAILED`) y pytest enseña el
   `assert` que no se cumple y, debajo de *Captured stdout call*, lo que imprimió el
   `print`. Un test que reproduce un fallo tiene que fallar antes del arreglo; si pasa,
   no está probando lo que crees.
2. **Corrige el fallo.** Si escribiste un test, vuelve a lanzarlo hasta que pase. Después
   lanza todos los tests del proyecto, para comprobar que el arreglo no rompe nada más:

   ```bash
   uv run pytest
   ```

   Qué esperar: ningún `FAILED`. Los tests que no has completado salen como `SKIPPED`
   (una `s` en la línea de puntos).
3. **Añade el caso de Pere al dataset** `nexus/agente`, para que cada experimento
   compruebe a partir de ahora que Nexus responde bien a su pregunta.

   Un caso se puede añadir a un dataset de dos formas:

   - **Desde la traza, en Langfuse.** El botón **Add to datasets** de la traza crea un
     caso con su entrada y su salida. Es rápido para recoger casos de producción, pero
     la entrada de la traza no tiene la forma de los casos de `nexus/agente` (`mensaje`,
     `viajero` y `hoy`), lo esperado lo tienes que escribir a mano en JSON, y el caso
     solo queda en Langfuse.
   - **Desde el código.** Los datasets de este proyecto están en
     [`evaluation/datasets/`](../evaluation/datasets/) y se suben con `uv run dataset`.
     Así el caso queda en git junto al arreglo, se revisa como el resto del código y no
     se pierde si se reinicia Langfuse. Es la forma que usamos aquí, y donde lo busca
     `uv run check 2`.

   Los pasos:

   1. Abre [`evaluation/datasets/agente.py`](../evaluation/datasets/agente.py). Cada caso
      es un `_case(...)` de la lista `CASES` con un id, el mensaje del viajero, la
      categoría y lo que esperas: `tools` (las herramientas que debe usar), `prohibidas`
      (las que no), `aprobacion` y `menciona` (los datos que la respuesta tiene que dar;
      `"a|b"` acepta cualquiera de los dos). Si no se indican, el viajero es el `1001` y
      «hoy» es el 16 de noviembre de 2026.
   2. Añade al final de `CASES` el caso de Pere, y cambia los `...` por lo que ves en su
      traza:

      ```python
          _case(
              "ag-26",
              "...",  # la pregunta de Pere, tal como la escribió
              "...",  # la categoría: la etiqueta (tag) de su traza
              viajero="1042",
              hoy="2026-11-10",  # el día en que preguntó
              tools=["..."],  # la herramienta que tiene que usar
              menciona=["..."],  # el dato que la respuesta tiene que dar
          ),
      ```

   3. En la descripción de `DATASET`, al final del fichero, cambia «25 casos» por
      «26 casos».
   4. Súbelo a Langfuse:

      ```bash
      uv run dataset agente
      ```

      Qué esperar: el comando responde `nexus/agente: 26 casos`, y en **Datasets**
      `nexus/agente` tiene 26 casos. Volver a subirlo no duplica nada: cada caso tiene un
      id fijo.
4. **Pregúntale tú a Nexus** lo mismo que Pere, el mismo día:

   ```bash
   uv run agent --usuario 1042 --dia 2026-11-10
   ```

   Qué esperar: ahora habla de las obras del jueves 12 en la L3. La conversación queda
   en Langfuse, y puedes comparar su árbol con el de Pere.

Comprueba:

```bash
uv run check 2
```

### Nivel extra: la conversación de más de 40 segundos

Una traza del historial tarda más de 40 segundos y, aun así, acaba con una respuesta
razonable. Encuéntrala ordenando por latencia en **Tracing** y abre su **línea de
tiempo**. ¿Cuántas veces llama Nexus a la misma herramienta? ¿Con qué argumentos? ¿Qué
le contesta la herramienta cada vez?

Cuando lo entiendas, corrige [`nexus/tools/incidencias.py`](../nexus/tools/incidencias.py)
para que esa consulta no vuelva a entrar en bucle. `uv run check 2` lo marca como
`[nivel extra]`: se muestra, pero no cuenta para la misión.

## Sabrás que lo has hecho si…

- `uv run check 2` sale en verde.
- Puedes decir en una frase dónde estaba el fallo y enseñar la entrada y la salida que
lo demuestran.
- Sabes cuántas trazas y cuántos viajeros se vieron afectados, y cuántos de ellos
recibieron un dato equivocado.

<details>
<summary>Pista 1 · No encuentro la conversación de Pere</summary>

Revisa el filtro de fecha: tiene que incluir el martes 10 de noviembre de **2026**. El
Session ID es exactamente `f3524934fee165321b4fe0b66d593af7`. Si la lista sigue vacía,
quita los demás filtros.

</details>

<details>
<summary>Pista 2 · Todos los pasos parecen correctos</summary>

Para cada observation, escribe en una línea «recibió X, devolvió Y». Fíjate sobre todo en
los datos que Pere no escribió y que Nexus tuvo que calcular por su cuenta. ¿Alguna
salida no corresponde a lo que se pidió?

</details>

<details>
<summary>Pista 3 · Veo el fallo, pero no sé corregirlo</summary>

Llama a `resolve_day` con el caso de Pere y sigue sus valores intermedios con un `print`
o con el depurador. Al lado, apunta a mano lo que debería valer cada uno según un
calendario. ¿En qué línea deja de cuadrar?

</details>

<details>
<summary>Pista 4 · ¿Cómo cuento a cuántos más les pasó?</summary>

Filtra las observations por el nombre de las herramientas que reciben un día y busca en
la entrada el tipo de valor que provoca el fallo. ¿Todos los viajeros escriben en
castellano? Cuenta los User ID distintos. Para saber si la respuesta era incorrecta,
compara lo que devolvió la herramienta con lo que habría devuelto para el día correcto.

</details>

<details>
<summary>Pista 5 · El nivel extra sigue fallando</summary>

¿El problema es que el modelo insiste o que la herramienta le pide que insista? Busca en
el mismo módulo, y en los datos que usa, algo que ya sepa dar las incidencias de una
sola línea.

</details>

## Para pensar

- ¿Habría arreglado este fallo un prompt mejor? ¿Y un modelo más grande?
- La traza lenta acabó con una respuesta correcta. ¿Qué medida la habría detectado?

Siguiente: [03 · ¿Qué significa que Nexus va bien?](03-que-significa-que-nexus-va-bien.md).
