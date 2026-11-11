from __future__ import annotations

from pathlib import Path

import pytest

from sakuratips_reader import server as server_module
from sakuratips_reader.database import DatabaseStore
from sakuratips_reader.server import create_app, open_local_browser

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


def test_put_focus_updates_only_one(client, app_and_dist):
    _app, dist = app_and_dist
    response = client.put("/api/focus/bbbbbbbbbbb", json={"focusIndex": 1})
    assert response.status_code == 200
    assert response.get_json()["focusIndex"] == 1

    data = DatabaseStore(dist).load()
    assert data["podcasts"][0]["focusIndex"] == 0
    assert data["podcasts"][1]["focusIndex"] == 1
    assert data["podcasts"][1]["progress"] == 20.0


def test_post_focus_alias(client, app_and_dist):
    _app, dist = app_and_dist
    response = client.post(
        "/api/focus/aaaaaaaaaaa", json={"focusIndex": 1}
    )
    assert response.status_code == 200
    assert DatabaseStore(dist).load()["podcasts"][0]["focusIndex"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"focusIndex": -1},
        {"focusIndex": 2},
        {"focusIndex": True},
        {"focusIndex": "1"},
        {"focusIndex": None},
        {"focusIndex": 0.5},
    ],
)
def test_invalid_focus_is_rejected(client, payload):
    response = client.put("/api/focus/aaaaaaaaaaa", json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_unknown_focus_podcast_returns_404(client):
    response = client.put(
        "/api/focus/zzzzzzzzzzz", json={"focusIndex": 0}
    )
    assert response.status_code == 404


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


def test_open_browser_can_be_disabled(monkeypatch):
    monkeypatch.setenv("SAKURATIPS_NO_BROWSER", "1")
    assert open_local_browser("http://127.0.0.1:8000/") is False


def test_open_browser_prefers_termux_opener(monkeypatch):
    monkeypatch.delenv("SAKURATIPS_NO_BROWSER", raising=False)
    monkeypatch.setenv("TERMUX_VERSION", "0.118")
    monkeypatch.setattr(
        server_module.shutil,
        "which",
        lambda command: f"/bin/{command}"
        if command == "termux-open-url"
        else None,
    )
    calls = []
    monkeypatch.setattr(
        server_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert open_local_browser("http://127.0.0.1:8000/") is True
    assert calls[0][0] == [
        "/bin/termux-open-url",
        "http://127.0.0.1:8000/",
    ]
    assert calls[0][1]["start_new_session"] is True


def test_open_browser_uses_xdg_open(monkeypatch):
    monkeypatch.delenv("SAKURATIPS_NO_BROWSER", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setattr(server_module.sys, "platform", "linux")
    monkeypatch.setattr(
        server_module.shutil,
        "which",
        lambda command: "/usr/bin/xdg-open" if command == "xdg-open" else None,
    )
    calls = []
    monkeypatch.setattr(
        server_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append(command),
    )

    assert open_local_browser("http://127.0.0.1:8000/") is True
    assert calls == [["/usr/bin/xdg-open", "http://127.0.0.1:8000/"]]


def test_open_browser_falls_back_to_webbrowser(monkeypatch):
    monkeypatch.delenv("SAKURATIPS_NO_BROWSER", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setattr(server_module.shutil, "which", lambda command: None)
    calls = []
    monkeypatch.setattr(
        server_module.webbrowser,
        "open",
        lambda url, new=0: calls.append((url, new)) or True,
    )

    assert open_local_browser("http://127.0.0.1:8000/") is True
    assert calls == [("http://127.0.0.1:8000/", 2)]


def test_serve_binds_before_scheduling_browser(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    events = []

    class FakeHttpServer:
        def serve_forever(self):
            events.append("serve_forever")

    class FakeTimer:
        def __init__(self, delay, callback, args):
            events.append(("timer", delay, callback, args))

        def start(self):
            events.append("timer_started")

    monkeypatch.delenv("SAKURATIPS_NO_BROWSER", raising=False)
    monkeypatch.setattr(server_module, "create_app", lambda path: object())
    monkeypatch.setattr(
        server_module,
        "make_server",
        lambda host, port, app, threaded: (
            events.append(("make_server", host, port, threaded))
            or FakeHttpServer()
        ),
    )
    monkeypatch.setattr(server_module.threading, "Timer", FakeTimer)

    server_module.serve(dist, 8123)

    assert events[0] == ("make_server", "127.0.0.1", 8123, True)
    assert events[1] == (
        "timer",
        0.4,
        server_module._open_browser_and_warn,
        ("http://127.0.0.1:8123/",),
    )
    assert events[2] == "timer_started"
    assert events[3] == "serve_forever"


def test_serve_does_not_schedule_browser_when_disabled(monkeypatch, tmp_path):
    events = []

    class FakeHttpServer:
        def serve_forever(self):
            events.append("serve_forever")

    class FakeTimer:
        def __init__(self, *args, **kwargs):
            events.append("timer")

        def start(self):
            events.append("timer_started")

    monkeypatch.setenv("SAKURATIPS_NO_BROWSER", "1")
    monkeypatch.setattr(server_module, "create_app", lambda path: object())
    monkeypatch.setattr(
        server_module,
        "make_server",
        lambda host, port, app, threaded: FakeHttpServer(),
    )
    monkeypatch.setattr(server_module.threading, "Timer", FakeTimer)

    server_module.serve(tmp_path / "dist", 8123)

    assert events == ["serve_forever"]


def test_put_difficulty_updates_only_one(client, app_and_dist):
    _app, dist = app_and_dist
    response = client.put(
        "/api/difficulty/bbbbbbbbbbb", json={"difficulty": 4}
    )
    assert response.status_code == 200
    assert response.get_json()["difficulty"] == 4

    data = DatabaseStore(dist).load()
    assert data["podcasts"][0]["difficulty"] == 0
    assert data["podcasts"][1]["difficulty"] == 4
    assert data["podcasts"][1]["progress"] == 20.0


def test_post_difficulty_alias(client, app_and_dist):
    _app, dist = app_and_dist
    response = client.post(
        "/api/difficulty/aaaaaaaaaaa", json={"difficulty": 3}
    )
    assert response.status_code == 200
    assert DatabaseStore(dist).load()["podcasts"][0]["difficulty"] == 3


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"difficulty": -1},
        {"difficulty": 6},
        {"difficulty": 1.5},
        {"difficulty": True},
        {"difficulty": "4"},
        {"difficulty": None},
    ],
)
def test_invalid_difficulty_is_rejected(client, payload):
    response = client.put("/api/difficulty/aaaaaaaaaaa", json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_unknown_difficulty_podcast_returns_404(client):
    response = client.put(
        "/api/difficulty/zzzzzzzzzzz", json={"difficulty": 3}
    )
    assert response.status_code == 404


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
