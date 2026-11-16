# 05 · Los despliegues

> «Hay cuatro cambios esperando para subir a producción. Quiero en
> producción todos los que sean seguros antes de las 17:00, y ninguno que no lo sea.»

**Tiempo:** 55 minutos · **Comprobación:** `uv run check 5` ·
**Cuaderno:** sección 05 de [`CUADERNO.md`](../CUADERNO.md)

## Los cuatro cambios

| Cambio | Autor | Qué promete |
| --- | --- | --- |
| A | Marc | Tono más cercano y avisos más claros |
| B | Jordi | Devoluciones más ágiles: menos fricción con el viajero |
| C | Laia | Prompt más corto: −30 % de tokens |
| D | Jordi | Herramienta nueva: próximos trenes en tiempo real |

B, C y D están construidos sobre A: **A tiene que estar en producción antes de
prepararlos.**

## Lo que necesitas saber

**Subir poco a poco, con marcha atrás en cada paso.** Un cambio primero pasa la
**puerta** (un experimento sobre el dataset `nexus/agente` que tiene que llegar a unos
mínimos) y después llega a cada vez más viajeros: 10 %, 50 %, 100 %. En cualquier
momento se puede volver atrás.

```text
cambio preparado → puerta → 10 % → 50 % → 100 % → promote
                      └────────── rollback ──────────┘
```

- **Blue** es la versión estable: los prompts con el label `production`.
- **Green** es la versión nueva: los prompts con el label `green` y sus funcionalidades
  (flags).
- **El router** decide qué viajeros van a green con `hash(viajero) % 100`: la misma
  persona va siempre a la misma versión.
- **Cada traza lleva su release:** puedes comparar blue y green en el mismo periodo.

El estado está en `release.toml`. No lo edites a mano: lo escribe `uv run release`.

**Decide antes qué te hará volver atrás.** Elige tus umbrales **antes** de mirar los
datos. Estos son ejemplos:

| Señal | Dónde se ve | Umbral de ejemplo | Si se cruza |
| --- | --- | --- | --- |
| Valoración de viajeros | Dashboard, por release | Cae más de 10 puntos frente a blue | Rollback |
| Juez de fidelidad en vivo | Scores, por release | Por debajo de 0,8 | Rollback |
| Latencia p95 | Dashboard, por release | El doble que blue | Rollback |
| Tokens por conversación | Dashboard, por release | +50 % frente a blue | Revisar |
| Errores | Tracing, nivel ERROR | Más del 2 % | Rollback |

**Mira también por segmento:** idioma y categoría. Un fallo en el 15 % de los viajeros
se esconde en la media.

La puerta de Nexus está en `release.toml`, sección `[gate]`: la media mínima de cada
score del experimento (`sin_errores`, `usa_tools_esperadas`, `evita_tools_prohibidas`,
`aprobacion_correcta` y `menciona_datos`). `uv run release status` la muestra.

## Los comandos

```bash
uv run release status                    # qué hay en blue y en green
uv run release prepare A                 # publica el cambio A en green, al 0 %
uv run release gate                      # la puerta: experimento sobre el dataset agente
uv run release shift 10                  # el 10 % de los viajeros va a green
uv run simulate --n 40                   # 40 viajeros simulados hablan con Nexus
uv run release promote --motivo "…"      # green pasa a ser blue (production)
uv run release rollback --motivo "…"     # green vuelve al 0 %; el cambio sigue en green
```

- `shift` no deja subir el tráfico si el cambio no ha superado la puerta.
- `simulate` imprime una tabla por release (conversaciones, valoración, latencia media y
  p95, errores y herramientas por conversación) y deja las trazas en Langfuse. Usa
  `--seed` para cambiar de viajeros y `--concurrencia` para ir más rápido (cuidado con
  los límites del proveedor).
- **Apunta siempre el motivo** de cada `promote` y `rollback`: en el comando y en la
  tabla del cuaderno.

## La misión

Para **cada** cambio:

1. `uv run release prepare <cambio>`.
2. `uv run release gate`. Si no pasa, no recibe tráfico: decide si lo descartas
   (rollback) o lo corriges.
3. `uv run release shift 10` y `uv run simulate --n 40`. Compara blue y green: en la
   tabla del simulador y en el dashboard **«Nexus en producción»**, por release y por
   segmento.
4. Si todo va bien, sube a 50 % y luego a 100 %, simulando y mirando en cada paso.
5. Cierra el cambio con `promote` o `rollback`, **con un motivo**.

**Si un cambio falla, corrígelo y vuelve a desplegarlo:**

| Dónde está el arreglo | Qué haces después |
| --- | --- |
| En un prompt del cambio (los prompts de los cambios están en `release/`) | `uv run release prepare <cambio>` para volver a publicarlo |
| En el código de una herramienta (`nexus/tools/`) | `uv run release gate` otra vez: el código ya está cambiado |

**Cada rollback deja un caso nuevo en el dataset.** Si el canary descubre algo que la
puerta no vio, añade a `evaluation/datasets/agente.py` los casos que lo habrían
detectado y súbelos con `uv run dataset agente`: la puerta solo ve los casos que están en
Langfuse. Para escribir un caso en otro idioma, asígnalo a un viajero que hable ese
idioma (`viajero="1002"` es Jordi, que escribe en catalán; `viajero="1013"` es James,
que escribe en inglés).

Comprueba:

```bash
uv run check 5
```

## Sabrás que lo has hecho si…

- Cada cambio acaba en *promote* o en *rollback*, con un motivo.
- Ningún cambio se queda a medias: green no tiene tráfico al terminar.
- Los que fallaban se han corregido y se han vuelto a desplegar.
- `uv run check 5` sale en verde.

<details>
<summary>Pista 1 · La puerta no pasa</summary>

Lee la tabla de la puerta: dice qué score no llega al mínimo. Después abre el run del
experimento en Langfuse y mira los casos que fallan en ese score. ¿Qué hace Nexus en
ellos que no debería?

</details>

<details>
<summary>Pista 2 · En la tabla del simulador todo parece igual</summary>

¿Cuántas conversaciones fueron a green? ¿Te basta ese número para concluir algo? ¿Y si
el fallo solo afecta a un grupo de viajeros?

</details>

<details>
<summary>Pista 3 · Green tarda mucho y gasta muchos tokens</summary>

Abre una traza lenta de green y mira su línea de tiempo. ¿El problema está en lo que
decide el modelo o en lo que le devuelve la herramienta? ¿Cómo lo comprobarías sin pasar
por el modelo?

</details>

<details>
<summary>Pista 4 · No puedo preparar un cambio</summary>

`prepare` falla si green todavía tiene tráfico (termina antes el cambio anterior) o si
el cambio necesita que A esté en producción. `uv run release status` te dice en qué
estado está cada uno.

</details>

## Para pensar

- ¿De qué te protege la puerta? ¿Y de qué te protege el canary?
- ¿Qué caso habrías añadido al dataset para que la puerta hubiera parado cada cambio que
  falló en el canary?

Siguiente: [06 · Proyecto final](06-proyecto-final.md).
