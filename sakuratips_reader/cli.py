"""Interfaz de linea de comandos."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

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
  sakuratips-reader --playlist <playlist_url> [opciones]

Con dos argumentos agrega un podcast al sitio en dist/.
El orden de las dos URLs no importa: se identifican por su dominio.
Con --playlist recorre una playlist de YouTube y agrega sus podcasts.
Sin argumentos inicia el servidor local en http://127.0.0.1:8000.

Opciones de --playlist:
  --dry-run            Muestra lo que se haria sin descargar ni escribir.
  --start N            Posicion inicial 1-based (por defecto 1).
  --limit N            Maximo de entradas a procesar.
  --delay SEGUNDOS     Pausa entre entradas (por defecto 0.5).
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


def add_podcast(
    first_url: str,
    second_url: str,
    *,
    metadata: dict | None = None,
) -> int:
    dist_dir = get_dist_dir()
    store = DatabaseStore(dist_dir)

    try:
        youtube_url, sakuratips_url = audio.classify_podcast_urls(
            first_url, second_url
        )
        youtube_id = audio.extract_youtube_id(youtube_url)
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

    if metadata is None:
        try:
            metadata = audio.fetch_metadata(youtube_url)
        except audio.AudioError as exc:
            _print_error(str(exc))
            return 1
    elif not isinstance(metadata, dict) or not all(
        key in metadata for key in ("id", "title", "duration")
    ):
        _print_error("Los metadatos de YouTube proporcionados no son validos.")
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


def _existing_youtube_ids(store: DatabaseStore) -> set[str]:
    data = store.load_or_empty()
    return {
        podcast["youtubeId"]
        for podcast in data["podcasts"]
        if isinstance(podcast, dict) and isinstance(podcast.get("youtubeId"), str)
    }


def _resolve_playlist_transcript(
    title: str,
    description: str,
    *,
    session: requests.Session,
) -> str | None:
    episode_number = scraper.extract_episode_number(title)
    direct = scraper.extract_transcript_url_from_description(
        description, episode_number
    )
    if direct is not None:
        return direct

    if scraper.description_says_no_transcript(description):
        return None
    if episode_number is None:
        return None

    return scraper.search_sakuratips_transcript(
        episode_number, session=session
    )


def import_playlist(
    playlist_url: str,
    *,
    start: int = 1,
    limit: int | None = None,
    delay: float = 0.5,
    dry_run: bool = False,
) -> int:
    if start < 1:
        _print_error("--start debe ser un entero mayor o igual a 1.")
        return 2
    if limit is not None and limit < 1:
        _print_error("--limit debe ser un entero mayor o igual a 1.")
        return 2
    if delay < 0:
        _print_error("--delay no puede ser negativo.")
        return 2

    dist_dir = get_dist_dir()
    store = DatabaseStore(dist_dir)

    try:
        entries = audio.fetch_playlist_entries(playlist_url)
    except audio.AudioError as exc:
        _print_error(str(exc))
        return 1

    if not entries:
        _print_error("La playlist no tiene entradas.")
        return 1

    try:
        existing = _existing_youtube_ids(store)
    except DatabaseError as exc:
        _print_error(str(exc))
        return 1

    selected = [
        entry for entry in entries if entry.position >= start
    ]
    if limit is not None:
        selected = selected[:limit]

    print(
        f"Playlist con {len(entries)} entradas; "
        f"procesando {len(selected)} desde la posicion {start}."
    )
    if dry_run:
        print("Modo dry-run: no se descargan audios ni se modifica la base.")

    stats = {
        "added": 0,
        "would_add": 0,
        "existing": 0,
        "skipped": 0,
        "no_transcript": 0,
        "errors": 0,
    }
    failures: list[str] = []
    http_session = requests.Session()

    def pause() -> None:
        if delay > 0:
            time.sleep(delay)

    try:
        for entry in selected:
            label = f"[{entry.position}/{len(entries)}]"
            youtube_id = entry.youtube_id
            title = entry.title

            if not youtube_id or not title:
                print(f"{label} Omitido: video privado o no disponible.")
                stats["skipped"] += 1
                pause()
                continue

            if youtube_id in existing:
                print(f"{label} {title} — ya existe.")
                stats["existing"] += 1
                pause()
                continue

            youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"
            try:
                metadata = audio.fetch_metadata(youtube_url)
            except audio.AudioError as exc:
                print(f"{label} Error al obtener metadatos: {exc}")
                stats["errors"] += 1
                failures.append(f"{youtube_id} ({title}): {exc}")
                pause()
                continue

            title = metadata.get("title") or title
            description = metadata.get("description") or ""
            try:
                transcript_url = _resolve_playlist_transcript(
                    title, description, session=http_session
                )
            except ScraperError as exc:
                print(f"{label} Error al buscar la transcripcion: {exc}")
                stats["errors"] += 1
                failures.append(f"{youtube_id} ({title}): {exc}")
                pause()
                continue

            if transcript_url is None:
                reason = (
                    "sin transcripcion en la descripcion"
                    if scraper.description_says_no_transcript(description)
                    else "sin enlace de transcripcion"
                )
                print(f"{label} {title} — omitido: {reason}.")
                stats["no_transcript"] += 1
                pause()
                continue

            print(f"{label} {title} -> {transcript_url}")
            if dry_run:
                stats["would_add"] += 1
                pause()
                continue

            status = add_podcast(
                youtube_url, transcript_url, metadata=metadata
            )
            if status == 0:
                stats["added"] += 1
                existing.add(youtube_id)
            else:
                stats["errors"] += 1
                failures.append(f"{youtube_id} ({title}): fallo al agregar")
            pause()
    finally:
        http_session.close()

    print()
    print("Resumen de la playlist:")
    print(f"  Entradas totales: {len(entries)}")
    print(f"  Procesadas en esta ejecucion: {len(selected)}")
    print(f"  Agregadas: {stats['added']}")
    if dry_run:
        print(f"  Se agregarian: {stats['would_add']}")
    print(f"  Ya existentes: {stats['existing']}")
    print(f"  Omitidas (privadas/no disponibles): {stats['skipped']}")
    print(f"  Omitidas (sin transcripcion): {stats['no_transcript']}")
    print(f"  Errores: {stats['errors']}")
    if failures:
        print("  Fallos:")
        for failure in failures:
            print(f"    - {failure}")

    return 1 if stats["errors"] else 0


def _parse_playlist_arguments(arguments: list[str]) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(
        prog="sakuratips-reader",
        description="Importa los podcasts de una playlist de YouTube.",
        add_help=False,
    )
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    try:
        return parser.parse_args(arguments)
    except SystemExit:
        return None


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

    if "--playlist" in arguments:
        options = _parse_playlist_arguments(arguments)
        if options is None:
            return 2
        return import_playlist(
            options.playlist,
            start=options.start,
            limit=options.limit,
            delay=options.delay,
            dry_run=options.dry_run,
        )

    if len(arguments) == 0:
        return start_server()

    if len(arguments) == 2:
        return add_podcast(arguments[0], arguments[1])

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
