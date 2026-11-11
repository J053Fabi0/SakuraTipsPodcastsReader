# SakuraTips Podcasts Reader

Lector local de los podcasts de [SakuraTips](https://sakuratips.com). Descarga
el audio desde YouTube, extrae los subtítulos japonés/inglés de la página del
podcast, genera el Furigana con MeCab y publica un sitio estático en `dist/`
con una interfaz de lectura tipo Spotify Lyrics.

- Audio local en MP3 (`dist/audio/<youtube_id>.mp3`), nunca se reproduce desde
  YouTube.
- Subtítulos intercalados japonés/inglés, traducción con blur y Furigana oculto
  por defecto.
- Foco de lectura por cercanía al centro; el scroll lo controla el usuario.
- Progreso persistido en `dist/database.json` mediante una API local.
- Servidor exclusivamente en `127.0.0.1`.

## Requisitos

- Python 3.10 o superior.
- `yt-dlp`, `ffmpeg` y `ffprobe` disponibles en el `PATH`.
- Conexión a Internet solo al agregar un podcast.

En Arch Linux, por ejemplo:

```bash
sudo pacman -S ffmpeg yt-dlp
```

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # opcional: instala el comando sakuratips-reader
```

También se puede ejecutar sin instalar el paquete:

```bash
python -m sakuratips_reader
```

La función de Fish (y su template de chezmoi) usa un venv fuera del repo:
`$HOME/.venvs/sakuratips-reader`. Así el entorno no se sincroniza y, en
Termux, no se intenta crear dentro del almacenamiento compartido. En el
teléfono instala solo `requirements-server.txt`; en la laptop usa
`requirements.txt` completo.

## Uso

Agregar un podcast:

```bash
sakuratips-reader <youtube_url> <sakuratips_url>
# o
python -m sakuratips_reader <youtube_url> <sakuratips_url>
```

El orden de las dos URLs no importa: el programa identifica cada una por su
dominio. Estos dos comandos son equivalentes:

```bash
sakuratips-reader \
  "https://www.youtube.com/watch?v=<youtube_id>" \
  "https://sakuratips.com/2020/12/20/54/"

sakuratips-reader \
  "https://sakuratips.com/2020/12/20/54/" \
  "https://www.youtube.com/watch?v=<youtube_id>"
```

### Importar una playlist completa

```bash
sakuratips-reader --playlist "<playlist_url>"
```

Opciones:

```bash
sakuratips-reader --playlist "<playlist_url>" --dry-run
sakuratips-reader --playlist "<playlist_url>" --dry-run --limit 10
sakuratips-reader --playlist "<playlist_url>" --start 100 --limit 20
sakuratips-reader --playlist "<playlist_url>" --delay 1.0
sakuratips-reader --playlist "<playlist_url>" --limit 10 --retry-failed
```

- `--dry-run`: resuelve los enlaces y muestra qué se haría, sin descargar
  audio ni modificar `database.json` ni el estado.
- `--start N`: posición inicial 1-based dentro de la playlist.
- `--limit N`: cantidad máxima de entradas a procesar.
- `--delay SEGUNDOS`: pausa entre entradas (por defecto `0.5`).
- `--retry-failed`: vuelve a procesar únicamente los videos cuyo estado previo
  fue un fallo.

El importador:

1. Lista la playlist con `yt-dlp --flat-playlist`.
2. Omite videos privados/no disponibles y YouTube IDs que ya existan.
3. Consulta `dist/playlist_state.json`; si un video ya fue procesado, lo omite
   **sin pedir metadatos, descripción, transcripción ni audio**.
4. Lee la descripción de cada video nuevo para obtener el enlace de
   transcripción.
5. Si la descripción solo enlaza a la categoría de SakuraTips, busca la entrada
   concreta por el número de episodio (`#N`) en el título.
6. Ejecuta el flujo normal de alta, con todas sus validaciones.
7. Guarda el resultado de cada video en `dist/playlist_state.json`,
   inmediatamente después de procesarlo.

La importación es idempotente: al volver a ejecutarla, los podcasts ya
agregados y los videos que fallaron se omiten sin repetir el trabajo caro. Para
reintentar fallos:

```bash
sakuratips-reader --playlist "<playlist_url>" --limit 10 --retry-failed
```

### Estado de la playlist (`playlist_state.json`)

`dist/playlist_state.json` es independiente de `database.json` y guarda el
resultado por YouTube ID:

```json
{
  "schemaVersion": 1,
  "videos": {
    "EJDZXEXP_Co": {
      "youtubeId": "EJDZXEXP_Co",
      "title": "Improve Japanese｜Listening Exercise  #93",
      "status": "line_mismatch",
      "transcriptUrl": "https://sakuratips.com/2021/01/28/93/",
      "reason": "La cantidad de lineas no coincide (japones: 28, ingles: 30).",
      "japaneseLines": 28,
      "englishLines": 30,
      "attempts": 1
    }
  },
  "lastRun": {}
}
```

Estados posibles: `added`, `exists`, `unavailable`, `no_transcript`,
`no_english`, `line_mismatch` y `error`.

- Se escribe de forma atómica después de cada video, así que una interrupción no
  pierde lo ya procesado.
- Si el archivo está corrupto o tiene una versión desconocida, se aborta sin
  sobrescribirlo.
- Para empezar de cero, se puede borrar `dist/playlist_state.json`.
- `database.json` no cambia de esquema ni se mezcla con este estado.

> [!IMPORTANT]
> La playlist **Japanese Listening** tiene 491 entradas. No todas se pueden
> importar bajo las reglas estrictas del proyecto: hay videos privados, videos
> sin enlace de transcripción, episodios recientes sin sección `English` y
> páginas con cantidades de líneas distintas. Esos casos se omiten o se
> reportan como error, sin completar ni adivinar traducciones. Usa
> `--dry-run --limit N` para revisar antes de lanzar una importación grande.

La resolución de transcripciones rechaza URLs directas cuyo número no coincide
con el del título. Por ejemplo, si un video titulado `#97` tiene una descripción
que apunta al episodio `93`, se ignora esa URL y se busca el `97` en SakuraTips.

### División de secciones y pie promocional

Las páginas de SakuraTips colocan un divisor `<div class="jin-sen">` después de
la transcripción. Después de ese divisor aparecen párrafos que no son
subtítulos, como `Sign up for SAKURA Letter`, `I would appreciate it if you
could support me. Thanks!` o `Become a Patron!`. El extractor se detiene en ese
divisor, por lo que ya no cuenta esas líneas como parte de la traducción.

En la revisión de los primeros 50 episodios, de los **44 guardados como
`line_mismatch`, 31 pasan a tener líneas iguales** con esta corrección. Los 13
restantes siguen teniendo diferencias reales de segmentación: por ejemplo, una
frase inglesa combina dos líneas japonesas. No se fusionan ni se inventan líneas
para forzarlos. Además, una página que antes fallaba por timeout de red volvió a
responder correctamente.

Si ya habías procesado la playlist antes de esta corrección, los fallos están
guardados en `dist/playlist_state.json` y se omiten por defecto. Para
reevaluarlos una vez:

```bash
sakuratips-reader --playlist "<playlist_url>" --limit 50 --retry-failed
```

Iniciar el servidor local:

```bash
sakuratips-reader
# o
python -m sakuratips_reader
```

El servidor escucha únicamente en `http://127.0.0.1:8000` y abre el navegador
automáticamente. En Termux usa `termux-open-url`; en Linux `xdg-open` (o el
navegador por defecto). Para evitarlo:

```bash
SAKURATIPS_NO_BROWSER=1 sakuratips-reader
```

El puerto se puede cambiar con la variable de entorno `SAKURATIPS_PORT` (por
ejemplo, `SAKURATIPS_PORT=8123 sakuratips-reader`).

Cada ejecución de alta agrega un podcast nuevo a `dist/database.json`; los
podcasts existentes nunca se eliminan. Un YouTube ID repetido se rechaza sin
volver a descargar nada. Si las cantidades de líneas japonesas e inglesas no
coinciden, el alta falla y no se descarga audio ni se escribe la base.

## Repo separado y Syncthing

El repositorio y el resultado publicado se mantienen separados:

```text
Laptop:
  repo:  ~/Documents/Bots_Telegram/SakuraTipsPodcastsReader
  dist:  ~/TemporalPermanente/Syncronizado/SakuraTipsPodcastsReader

Teléfono:
  repo:  ~/Documents/Bots_Telegram/SakuraTipsPodcastsReader
  dist:  ~/storage/shared/Download/Permanente/Sincronizado/SakuraTipsPodcastsReader
```

Syncthing sincroniza **solo el contenido de `dist`**, no el repo. La carpeta
sincronizada contiene `index.html`, `assets/`, `audio/`, `database.json` y
`playlist_state.json`, pero no `.git`, código fuente ni venv.

La función de Fish exporta `SAKURATIPS_DIST` con la ruta correspondiente:

- laptop: la carpeta de Syncthing;
- teléfono: la carpeta compartida de Termux.

El repo de Termux se clona aparte y se actualiza con `git pull`:

```fish
git clone https://github.com/J053Fabi0/SakuraTipsPodcastsReader.git \
  ~/Documents/Bots_Telegram/SakuraTipsPodcastsReader
```

En el teléfono:

- El venv se crea en `$HOME/.venvs/sakuratips-reader`, en almacenamiento
  privado de Termux, porque `/storage/emulated/0` es FUSE y no permite crear el
  symlink `lib64`.
- Se instala `requirements-server.txt` (servidor/lector). No incluye MeCab ni
  `yt-dlp`, por lo que **agregar podcasts se hace en la laptop**.

`database.json` es un único archivo que ambos dispositivos pueden escribir:

- no ejecutes el servidor en laptop y teléfono al mismo tiempo;
- activa versionado de archivos en Syncthing;
- si aparece un `*.sync-conflict-*`, detén ambos servidores y conserva la base
  con los datos más recientes.

## Flujo de alta

1. Se extrae el YouTube ID de la URL y se comprueba que no exista.
2. Se descarga el HTML de SakuraTips y se extraen las líneas japonesas e
   inglesas dividiendo por `<br>` y por párrafos.
3. Se valida que ambas secciones tengan exactamente la misma cantidad de
   líneas. Si no coinciden, se aborta sin descargar audio ni tocar la base.
4. Se genera el Furigana línea por línea con MeCab/IPADIC.
5. Se obtienen título y duración con `yt-dlp` y se descarga el audio en MP3 a
   `dist/audio/<youtube_id>.mp3`.
6. Se agrega el registro a `dist/database.json` con escritura atómica
   (archivo temporal + `os.replace`) y bloqueo entre procesos.

## Estructura generada

La ruta de `dist` se controla con `SAKURATIPS_DIST`; en la configuración de
Syncthing es una carpeta externa al repo:

```text
SakuraTipsPodcastsReader/       # contenido plano de dist
├── index.html
├── podcast.html
├── favicon.svg
├── assets/
│   ├── css/style.css
│   └── js/
│       ├── index.js
│       └── podcast.js
├── audio/
│   └── <youtube_id>.mp3
├── database.json
└── playlist_state.json
```

`dist` se genera automáticamente y está ignorado por git. Al arrancar el
servidor o agregar un podcast se refrescan los assets del frontend, sin tocar
`database.json` ni los audios existentes. Si no se usa la función de Fish hay
que exportar `SAKURATIPS_DIST` manualmente.

## `database.json`

```json
{
  "schemaVersion": 1,
  "podcasts": [
    {
      "youtubeId": "dQw4w9WgXcQ",
      "youtubeUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "sakuratipsUrl": "https://sakuratips.com/2020/12/20/54/",
      "title": "54.こたつ Kotatsu",
      "audioFile": "audio/dQw4w9WgXcQ.mp3",
      "duration": 312.4,
      "japanese": ["今日のテーマは、こたつについてです。"],
      "english": ["Today's theme is about kotatsu."],
      "furigana": [
        [
          {"text": "今日", "reading": "きょう"},
          {"text": "のテーマは、こたつについてです。"}
        ]
      ],
      "progress": 0.0,
      "focusIndex": 0,
      "addedAt": "2026-11-10T09:00:00-06:00"
    }
  ]
}
```

- `furigana[i]` corresponde a `japanese[i]`.
- Cada token tiene `text` y `reading`; `reading` es `null` cuando no lleva
  lectura.
- `progress` está en segundos y cumple `0 <= progress <= duration`.
- `focusIndex` es el índice 0-based del subtítulo enfocado y cumple
  `0 <= focusIndex < len(japanese)`. En registros antiguos que no lo tengan,
  el navegador asume `0`.
- `schemaVersion` permite migraciones futuras; una versión desconocida se
  rechaza en lugar de sobrescribir la base.

## API local

- `GET /api/database`: devuelve la base completa validada.
- `PUT /api/progress/<youtube_id>` con `{"progress": <segundos>}`: actualiza el
  progreso de un podcast. También se acepta `POST` para el guardado con
  `navigator.sendBeacon`.
- `PUT /api/focus/<youtube_id>` con `{"focusIndex": <entero>}`: guarda el
  subtítulo enfocado. También acepta `POST` para `sendBeacon`.

Validaciones del progreso:

- El YouTube ID debe existir.
- El valor debe ser un número finito.
- No puede ser negativo ni superar la duración total.

Validaciones del foco:

- El YouTube ID debe existir.
- `focusIndex` debe ser un entero no booleano.
- Debe estar entre `0` y `len(japanese) - 1`.

Escrituras concurrentes se serializan con `threading.RLock` y, cuando el
filesystem lo permite, `fcntl.flock`; la lectura-modificación-escritura siempre
ocurre bajo el bloqueo. En Android/FUSE, donde `flock` no está implementado, se
usa el bloqueo del proceso. El servidor relee `database.json` en cada petición y
nunca mantiene una copia obsoleta.

## Interfaz

### Biblioteca

- Pestañas **Pendientes** (`<95%`) y **Vistos** (`>=95%`).
- Cada tarjeta muestra título, porcentaje y duración.
- El progreso se calcula como `progress / duration * 100`.

### Lector

- Frases japonesas e inglesas intercaladas por posición.
- Inglés con `blur` y Furigana oculto por defecto.
- Cada pareja es una unidad independiente.
- Clic en una unidad no enfocada: la desplaza suavemente al centro, sin
  revelar nada.
- Clic en la unidad enfocada: alterna Furigana + traducción.
- Seleccionar texto no activa ni desactiva la unidad; el Furigana no es
  seleccionable y no interfiere con el arrastre de selección.
- El foco se actualiza al hacer scroll manual; no hay sincronización
  automática con el audio.
- El subtítulo enfocado se guarda en `focusIndex` y se restaura al volver a
  abrir el podcast.
- Reproductor fijo inferior con barra de progreso, tiempo transcurrido,
  duración y botones `-3s`, `-1s`, Play/Pause, `+1s`, `+3s`.
- Progreso guardado cada 5 segundos mientras reproduce, al pausar, al cambiar
  de posición, al terminar, al ocultar la pestaña y al abandonar la página.
- No se usa `localStorage` ni `IndexedDB`.

## Pruebas

```bash
python -m pytest
```

Las pruebas no requieren red: usan fixtures HTML recortados y `yt-dlp`
simulado. Cubren scraper, validación de líneas, Furigana (24 casos del addon
de Anki), base de datos atómica y concurrente, CLI, servidor/API, assets del
sitio e importación de playlists (descripciones, búsqueda por episodio,
persistencia de estados, omisión de videos ya procesados, `--retry-failed`,
`--dry-run`, límites e idempotencia).

Verificación manual recomendada tras un alta real:

```bash
python -m sakuratips_reader
```

Abrir `http://127.0.0.1:8000`, comprobar las pestañas, el blur, el Furigana,
el foco por scroll y que el progreso se conserva al recargar.

### Nota sobre la página 53

La especificación menciona 34/30 líneas para
`https://sakuratips.com/2020/12/19/53/`. El DOM actual y la copia archivada de
2020-12-19 producen **23 líneas japonesas y 20 inglesas** con el algoritmo
definido. El caso sigue fallando como exige la especificación y el mensaje
reporta ambas cantidades reales. Si se necesita el valor histórico 34/30 haría
falta un snapshot distinto de esa página.

## Licencia

GPL-3.0-or-later. El módulo de Furigana es una adaptación del complemento
[JapaneseFurigana](https://github.com/obynio/anki-japanese-furigana) de
obynio. Ver [LICENSE](LICENSE) y
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
