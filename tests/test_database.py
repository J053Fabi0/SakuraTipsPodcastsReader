from __future__ import annotations

import errno
import json
import os
import stat
import threading
from pathlib import Path

import pytest

from sakuratips_reader.config import SCHEMA_VERSION
from sakuratips_reader.database import (
    DatabaseError,
    DatabaseStore,
    DuplicatePodcastError,
    empty_database,
)

from conftest import make_podcast


def test_initialize_and_load(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    assert not store.exists()
    data = store.ensure_initialized()
    assert data == empty_database()
    assert store.exists()
    assert store.load()["schemaVersion"] == SCHEMA_VERSION


def test_append_preserves_existing(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.ensure_initialized()
    first = make_podcast("aaaaaaaaaaa")
    second = make_podcast("bbbbbbbbbbb", title="Segundo")
    store.append(first)
    data = store.append(second)

    assert [p["youtubeId"] for p in data["podcasts"]] == [
        "aaaaaaaaaaa",
        "bbbbbbbbbbb",
    ]
    loaded = store.load()
    assert loaded["podcasts"][0] == first
    assert loaded["podcasts"][1]["title"] == "Segundo"


def test_duplicate_is_rejected_and_prepare_not_called(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    called = False

    def prepare() -> None:
        nonlocal called
        called = True

    with pytest.raises(DuplicatePodcastError):
        store.append(make_podcast("aaaaaaaaaaa"), prepare=prepare)

    assert called is False
    assert len(store.load()["podcasts"]) == 1


def test_append_without_database_creates_it(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    assert not store.exists()
    store.append(make_podcast("aaaaaaaaaaa"))
    assert store.exists()
    assert store.load()["podcasts"][0]["youtubeId"] == "aaaaaaaaaaa"


def test_update_progress_only_target(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa", progress=10.0))
    store.append(make_podcast("bbbbbbbbbbb", progress=20.0))

    updated = store.update_progress("bbbbbbbbbbb", 42.5)

    assert updated["progress"] == 42.5
    data = store.load()
    assert data["podcasts"][0]["progress"] == 10.0
    assert data["podcasts"][1]["progress"] == 42.5
    assert data["podcasts"][0]["title"] == "Podcast de prueba"


@pytest.mark.parametrize(
    "value",
    [-1, 120.1, float("nan"), float("inf"), True, "12", None],
)
def test_update_progress_rejects_invalid_values(dist_dir: Path, value):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    with pytest.raises((ValueError, DatabaseError)):
        store.update_progress("aaaaaaaaaaa", value)
    assert store.load()["podcasts"][0]["progress"] == 0.0


def test_update_focus_only_target(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa", focusIndex=0))
    store.append(make_podcast("bbbbbbbbbbb", focusIndex=0))

    updated = store.update_focus("bbbbbbbbbbb", 1)

    assert updated["focusIndex"] == 1
    data = store.load()
    assert data["podcasts"][0]["focusIndex"] == 0
    assert data["podcasts"][1]["focusIndex"] == 1
    assert data["podcasts"][1]["progress"] == 0.0


@pytest.mark.parametrize(
    "value",
    [-1, 2, True, "1", None, 1.5],
)
def test_update_focus_rejects_invalid_values(dist_dir: Path, value):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa", focusIndex=0))
    with pytest.raises(ValueError):
        store.update_focus("aaaaaaaaaaa", value)
    assert store.load()["podcasts"][0]["focusIndex"] == 0


def test_update_focus_unknown_id_raises_keyerror(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    with pytest.raises(KeyError):
        store.update_focus("zzzzzzzzzzz", 0)


def test_focus_index_validation(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa", focusIndex=1))
    assert store.load()["podcasts"][0]["focusIndex"] == 1

    missing = make_podcast("bbbbbbbbbbb")
    missing.pop("focusIndex")
    store.append(missing)

    with pytest.raises(DatabaseError):
        store.append(make_podcast("ccccccccccc", focusIndex=2))
    with pytest.raises(DatabaseError):
        store.append(make_podcast("ddddddddddd", focusIndex=True))


def test_update_unknown_id_raises_keyerror(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    with pytest.raises(KeyError):
        store.update_progress("zzzzzzzzzzz", 1.0)


def test_corrupt_database_is_not_overwritten(dist_dir: Path):
    dist_dir.mkdir(parents=True)
    (dist_dir / "database.json").write_text("{no es json", encoding="utf-8")
    store = DatabaseStore(dist_dir)
    with pytest.raises(DatabaseError):
        store.load()
    with pytest.raises(DatabaseError):
        store.append(make_podcast("aaaaaaaaaaa"))
    assert (dist_dir / "database.json").read_text(encoding="utf-8") == "{no es json"


def test_unknown_schema_version_is_rejected(dist_dir: Path):
    dist_dir.mkdir(parents=True)
    (dist_dir / "database.json").write_text(
        json.dumps({"schemaVersion": 999, "podcasts": []}), encoding="utf-8"
    )
    with pytest.raises(DatabaseError):
        DatabaseStore(dist_dir).load()


def test_mismatched_subtitles_are_rejected(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    bad = make_podcast("aaaaaaaaaaa")
    bad["english"] = bad["english"][:1]
    bad["furigana"] = bad["furigana"][:1]
    with pytest.raises(DatabaseError):
        store.append(bad)
    assert not store.exists()


def test_corrupt_furigana_is_rejected(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    bad = make_podcast("aaaaaaaaaaa")
    bad["furigana"][0][0]["text"] = "別の文字"
    with pytest.raises(DatabaseError):
        store.append(bad)
    assert not store.exists()


def test_flock_unsupported_falls_back_to_thread_lock(monkeypatch, dist_dir: Path):
    import sakuratips_reader.database as database_module

    if database_module.fcntl is None:
        pytest.skip("fcntl no disponible")

    def unsupported(*args, **kwargs):
        raise OSError(errno.ENOSYS, "Function not implemented")

    monkeypatch.setattr(database_module.fcntl, "flock", unsupported)
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    assert store.load()["podcasts"][0]["youtubeId"] == "aaaaaaaaaaa"


def test_database_is_readable_for_syncthing(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o644


def test_atomic_write_leaves_no_temporary_files(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa"))
    leftovers = [
        path.name
        for path in dist_dir.iterdir()
        if path.name.startswith(".database-") and path.suffix == ".tmp"
    ]
    assert leftovers == []


def test_concurrent_appends_from_separate_stores(dist_dir: Path):
    DatabaseStore(dist_dir).ensure_initialized()
    errors: list[BaseException] = []

    def worker(number: int) -> None:
        try:
            DatabaseStore(dist_dir).append(
                make_podcast(f"{number:011d}", title=f"Podcast {number}")
            )
        except BaseException as exc:  # pragma: no cover - se reporta abajo
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    data = DatabaseStore(dist_dir).load()
    assert len(data["podcasts"]) == 10
    assert len({p["youtubeId"] for p in data["podcasts"]}) == 10


def test_concurrent_progress_updates_do_not_lose_podcasts(dist_dir: Path):
    store = DatabaseStore(dist_dir)
    store.append(make_podcast("aaaaaaaaaaa", progress=0.0))
    store.append(make_podcast("bbbbbbbbbbb", progress=0.0))
    errors: list[BaseException] = []

    def worker(value: float) -> None:
        try:
            DatabaseStore(dist_dir).update_progress("aaaaaaaaaaa", value)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(float(i),)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    data = DatabaseStore(dist_dir).load()
    assert data["podcasts"][0]["progress"] in {float(i) for i in range(20)}
    assert data["podcasts"][1]["youtubeId"] == "bbbbbbbbbbb"
