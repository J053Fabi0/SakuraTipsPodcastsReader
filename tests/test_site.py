from __future__ import annotations

from pathlib import Path

from sakuratips_reader.site import ensure_site
from sakuratips_reader.database import DatabaseStore

from conftest import make_podcast


def test_ensure_site_copies_frontend_without_touching_data(tmp_path: Path):
    dist = tmp_path / "dist"
    store = DatabaseStore(dist)
    store.append(make_podcast("aaaaaaaaaaa"))
    audio = dist / "audio" / "aaaaaaaaaaa.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"audio")
    before_database = (dist / "database.json").read_bytes()

    ensure_site(dist)

    assert (dist / "index.html").is_file()
    assert (dist / "podcast.html").is_file()
    assert (dist / "assets" / "css" / "style.css").is_file()
    assert (dist / "assets" / "js" / "index.js").is_file()
    assert (dist / "assets" / "js" / "podcast.js").is_file()
    assert (dist / "database.json").read_bytes() == before_database
    assert audio.read_bytes() == b"audio"


def test_ensure_site_is_idempotent(tmp_path: Path):
    dist = tmp_path / "dist"
    ensure_site(dist)
    first = (dist / "index.html").read_bytes()
    ensure_site(dist)
    assert (dist / "index.html").read_bytes() == first
