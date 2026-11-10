# SakuraTips Podcasts Reader

Lector local de los podcasts de [SakuraTips](https://sakuratips.com). Descarga
el audio desde YouTube, extrae los subtítulos japonés/inglés de la página del
podcast, genera el Furigana con MeCab y publica un sitio estático en `dist/`
con una interfaz de lectura tipo Spotify Lyrics.

## Requisitos

- Python 3.10 o superior.
- `yt-dlp` y FFmpeg (`ffmpeg` y `ffprobe`) disponibles en el `PATH`.
- Conexión a Internet solo al agregar un podcast.

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

Iniciar el servidor local:

```bash
sakuratips-reader
# o
python -m sakuratips_reader
```

El servidor escucha únicamente en `http://127.0.0.1:8000`. El puerto se puede
cambiar con la variable de entorno `SAKURATIPS_PORT`.

Cada ejecución de alta agrega un podcast nuevo a `dist/database.json`; los
podcasts existentes nunca se eliminan. Un YouTube ID repetido se rechaza sin
volver a descargar nada.

## Flujo de alta

1. Se extrae el YouTube ID de la URL y se comprueba que no exista.
2. Se descarga el HTML de SakuraTips y se extraen las líneas japonesas e
   inglesas dividiendo por `<br>` y por párrafos.
3. Se valida que ambas secciones tengan exactamente la misma cantidad de
   líneas. Si no coinciden, no se descarga audio ni se escribe la base.
4. Se genera el Furigana línea por línea con MeCab/IPADIC.
5. Se obtienen título y duración con `yt-dlp` y se descarga el audio en MP3 a
   `dist/audio/<youtube_id>.mp3`.
6. Se agrega el registro a `dist/database.json` con escritura atómica.

## Estructura generada

```text
dist/
├── index.html
├── podcast.html
├── assets/
├── audio/
│   └── <youtube_id>.mp3
└── database.json
```

`dist/` se genera automáticamente y está ignorado por git.

## API local

- `GET /api/database`: devuelve la base completa.
- `PUT /api/progress/<youtube_id>` con `{"progress": <segundos>}`: actualiza el
  progreso de un podcast. También se acepta `POST` para el guardado con
  `navigator.sendBeacon`.
- El sitio estático se sirve desde `dist/`.

## Pruebas

```bash
python -m pytest
```

Las pruebas no requieren red; usan fixtures HTML recortados y `yt-dlp`
simulado. Las pruebas marcadas con `network` son opcionales.

## Licencia

GPL-3.0-or-later. El módulo de Furigana es una adaptación del complemento
[JapaneseFurigana](https://github.com/obynio/anki-japanese-furigana). Ver
[LICENSE](LICENSE) y [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
