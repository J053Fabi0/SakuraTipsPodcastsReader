"""Interfaz de linea de comandos."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import audio, furigana, scraper, site
from .config import get_dist_dir, get_server_port
from .database import (
    DatabaseError,
    DatabaseStore,
    DuplicatePodcastError,
)
from .scraper import ScraperError, SubtitleMismatchError

USAGE = """Uso:
  sakuratips-reader <youtube_url> <sakuratips_url>
  sakuratips-reader

Con dos argumentos agrega un podcast al sitio en dist/.
Sin argumentos inicia el servidor local en http://127.0.0.1:8000.
"""


class CliError(Exception):
    pass


def _print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def _duplicate_exists(store: DatabaseStore, youtube_id: str) -> bool:
    data = store.load_or_empty()
    return any(
        podcast.get("youtubeId") == youtube_id for podcast in data["podcasts"]
    )


def add_podcast(youtube_url: str, sakuratips_url: str) -> int:
    dist_dir = get_dist_dir()
    store = DatabaseStore(dist_dir)

    try:
        youtube_id = audio.extract_youtube_id(youtube_url)
        sakuratips_url = audio.validate_sakuratips_url(sakuratips_url)
    except audio.AudioError as exc:
        _print_error(str(exc))
        return 1

    try:
        duplicate = _duplicate_exists(store, youtube_id)
    except DatabaseError as exc:
        _print_error(str(exc))
        return 1

    if duplicate:
        _print_error(f"El podcast {youtube_id} ya fue agregado.")
        return 1

    try:
        japanese, english = scraper.fetch_subtitles(sakuratips_url)
    except SubtitleMismatchError as exc:
        _print_error(str(exc))
        return 1
    except ScraperError as exc:
        _print_error(str(exc))
        return 1
    except Exception as exc:  # pragma: no cover - red inesperada
        _print_error(f"No se pudieron obtener los subtitulos: {exc}")
        return 1

    try:
        furigana_data = furigana.generate_furigana(japanese)
    except furigana.FuriganaError as exc:
        _print_error(str(exc))
        return 1

    try:
        metadata = audio.fetch_metadata(youtube_url)
    except audio.AudioError as exc:
        _print_error(str(exc))
        return 1

    if metadata["id"] != youtube_id:
        _print_error(
            "El ID de YouTube de la URL no coincide con el de los metadatos "
            f"({youtube_id} != {metadata['id']})."
        )
        return 1

    record = audio.build_podcast_record(
        youtube_id=youtube_id,
        youtube_url=youtube_url.strip(),
        sakuratips_url=sakuratips_url,
        title=metadata["title"],
        duration=metadata["duration"],
        japanese=japanese,
        english=english,
        furigana=furigana_data,
        added_at=datetime.now(timezone.utc).astimezone().isoformat(),
    )

    try:
        site.ensure_site(dist_dir)
    except OSError as exc:
        _print_error(f"No se pudo preparar el sitio en {dist_dir}: {exc}")
        return 1

    audio_dir = dist_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=audio_dir))
    final_audio = audio_dir / f"{youtube_id}.mp3"
    moved = False

    try:
        downloaded = audio.download_audio(youtube_url, youtube_id, tmp_dir)
        downloaded_size = downloaded.stat().st_size
        if downloaded_size <= 0:
            raise audio.AudioError("El archivo MP3 descargado esta vacio.")

        def prepare() -> None:
            nonlocal moved
            final_audio.parent.mkdir(parents=True, exist_ok=True)
            downloaded.replace(final_audio)
            moved = True

        store.append(record, prepare=prepare)
    except DuplicatePodcastError as exc:
        _print_error(str(exc))
        return 1
    except (audio.AudioError, DatabaseError, OSError) as exc:
        if moved:
            try:
                final_audio.unlink()
            except FileNotFoundError:
                pass
        _print_error(str(exc))
        return 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Podcast agregado: {record['title']} ({youtube_id})")
    return 0


def start_server() -> int:
    try:
        port = get_server_port()
    except ValueError as exc:
        _print_error(str(exc))
        return 1

    from .server import serve

    try:
        serve(get_dist_dir(), port)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        _print_error(f"No se pudo iniciar el servidor: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if arguments in (["-h"], ["--help"]):
        print(USAGE)
        return 0

    if len(arguments) == 0:
        return start_server()

    if len(arguments) == 2:
        return add_podcast(arguments[0], arguments[1])

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
