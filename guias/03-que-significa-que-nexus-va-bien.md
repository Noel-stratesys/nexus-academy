# 03 · ¿Qué significa que Nexus va bien?

> «Me dicen que Nexus va bien. Quiero un número que me lo
> demuestre, y saber cuánto me puedo fiar de ese número.»

**Tiempo:** 50 minutos · **Comprobación:** `uv run check 3` ·
**Cuaderno:** sección 03 de [`CUADERNO.md`](../CUADERNO.md)

## Lo que necesitas saber

**La calidad se mide por capas**, de lo más objetivo a lo más subjetivo:

| Capa | Pregunta | Cómo se mide | En Nexus |
| --- | --- | --- | --- |
| Nodo | ¿El orquestador clasificó bien? | Código | `veredicto_correcto` |
| Trayectoria | ¿Usó las herramientas correctas? ¿Evitó las prohibidas? ¿Pidió aprobación? | Código | `usa_tools_esperadas`, `evita_tools_prohibidas`, `aprobacion_correcta` |
| Respuesta | ¿Da los datos que debe? ¿Es fiel a lo que dijeron las herramientas? | Código + juez | `menciona_datos`, `fidelidad` |
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

**El juez también se equivoca.** Antes de fiarte de él, compáralo con personas sobre las
mismas trazas. La **kappa de Cohen** mide su acuerdo descontando el que saldría por
azar: si el juez dijera siempre «bien», acertaría mucho sin saber nada.

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

1. Abre `evaluation/evaluators.py` y completa dos evaluadores. Cada uno recibe la
   salida de Nexus (`output`) y lo esperado (`expected_output`) y devuelve un
   `Evaluation(name=..., value=...)`:
   - `veredicto_correcto`: 1 si el veredicto del orquestador (`output["verdict"]`)
     coincide con el esperado y 0 si no. Si el caso no tiene veredicto esperado, no hay
     nada que puntuar: devuelve `[]`.
   - `usa_tools_esperadas`: la proporción de herramientas esperadas que se usaron
     (`output["tools"]` es la lista de llamadas, cada una con su `name`). `"a|b"` se
     cumple con cualquiera de las dos. Una de dos es 0,5; usar herramientas de más no
     resta. Sin herramientas esperadas, devuelve `[]`.
2. Comprueba que los datasets están en Langfuse (pestaña **Datasets**). Si no, súbelos:

   ```bash
   uv run dataset
   ```

3. Lanza los experimentos:

   ```bash
   uv run experiment orquestador
   uv run experiment agente --repeat 3
   ```

   Al terminar verás la media de cada score, su dispersión entre repeticiones y el
   resultado por categoría. Cada ejecución queda en Langfuse como un *run* del dataset:
   ábrelo y compara los runs entre sí.

### En Langfuse

1. **Crea el juez.** En **Evaluators → LLM-as-a-judge**, crea un evaluador que se llame
   exactamente `fidelidad`: ¿la respuesta solo afirma lo que devolvieron las
   herramientas? Puntuación de 0 a 1. Usa la conexión al modelo que configuraste en el
   capítulo 1. Aplícalo a trazas de Nexus, incluidas las que ya existen.
2. **Anota tú.** Crea un score `fidelidad_humana` (**Settings → Scores**, de 0 a 1) y una
   **Annotation queue** con 15 trazas **que el juez ya haya puntuado**. Puntúa cada una
   sin mirar la nota del juez.
3. **Compara:**

   ```bash
   uv run judge-agreement
   ```

   Verás la concordancia, la kappa, la matriz de acuerdos y los enlaces a las trazas en
   las que no coincidís. Léelas, ajusta la rúbrica del juez y vuelve a medir hasta llegar
   a una kappa de 0,6.

Comprueba:

```bash
uv run check 3
```

## Sabrás que lo has hecho si…

- `uv run check 3` sale en verde.
- Tu juez tiene una kappa de 0,6 o más con al menos 10 trazas anotadas (la misión pide
  15).
- Sabes cuánto varía tu experimento entre repeticiones y cuál es la mejora mínima que
  podrías detectar.

<details>
<summary>Pista 1 · Mi evaluador da error en el check</summary>

Lee la línea del check: dice qué caso falla, qué esperaba y qué ha dado. Fíjate en el
nombre del score (tiene que coincidir con el de la función) y en devolver `[]` cuando no
hay nada que comprobar.

</details>

<details>
<summary>Pista 2 · El juez no tiene con qué comparar</summary>

¿Qué tendría que tener delante una persona para decidir si una respuesta es fiel? Mira
qué variables le pasas al juez en la rúbrica y de qué parte de la traza salen. ¿Le estás
dando todo eso?

</details>

<details>
<summary>Pista 3 · La kappa no sube</summary>

Mira los desacuerdos uno a uno. ¿El juez es más estricto o más permisivo que tú? Agrupa
las frases en las que no coincidís: ese tipo de frase es lo que le falta aclarar a la
rúbrica.

</details>

<details>
<summary>Pista 4 · El check dice que no hay trazas con los dos scores</summary>

Solo cuentan las trazas que tienen a la vez `fidelidad` (del juez) y `fidelidad_humana`
(tuya). Comprueba que los nombres son exactamente esos y que anotaste trazas que el juez
ya había evaluado.

</details>

## Para pensar

- Anota las mismas 15 trazas que tu pareja, por separado, y comparad. ¿Coincidís
  siempre las personas?
- Con la dispersión que has medido, ¿cuántos puntos tendría que mejorar una variante
  para que te lo creyeras?

Siguiente: [04 · La normativa que nadie leía](04-la-normativa-que-nadie-leia.md).
