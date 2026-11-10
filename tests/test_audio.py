from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sakuratips_reader import audio
from sakuratips_reader.audio import (
    AudioError,
    build_podcast_record,
    classify_podcast_urls,
    download_audio,
    extract_youtube_id,
    fetch_metadata,
    validate_sakuratips_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_extract_youtube_id(url: str, expected: str):
    assert extract_youtube_id(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/",
        "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_extract_youtube_id_rejects_invalid(url: str):
    with pytest.raises(AudioError):
        extract_youtube_id(url)


def test_validate_sakuratips_url():
    assert (
        validate_sakuratips_url("https://sakuratips.com/2020/12/20/54/")
        == "https://sakuratips.com/2020/12/20/54/"
    )
    with pytest.raises(AudioError):
        validate_sakuratips_url("https://example.com/54/")
    with pytest.raises(AudioError):
        validate_sakuratips_url("not-a-url")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://sakuratips.com/2020/12/20/54/",
        ),
        (
            "https://sakuratips.com/2020/12/20/54/",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
    ],
)
def test_classify_podcast_urls_ignores_order(first: str, second: str):
    youtube_url, sakuratips_url = classify_podcast_urls(first, second)
    assert youtube_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert sakuratips_url == "https://sakuratips.com/2020/12/20/54/"


def test_classify_podcast_urls_rejects_two_youtube_urls():
    with pytest.raises(AudioError, match="SakuraTips"):
        classify_podcast_urls(
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=BaW_jenozKc",
        )


def test_classify_podcast_urls_rejects_two_sakuratips_urls():
    with pytest.raises(AudioError, match="YouTube"):
        classify_podcast_urls(
            "https://sakuratips.com/2020/12/20/54/",
            "https://sakuratips.com/2020/12/19/53/",
        )


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["cmd"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_fetch_metadata_parses_json():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return completed(
            json.dumps(
                {"id": "dQw4w9WgXcQ", "title": "Mi podcast", "duration": 123.5}
            )
        )

    metadata = fetch_metadata("https://youtu.be/dQw4w9WgXcQ", runner=runner)
    assert metadata == {
        "id": "dQw4w9WgXcQ",
        "title": "Mi podcast",
        "duration": 123.5,
    }
    assert "-J" in calls[0]
    assert "--no-playlist" in calls[0]


@pytest.mark.parametrize(
    "payload",
    [
        "no json",
        json.dumps({"id": "bad", "title": "x", "duration": 1}),
        json.dumps({"id": "dQw4w9WgXcQ", "title": "", "duration": 1}),
        json.dumps({"id": "dQw4w9WgXcQ", "title": "x", "duration": 0}),
        json.dumps({"id": "dQw4w9WgXcQ", "title": "x", "duration": "12"}),
        json.dumps({"_type": "playlist", "entries": []}),
    ],
)
def test_fetch_metadata_rejects_invalid_payload(payload: str):
    def runner(command, **kwargs):
        return completed(payload)

    with pytest.raises(AudioError):
        fetch_metadata("https://youtu.be/dQw4w9WgXcQ", runner=runner)


def test_fetch_metadata_reports_command_failure():
    def runner(command, **kwargs):
        return completed(returncode=1, stderr="ERROR: video no disponible")

    with pytest.raises(AudioError, match="video no disponible"):
        fetch_metadata("https://youtu.be/dQw4w9WgXcQ", runner=runner)


def test_download_audio_builds_expected_command(tmp_path: Path):
    calls = []
    youtube_id = "dQw4w9WgXcQ"

    def runner(command, **kwargs):
        calls.append(command)
        output_template = command[command.index("-o") + 1]
        output = output_template.replace("%(id)s", youtube_id).replace(
            "%(ext)s", "mp3"
        )
        Path(output).write_bytes(b"fake-mp3")
        return completed()

    path = download_audio(
        "https://youtu.be/dQw4w9WgXcQ", youtube_id, tmp_path, runner=runner
    )
    assert path.read_bytes() == b"fake-mp3"
    command = calls[0]
    assert "-x" in command
    assert command[command.index("--audio-format") + 1] == "mp3"
    assert command[command.index("--audio-quality") + 1] == "0"
    assert "--no-playlist" in command


def test_download_audio_fails_without_mp3(tmp_path: Path):
    def runner(command, **kwargs):
        return completed()

    with pytest.raises(AudioError, match="no genero"):
        download_audio(
            "https://youtu.be/dQw4w9WgXcQ",
            "dQw4w9WgXcQ",
            tmp_path,
            runner=runner,
        )


def test_missing_tool_is_reported(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda name: None)
    with pytest.raises(AudioError, match="yt-dlp"):
        audio.check_tools()


def test_build_podcast_record():
    record = build_podcast_record(
        youtube_id="dQw4w9WgXcQ",
        youtube_url="https://youtu.be/dQw4w9WgXcQ",
        sakuratips_url="https://sakuratips.com/2020/12/20/54/",
        title="Podcast",
        duration=10,
        japanese=["千葉"],
        english=["Chiba"],
        furigana=[[{"text": "千葉", "reading": "ちば"}]],
        added_at="2026-11-10T09:00:00-06:00",
    )
    assert record["audioFile"] == "audio/dQw4w9WgXcQ.mp3"
    assert record["progress"] == 0.0
    assert record["duration"] == 10.0

    with pytest.raises(ValueError):
        build_podcast_record(
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://youtu.be/dQw4w9WgXcQ",
            sakuratips_url="https://sakuratips.com/2020/12/20/54/",
            title="Podcast",
            duration=10,
            japanese=["a", "b"],
            english=["a"],
            furigana=[[{"text": "a", "reading": None}]],
            added_at="2026-11-10T09:00:00-06:00",
        )
