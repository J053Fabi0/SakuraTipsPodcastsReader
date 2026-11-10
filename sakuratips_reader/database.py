"""Persistencia de ``database.json``.

El archivo es la fuente de verdad del sitio. Las escrituras se hacen en un
archivo temporal del mismo directorio y se publican con ``os.replace`` para que
los lectores nunca vean un JSON a medio escribir.

La coordinacion entre procesos se realiza con ``fcntl.flock`` sobre un archivo
de bloqueo separado. Dentro de un proceso se usa un ``RLock``.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import SCHEMA_VERSION

try:  # Linux/POSIX; en otros sistemas queda sin bloqueo entre procesos.
    import fcntl
except ImportError:  # pragma: no cover - portabilidad
    fcntl = None  # type: ignore[assignment]


class DatabaseError(Exception):
    """La base de datos no existe, esta corrupta o no cumple el esquema."""


class DuplicatePodcastError(DatabaseError):
    """Ya existe un podcast con el mismo YouTube ID."""


def empty_database() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "podcasts": []}


def _is_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DatabaseError(message)


def validate_podcast(podcast: Any, index: int | None = None) -> None:
    prefix = f"podcast #{index}: " if index is not None else "podcast: "
    _require(isinstance(podcast, dict), prefix + "debe ser un objeto")

    for field in (
        "youtubeId",
        "youtubeUrl",
        "sakuratipsUrl",
        "title",
        "audioFile",
    ):
        _require(
            isinstance(podcast.get(field), str) and podcast[field].strip() != "",
            prefix + f"campo {field!r} invalido",
        )

    duration = podcast.get("duration")
    _require(
        _is_number(duration) and float(duration) > 0,
        prefix + "duration debe ser un numero positivo",
    )

    japanese = podcast.get("japanese")
    english = podcast.get("english")
    _require(isinstance(japanese, list), prefix + "japanese debe ser una lista")
    _require(isinstance(english, list), prefix + "english debe ser una lista")
    _require(
        all(isinstance(line, str) for line in japanese),
        prefix + "japanese debe contener solo textos",
    )
    _require(
        all(isinstance(line, str) for line in english),
        prefix + "english debe contener solo textos",
    )
    _require(
        len(japanese) == len(english),
        prefix
        + f"cantidad de lineas distinta (japones: {len(japanese)}, ingles: {len(english)})",
    )

    furigana = podcast.get("furigana")
    _require(isinstance(furigana, list), prefix + "furigana debe ser una lista")
    _require(
        len(furigana) == len(japanese),
        prefix + "furigana debe tener una entrada por linea japonesa",
    )
    for line_index, (line, tokens) in enumerate(zip(japanese, furigana)):
        _require(
            isinstance(tokens, list) and tokens,
            prefix + f"furigana[{line_index}] debe ser una lista no vacia",
        )
        joined = ""
        for token in tokens:
            _require(
                isinstance(token, dict)
                and isinstance(token.get("text"), str)
                and token["text"] != ""
                and (
                    token.get("reading") is None
                    or isinstance(token.get("reading"), str)
                ),
                prefix + f"token invalido en furigana[{line_index}]",
            )
            joined += token["text"]
        _require(
            joined == line,
            prefix
            + f"furigana[{line_index}] no reconstruye la linea japonesa original",
        )

    progress = podcast.get("progress")
    _require(
        _is_number(progress) and 0 <= float(progress) <= float(duration),
        prefix + "progress debe estar entre 0 y duration",
    )


def validate_database(data: Any) -> dict[str, Any]:
    _require(isinstance(data, dict), "database.json debe ser un objeto")
    version = data.get("schemaVersion")
    _require(
        isinstance(version, int) and version == SCHEMA_VERSION,
        f"schemaVersion no soportada: {version!r} (se esperaba {SCHEMA_VERSION})",
    )
    podcasts = data.get("podcasts")
    _require(isinstance(podcasts, list), "podcasts debe ser una lista")

    seen: set[str] = set()
    for index, podcast in enumerate(podcasts):
        validate_podcast(podcast, index)
        youtube_id = podcast["youtubeId"]
        _require(
            youtube_id not in seen,
            f"YouTube ID duplicado en database.json: {youtube_id}",
        )
        seen.add(youtube_id)

    return data


def _coerce_progress(value: Any) -> float:
    _require(_is_number(value), "El progreso debe ser un numero finito")
    return float(value)


class DatabaseStore:
    """Acceso a ``dist/database.json`` con escritura atomica."""

    def __init__(self, dist_dir: str | Path) -> None:
        self.dist_dir = Path(dist_dir)
        self.path = self.dist_dir / "database.json"
        self.lock_path = self.dist_dir / ".database.lock"
        self._thread_lock = threading.RLock()

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise DatabaseError(
                f"No existe la base de datos: {self.path}"
            ) from exc
        except OSError as exc:
            raise DatabaseError(f"No se pudo leer {self.path}: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DatabaseError(
                f"database.json no contiene JSON valido: {exc}"
            ) from exc
        return validate_database(data)

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
        validate_database(data)
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".database-", suffix=".json.tmp", dir=self.dist_dir
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
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self, *, create: bool = False) -> dict[str, Any]:
        if not self.path.exists():
            if not create:
                raise DatabaseError(f"No existe la base de datos: {self.path}")
            with self._locked():
                if not self.path.exists():
                    self._write_unlocked(empty_database())
                return self._read_unlocked()
        return self._read_unlocked()

    def load_or_empty(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_database()
        return self._read_unlocked()

    def ensure_initialized(self) -> dict[str, Any]:
        return self.load(create=True)

    def append(
        self,
        podcast: dict[str, Any],
        *,
        prepare: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Agrega un podcast.

        ``prepare`` se ejecuta bajo el bloqueo, tras verificar de nuevo que no
        exista un duplicado, y antes de escribir la base. Se usa para mover el
        audio final solo cuando la operacion ya es segura.
        """

        validate_podcast(podcast)
        youtube_id = podcast["youtubeId"]

        with self._locked():
            if self.path.exists():
                data = self._read_unlocked()
            else:
                data = empty_database()

            if any(
                existing.get("youtubeId") == youtube_id
                for existing in data["podcasts"]
            ):
                raise DuplicatePodcastError(
                    f"El podcast {youtube_id} ya fue agregado."
                )

            if prepare is not None:
                prepare()

            data["podcasts"].append(podcast)
            self._write_unlocked(data)
            return data

    def update_progress(self, youtube_id: str, progress: Any) -> dict[str, Any]:
        value = _coerce_progress(progress)

        with self._locked():
            data = self._read_unlocked()
            entry = next(
                (
                    podcast
                    for podcast in data["podcasts"]
                    if podcast.get("youtubeId") == youtube_id
                ),
                None,
            )
            if entry is None:
                raise KeyError(youtube_id)

            duration = float(entry["duration"])
            if value < 0:
                raise ValueError("El progreso no puede ser negativo")
            if value > duration:
                raise ValueError(
                    f"El progreso ({value}) supera la duracion total ({duration})"
                )

            entry["progress"] = value
            self._write_unlocked(data)
            return dict(entry)
