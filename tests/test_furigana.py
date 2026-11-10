from __future__ import annotations

import pytest

from sakuratips_reader.furigana import (
    FuriganaGenerator,
    convert_to_hiragana,
    generate_furigana,
    render_ruby,
)


def format_bracket(tokens) -> str:
    """Formato de corchetes del addon, para comparar comportamiento."""

    output = ""
    for token in tokens:
        reading = token["reading"]
        if reading is None:
            output += token["text"]
        else:
            if output and not output.endswith("]"):
                output += " "
            output += f"{token['text']}[{reading}]"
    return output


@pytest.fixture(scope="module")
def generator() -> FuriganaGenerator:
    return FuriganaGenerator()


CASES = [
    (
        "カリン、自分でまいた種は自分で刈り取れ",
        "カリン、 自分[じぶん]でまいた 種[たね]は 自分[じぶん]で 刈[か]り 取[と]れ",
    ),
    ("千葉", "千葉[ちば]"),
    (
        "昨日、林檎を2個買った。",
        "昨日[きのう]、 林檎[りんご]を2 個[こ]買[か]った。",
    ),
    ("真莉、大好きだよん＾＾", "真[ま]莉、 大好[だいす]きだよん＾＾"),
    ("ウィキペディア", "ウィキペディア"),
    ("テレビ・ゲームがマシ", "テレビ・ゲームがマシ"),
    ("彼２０００万も使った。", "彼[かれ]２０００ 万[まん]も 使[つか]った。"),
    (
        "彼二千三百六十円も使った。",
        "彼[かれ]二 千[せん]三 百[ひゃく]六十 円[えん]も 使[つか]った。",
    ),
    ("口走る", "口走[くちばし]る"),
    (
        "テスト勉強の息抜きとか　どうしてんの",
        "テスト 勉強[べんきょう]の 息抜[いきぬ]きとか　どうしてんの",
    ),
    ("お前", "お 前[まえ]"),
    ("ローマ字", "ローマ 字[じ]"),
    ("ローマ帝国", "ローマ 帝国[ていこく]"),
    ("みじん切り", "みじん 切[ぎ]り"),
    ("書き込む", "書[か]き 込[こ]む"),
    ("走り抜く", "走[はし]り 抜[ぬ]く"),
    ("走り回る", "走[はし]り 回[まわ]る"),
    (
        "この文に 空白が あります",
        "この 文[ぶん]に  空白[くうはく]が あります",
    ),
    ("hello world", "hello world"),
    (
        "彼はトルコを2ヵ月間訪問するつもりです",
        "彼[かれ]はトルコを2 ヵ[か]月[げつ]間[かん]訪問[ほうもん]するつもりです",
    ),
    (
        "彼はトルコを2ヶ月間訪問するつもりです",
        "彼[かれ]はトルコを2 ヶ[か]月[げつ]間[かん]訪問[ほうもん]するつもりです",
    ),
    ("千駄ヶ谷", "千駄[せんだ]ヶ[が]谷[や]"),
    ("霞ヶ浦", "霞[かすみ]ヶ[が]浦[うら]"),
    ("１ヶ月", "１ ヶ[か]月[げつ]"),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_matches_addon_output(generator: FuriganaGenerator, text: str, expected: str):
    tokens = generator.generate_line(text)
    assert format_bracket(tokens) == expected
    assert "".join(token["text"] for token in tokens) == text


def test_structured_tokens_for_example(generator: FuriganaGenerator):
    tokens = generator.generate_line("化粧についてです。")
    assert tokens[0] == {"text": "化粧", "reading": "けしょう"}
    assert "".join(token["text"] for token in tokens) == "化粧についてです。"


def test_render_ruby(generator: FuriganaGenerator):
    tokens = [
        {"text": "化粧", "reading": "けしょう"},
        {"text": "についてです。"},
    ]
    assert (
        render_ruby(tokens)
        == "<ruby>化粧<rt>けしょう</rt></ruby>についてです。"
    )


def test_convert_to_hiragana_keeps_marks():
    assert convert_to_hiragana("ケショウ・メイクー") == "けしょう・めいくー"


def test_generate_furigana_for_all_lines():
    lines = ["千葉", "こんにちは"]
    result = generate_furigana(lines)
    assert len(result) == 2
    assert result[0][0] == {"text": "千葉", "reading": "ちば"}
    assert "".join(token["text"] for token in result[1]) == "こんにちは"


def test_generator_is_cached():
    first = generate_furigana(["千葉"])
    second = generate_furigana(["千葉"])
    assert first == second
