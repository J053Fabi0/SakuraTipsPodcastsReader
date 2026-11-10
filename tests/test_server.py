from __future__ import annotations

from pathlib import Path

import pytest

from sakuratips_reader.database import DatabaseStore
from sakuratips_reader.server import create_app

from conftest import make_podcast


@pytest.fixture
def app_and_dist(tmp_path: Path):
    dist = tmp_path / "dist"
    store = DatabaseStore(dist)
    store.ensure_initialized()
    store.append(make_podcast("aaaaaaaaaaa", progress=10.0))
    store.append(make_podcast("bbbbbbbbbbb", progress=20.0))
    app = create_app(dist)
    app.config.update(TESTING=True)
    return app, dist


@pytest.fixture
def client(app_and_dist):
    app, _dist = app_and_dist
    return app.test_client()


def test_index_and_static_assets(client):
    assert client.get("/").status_code == 200
    assert client.get("/index.html").status_code == 200
    assert client.get("/podcast.html").status_code == 200
    assert client.get("/assets/css/style.css").status_code == 200
    assert client.get("/assets/js/podcast.js").status_code == 200
    assert client.get("/database.json").status_code == 200
    response = client.get("/")
    assert response.headers["Cache-Control"] == "no-store"


def test_static_audio_supports_range(app_and_dist):
    app, dist = app_and_dist
    audio = dist / "audio" / "aaaaaaaaaaa.mp3"
    audio.write_bytes(b"0123456789abcdef")
    client = app.test_client()

    response = client.get(
        "/audio/aaaaaaaaaaa.mp3", headers={"Range": "bytes=0-3"}
    )
    assert response.status_code == 206
    assert response.data == b"0123"


def test_get_database_api(client):
    response = client.get("/api/database")
    assert response.status_code == 200
    data = response.get_json()
    assert data["schemaVersion"] == 1
    assert [p["youtubeId"] for p in data["podcasts"]] == [
        "aaaaaaaaaaa",
        "bbbbbbbbbbb",
    ]
    assert response.headers["Cache-Control"] == "no-store"


def test_put_progress_updates_only_one(client, app_and_dist):
    _app, dist = app_and_dist
    response = client.put(
        "/api/progress/bbbbbbbbbbb", json={"progress": 42.5}
    )
    assert response.status_code == 200
    assert response.get_json()["progress"] == 42.5

    data = DatabaseStore(dist).load()
    assert data["podcasts"][0]["progress"] == 10.0
    assert data["podcasts"][1]["progress"] == 42.5
    assert data["podcasts"][0]["title"] == "Podcast de prueba"


def test_post_progress_alias(client, app_and_dist):
    _app, dist = app_and_dist
    response = client.post(
        "/api/progress/aaaaaaaaaaa", json={"progress": 33}
    )
    assert response.status_code == 200
    assert DatabaseStore(dist).load()["podcasts"][0]["progress"] == 33


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"progress": -1},
        {"progress": 120.1},
        {"progress": "12"},
        {"progress": True},
        {"progress": None},
        {"progress": float("nan")},
    ],
)
def test_invalid_progress_is_rejected(client, payload):
    response = client.put("/api/progress/aaaaaaaaaaa", json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_malformed_json_is_rejected(client):
    response = client.put(
        "/api/progress/aaaaaaaaaaa",
        data="{",
        content_type="application/json",
    )
    assert response.status_code == 400


def test_unknown_podcast_returns_404(client):
    response = client.put(
        "/api/progress/zzzzzzzzzzz", json={"progress": 1}
    )
    assert response.status_code == 404


def test_create_app_initializes_site(tmp_path):
    dist = tmp_path / "nuevo"
    app = create_app(dist)
    assert (dist / "index.html").is_file()
    assert (dist / "database.json").is_file()
    assert app.test_client().get("/").status_code == 200


def test_corrupt_database_returns_500(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "database.json").write_text("{", encoding="utf-8")
    app = create_app(dist)
    client = app.test_client()
    assert client.get("/api/database").status_code == 500
    assert client.put(
        "/api/progress/aaaaaaaaaaa", json={"progress": 1}
    ).status_code == 500
