"""Persistencia del estado de procesamiento de una playlist.

Este archivo es independiente de ``database.json``. Guarda, por YouTube ID, el
resultado del ultimo intento de importacion (incluidos los fallos), para que una
nueva ejecucion no vuelva a pedir metadatos, transcripciones ni audio de videos
ya procesados.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:  # Linux/POSIX
    import fcntl
except ImportError:  # pragma: no cover - portabilidad
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = 1

STATUS_ADDED = "added"
STATUS_EXISTS = "exists"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NO_TRANSCRIPT = "no_transcript"
STATUS_NO_ENGLISH = "no_english"
STATUS_LINE_MISMATCH = "line_mismatch"
STATUS_ERROR = "error"

ALL_STATUSES = {
    STATUS_ADDED,
    STATUS_EXISTS,
    STATUS_UNAVAILABLE,
    STATUS_NO_TRANSCRIPT,
    STATUS_NO_ENGLISH,
    STATUS_LINE_MISMATCH,
    STATUS_ERROR,
}

SUCCESS_STATUSES = {STATUS_ADDED, STATUS_EXISTS}
RETRYABLE_STATUSES = {
    STATUS_UNAVAILABLE,
    STATUS_NO_TRANSCRIPT,
    STATUS_NO_ENGLISH,
    STATUS_LINE_MISMATCH,
    STATUS_ERROR,
}


class PlaylistStateError(Exception):
    """El estado de la playlist no existe, esta corrupto o no es valido."""


def empty_state() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "videos": {}, "lastRun": None}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def validate_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PlaylistStateError("playlist_state.json debe ser un objeto")
    version = data.get("schemaVersion")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != SCHEMA_VERSION
    ):
        raise PlaylistStateError(
            "schemaVersion no soportada en playlist_state.json: "
            f"{version!r} (se esperaba {SCHEMA_VERSION})"
        )

    videos = data.get("videos")
    if not isinstance(videos, dict):
        raise PlaylistStateError("videos debe ser un objeto")

    for video_id, entry in videos.items():
        if not isinstance(video_id, str) or not video_id:
            raise PlaylistStateError("Hay un YouTube ID invalido en videos")
        if not isinstance(entry, dict):
            raise PlaylistStateError(f"El estado de {video_id} no es un objeto")
        if entry.get("status") not in ALL_STATUSES:
            raise PlaylistStateError(
                f"Estado desconocido para {video_id}: {entry.get('status')!r}"
            )
        attempts = entry.get("attempts", 0)
        if (
            not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or attempts < 0
        ):
            raise PlaylistStateError(
                f"attempts invalido para {video_id}: {attempts!r}"
            )

    last_run = data.get("lastRun")
    if last_run is not None and not isinstance(last_run, dict):
        raise PlaylistStateError("lastRun debe ser un objeto o null")

    return data


class PlaylistStateStore:
    """Acceso atomico a ``dist/playlist_state.json``."""

    def __init__(self, dist_dir: str | Path) -> None:
        self.dist_dir = Path(dist_dir)
        self.path = self.dist_dir / "playlist_state.json"
        self.lock_path = self.dist_dir / ".playlist_state.lock"
        self._thread_lock = threading.RLock()

    def exists(self) -> bool:
        return self.path.exists()

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty_state()
        except OSError as exc:
            raise PlaylistStateError(
                f"No se pudo leer {self.path}: {exc}"
            ) from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PlaylistStateError(
                f"playlist_state.json no contiene JSON valido: {exc}"
            ) from exc
        return validate_state(data)

    def load(self) -> dict[str, Any]:
        return self._read_unlocked()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with open(self.lock_path, "a+", encoding="utf-8") as lock_file:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        validate_state(data)
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".playlist_state-", suffix=".json.tmp", dir=self.dist_dir
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            self._sync_directory()
        except Exception:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def _sync_directory(self) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        try:
            dir_fd = os.open(self.dist_dir, os.O_DIRECTORY)
        except OSError:
            return
        try:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
        finally:
            os.close(dir_fd)

    def record(
        self,
        youtube_id: str,
        status: str,
        *,
        title: str | None = None,
        playlist_id: str | None = None,
        position: int | None = None,
        transcript_url: str | None = None,
        reason: str | None = None,
        japanese_lines: int | None = None,
        english_lines: int | None = None,
        attempted: bool = True,
    ) -> dict[str, Any]:
        """Guarda o actualiza el resultado de un video."""

        if status not in ALL_STATUSES:
            raise PlaylistStateError(f"Estado desconocido: {status!r}")
        if not youtube_id:
            raise PlaylistStateError("Se requiere un YouTube ID para guardar estado")

        with self._locked():
            data = self._read_unlocked()
            current = data["videos"].get(youtube_id, {})
            timestamp = now_iso()

            attempts = int(current.get("attempts", 0))
            if attempted:
                attempts += 1

            entry: dict[str, Any] = dict(current)
            entry.update(
                {
                    "youtubeId": youtube_id,
                    "status": status,
                    "attempts": attempts,
                    "updatedAt": timestamp,
                }
            )
            for key, value in (
                ("title", title),
                ("playlistId", playlist_id),
                ("position", position),
                ("transcriptUrl", transcript_url),
                ("reason", reason),
                ("japaneseLines", japanese_lines),
                ("englishLines", english_lines),
            ):
                entry[key] = value

            if attempted:
                entry["lastAttemptAt"] = timestamp
                entry.setdefault("firstAttemptAt", timestamp)

            data["videos"][youtube_id] = entry
            self._write_unlocked(data)
            return dict(entry)

    def set_last_run(self, run: dict[str, Any]) -> None:
        with self._locked():
            data = self._read_unlocked()
            data["lastRun"] = run
            self._write_unlocked(data)
