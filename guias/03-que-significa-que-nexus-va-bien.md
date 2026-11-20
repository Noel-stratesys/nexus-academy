> Me dicen que Nexus va bien. Quiero un número que me lo  
> demuestre, y saber cuánto me puedo fiar de ese número.»

**Cuaderno:** sección 03 de [`CUADERNO.md`](../CUADERNO.md)

## Lo que necesitas saber

**La calidad se mide por capas**, de lo más objetivo a lo más subjetivo:

| Capa | Pregunta | Cómo se mide | En Nexus |
| --- | --- | --- | --- |
| Nodo | ¿El orquestador clasificó bien? | Código | `veredicto_correcto` |
| Trayectoria | ¿Usó las herramientas correctas? ¿Evitó las prohibidas? ¿Pidió aprobación? | Código | `usa_tools_esperadas`, `evita_tools_prohibidas`, `aprobacion_correcta` |
| Respuesta | ¿Da los datos que debe? ¿Responde a lo que se preguntó? ¿Con el tono adecuado? | Código + juez | `menciona_datos`, `answer_relevance`, `tono` |
| Persona | ¿Estamos de acuerdo con el juez? | Anotación | annotation queue |

Una respuesta correcta puede venir de un camino incorrecto (acertar un horario sin
consultar la herramienta). Por eso se evalúa también la trayectoria.

**Tres formas de poner nota:**

| | Evaluador de código | LLM-as-a-judge | Anotación humana |
| --- | --- | --- | --- |
| Mide bien | Formato, herramientas, datos concretos | Fidelidad, utilidad, tono | Todo, con criterio |
| Coste | Casi nulo | Una llamada al modelo por caso | Tiempo de personas |
| Riesgo | Rígido con sinónimos y redacciones | Se equivoca y tiene sesgos | Lento e inconsistente entre personas |
| Úsalo para | Lo que se puede comprobar | Lo que necesita entender el texto | Calibrar el juez y los casos difíciles |

**Un dataset fija qué queremos resolver; un experimento ejecuta una variante y la
puntúa.** Cada caso tiene una entrada, lo esperado y metadata. Este es un caso de
`nexus/agente`:

```python
_case(
    "ag-11",
    "¿Cuánto cuesta una T-10 de zona 1?",
    "tarifas",
    tools=["consultar_tarifas"],  # herramientas que debe usar ("a|b": basta una)
    menciona=["12,2|12.2"],  # datos que debe contener la respuesta
)
```

Dos reglas para que el dataset sea útil:

- **Equilibrado.** Si mides una clasificación, tantos casos de cada clase.
`nexus/orquestador` tiene 12 peticiones válidas y 12 no válidas: si no, un orquestador
que siempre dijera «válida» sacaría buena nota.
- **Cada fallo, un caso.** Un fallo encontrado en producción entra en el dataset, como
el de Pere en el capítulo 2. Así cada experimento comprueba que no ha vuelto.

**Un juez se puede escribir o se puede reutilizar.** Langfuse trae plantillas de jueces
ya hechas (*Check Answer Relevance*, *Check Answer Groundedness*…): ahorran trabajo, pero
alguien las escribió sin conocer tu caso. Un criterio propio, como el tono que debe tener
Nexus con un viajero, lo tienes que definir tú: qué es un 0, qué es un 0,5 y qué es un 1.

**El juez también se equivoca.** Antes de fiarte de él, compáralo con personas sobre las
mismas trazas. La **kappa de Cohen** mide su acuerdo descontando el que saldría por
azar: si el juez dijera siempre «bien», acertaría mucho sin saber nada. Con notas de tres
niveles (0, 0,5 y 1) se usa la **kappa ponderada**: un 0 frente a un 0,5 es medio
desacuerdo; un 0 frente a un 1, uno entero.

| Kappa | Qué significa |
| --- | --- |
| ≥ 0,6 | Fiable |
| 0,4 – 0,6 | Mejora la rúbrica |
| < 0,4 | No lo uses |

**Repite antes de celebrar.** El mismo experimento da notas distintas por la
temperatura, el proveedor y los casos frontera. Si la diferencia entre dos variantes no
supera la dispersión de cada una, no hay evidencia de mejora. Con unos 25 casos, un solo
caso son 4 puntos.

## La misión

### En el código

1. Lee `evaluation/experiment.py` y `evaluation/evaluators.py` y rellena en el cuaderno
   *Cómo funcionan los evaluadores*.

2. Completa `usa_tools_esperadas` en `evaluation/evaluators.py`. Un evaluador
   recibe la salida de Nexus (`output`) y lo esperado del caso (`expected_output`) y
   devuelve un `Evaluation(name=..., value=...)`, o `[]` si el caso no tiene nada que
   puntuar. `veredicto_correcto`, justo encima, ya está hecho: te sirve de modelo.

   `usa_tools_esperadas` da la proporción de herramientas esperadas que usó Nexus. Las
   condiciones y un ejemplo están en su docstring.

3. Comprueba que los datasets están en Langfuse (pestaña **Datasets**). Si no, súbelos:

   ```bash
   uv run dataset
   ```

4. Lanza los experimentos:

   ```bash
   uv run experiment orquestador
   uv run experiment agente --repeat 3
   ```

   Al terminar verás la media de cada score, su dispersión entre repeticiones y el
   resultado por categoría. Cada ejecución queda en Langfuse como un *run* del dataset:
   ábrelo y compara los runs entre sí.

### En Langfuse

1. Compara el resultado de los tres experimentos de `agente`.

2. **Lee las trazas del capítulo.** En **Tracing**, filtra por la etiqueta `cap3` (entorno
   `cap3`). Son 10 conversaciones de Nexus escritas a propósito para calibrar jueces: todas
   dicen la verdad, pero cambian el tono y si responden a lo que se preguntó. Las cargó
   `uv run seed` en la instalación; si no las ves, súbelas con `uv run trazas-cap3`.

3. **Define tus notas antes de ver nada más.** Escribe en el cuaderno qué es para ti un
   tono brusco, uno seco y uno cercano: cómo debería hablar Nexus a un viajero. Después,
   en **Settings → Scores → Add new score config**, crea dos scores de tipo
   **CATEGORICAL**, con las categorías en este orden (Langfuse les asigna los valores 0, 1
   y 2 automáticamente):

   | Name | Value 0 | Value 1 | Value 2 |
   | --- | --- | --- | --- |
   | `tono_humano` | `brusco` | `seco` | `cercano` |
   | `relevancia_humana` | `irrelevante` | `poco relevante` | `relevante` |

   > **El orden importa:** la primera categoría cuenta como 0; la del medio, como 0,5;
   > la última, como 1.

4. **Anota tú.** Crea una **Annotation queue** con las 10 trazas `cap3` y los dos scores.
   Puntúa cada traza en los dos criterios. Todavía no hay jueces: así nada te influye.

5. **Crea los dos jueces.** En **Evaluators → LLM-as-a-judge**, con la conexión al modelo
   del capítulo 1. Aplica los dos solo a las trazas con la etiqueta `cap3`, incluidas las
   que ya existen: al guardar la regla, marca *Also run on past observations*.

   - **Tu criterio:** parte de la plantilla *Judge on One Quality Criterion* (o de un
     evaluador en blanco). Llámalo exactamente `tono`, escribe la rúbrica con tus
     definiciones del paso 3 y haz que devuelva una categoría con **las mismas
     etiquetas** que tu score: `brusco`, `seco` o `cercano`.
   - **La plantilla de Langfuse:** elige *Check Answer Relevance* y **no cambies su
     prompt**. Cámbiale el nombre a `answer_relevance`.

6. **Compara:**

   ```bash
   uv run judge-agreement
   ```

   Verás, para cada juez, la concordancia, la kappa ponderada, la matriz de 3×3 y los
   enlaces a las trazas en las que no coincidís. Ajusta la rúbrica de `tono` y vuelve a
   medir hasta llegar a 0,6. Si es la plantilla la que no llega, ¿qué puedes cambiar sin
   tocar su prompt?

Comprueba:

```bash
uv run check 3
```

## Sabrás que lo has hecho si…

- `uv run check 3` sale en verde.
- Tus dos jueces, `tono` y `answer_relevance`, tienen una kappa ponderada de 0,6 o más
con las 10 trazas del capítulo.
- Sabes cuánto varía tu experimento entre repeticiones y cuál es la mejora mínima que  
podrías detectar.

## Para pensar

- Anota las mismas 10 trazas que tu pareja, por separado, y comparad. ¿Coincidís más en
la relevancia o en el tono? ¿Por qué?
- ¿Qué te ha costado más ajustar: tu criterio o la plantilla? ¿Cuándo usarías cada uno?
- Con la dispersión que has medido, ¿cuántos puntos tendría que mejorar una variante
para que te lo creyeras?

Siguiente: [04 · La normativa que nadie leía](04-la-normativa-que-nadie-leia.md).
