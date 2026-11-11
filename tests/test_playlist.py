from __future__ import annotations

from pathlib import Path

import pytest

from sakuratips_reader import cli, playlist_state
from sakuratips_reader.audio import AudioError, PlaylistEntry
from sakuratips_reader.database import DatabaseStore
from sakuratips_reader.playlist_state import PlaylistStateStore
from sakuratips_reader.scraper import (
    MissingEnglishError,
    SubtitleMismatchError,
    TranscriptPage,
)

from conftest import make_podcast

PLAYLIST_URL = (
    "https://www.youtube.com/playlist?list=PLMPxq7lpQtNc_7d2a9kjGNVzbSuIl39Xi"
)
EXISTING_ID = "existing000"
DIRECT_ID = "aaaaaaaaaaa"
SEARCH_ID = "bbbbbbbbbbb"
NO_TRANSCRIPT_ID = "ccccccccccc"
MISMATCH_ID = "ddddddddddd"
NO_ENGLISH_ID = "eeeeeeeeeee"
METADATA_ERROR_ID = "fffffffffff"
ADD_ERROR_ID = "ggggggggggg"

DIRECT_URL = "https://sakuratips.com/2021/01/27/92/"
SEARCH_URL = "https://sakuratips.com/2024/02/04/638/"
MISMATCH_URL = "https://sakuratips.com/2021/01/28/93/"
NO_ENGLISH_URL = "https://sakuratips.com/2024/02/04/500/"
ADD_ERROR_URL = "https://sakuratips.com/2024/02/04/601/"


def playlist_entries() -> list[PlaylistEntry]:
    return [
        PlaylistEntry(1, None, None, None),
        PlaylistEntry(2, EXISTING_ID, "Existente #1", 10.0),
        PlaylistEntry(3, DIRECT_ID, "Improve Japanese #92", 260.0),
        PlaylistEntry(4, SEARCH_ID, "Japanese Podcast #638", 300.0),
        PlaylistEntry(5, NO_TRANSCRIPT_ID, "Japanese Podcast #442", 280.0),
        PlaylistEntry(6, MISMATCH_ID, "Japanese Podcast #93", 200.0),
        PlaylistEntry(7, NO_ENGLISH_ID, "Japanese Podcast #500", 250.0),
        PlaylistEntry(8, METADATA_ERROR_ID, "Japanese Podcast #600", 240.0),
        PlaylistEntry(9, ADD_ERROR_ID, "Japanese Podcast #601", 230.0),
    ]


def metadata_for(youtube_id: str) -> dict:
    if youtube_id == DIRECT_ID:
        description = f"■Transcript : {DIRECT_URL}\n"
        title = "Improve Japanese #92"
    elif youtube_id == SEARCH_ID:
        description = (
            "■Podcast Transcripts :\n"
            "https://sakuratips.com/category/pod-cast/\n"
        )
        title = "Japanese Podcast #638"
    elif youtube_id == NO_TRANSCRIPT_ID:
        description = (
            "■Podcast Transcripts : (No Transcripts for this episode)\n"
            "https://sakuratips.com/category/pod-cast/\n"
        )
        title = "Japanese Podcast #442"
    elif youtube_id == MISMATCH_ID:
        description = f"■Transcript : {MISMATCH_URL}\n"
        title = "Japanese Podcast #93"
    elif youtube_id == NO_ENGLISH_ID:
        description = f"■Transcript : {NO_ENGLISH_URL}\n"
        title = "Japanese Podcast #500"
    elif youtube_id == ADD_ERROR_ID:
        description = f"■Transcript : {ADD_ERROR_URL}\n"
        title = "Japanese Podcast #601"
    else:
        raise AudioError("video no disponible")
    return {
        "id": youtube_id,
        "title": title,
        "duration": 100.0,
        "description": description,
    }


def fake_transcript(url: str) -> TranscriptPage:
    if url == MISMATCH_URL:
        raise SubtitleMismatchError(28, 30)
    if url == NO_ENGLISH_URL:
        raise MissingEnglishError("No se encontro el encabezado English.")
    return TranscriptPage(
        title="Titulo de SakuraTips",
        chapter_number=1,
        japanese=["日本語の行"],
        english=["English line"],
    )


def prepare(monkeypatch, tmp_path: Path):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    DatabaseStore(dist).append(make_podcast(EXISTING_ID, title="Existente #1"))
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
        lambda number, session=None: SEARCH_URL if number == 638 else None,
    )
    monkeypatch.setattr(cli.scraper, "fetch_transcript", fake_transcript)
    sleeps: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    return dist, sleeps


def install_fake_add(monkeypatch, dist: Path, *, failing_id: str | None = None):
    calls: list[dict] = []

    def fake_add(first, second, *, metadata=None, subtitles=None, transcript_title=None):
        calls.append(
            {
                "first": first,
                "second": second,
                "metadata": metadata,
                "subtitles": subtitles,
                "transcript_title": transcript_title,
            }
        )
        if metadata and metadata["id"] == failing_id:
            return 1
        youtube_id = metadata["id"]
        DatabaseStore(dist).append(
            make_podcast(
                youtube_id,
                title=metadata["title"],
                duration=float(metadata["duration"]),
            )
        )
        return 0

    monkeypatch.setattr(cli, "add_podcast", fake_add)
    return calls


def test_first_run_records_each_status(monkeypatch, tmp_path, capsys):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    calls = install_fake_add(monkeypatch, dist, failing_id=ADD_ERROR_ID)

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--limit", "9", "--delay", "0"]
    )

    output = capsys.readouterr().out
    assert status == 1
    assert len(calls) == 3

    videos = PlaylistStateStore(dist).load()["videos"]
    assert None not in videos
    assert videos[EXISTING_ID]["status"] == playlist_state.STATUS_EXISTS
    assert videos[DIRECT_ID]["status"] == playlist_state.STATUS_ADDED
    assert videos[SEARCH_ID]["status"] == playlist_state.STATUS_ADDED
    assert (
        videos[NO_TRANSCRIPT_ID]["status"]
        == playlist_state.STATUS_NO_TRANSCRIPT
    )
    assert (
        videos[MISMATCH_ID]["status"] == playlist_state.STATUS_LINE_MISMATCH
    )
    assert videos[MISMATCH_ID]["japaneseLines"] == 28
    assert videos[MISMATCH_ID]["englishLines"] == 30
    assert videos[MISMATCH_ID]["transcriptUrl"] == MISMATCH_URL
    assert videos[NO_ENGLISH_ID]["status"] == playlist_state.STATUS_NO_ENGLISH
    assert (
        videos[METADATA_ERROR_ID]["status"] == playlist_state.STATUS_ERROR
    )
    assert videos[ADD_ERROR_ID]["status"] == playlist_state.STATUS_ERROR

    assert "Agregadas: 2" in output
    assert "Omitidas (sin transcripcion): 1" in output
    assert "Omitidas (sin ingles): 1" in output
    assert "Omitidas (discrepancia de lineas): 1" in output
    assert "Errores: 2" in output
    assert "playlist_state.json" in output


def test_second_run_skips_all_processed_without_per_video_requests(
    monkeypatch, tmp_path, capsys
):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    install_fake_add(monkeypatch, dist, failing_id=ADD_ERROR_ID)
    assert cli.main(["--playlist", PLAYLIST_URL, "--limit", "9", "--delay", "0"]) == 1

    # A partir de aqui ninguna operacion por video debe ocurrir.
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: pytest.fail("no debe pedir metadatos de nuevo"),
    )
    monkeypatch.setattr(
        cli.scraper,
        "search_sakuratips_transcript",
        lambda *args, **kwargs: pytest.fail("no debe buscar transcripciones"),
    )
    monkeypatch.setattr(
        cli.scraper,
        "fetch_transcript",
        lambda url: pytest.fail("no debe pedir subtitulos"),
    )
    monkeypatch.setattr(
        cli,
        "add_podcast",
        lambda *args, **kwargs: pytest.fail("no debe agregar de nuevo"),
    )

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--limit", "9", "--delay", "0"]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert "Omitidas por estado previo: 5" in output
    assert "Ya existentes: 3" in output
    assert "Errores: 0" in output

    videos = PlaylistStateStore(dist).load()["videos"]
    assert videos[DIRECT_ID]["status"] == playlist_state.STATUS_ADDED
    assert videos[DIRECT_ID]["attempts"] == 1
    assert videos[MISMATCH_ID]["attempts"] == 1
    assert videos[ADD_ERROR_ID]["attempts"] == 1


def test_retry_failed_reprocesses_only_failed_statuses(
    monkeypatch, tmp_path, capsys
):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    install_fake_add(monkeypatch, dist, failing_id=ADD_ERROR_ID)
    assert cli.main(["--playlist", PLAYLIST_URL, "--limit", "9", "--delay", "0"]) == 1

    requested_ids: list[str] = []
    original = metadata_for

    def tracking_metadata(url):
        youtube_id = url.rsplit("=", 1)[-1]
        requested_ids.append(youtube_id)
        return original(youtube_id)

    monkeypatch.setattr(cli.audio, "fetch_metadata", tracking_metadata)

    status = cli.main(
        [
            "--playlist",
            PLAYLIST_URL,
            "--limit",
            "9",
            "--delay",
            "0",
            "--retry-failed",
        ]
    )

    assert status == 1
    assert set(requested_ids) == {
        NO_TRANSCRIPT_ID,
        MISMATCH_ID,
        NO_ENGLISH_ID,
        METADATA_ERROR_ID,
        ADD_ERROR_ID,
    }
    assert DIRECT_ID not in requested_ids
    assert SEARCH_ID not in requested_ids
    assert EXISTING_ID not in requested_ids
    assert "Reintentando estados fallidos" in capsys.readouterr().out


def test_dry_run_does_not_persist_state(monkeypatch, tmp_path, capsys):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli.scraper,
        "fetch_transcript",
        lambda url: pytest.fail("dry-run no debe validar subtitulos"),
    )
    monkeypatch.setattr(
        cli,
        "add_podcast",
        lambda *args, **kwargs: pytest.fail("dry-run no debe agregar"),
    )

    status = cli.main(
        [
            "--playlist",
            PLAYLIST_URL,
            "--dry-run",
            "--limit",
            "7",
            "--delay",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert "Modo dry-run" in output
    assert not (dist / "playlist_state.json").exists()
    assert "Se agregarian:" in output


def test_existing_database_is_recorded_and_skips_metadata(
    monkeypatch, tmp_path, capsys
):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli.audio,
        "fetch_metadata",
        lambda url: pytest.fail("ya existe en la base"),
    )

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--start", "2", "--limit", "1"]
    )

    assert status == 0
    assert "ya existe" in capsys.readouterr().out.lower()
    entry = PlaylistStateStore(dist).load()["videos"][EXISTING_ID]
    assert entry["status"] == playlist_state.STATUS_EXISTS
    assert entry["attempts"] == 0


def test_stale_added_state_is_retried_if_missing_from_database(
    monkeypatch, tmp_path
):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    PlaylistStateStore(dist).record(
        DIRECT_ID,
        playlist_state.STATUS_ADDED,
        title="Improve Japanese #92",
        position=3,
    )
    calls = install_fake_add(monkeypatch, dist)

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--start", "3", "--limit", "1"]
    )

    assert status == 0
    assert len(calls) == 1
    assert PlaylistStateStore(dist).load()["videos"][DIRECT_ID]["attempts"] == 2


def test_playlist_start_and_limit(monkeypatch, tmp_path):
    dist, _sleeps = prepare(monkeypatch, tmp_path)
    calls = install_fake_add(monkeypatch, dist)

    status = cli.main(
        ["--playlist", PLAYLIST_URL, "--start", "3", "--limit", "1"]
    )

    assert status == 0
    assert len(calls) == 1
    assert calls[0]["second"] == DIRECT_URL


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
    output = capsys.readouterr().out
    assert "--playlist" in output
    assert "--retry-failed" in output


def test_add_podcast_uses_preloaded_metadata_and_subtitles(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))
    monkeypatch.setattr(
        cli.scraper,
        "fetch_subtitles",
        lambda url: pytest.fail("no debe volver a pedir subtitulos"),
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
        subtitles=(["化粧についてです。"], ["About makeup."]),
    )

    assert status == 0
    assert DatabaseStore(dist).load()["podcasts"][0]["title"] == "Podcast"


def test_add_podcast_rejects_mismatched_preloaded_subtitles(
    monkeypatch, tmp_path, capsys
):
    dist = tmp_path / "dist"
    monkeypatch.setenv("SAKURATIPS_DIST", str(dist))

    status = cli.add_podcast(
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://sakuratips.com/2020/12/20/54/",
        metadata={
            "id": "aaaaaaaaaaa",
            "title": "Podcast",
            "duration": 10.0,
            "description": "",
        },
        subtitles=(["a", "b"], ["a"]),
    )

    assert status == 1
    assert "cantidades distintas" in capsys.readouterr().err
    assert not DatabaseStore(dist).exists()
