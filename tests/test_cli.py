from __future__ import annotations

from pathlib import Path

import pytest

from sakuratips_reader import cli
from sakuratips_reader.database import DatabaseStore
from sakuratips_reader.scraper import SubtitleMismatchError, TranscriptPage

from conftest import make_podcast

YOUTUBE_URL = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
YOUTUBE_ID = "aaaaaaaaaaa"
SAKURA_URL = "https://sakuratips.com/2020/12/20/54/"
JAPANESE = ["化粧についてです。", "みなさん、こんにちは。"]
ENGLISH = ["About makeup.", "Hello, everyone."]


def transcript_page(title: str = "54.こたつ Kotatsu") -> TranscriptPage:
    return TranscriptPage(
        title=title,
        chapter_number=54,
        japanese=list(JAPANESE),
        english=list(ENGLISH),
    )


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

    monkeypatch.setattr(cli.scraper, "fetch_transcript", fail)
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

    monkeypatch.setattr(cli.scraper, "fetch_transcript", mismatch)
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
        "fetch_transcript",
        lambda url: transcript_page(),
    )
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: {
            "id": YOUTUBE_ID,
            "title": "Titulo del video",
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
    assert record["chapterNumber"] == 54
    assert record["difficulty"] == 0
    assert record["duration"] == 42.5
    assert record["progress"] == 0.0
    assert record["audioFile"] == f"audio/{YOUTUBE_ID}.mp3"
    assert record["japanese"] == JAPANESE
    assert record["english"] == ENGLISH
    assert record["furigana"][0][0]["reading"] == "けしょう"
    assert (dist / "audio" / f"{YOUTUBE_ID}.mp3").read_bytes() == b"fake-mp3"
    assert (dist / "index.html").parent.exists()
    assert not any((dist / "audio").glob(".tmp-*"))


def test_url_order_does_not_matter(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))

    requested_sakuratips_urls = []

    def fake_fetch(url):
        requested_sakuratips_urls.append(url)
        return transcript_page()

    monkeypatch.setattr(cli.scraper, "fetch_transcript", fake_fetch)
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: {
            "id": YOUTUBE_ID,
            "title": "Orden independiente",
            "duration": 42.5,
        },
    )

    def fake_download(url, youtube_id, tmp_dir):
        path = Path(tmp_dir) / f"{youtube_id}.mp3"
        path.write_bytes(b"fake-mp3")
        return path

    monkeypatch.setattr(cli.audio, "download_audio", fake_download)

    # SakuraTips primero, YouTube después.
    assert cli.main([SAKURA_URL, YOUTUBE_URL]) == 0
    assert requested_sakuratips_urls == [SAKURA_URL]
    record = DatabaseStore(dist).load()["podcasts"][0]
    assert record["youtubeId"] == YOUTUBE_ID
    assert record["sakuratipsUrl"] == SAKURA_URL
    assert "Podcast agregado" in capsys.readouterr().out


def test_two_youtube_urls_are_rejected(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SAKURATIPS_DIST", str(tmp_path / "dist"))
    assert cli.main([YOUTUBE_URL, YOUTUBE_URL]) == 1
    assert "SakuraTips" in capsys.readouterr().err


def test_two_sakuratips_urls_are_rejected(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SAKURATIPS_DIST", str(tmp_path / "dist"))
    assert cli.main([SAKURA_URL, SAKURA_URL]) == 1
    assert "YouTube" in capsys.readouterr().err


def test_metadata_id_mismatch_is_rejected(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    monkeypatch.setattr(
        cli.scraper,
        "fetch_transcript",
        lambda url: transcript_page(),
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
        "fetch_transcript",
        lambda url: transcript_page(),
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


def test_migrate_titles_updates_current_data(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    store = DatabaseStore(dist)
    store.append(
        make_podcast("aaaaaaaaaaa", title="Video viejo", chapterNumber=None)
    )
    store.append(
        make_podcast(
            "bbbbbbbbbbb",
            title="Otro video",
            chapterNumber=None,
            sakuratipsUrl="https://sakuratips.com/2024/02/04/638/",
        )
    )

    titles = {
        "https://sakuratips.com/2020/12/20/54/": ("93. 神社 Shrine", 93),
    }
    monkeypatch.setattr(
        cli.scraper,
        "fetch_title_metadata",
        lambda url, session=None: titles.get(url, ("638. 宮崎県", 638)),
    )

    assert cli.main(["--migrate-titles"]) == 0
    data = store.load()
    assert data["podcasts"][0]["title"] == "93. 神社 Shrine"
    assert data["podcasts"][0]["chapterNumber"] == 93
    assert data["podcasts"][1]["title"] == "638. 宮崎県"
    assert data["podcasts"][1]["chapterNumber"] == 638
    assert "Actualizados: 2" in capsys.readouterr().out


def test_migrate_titles_dry_run_does_not_write(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    store = DatabaseStore(dist)
    store.append(make_podcast("aaaaaaaaaaa", title="Video viejo"))

    monkeypatch.setattr(
        cli.scraper,
        "fetch_title_metadata",
        lambda url, session=None: ("93. 神社 Shrine", 93),
    )

    assert cli.main(["--migrate-titles", "--dry-run"]) == 0
    assert store.load()["podcasts"][0]["title"] == "Video viejo"
    assert "dry-run" in capsys.readouterr().out


def test_migrate_titles_continues_after_errors(monkeypatch, tmp_path, capsys):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    store = DatabaseStore(dist)
    store.append(make_podcast("aaaaaaaaaaa", title="Viejo 1"))
    store.append(
        make_podcast(
            "bbbbbbbbbbb",
            title="Viejo 2",
            sakuratipsUrl="https://sakuratips.com/2024/02/04/638/",
        )
    )

    def fetch(url, session=None):
        if url.endswith("/54/"):
            raise cli.scraper.ScraperError("fallo simulado")
        return "638. 宮崎県", 638

    monkeypatch.setattr(cli.scraper, "fetch_title_metadata", fetch)

    assert cli.main(["--migrate-titles"]) == 1
    data = store.load()
    assert data["podcasts"][0]["title"] == "Viejo 1"
    assert data["podcasts"][1]["title"] == "638. 宮崎県"
    assert "Errores: 1" in capsys.readouterr().out
