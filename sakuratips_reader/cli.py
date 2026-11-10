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

from . import audio, furigana, playlist_state, scraper, site
from .config import get_dist_dir, get_server_port
from .database import (
    DatabaseError,
    DatabaseStore,
    DuplicatePodcastError,
)
from .scraper import MissingEnglishError, ScraperError, SubtitleMismatchError

USAGE = """Uso:
  sakuratips-reader <youtube_url> <sakuratips_url>
  sakuratips-reader
  sakuratips-reader --playlist <playlist_url> [opciones]

Con dos argumentos agrega un podcast al sitio en dist/.
El orden de las dos URLs no importa: se identifican por su dominio.
Con --playlist recorre una playlist de YouTube y agrega sus podcasts.
Sin argumentos inicia el servidor local en http://127.0.0.1:8000 y abre el
navegador. Usa SAKURATIPS_NO_BROWSER=1 para evitarlo.

Opciones de --playlist:
  --dry-run            Muestra lo que se haria sin descargar ni escribir.
  --start N            Posicion inicial 1-based (por defecto 1).
  --limit N            Maximo de entradas a procesar.
  --delay SEGUNDOS     Pausa entre entradas (por defecto 0.5).
  --retry-failed       Reintenta videos cuyo estado previo fue un fallo.
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
    subtitles: tuple[list[str], list[str]] | None = None,
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

    if subtitles is not None:
        japanese, english = subtitles
        if len(japanese) != len(english):
            _print_error(
                "Los subtitulos proporcionados tienen cantidades distintas "
                f"(japones: {len(japanese)}, ingles: {len(english)})."
            )
            return 1
    else:
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
    retry_failed: bool = False,
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
    state_store = playlist_state.PlaylistStateStore(dist_dir)

    try:
        playlist_id = audio.extract_playlist_id(playlist_url)
        entries = audio.fetch_playlist_entries(playlist_url)
    except audio.AudioError as exc:
        _print_error(str(exc))
        return 1

    if not entries:
        _print_error("La playlist no tiene entradas.")
        return 1

    try:
        existing = _existing_youtube_ids(store)
        state = state_store.load()
    except DatabaseError as exc:
        _print_error(str(exc))
        return 1
    except playlist_state.PlaylistStateError as exc:
        _print_error(str(exc))
        return 1

    state_videos = state["videos"]
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
        print("Modo dry-run: no se descargan audios ni se modifica el estado.")
    elif retry_failed:
        print("Reintentando estados fallidos (--retry-failed).")

    stats = {
        "added": 0,
        "would_add": 0,
        "exists": 0,
        "skipped_previous": 0,
        "unavailable": 0,
        "no_transcript": 0,
        "no_english": 0,
        "line_mismatch": 0,
        "errors": 0,
    }
    failures: list[str] = []
    http_session = requests.Session()
    started_at = playlist_state.now_iso()

    def pause() -> None:
        if delay > 0:
            time.sleep(delay)

    def save_status(youtube_id: str, status: str, **fields) -> None:
        if dry_run:
            return
        entry = state_store.record(
            youtube_id, status, playlist_id=playlist_id, **fields
        )
        state_videos[youtube_id] = entry

    def skipped_message(entry: dict) -> str:
        status = entry.get("status")
        if status == playlist_state.STATUS_LINE_MISMATCH:
            return (
                "line_mismatch, "
                f"{entry.get('japaneseLines')}/{entry.get('englishLines')} lineas"
            )
        if status == playlist_state.STATUS_NO_ENGLISH:
            return "sin ingles"
        if status == playlist_state.STATUS_NO_TRANSCRIPT:
            return "sin transcripcion"
        if status == playlist_state.STATUS_UNAVAILABLE:
            return "video privado o no disponible"
        if status == playlist_state.STATUS_ERROR:
            return "error previo"
        return str(status)

    try:
        for entry in selected:
            label = f"[{entry.position}/{len(entries)}]"
            youtube_id = entry.youtube_id
            title = entry.title or ""

            if not youtube_id:
                print(f"{label} Omitido: entrada sin YouTube ID.")
                stats["unavailable"] += 1
                pause()
                continue

            if youtube_id in existing:
                stored = state_videos.get(youtube_id)
                if (
                    stored is None
                    or stored.get("status") not in playlist_state.SUCCESS_STATUSES
                ):
                    save_status(
                        youtube_id,
                        playlist_state.STATUS_EXISTS,
                        title=title or None,
                        position=entry.position,
                        attempted=False,
                    )
                print(f"{label} {title or youtube_id} — ya existe.")
                stats["exists"] += 1
                pause()
                continue

            stored = state_videos.get(youtube_id)
            if stored is not None:
                status = stored.get("status")
                stale_success = status in playlist_state.SUCCESS_STATUSES
                retryable = status in playlist_state.RETRYABLE_STATUSES
                if stale_success:
                    # El estado decia agregado/existente, pero ya no esta en la
                    # base: hay que volver a procesarlo.
                    pass
                elif retryable and retry_failed:
                    pass
                else:
                    print(
                        f"{label} {stored.get('title') or title or youtube_id} "
                        f"— ya procesado ({skipped_message(stored)})."
                    )
                    stats["skipped_previous"] += 1
                    pause()
                    continue

            if not title:
                reason = "video privado o no disponible"
                save_status(
                    youtube_id,
                    playlist_state.STATUS_UNAVAILABLE,
                    title=None,
                    position=entry.position,
                    reason=reason,
                )
                print(f"{label} Omitido: {reason}.")
                stats["unavailable"] += 1
                pause()
                continue

            youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"
            try:
                metadata = audio.fetch_metadata(youtube_url)
            except audio.AudioError as exc:
                reason = f"Error al obtener metadatos: {exc}"
                save_status(
                    youtube_id,
                    playlist_state.STATUS_ERROR,
                    title=title,
                    position=entry.position,
                    reason=reason,
                )
                print(f"{label} {title} — {reason}")
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
                reason = f"Error al buscar la transcripcion: {exc}"
                save_status(
                    youtube_id,
                    playlist_state.STATUS_ERROR,
                    title=title,
                    position=entry.position,
                    reason=reason,
                )
                print(f"{label} {title} — {reason}")
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
                save_status(
                    youtube_id,
                    playlist_state.STATUS_NO_TRANSCRIPT,
                    title=title,
                    position=entry.position,
                    reason=reason,
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

            try:
                japanese, english = scraper.fetch_subtitles(transcript_url)
            except SubtitleMismatchError as exc:
                save_status(
                    youtube_id,
                    playlist_state.STATUS_LINE_MISMATCH,
                    title=title,
                    position=entry.position,
                    transcript_url=transcript_url,
                    reason=str(exc),
                    japanese_lines=exc.japanese_count,
                    english_lines=exc.english_count,
                )
                print(
                    f"{label} {title} — discrepancia de lineas "
                    f"({exc.japanese_count}/{exc.english_count})."
                )
                stats["line_mismatch"] += 1
                pause()
                continue
            except MissingEnglishError as exc:
                save_status(
                    youtube_id,
                    playlist_state.STATUS_NO_ENGLISH,
                    title=title,
                    position=entry.position,
                    transcript_url=transcript_url,
                    reason=str(exc),
                )
                print(f"{label} {title} — omitido: sin ingles.")
                stats["no_english"] += 1
                pause()
                continue
            except ScraperError as exc:
                save_status(
                    youtube_id,
                    playlist_state.STATUS_ERROR,
                    title=title,
                    position=entry.position,
                    transcript_url=transcript_url,
                    reason=str(exc),
                )
                print(f"{label} {title} — error de subtitulos: {exc}")
                stats["errors"] += 1
                failures.append(f"{youtube_id} ({title}): {exc}")
                pause()
                continue
            except Exception as exc:  # pragma: no cover - red inesperada
                save_status(
                    youtube_id,
                    playlist_state.STATUS_ERROR,
                    title=title,
                    position=entry.position,
                    transcript_url=transcript_url,
                    reason=str(exc),
                )
                print(f"{label} {title} — error inesperado: {exc}")
                stats["errors"] += 1
                failures.append(f"{youtube_id} ({title}): {exc}")
                pause()
                continue

            status = add_podcast(
                youtube_url,
                transcript_url,
                metadata=metadata,
                subtitles=(japanese, english),
            )
            if status == 0:
                save_status(
                    youtube_id,
                    playlist_state.STATUS_ADDED,
                    title=title,
                    position=entry.position,
                    transcript_url=transcript_url,
                    reason=None,
                    japanese_lines=len(japanese),
                    english_lines=len(english),
                )
                stats["added"] += 1
                existing.add(youtube_id)
            else:
                try:
                    duplicate_now = _duplicate_exists(store, youtube_id)
                except DatabaseError:
                    duplicate_now = False
                if duplicate_now:
                    save_status(
                        youtube_id,
                        playlist_state.STATUS_EXISTS,
                        title=title,
                        position=entry.position,
                        transcript_url=transcript_url,
                        attempted=False,
                    )
                    stats["exists"] += 1
                else:
                    reason = "fallo al agregar (ver salida anterior)"
                    save_status(
                        youtube_id,
                        playlist_state.STATUS_ERROR,
                        title=title,
                        position=entry.position,
                        transcript_url=transcript_url,
                        reason=reason,
                    )
                    stats["errors"] += 1
                    failures.append(f"{youtube_id} ({title}): fallo al agregar")
            pause()
    except playlist_state.PlaylistStateError as exc:
        _print_error(f"No se pudo guardar el estado de la playlist: {exc}")
        return 1
    finally:
        http_session.close()

    if not dry_run:
        try:
            state_store.set_last_run(
                {
                    "playlistId": playlist_id,
                    "playlistUrl": playlist_url,
                    "start": start,
                    "limit": limit,
                    "dryRun": dry_run,
                    "retryFailed": retry_failed,
                    "startedAt": started_at,
                    "finishedAt": playlist_state.now_iso(),
                    "counts": dict(stats),
                }
            )
        except playlist_state.PlaylistStateError as exc:
            _print_error(f"No se pudo guardar lastRun: {exc}")
            return 1

    print()
    print("Resumen de la playlist:")
    print(f"  Entradas totales: {len(entries)}")
    print(f"  Procesadas en esta ejecucion: {len(selected)}")
    print(f"  Agregadas: {stats['added']}")
    if dry_run:
        print(f"  Se agregarian: {stats['would_add']}")
    print(f"  Ya existentes: {stats['exists']}")
    print(f"  Omitidas por estado previo: {stats['skipped_previous']}")
    print(f"  Omitidas (privadas/no disponibles): {stats['unavailable']}")
    print(f"  Omitidas (sin transcripcion): {stats['no_transcript']}")
    print(f"  Omitidas (sin ingles): {stats['no_english']}")
    print(f"  Omitidas (discrepancia de lineas): {stats['line_mismatch']}")
    print(f"  Errores: {stats['errors']}")
    if failures:
        print("  Fallos:")
        for failure in failures:
            print(f"    - {failure}")
    print(f"  Estado guardado en: {state_store.path}")

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
    parser.add_argument("--retry-failed", action="store_true")
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
            retry_failed=options.retry_failed,
        )

    if len(arguments) == 0:
        return start_server()

    if len(arguments) == 2:
        return add_podcast(arguments[0], arguments[1])

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
