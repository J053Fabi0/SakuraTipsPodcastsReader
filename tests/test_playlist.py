from __future__ import annotations

from pathlib import Path

import pytest

from sakuratips_reader import cli
from sakuratips_reader.audio import AudioError, PlaylistEntry
from sakuratips_reader.database import DatabaseStore

from conftest import make_podcast

PLAYLIST_URL = (
    "https://www.youtube.com/playlist?list=PLMPxq7lpQtNc_7d2a9kjGNVzbSuIl39Xi"
)
EXISTING_ID = "existing000"
DIRECT_ID = "aaaaaaaaaaa"
SEARCH_ID = "bbbbbbbbbbb"
NO_TRANSCRIPT_ID = "ccccccccccc"
ERROR_ID = "ddddddddddd"


def playlist_entries() -> list[PlaylistEntry]:
    return [
        PlaylistEntry(1, None, None, None),
        PlaylistEntry(2, EXISTING_ID, "Existente #1", 10.0),
        PlaylistEntry(3, DIRECT_ID, "Improve Japanese #92", 260.0),
        PlaylistEntry(4, SEARCH_ID, "Japanese Podcast #638", 300.0),
        PlaylistEntry(5, NO_TRANSCRIPT_ID, "Japanese Podcast #442", 280.0),
        PlaylistEntry(6, ERROR_ID, "Japanese Podcast #500", 200.0),
    ]


def metadata_for(youtube_id: str) -> dict:
    if youtube_id == DIRECT_ID:
        description = (
            "■Transcript : https://sakuratips.com/2021/01/27/92/\n"
        )
    elif youtube_id == SEARCH_ID:
        description = (
            "■Podcast Transcripts :\n"
            "https://sakuratips.com/category/pod-cast/\n"
        )
    elif youtube_id == NO_TRANSCRIPT_ID:
        description = (
            "■Podcast Transcripts : (No Transcripts for this episode)\n"
            "https://sakuratips.com/category/pod-cast/\n"
        )
    else:
        raise AudioError("video no disponible")
    return {
        "id": youtube_id,
        "title": {
            DIRECT_ID: "Improve Japanese #92",
            SEARCH_ID: "Japanese Podcast #638",
            NO_TRANSCRIPT_ID: "Japanese Podcast #442",
        }[youtube_id],
        "duration": 100.0,
        "description": description,
    }


def prepare(monkeypatch, tmp_path: Path):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    DatabaseStore(dist).append(
        make_podcast(EXISTING_ID, title="Existente #1")
    )
    monkeypatch.setattr(
        cli.audio, "fetch_playlist_entries", lambda url: playlist_entries()
    )
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: metadata_for(url.rsplit("=", 1)[-1]),
    )
    monkeypatch.setattr(
        cli.scraper,
        "search_sakuratips_transcript",
        lambda number, session=None: (
            "https://sakuratips.com/2024/02/04/638/"
            if number == 638
            else None
        ),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    return dist, sleeps


def test_playlist_dry_run_does_not_add_or_download(monkeypatch, tmp_path, capsys):
    dist, sleeps = prepare(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        cli, "add_podcast", lambda *args, **kwargs: calls.append(args)
    )

    status = cli.main(
        [
            "--playlist",
            PLAYLIST_URL,
            "--dry-run",
            "--limit",
            "5",
            "--delay",
            "0.25",
        ]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert calls == []
    assert "Se agregarian: 2" in output
    assert "Ya existentes: 1" in output
    assert "sin transcripcion" in output
    assert not (dist / "audio").exists()
    assert len(DatabaseStore(dist).load()["podcasts"]) == 1
    assert sleeps == [0.25] * 5


def test_playlist_real_mode_calls_add_with_metadata(monkeypatch, tmp_path, capsys):
    _dist, _sleeps = prepare(monkeypatch, tmp_path)
    calls = []

    def fake_add(first, second, *, metadata=None):
        calls.append((first, second, metadata))
        return 0

    monkeypatch.setattr(cli, "add_podcast", fake_add)

    status = cli.main(["--playlist", PLAYLIST_URL, "--limit", "4"])

    output = capsys.readouterr().out
    assert status == 0
    assert len(calls) == 2
    assert calls[0][1] == "https://sakuratips.com/2021/01/27/92/"
    assert calls[1][1] == "https://sakuratips.com/2024/02/04/638/"
    assert calls[0][2]["id"] == DIRECT_ID
    assert "Agregadas: 2" in output
    assert "Errores: 0" in output


def test_playlist_existing_is_skipped_before_metadata(
    monkeypatch, tmp_path, capsys
):
    _dist, _sleeps = prepare(monkeypatch, tmp_path)
    requested_ids = []
    original = cli.audio.fetch_metadata

    def tracking_metadata(url):
        requested_ids.append(url.rsplit("=", 1)[-1])
        return original(url)

    monkeypatch.setattr(cli.audio, "fetch_metadata", tracking_metadata)
    monkeypatch.setattr(cli, "add_podcast", lambda *args, **kwargs: 0)

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--start", "2", "--limit", "3"]
    )

    assert status == 0
    assert EXISTING_ID not in requested_ids
    assert DIRECT_ID in requested_ids
    assert "ya existe" in capsys.readouterr().out.lower()


def test_playlist_continues_after_metadata_error(monkeypatch, tmp_path, capsys):
    _dist, _sleeps = prepare(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        cli,
        "add_podcast",
        lambda first, second, *, metadata=None: calls.append((first, second)) or 0,
    )

    status = cli.main(["--playlist", PLAYLIST_URL, "--limit", "6"])

    output = capsys.readouterr().out
    assert status == 1
    assert len(calls) == 2
    assert "Errores: 1" in output
    assert ERROR_ID in output


def test_playlist_start_and_limit(monkeypatch, tmp_path):
    _dist, _sleeps = prepare(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        cli,
        "add_podcast",
        lambda first, second, *, metadata=None: calls.append((first, second)) or 0,
    )

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--start", "3", "--limit", "1"]
    )

    assert status == 0
    assert len(calls) == 1
    assert calls[0][1] == "https://sakuratips.com/2021/01/27/92/"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--playlist", PLAYLIST_URL, "--start", "0"],
        ["--playlist", PLAYLIST_URL, "--limit", "0"],
        ["--playlist", PLAYLIST_URL, "--delay", "-1"],
    ],
)
def test_playlist_rejects_invalid_options(monkeypatch, tmp_path, arguments, capsys):
    monkeypatch.setenv("SAKURATIPS_DIST", str(tmp_path / "dist"))
    monkeypatch.setattr(
        cli.audio, "fetch_playlist_entries", lambda url: playlist_entries()
    )
    status = cli.main(arguments)
    assert status == 2
    assert "Error:" in capsys.readouterr().err


def test_playlist_help_is_shown_in_usage(capsys):
    assert cli.main(["--help"]) == 0
    assert "--playlist" in capsys.readouterr().out


def test_add_podcast_uses_preloaded_metadata(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    monkeypatch.setattr(
        cli.scraper,
        "fetch_subtitles",
        lambda url: (["化粧についてです。"], ["About makeup."]),
    )
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: pytest.fail("no debe volver a pedir metadatos"),
    )

    def fake_download(url, youtube_id, tmp_dir):
        path = Path(tmp_dir) / f"{youtube_id}.mp3"
        path.write_bytes(b"fake-mp3")
        return path

    monkeypatch.setattr(cli.audio, "download_audio", fake_download)

    status = cli.add_podcast(
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://sakuratips.com/2020/12/20/54/",
        metadata={
            "id": "aaaaaaaaaaa",
            "title": "Podcast",
            "duration": 10.0,
            "description": "",
        },
    )

    assert status == 0
    assert DatabaseStore(dist).load()["podcasts"][0]["title"] == "Podcast"
