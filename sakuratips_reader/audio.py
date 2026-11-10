"""Metadatos y descarga de audio de YouTube mediante ``yt-dlp``."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
SAKURATIPS_HOSTS = {"sakuratips.com", "www.sakuratips.com"}

METADATA_TIMEOUT = 300
DOWNLOAD_TIMEOUT = 1800

Runner = Callable[..., subprocess.CompletedProcess]


class AudioError(Exception):
    """Fallo al obtener metadatos o descargar el audio."""


def extract_youtube_id(url: str) -> str:
    """Extrae y valida el ID de 11 caracteres de una URL de YouTube."""

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise AudioError("La URL de YouTube debe usar http o https.")
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise AudioError(f"La URL no pertenece a YouTube: {url!r}")

    candidate: str | None = None
    if host in ("youtu.be", "www.youtu.be"):
        segments = [segment for segment in parsed.path.split("/") if segment]
        if segments:
            candidate = segments[0]
    else:
        query_id = parse_qs(parsed.query).get("v")
        if query_id:
            candidate = query_id[0]
        else:
            segments = [segment for segment in parsed.path.split("/") if segment]
            if len(segments) >= 2 and segments[0] in (
                "shorts",
                "embed",
                "live",
                "v",
            ):
                candidate = segments[1]

    if candidate is None or not YOUTUBE_ID_PATTERN.fullmatch(candidate):
        raise AudioError(
            "No se pudo extraer un YouTube ID valido de la URL proporcionada."
        )
    return candidate


def validate_sakuratips_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise AudioError("La URL de SakuraTips debe usar http o https.")
    if (parsed.hostname or "").lower() not in SAKURATIPS_HOSTS:
        raise AudioError("La URL debe pertenecer a sakuratips.com.")
    return url.strip()


def classify_podcast_urls(first: str, second: str) -> tuple[str, str]:
    """Identifica las URLs de YouTube y SakuraTips sin importar su orden."""

    youtube_url: str | None = None
    sakuratips_url: str | None = None

    for url in (first, second):
        if youtube_url is None:
            try:
                extract_youtube_id(url)
            except AudioError:
                pass
            else:
                youtube_url = url.strip()
                continue

        if sakuratips_url is None:
            try:
                validate_sakuratips_url(url)
            except AudioError:
                pass
            else:
                sakuratips_url = url.strip()

    if youtube_url is None:
        raise AudioError(
            "Falta una URL de YouTube valida entre los dos argumentos."
        )
    if sakuratips_url is None:
        raise AudioError(
            "Falta una URL de SakuraTips valida (sakuratips.com) entre los "
            "dos argumentos."
        )
    return youtube_url, sakuratips_url


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioError(
            f"No se encontro {name!r} en el PATH. Instalelo antes de continuar."
        )
    return path


def check_tools() -> tuple[str, str, str]:
    """Verifica yt-dlp, ffmpeg y ffprobe."""

    return (_tool("yt-dlp"), _tool("ffmpeg"), _tool("ffprobe"))


def _run_command(
    command: list[str],
    *,
    timeout: int,
    runner: Runner | None = None,
) -> subprocess.CompletedProcess:
    run = runner or subprocess.run
    try:
        result = run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError(
            f"El comando {' '.join(command[:2])} excedio el tiempo limite."
        ) from exc
    except OSError as exc:
        raise AudioError(f"No se pudo ejecutar el comando: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if len(detail) > 1200:
            detail = detail[-1200:]
        raise AudioError(
            f"El comando {' '.join(command[:2])} fallo "
            f"(codigo {result.returncode}). {detail}"
        )
    return result


def fetch_metadata(
    youtube_url: str,
    *,
    runner: Runner | None = None,
    timeout: int = METADATA_TIMEOUT,
) -> dict[str, Any]:
    """Obtiene id, titulo y duracion desde los metadatos de yt-dlp."""

    yt_dlp = _tool("yt-dlp")
    command = [
        yt_dlp,
        "--no-playlist",
        "--no-warnings",
        "-J",
        youtube_url,
    ]
    result = _run_command(command, timeout=timeout, runner=runner)
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AudioError("yt-dlp no devolvio metadatos JSON validos.") from exc

    if not isinstance(metadata, dict):
        raise AudioError("Los metadatos de YouTube no son un objeto JSON.")
    if metadata.get("_type") in ("playlist", "multi_video"):
        raise AudioError("La URL de YouTube corresponde a una lista de videos.")

    youtube_id = metadata.get("id")
    title = metadata.get("title")
    duration = metadata.get("duration")

    if not isinstance(youtube_id, str) or not YOUTUBE_ID_PATTERN.fullmatch(
        youtube_id
    ):
        raise AudioError("yt-dlp no devolvio un YouTube ID valido.")
    if not isinstance(title, str) or not title.strip():
        raise AudioError("yt-dlp no devolvio un titulo valido.")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or float(duration) <= 0
    ):
        raise AudioError("yt-dlp no devolvio una duracion valida.")

    return {
        "id": youtube_id,
        "title": title.strip(),
        "duration": float(duration),
    }


def download_audio(
    youtube_url: str,
    youtube_id: str,
    tmp_dir: str | Path,
    *,
    runner: Runner | None = None,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> Path:
    """Descarga el audio como MP3 dentro de ``tmp_dir``."""

    yt_dlp, _ffmpeg, _ffprobe = check_tools()
    tmp_path = Path(tmp_dir)
    tmp_path.mkdir(parents=True, exist_ok=True)

    command = [
        yt_dlp,
        "--no-playlist",
        "--no-progress",
        "--newline",
        "--no-write-info-json",
        "-f",
        "bestaudio/best",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "-o",
        str(tmp_path / "%(id)s.%(ext)s"),
        youtube_url,
    ]
    _run_command(command, timeout=timeout, runner=runner)

    expected = tmp_path / f"{youtube_id}.mp3"
    if expected.exists() and expected.stat().st_size > 0:
        return expected

    candidates = [
        path
        for path in tmp_path.glob("*.mp3")
        if path.is_file() and path.stat().st_size > 0
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise AudioError("yt-dlp no genero ningun archivo MP3.")
    raise AudioError("yt-dlp genero varios archivos MP3 inesperados.")


def build_podcast_record(
    *,
    youtube_id: str,
    youtube_url: str,
    sakuratips_url: str,
    title: str,
    duration: float,
    japanese: list[str],
    english: list[str],
    furigana: list[list[dict[str, Any]]],
    added_at: str,
) -> dict[str, Any]:
    if len(japanese) != len(english):
        raise ValueError(
            "Las lineas japonesas e inglesas deben tener la misma cantidad."
        )
    if len(furigana) != len(japanese):
        raise ValueError("Debe existir Furigana para cada linea japonesa.")

    return {
        "youtubeId": youtube_id,
        "youtubeUrl": youtube_url,
        "sakuratipsUrl": sakuratips_url,
        "title": title,
        "audioFile": f"audio/{youtube_id}.mp3",
        "duration": float(duration),
        "japanese": list(japanese),
        "english": list(english),
        "furigana": furigana,
        "progress": 0.0,
        "addedAt": added_at,
    }
