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

## Uso

Agregar un podcast:

```bash
sakuratips-reader <youtube_url> <sakuratips_url>
# o
python -m sakuratips_reader <youtube_url> <sakuratips_url>
```

Ejemplo de forma de las URLs:

```bash
sakuratips-reader \
  "https://www.youtube.com/watch?v=<youtube_id>" \
  "https://sakuratips.com/2020/12/20/54/"
```

Iniciar el servidor local:

```bash
sakuratips-reader
# o
python -m sakuratips_reader
```

El servidor escucha únicamente en `http://127.0.0.1:8000`. El puerto se puede
cambiar con la variable de entorno `SAKURATIPS_PORT` (por ejemplo,
`SAKURATIPS_PORT=8123 sakuratips-reader`).

Cada ejecución de alta agrega un podcast nuevo a `dist/database.json`; los
podcasts existentes nunca se eliminan. Un YouTube ID repetido se rechaza sin
volver a descargar nada. Si las cantidades de líneas japonesas e inglesas no
coinciden, el alta falla y no se descarga audio ni se escribe la base.

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

```text
dist/
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
└── database.json
```

`dist/` se genera automáticamente y está ignorado por git. Al arrancar el
servidor o agregar un podcast se refrescan los assets del frontend, sin tocar
`database.json` ni los audios existentes.

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
      "addedAt": "2026-11-10T09:00:00-06:00"
    }
  ]
}
```

- `furigana[i]` corresponde a `japanese[i]`.
- Cada token tiene `text` y `reading`; `reading` es `null` cuando no lleva
  lectura.
- `progress` está en segundos y cumple `0 <= progress <= duration`.
- `schemaVersion` permite migraciones futuras; una versión desconocida se
  rechaza en lugar de sobrescribir la base.

## API local

- `GET /api/database`: devuelve la base completa validada.
- `PUT /api/progress/<youtube_id>` con `{"progress": <segundos>}`: actualiza el
  progreso de un podcast. También se acepta `POST` para el guardado con
  `navigator.sendBeacon`.

Validaciones del progreso:

- El YouTube ID debe existir.
- El valor debe ser un número finito.
- No puede ser negativo ni superar la duración total.

Escrituras concurrentes se serializan con `threading.RLock` y `fcntl.flock`;
la lectura-modificación-escritura siempre ocurre bajo el bloqueo. El servidor
relee `database.json` en cada petición y nunca mantiene una copia obsoleta.

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
- El foco se actualiza al hacer scroll manual; no hay sincronización
  automática con el audio.
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
de Anki), base de datos atómica y concurrente, CLI, servidor/API y assets del
sitio.

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
