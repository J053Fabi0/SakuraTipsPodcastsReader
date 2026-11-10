from __future__ import annotations

import copy
from pathlib import Path

import pytest


@pytest.fixture
def dist_dir(tmp_path: Path) -> Path:
    return tmp_path / "dist"


def make_podcast(youtube_id: str = "dQw4w9WgXcQ", **overrides):
    podcast = {
        "youtubeId": youtube_id,
        "youtubeUrl": f"https://www.youtube.com/watch?v={youtube_id}",
        "sakuratipsUrl": "https://sakuratips.com/2020/12/20/54/",
        "title": "Podcast de prueba",
        "audioFile": f"audio/{youtube_id}.mp3",
        "duration": 120.0,
        "japanese": ["化粧についてです。", "みなさん、こんにちは。"],
        "english": ["About makeup.", "Hello, everyone."],
        "furigana": [
            [
                {"text": "化粧", "reading": "けしょう"},
                {"text": "についてです。"},
            ],
            [
                {"text": "みなさん、こんにちは。"},
            ],
        ],
        "progress": 0.0,
        "focusIndex": 0,
        "addedAt": "2026-11-10T09:00:00-06:00",
    }
    podcast.update(overrides)
    return copy.deepcopy(podcast)


@pytest.fixture
def sample_podcast():
    return make_podcast()
