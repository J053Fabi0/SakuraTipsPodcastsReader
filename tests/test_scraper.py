from __future__ import annotations

from pathlib import Path

import pytest
import requests

from sakuratips_reader.scraper import (
    MissingEnglishError,
    ScraperError,
    SubtitleMismatchError,
    description_says_no_transcript,
    extract_episode_number,
    extract_transcript_url_from_description,
    fetch_subtitles,
    normalize_text,
    parse_subtitles,
    search_sakuratips_transcript,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_page_54_has_equal_sections():
    html = (FIXTURES / "54.html").read_text(encoding="utf-8")
    japanese, english = parse_subtitles(html)

    assert len(japanese) == 25
    assert len(english) == 25
    assert japanese[0] == "みなさん、こんにちは。"
    assert english[0] == "Hello, everyone."
    assert japanese[4] == "〜広告〜"
    assert english[4] == "~ad~"
    assert japanese[-1] == "それでは、またね〜。"
    assert english[-1] == "I’ll see you tomorrow."


def test_page_53_mismatch_reports_both_counts():
    html = (FIXTURES / "53.html").read_text(encoding="utf-8")

    with pytest.raises(SubtitleMismatchError) as error:
        parse_subtitles(html)

    assert error.value.japanese_count == 23
    assert error.value.english_count == 20
    message = str(error.value)
    assert "japones: 23" in message
    assert "ingles: 20" in message


def test_br_and_paragraph_boundaries_split_lines():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>一行目<br/>二行目<br />三行目</p>
      <p>四行目</p>
      <h2>English</h2>
      <p>Line one<br/>Line two<br />Line three</p>
      <p>Line four</p>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["一行目", "二行目", "三行目", "四行目"]
    assert english == ["Line one", "Line two", "Line three", "Line four"]


def test_inline_tags_are_preserved_as_text():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p><b>大事</b>なこと<br/><span>次の<i>行</i></span></p>
      <h2>English</h2>
      <p><b>Important</b> thing<br/><span>Next <i>line</i></span></p>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["大事なこと", "次の行"]
    assert english == ["Important thing", "Next line"]


def test_entities_are_decoded_and_punctuation_not_split():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>今日はいい天気です。散歩しましょう！<br/>本当ですか？</p>
      <h2>English</h2>
      <p>Today&#8217;s weather is nice. Let&#39;s walk!<br/>Really?</p>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["今日はいい天気です。散歩しましょう！", "本当ですか？"]
    assert english == ["Today’s weather is nice. Let's walk!", "Really?"]


def test_ad_lines_are_not_removed():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>〜広告〜</p>
      <p>本文</p>
      <h2>English</h2>
      <p>~ad~</p>
      <p>Body</p>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["〜広告〜", "本文"]
    assert english == ["~ad~", "Body"]


def test_empty_segments_are_skipped_but_ideographic_space_preserved():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>前<br/><br/>テスト勉強の息抜きとか　どうしてんの<br/></p>
      <h2>English</h2>
      <p>Before<br/><br/>After<br/></p>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["前", "テスト勉強の息抜きとか　どうしてんの"]
    assert english == ["Before", "After"]


def test_intermediate_non_paragraph_elements_are_ignored():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>一</p>
      <div class="ad">publicidad</div>
      <p>二</p>
      <h2>English</h2>
      <p>One</p>
      <div class="share">compartir</div>
      <p>Two</p>
      <div class="clearfix"></div>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["一", "二"]
    assert english == ["One", "Two"]


def test_missing_headings_fail():
    with pytest.raises(ScraperError):
        parse_subtitles("<article><h2>にほんご</h2><p>x</p></article>")
    with pytest.raises(ScraperError):
        parse_subtitles("<article><h2>English</h2><p>x</p></article>")


def test_missing_english_has_specific_error():
    with pytest.raises(MissingEnglishError):
        parse_subtitles(
            "<article><h2>にほんご</h2><p>x</p></article>"
        )


def test_english_before_japanese_fails():
    html = """
    <div itemprop="articleBody">
      <h2>English</h2>
      <p>x</p>
      <h2>にほんご</h2>
      <p>y</p>
    </div>
    """
    with pytest.raises(ScraperError):
        parse_subtitles(html)


def test_english_section_stops_at_next_heading():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>一</p>
      <h2>English</h2>
      <p>One</p>
      <h2>Otra seccion</h2>
      <p>No debe incluirse</p>
    </div>
    """
    japanese, english = parse_subtitles(html)
    assert japanese == ["一"]
    assert english == ["One"]


def test_unexpected_heading_inside_japanese_fails():
    html = """
    <div itemprop="articleBody">
      <h2>にほんご</h2>
      <p>x</p>
      <h2>Otra seccion</h2>
      <p>y</p>
      <h2>English</h2>
      <p>x</p>
    </div>
    """
    with pytest.raises(ScraperError):
        parse_subtitles(html)


def test_normalize_text_keeps_ideographic_space():
    assert normalize_text("  a\t b\u00a0 c　d  ") == "a b c　d"


def test_extract_episode_number():
    assert extract_episode_number("Improve Japanese｜Listening Exercise  #92") == 92
    assert extract_episode_number("Japanese Podcast #638. 宮崎県 Miyazaki") == 638
    assert extract_episode_number("Improve Japanese # 153｜SAKURA TIPS") == 153
    assert extract_episode_number("Sin numero") is None
    assert extract_episode_number(None) is None


def test_extract_direct_transcript_url_by_episode_number():
    description = """
■Twitter : https://twitter.com/sakura_tips_m
■Podcast : https://anchor.fm/69612
■Transcript : https://sakuratips.com/2021/01/27/92/

#Japanese #日本語
"""
    assert (
        extract_transcript_url_from_description(description, 92)
        == "https://sakuratips.com/2021/01/27/92/"
    )


def test_mismatched_direct_transcript_url_is_rejected():
    description = """
■Transcript : https://sakuratips.com/2021/01/28/93/
"""
    assert extract_transcript_url_from_description(description, 97) is None


def test_mismatched_description_falls_back_to_search_by_number():
    description = """
■Transcript : https://sakuratips.com/2021/01/28/93/
"""
    html = """
    <a href="https://sakuratips.com/2021/01/28/93/">93</a>
    <a href="https://sakuratips.com/2021/02/01/97/">97</a>
    """
    session = FakeSession(FakeResponse(html))
    resolved = extract_transcript_url_from_description(description, 97)
    if resolved is None:
        resolved = search_sakuratips_transcript(97, session=session)
    assert resolved == "https://sakuratips.com/2021/02/01/97/"


def test_category_only_description_has_no_direct_url():
    description = """
■Podcast Transcripts :
https://sakuratips.com/category/pod-cast/

■SAKURA News Letter :
https://sakuratips.com/2021/07/07/sakuraletter/
"""
    assert extract_transcript_url_from_description(description, 638) is None


def test_no_transcripts_marker_returns_none():
    description = """
■Podcast Transcripts : （No Transcripts for this episode)
https://sakuratips.com/category/pod-cast/
"""
    assert description_says_no_transcript(description) is True
    assert extract_transcript_url_from_description(description, 442) is None


def test_transcript_url_on_next_line_without_episode_number():
    description = """
■Transcript :
https://sakuratips.com/2021/01/27/92/

#Japanese
"""
    assert (
        extract_transcript_url_from_description(description, None)
        == "https://sakuratips.com/2021/01/27/92/"
    )


def test_search_transcript_picks_exact_episode_suffix():
    html = """
    <html><body>
      <a href="https://sakuratips.com/2021/03/01/592/">592. コロナ</a>
      <a href="/2021/03/01/392/">392. 言葉</a>
      <a href="https://sakuratips.com/2021/03/01/292/">292. 大雨</a>
      <a href="https://sakuratips.com/2021/01/27/92/">92. カニ</a>
      <a href="https://sakuratips.com/category/pod-cast/">Podcast</a>
    </body></html>
    """
    session = FakeSession(FakeResponse(html))
    url = search_sakuratips_transcript(92, session=session)
    assert url == "https://sakuratips.com/2021/01/27/92/"
    assert session.calls[0][1]["params"] == {"s": "92"}


def test_search_transcript_returns_none_without_exact_match():
    html = '<a href="https://sakuratips.com/2021/03/01/592/">592</a>'
    session = FakeSession(FakeResponse(html))
    assert search_sakuratips_transcript(92, session=session) is None


def test_search_transcript_wraps_network_errors():
    session = FakeSession(requests.ConnectionError("sin red"))
    with pytest.raises(ScraperError, match="No se pudo buscar"):
        search_sakuratips_transcript(92, session=session)


class FakeResponse:
    def __init__(self, text: str, content_type: str = "text/html; charset=UTF-8"):
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_fetch_subtitles_uses_session_and_validates():
    html = (FIXTURES / "54.html").read_text(encoding="utf-8")
    session = FakeSession(FakeResponse(html))
    japanese, english = fetch_subtitles("https://sakuratips.com/x/", session=session)
    assert len(japanese) == len(english) == 25
    assert session.calls[0][0] == "https://sakuratips.com/x/"
    assert "User-Agent" in session.calls[0][1]["headers"]


def test_fetch_subtitles_wraps_network_errors():
    session = FakeSession(requests.ConnectionError("sin red"))
    with pytest.raises(ScraperError, match="No se pudo descargar"):
        fetch_subtitles("https://sakuratips.com/x/", session=session)


def test_fetch_subtitles_rejects_non_html():
    session = FakeSession(FakeResponse("{}", "application/json"))
    with pytest.raises(ScraperError, match="no devolvio HTML"):
        fetch_subtitles("https://sakuratips.com/x/", session=session)
