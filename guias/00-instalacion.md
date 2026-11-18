# 00 · Instalación

**Objetivo:** tener Langfuse corriendo en tu portátil, Nexus instalado y el historial de
tres semanas cargado. Cuando `uv run check 0` salga en verde, estás listo.

**Tiempo:** unos 15 minutos, la mayoría esperando descargas. Lanza los pasos lentos
(4 y 6) cuanto antes y sigue escuchando.

## Antes de empezar

- **Docker Desktop** instalado y **abierto**. Langfuse necesita unos 8 GB de RAM libres.
- **git** instalado.
- Una **clave de Groq**, el proveedor del modelo que usa Nexus. Es gratis: créala en
  [console.groq.com/keys](https://console.groq.com/keys).

No hace falta que instales Python: uv descarga la versión que necesita el proyecto (3.13).

## Paso a paso

### 1 · Instala uv, el gestor de entornos de Python

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Cierra la terminal y abre una nueva**: si no, el comando `uv` no existirá todavía.
Comprueba que funciona:

```bash
uv --version
```

### 2 · Descarga el proyecto

```bash
git clone ‹enlace del repositorio›
cd nexus-academy
```

Todos los comandos de esta guía, y de las siguientes, se ejecutan desde esta carpeta.

### 3 · Configura las claves

```powershell
copy .env.example .env      # macOS/Linux: cp .env.example .env
```

Abre `.env` y pega tu clave de Groq en `GROQ_API_KEY=`. Las claves de Langfuse ya vienen
puestas y funcionan con el `docker-compose.yml` del proyecto: no las cambies.

### 4 · Arranca Langfuse · *tarda*

```bash
docker compose up -d
```

La primera vez descarga las imágenes y puede tardar varios minutos. Cuando termine, abre
[http://localhost:3100](http://localhost:3100) y entra con:

| | |
| --- | --- |
| Usuario | `equipo@metrovilaverda.test` |
| Contraseña | `academy-password` |
| Proyecto | Nexus |

No tienes que crear el proyecto ni copiar claves: se crean solos al arrancar.

### 5 · Instala las dependencias de Python

```bash
uv sync
```

### 6 · Carga el historial de tres semanas · *tarda*

Lánzalo cuando Langfuse ya responda en el navegador:

```bash
uv run seed
```

Carga en tu Langfuse todo lo que ha hecho Nexus en producción, del 26 de octubre al 15
de noviembre de 2026: las conversaciones, las dos versiones del prompt de la primera
semana, las valoraciones de los viajeros, los datasets y el dashboard «Nexus en
producción». Tarda un par de minutos y no gasta tokens: no llama a ningún modelo. Si se
corta, vuelve a lanzarlo: sigue por donde iba y no duplica nada.

### 7 · Comprueba que todo está listo

```bash
uv run check 0
```

Verás una línea por comprobación. Todo tiene que salir con `✔`:

```text
Misión 0 · Todo listo para empezar  (ejercicios/test_cap0.py)

  ✔ Existe el fichero .env con tu configuración
  ✔ Las claves de Langfuse están en el .env
  ✔ Langfuse responde en http://localhost:3100 y acepta tus claves
  ✔ Los prompts nexus/orchestrator y nexus/executor están publicados en Langfuse
  ✔ La clave del proveedor del modelo está en el .env
  ✔ El proveedor del modelo responde a una pregunta mínima
  ✔ El historial de tres semanas de Nexus está cargado en Langfuse
```

Si algo sale con `✘`, debajo aparece una pista. La comprobación del modelo hace una
llamada real; si quieres saltarla mientras arreglas lo demás:
`uv run check 0 -k "not modelo"`.

## Ahora abre Langfuse

Ve a **Tracing** y **amplía el filtro de fecha** para que cubra del 26 de octubre al 15
de noviembre de 2026. El historial está en esas fechas: con el filtro por defecto verás
la lista vacía.

Y habla con Nexus por primera vez:

```bash
uv run agent --usuario 1042
```

Pregúntale algo como «¿A qué hora pasa el primer tren de la L1 por Plaça Major
mañana?». Escribe `salir` para terminar. En Nexus, «hoy» es el lunes 16 de noviembre de
2026 (lo puedes cambiar con `--dia AAAA-MM-DD`). Busca después tu conversación en
Tracing: es la traza más reciente.

## Tu cuaderno de trabajo

En [`CUADERNO.md`](../CUADERNO.md) irás apuntando lo que encuentres en cada capítulo:
ids de trazas, cifras y decisiones, con el porqué. Ya tiene las tablas y los huecos
preparados: casi todo es marcar una opción o escribir una cifra. Cada guía te dice qué
sección le toca.

## Si algo falla

| Si ves… | Haz esto |
| --- | --- |
| `port 3100 is already allocated` | Tienes otro Langfuse u otra aplicación en ese puerto. Ciérrala o cambia `3100` en `docker-compose.yml` y en `LANGFUSE_BASE_URL` del `.env`. |
| Langfuse no carga tras 3 minutos | `docker compose logs langfuse-web`. Casi siempre es falta de memoria: dale más RAM a Docker Desktop. |
| `Faltan variables en .env` | No has copiado `.env.example` como `.env`, o lo has guardado con otro nombre. |
| `Falta GROQ_API_KEY` | Pega tu clave de Groq en el `.env`, sin comillas ni espacios. |
| El modelo responde `429` | Es el límite de peticiones de Groq. Espera un minuto y repite. |
| `seed` se cortó | Vuelve a lanzarlo: no duplica nada. |
| `uv: command not found` | Abre una terminal nueva después de instalar uv. |

¿Sigue sin funcionar? Levanta la mano o emparéjate con alguien que ya lo tenga en verde y
sigue con él: no te quedes parado.

## Comandos del proyecto

Todo lo que harás desde la terminal empieza por `uv run`. `uv run help` los lista todos.

| Comando | Para qué | Capítulo |
| --- | --- | --- |
| `uv run agent --usuario 1042` | Hablar con Nexus como un viajero | Todos |
| `uv run check N` | Comprobar la misión N | Todos |
| `uv run prompts --label X` | Publicar los prompts del código como versión nueva | 1 |
| `uv run dataset` | Subir los datasets a Langfuse | 2, 3 y 5 |
| `uv run experiment <dataset>` | Ejecutar Nexus sobre un dataset y puntuarlo | 3, 4 y 5 |
| `uv run trazas-cap3` | Reponer las 10 trazas para calibrar los jueces (ya las sube `seed`) | 3 |
| `uv run judge-agreement` | Comparar los jueces con las anotaciones humanas | 3 |
| `uv run index --buscar "…"` | Probar el buscador de normativa | 4 |
| `uv run release …` · `uv run simulate` | Desplegar por fases y simular viajeros | 5 |

Siguiente: [01 · Dos prompts y una discusión](01-dos-prompts-y-una-discusion.md).
