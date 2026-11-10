from __future__ import annotations

import errno
import json
import os
import stat
import threading
from pathlib import Path

import pytest

from sakuratips_reader.playlist_state import (
    STATUS_ADDED,
    STATUS_ERROR,
    STATUS_EXISTS,
    STATUS_LINE_MISMATCH,
    PlaylistStateError,
    PlaylistStateStore,
    empty_state,
)


def test_missing_state_loads_empty(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    assert store.load() == empty_state()
    assert not store.exists()


def test_record_and_reload(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    entry = store.record(
        "EJDZXEXP_Co",
        STATUS_LINE_MISMATCH,
        title="Episodio 93",
        playlist_id="PL123",
        position=3,
        transcript_url="https://sakuratips.com/2021/01/28/93/",
        reason="lineas 28/30",
        japanese_lines=28,
        english_lines=30,
    )

    assert entry["status"] == STATUS_LINE_MISMATCH
    assert entry["attempts"] == 1
    assert entry["japaneseLines"] == 28
    assert entry["firstAttemptAt"] == entry["lastAttemptAt"]

    loaded = store.load()
    assert loaded["videos"]["EJDZXEXP_Co"] == entry


def test_attempts_and_first_attempt_are_preserved_on_retry(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    first = store.record(
        "aaaaaaaaaaa",
        STATUS_ERROR,
        title="Fallo",
        reason="sin red",
    )
    second = store.record(
        "aaaaaaaaaaa",
        STATUS_ADDED,
        title="Episodio",
        reason=None,
    )

    assert second["attempts"] == 2
    assert second["firstAttemptAt"] == first["firstAttemptAt"]
    assert second["lastAttemptAt"] >= first["lastAttemptAt"]
    assert second["reason"] is None
    assert second["status"] == STATUS_ADDED


def test_exists_does_not_count_as_attempt(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    entry = store.record(
        "aaaaaaaaaaa", STATUS_EXISTS, title="Existente", attempted=False
    )
    assert entry["attempts"] == 0
    assert "lastAttemptAt" not in entry


def test_set_last_run(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    store.record("aaaaaaaaaaa", STATUS_EXISTS, title="x", attempted=False)
    run = {"playlistId": "PL123", "counts": {"added": 0, "exists": 1}}
    store.set_last_run(run)
    assert store.load()["lastRun"] == run


def test_corrupt_state_is_rejected(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "playlist_state.json").write_text("{", encoding="utf-8")
    with pytest.raises(PlaylistStateError):
        PlaylistStateStore(dist).load()


def test_unknown_schema_is_rejected(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "playlist_state.json").write_text(
        json.dumps({"schemaVersion": 99, "videos": {}}), encoding="utf-8"
    )
    with pytest.raises(PlaylistStateError):
        PlaylistStateStore(dist).load()


def test_invalid_status_is_rejected(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    with pytest.raises(PlaylistStateError):
        store.record("aaaaaaaaaaa", "inventado")


def test_flock_unsupported_falls_back_to_thread_lock(monkeypatch, tmp_path: Path):
    import sakuratips_reader.playlist_state as state_module

    if state_module.fcntl is None:
        pytest.skip("fcntl no disponible")

    def unsupported(*args, **kwargs):
        raise OSError(errno.ENOSYS, "Function not implemented")

    monkeypatch.setattr(state_module.fcntl, "flock", unsupported)
    store = PlaylistStateStore(tmp_path / "dist")
    store.record("aaaaaaaaaaa", STATUS_EXISTS, title="x", attempted=False)
    assert store.load()["videos"]["aaaaaaaaaaa"]["status"] == STATUS_EXISTS


def test_state_is_readable_for_syncthing(tmp_path: Path):
    store = PlaylistStateStore(tmp_path / "dist")
    store.record("aaaaaaaaaaa", STATUS_EXISTS, title="x", attempted=False)
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o644


def test_atomic_write_does_not_leave_temporary_files(tmp_path: Path):
    dist = tmp_path / "dist"
    store = PlaylistStateStore(dist)
    store.record("aaaaaaaaaaa", STATUS_EXISTS, title="x", attempted=False)
    leftovers = [
        path.name
        for path in dist.iterdir()
        if path.name.startswith(".playlist_state-") and path.suffix == ".tmp"
    ]
    assert leftovers == []


def test_concurrent_records_from_separate_stores(tmp_path: Path):
    dist = tmp_path / "dist"
    PlaylistStateStore(dist).record(
        "99999999999", STATUS_EXISTS, title="inicial", attempted=False
    )
    errors: list[BaseException] = []

    def worker(number: int) -> None:
        try:
            PlaylistStateStore(dist).record(
                f"{number:011d}",
                STATUS_EXISTS,
                title=f"Video {number}",
                attempted=False,
            )
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    videos = PlaylistStateStore(dist).load()["videos"]
    assert len(videos) == 11
