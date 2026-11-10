from __future__ import annotations

from pathlib import Path

import pytest

from sakuratips_reader import cli
from sakuratips_reader.database import DatabaseStore
from sakuratips_reader.scraper import SubtitleMismatchError

from conftest import make_podcast

YOUTUBE_URL = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
YOUTUBE_ID = "aaaaaaaaaaa"
SAKURA_URL = "https://sakuratips.com/2020/12/20/54/"
JAPANESE = ["化粧についてです。", "みなさん、こんにちは。"]
ENGLISH = ["About makeup.", "Hello, everyone."]


def test_no_arguments_starts_server(monkeypatch, tmp_path):
    from sakuratips_reader import server

    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    monkeypatch.setenv("SAKURATIPS_PORT", "8123")
    calls = []
    monkeypatch.setattr(
        server, "serve", lambda dist_dir, port: calls.append((dist_dir, port))
    )

    assert cli.main([]) == 0
    assert calls == [(dist.resolve(), 8123)]


def test_help_and_wrong_argument_count(capsys):
    assert cli.main(["--help"]) == 0
    assert "Uso:" in capsys.readouterr().out

    assert cli.main(["solo-un-argumento"]) == 2
    assert "Uso:" in capsys.readouterr().err

    assert cli.main(["a", "b", "c"]) == 2
    assert "Uso:" in capsys.readouterr().err


def test_duplicate_is_rejected_without_network(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    DatabaseStore(dist).append(make_podcast(YOUTUBE_ID))

    def fail(*args, **kwargs):
        raise AssertionError("no se debe consultar la red para un duplicado")

    monkeypatch.setattr(cli.scraper, "fetch_subtitles", fail)
    monkeypatch.setattr(cli.audio, "fetch_metadata", fail)

    assert cli.main([YOUTUBE_URL, SAKURA_URL]) == 1
    assert "ya fue agregado" in capsys.readouterr().err
    assert len(DatabaseStore(dist).load()["podcasts"]) == 1


def test_mismatch_does_not_download_or_write(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))

    def mismatch(*args, **kwargs):
        raise SubtitleMismatchError(23, 20)

    def fail(*args, **kwargs):
        raise AssertionError("no se debe descargar audio si falla la validacion")

    monkeypatch.setattr(cli.scraper, "fetch_subtitles", mismatch)
    monkeypatch.setattr(cli.audio, "fetch_metadata", fail)
    monkeypatch.setattr(cli.audio, "download_audio", fail)

    assert cli.main([YOUTUBE_URL, SAKURA_URL]) == 1
    assert "japones: 23" in capsys.readouterr().err
    assert not (dist / "database.json").exists()
    assert not (dist / "audio").exists()


def test_invalid_sakuratips_url(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SAKURATIPS_DIST", str(tmp_path / "dist"))
    assert cli.main([YOUTUBE_URL, "https://example.com/54/"]) == 1
    assert "sakuratips.com" in capsys.readouterr().err


def test_successful_add_and_preserve_existing(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    DatabaseStore(dist).append(make_podcast("bbbbbbbbbbb", title="Existente"))

    monkeypatch.setattr(
        cli.scraper,
        "fetch_subtitles",
        lambda url: (list(JAPANESE), list(ENGLISH)),
    )
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: {
            "id": YOUTUBE_ID,
            "title": "54.こたつ Kotatsu",
            "duration": 42.5,
        },
    )

    def fake_download(url, youtube_id, tmp_dir):
        path = Path(tmp_dir) / f"{youtube_id}.mp3"
        path.write_bytes(b"fake-mp3")
        return path

    monkeypatch.setattr(cli.audio, "download_audio", fake_download)

    assert cli.main([YOUTUBE_URL, SAKURA_URL]) == 0
    output = capsys.readouterr().out
    assert "Podcast agregado" in output

    data = DatabaseStore(dist).load()
    assert [p["youtubeId"] for p in data["podcasts"]] == [
        "bbbbbbbbbbb",
        YOUTUBE_ID,
    ]
    record = data["podcasts"][1]
    assert record["title"] == "54.こたつ Kotatsu"
    assert record["duration"] == 42.5
    assert record["progress"] == 0.0
    assert record["audioFile"] == f"audio/{YOUTUBE_ID}.mp3"
    assert record["japanese"] == JAPANESE
    assert record["english"] == ENGLISH
    assert record["furigana"][0][0]["reading"] == "けしょう"
    assert (dist / "audio" / f"{YOUTUBE_ID}.mp3").read_bytes() == b"fake-mp3"
    assert (dist / "index.html").parent.exists()
    assert not any((dist / "audio").glob(".tmp-*"))


def test_metadata_id_mismatch_is_rejected(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    monkeypatch.setattr(
        cli.scraper,
        "fetch_subtitles",
        lambda url: (list(JAPANESE), list(ENGLISH)),
    )
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: {"id": "ccccccccccc", "title": "Otro", "duration": 10},
    )
    monkeypatch.setattr(
        cli.audio,
        "download_audio",
        lambda *args, **kwargs: pytest.fail("no debe descargar"),
    )

    assert cli.main([YOUTUBE_URL, SAKURA_URL]) == 1
    assert "no coincide" in capsys.readouterr().err
    assert not (dist / "database.json").exists()


def test_download_failure_leaves_no_database(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    monkeypatch.setattr(
        cli.scraper,
        "fetch_subtitles",
        lambda url: (list(JAPANESE), list(ENGLISH)),
    )
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: {"id": YOUTUBE_ID, "title": "Podcast", "duration": 10},
    )

    from sakuratips_reader.audio import AudioError

    def fail_download(*args, **kwargs):
        raise AudioError("fallo simulado")

    monkeypatch.setattr(cli.audio, "download_audio", fail_download)

    assert cli.main([YOUTUBE_URL, SAKURA_URL]) == 1
    assert "fallo simulado" in capsys.readouterr().err
    assert not (dist / "database.json").exists()
    assert not (dist / "audio" / f"{YOUTUBE_ID}.mp3").exists()
    assert not any((dist / "audio").glob(".tmp-*"))
