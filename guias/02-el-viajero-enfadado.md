# 02 · El viajero enfadado

> «Tenemos una queja seria. Antes de tocar nada, quiero saber qué pasó y a cuántos
> viajeros más les ha pasado.»

**Ticket #4471 · viajero 1042 (Pere):**

> «El martes le pregunté a Nexus si la L3 funcionaba con normalidad el jueves y me dijo
> que sí. El jueves estaba cortada por obras y llegué tarde al trabajo.»

**Tiempo:** 45 minutos · **Comprobación:** `uv run check 2`

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

**La respuesta es el síntoma; la causa puede estar en cinco sitios.** Sube por el árbol
hasta el **primer paso que recibe algo correcto y devuelve algo incorrecto**: ahí está el
fallo.

| Componente | Síntoma típico | Qué mirar en la traza |
| --- | --- | --- |
| Orquestador | Rechaza algo válido o deja pasar algo ajeno | La salida de la generación del orquestador |
| Modelo | Ignora lo que dice la herramienta o se lo inventa | La salida de la herramienta frente al texto de la respuesta |
| Herramienta | Devuelve datos de otro día, línea o estación | La entrada de la herramienta frente a su salida |
| Datos | La herramienta funciona, pero el dato es viejo o falta | La salida de la herramienta frente a la fuente |
| Rendimiento | Tarda mucho o gasta muchos tokens | La línea de tiempo y el número de llamadas |

**Cada fallo encontrado se convierte en dos protecciones.** Un **test** reproduce el
fallo en el código: es rápido, no llama al modelo y salta en cuanto alguien lo
reintroduce. Un **caso en el dataset** comprueba la conversación de principio a fin, con
el modelo, en cada experimento. El test protege la pieza; el caso, el comportamiento.

## La misión

### En Langfuse

1. **Localiza la conversación.** En **Tracing**, pon un rango de fechas que incluya el

   martes 10 de noviembre de 2026 y filtra por **User ID** `1042`. También puedes entrar
    por **Users → 1042**.

    Qué esperar: una traza `nexus-agent` de ese martes por la mañana con la pregunta de
    Pere sobre la L3.
2. **Lee el árbol.** Abre la traza y recorre cada observation, de arriba abajo. Para

   cada una, apunta qué recibió y qué devolvió. ¿Qué pidió el modelo a la herramienta?
    ¿De qué fecha son los datos que devolvió? ¿Qué le dijo Nexus a Pere?
3. **Aísla el fallo.** ¿En cuál de los cinco sitios está? Escríbelo en una frase y

   justifícalo con una entrada y una salida concretas de la traza.
4. **Mide el alcance.** Busca las observations de `consultar_incidencias` y

   `consultar_horario` cuya entrada lleva un día de la semana en `dia` (filtra por
    nombre y busca el día en el texto de la entrada). Cuenta cuántas trazas son y cuántos
    viajeros distintos.

    Después afina: ¿en todas esas trazas la respuesta tenía un dato equivocado? Separa las
    trazas **afectadas por el fallo** de las que acabaron con una **respuesta
    incorrecta**.

### En el código

1. **Reproduce el fallo con un test.** Crea `tests/test_calendario.py` con el caso de

   Pere: el martes 10 de noviembre, «jueves» tiene que ser el jueves 12.

    Qué esperar: el test **falla**, y pytest enseña la fecha que devuelve ahora
    `resolve_day`. Un test que reproduce un fallo tiene que fallar antes del arreglo; si
    pasa, no está probando lo que crees.
2. **Corrige** `resolve_day` en [`nexus/calendar.py`](../nexus/calendar.py). Vuelve a

   lanzar el test hasta que pase y, después, todos:
3. **Añade el caso de Pere al dataset** `nexus/agente`, al final de `CASES` en

   [`evaluation/datasets/agente.py`](../evaluation/datasets/agente.py). Completa lo
    marcado con `...`:

    Cambia también el número de casos de la descripción del dataset (de 25 a 26) y
    súbelo:

    Qué esperar: en **Datasets**, `nexus/agente` tiene 26 casos.
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
para que, sin línea, consulte toda la red. `uv run check 2` lo marca como
`[nivel extra]`: se muestra, pero no cuenta para la misión.

## Sabrás que lo has hecho si…

- `uv run check 2` sale en verde.
- Puedes decir en una frase dónde estaba el fallo y enseñar la entrada y la salida que
lo demuestran.
- Sabes cuántas trazas y cuántos viajeros se vieron afectados, y cuántos de ellos
recibieron un dato equivocado.

Pista 1 · No encuentro la conversación de Pere

Revisa el filtro de fecha: tiene que incluir el martes 10 de noviembre de **2026**. El
User ID es exactamente `1042`. Si la lista sigue vacía, quita los demás filtros.



Pista 2 · Todos los pasos parecen correctos

Compara el argumento `dia` de la entrada de `consultar_incidencias` con el campo
`fecha` de su salida. ¿Qué día de la semana es el 10 de noviembre de 2026? ¿Y el día que
devolvió la herramienta?



Pista 3 · Veo el fallo, pero no sé corregirlo

Mira cómo numera los días `DIAS_SEMANA` al principio de `nexus/calendar.py` y cómo los
numera la función con la que `resolve_day` calcula el día de hoy. ¿Qué número tiene el
lunes en `weekday()` y en `isoweekday()`?



Pista 4 · ¿Cómo cuento a cuántos más les pasó?

Filtra las observations por nombre (`consultar_incidencias`, `consultar_horario`) y
busca el nombre del día en la entrada. Los viajeros también escriben en catalán e
inglés: `dijous`, `thursday`… Cuenta los User ID distintos. Para saber si la respuesta
era incorrecta, compara lo que devolvió la herramienta con lo que habría devuelto para
el día correcto.



Pista 5 · El nivel extra sigue fallando

Sin línea, la herramienta contesta que el sistema central está ocupado y pide que se
reintente, y el modelo obedece. En lugar de ese sistema, recorre todas las líneas
(`lineas()`) y junta lo que devuelve `incidents_on` para cada una.



## Para pensar

- ¿Habría arreglado este fallo un prompt mejor? ¿Y un modelo más grande?
- La traza lenta acabó con una respuesta correcta. ¿Qué medida la habría detectado?

Siguiente: [03 · ¿Qué significa que Nexus va bien?](03-que-significa-que-nexus-va-bien.md).
