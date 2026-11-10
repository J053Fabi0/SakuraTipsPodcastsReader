# -*- coding: utf-8 -*-

# Este archivo es parte de SakuraTips Podcasts Reader y adapta el algoritmo de
# Japanese Furigana <https://github.com/obynio/anki-japanese-furigana>.
#
# Japanese Furigana es software libre: puede redistribuirse y/o modificarse bajo
# los terminos de la GNU General Public License publicada por la Free Software
# Foundation, version 3 o posterior.
#
# Japanese Furigana se distribuye con la esperanza de ser util, pero SIN NINGUNA
# GARANTIA. Ver <http://www.gnu.org/licenses/>.
#
# La adaptacion usa mecab-python3 + IPADIC en lugar del binario incluido por el
# complemento de Anki, manteniendo el mismo procedimiento de lectura y division
# kanji/kana.

"""Generacion de Furigana estructurado con MeCab.

La salida es una lista de lineas; cada linea es una lista de tokens
``{"text": str, "reading": str | None}``. El navegador convierte los tokens con
lectura en elementos ``<ruby>``/``<rt>``.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

try:
    import MeCab
except ImportError as exc:  # pragma: no cover - depende del entorno
    MeCab = None  # type: ignore[assignment]
    _MECAB_IMPORT_ERROR = exc
else:
    _MECAB_IMPORT_ERROR = None

try:
    import ipadic
except ImportError as exc:  # pragma: no cover - depende del entorno
    ipadic = None  # type: ignore[assignment]
    _IPADIC_IMPORT_ERROR = exc
else:
    _IPADIC_IMPORT_ERROR = None


# Centinela usado por el addon para distinguir el espacio ASCII de los espacios
# que MeCab inserta entre nodos.
ASCII_SPACE_TOKEN = "\U0000FFFF"

# Valores de ``Node.stat`` de MeCab. El addon fuerza lectura vacia para nodos
# desconocidos mediante ``--unk-format=%m[]``.
MECAB_UNK_NODE = 1

UNICODE_HIRAGANA_START = 0x3041
UNICODE_HIRAGANA_END = 0x309F
UNICODE_KATAKANA_START = 0x30A1
UNICODE_KATAKANA_END = 0x30FF
UNICODE_MIDDLE_DOT = 0x30FB
UNICODE_PROLONGED_SOUND_MARK = 0x30FC


class FuriganaError(Exception):
    """No se pudo inicializar MeCab o generar el Furigana."""


@dataclass(frozen=True)
class _RegexDefinition:
    text: str
    regex_group_index: int | None


def _require_dependencies() -> None:
    if MeCab is None:  # pragma: no cover
        raise FuriganaError(
            "Falta la dependencia mecab-python3. Ejecute: "
            "pip install -r requirements.txt"
        ) from _MECAB_IMPORT_ERROR
    if ipadic is None:  # pragma: no cover
        raise FuriganaError(
            "Falta el diccionario ipadic. Ejecute: pip install -r requirements.txt"
        ) from _IPADIC_IMPORT_ERROR


def convert_to_hiragana(text: str) -> str:
    """Convierte katakana a hiragana, sin tocar ・ ni ー."""

    output: list[str] = []
    for character in text:
        code = ord(character)
        if (
            UNICODE_KATAKANA_START <= code <= UNICODE_KATAKANA_END
            and code not in (UNICODE_MIDDLE_DOT, UNICODE_PROLONGED_SOUND_MARK)
        ):
            output.append(chr(UNICODE_HIRAGANA_START + code - UNICODE_KATAKANA_START))
        else:
            output.append(character)
    return "".join(output)


def _is_kana(character: str) -> bool:
    code = ord(character)
    return (
        UNICODE_HIRAGANA_START <= code <= UNICODE_HIRAGANA_END
        or UNICODE_KATAKANA_START <= code <= UNICODE_KATAKANA_END
    )


def _additional_possible_readings(hiragana: str) -> list[str] | None:
    # ヵ y ヶ pueden leerse como か o が (por ejemplo ヶ月, 千駄ヶ谷).
    if hiragana in ("ゕ", "ゖ"):
        return ["か", "が"]
    return None


def _kanji_to_regex(surface: str) -> tuple[str, list[_RegexDefinition]]:
    pieces: list[str] = []
    definitions: list[_RegexDefinition] = []
    capture_groups = 0
    index = 0

    while index < len(surface):
        if _is_kana(surface[index]):
            hiragana = convert_to_hiragana(surface[index])
            additional = _additional_possible_readings(hiragana)
            if additional:
                pieces.append("(" + "|".join([hiragana, *additional]) + ")")
                definitions.append(_RegexDefinition(surface[index], capture_groups))
                capture_groups += 1
            else:
                pieces.append(hiragana)
                definitions.append(_RegexDefinition(surface[index], None))
            index += 1
            continue

        capture = ""
        while index < len(surface) and not _is_kana(surface[index]):
            capture += surface[index]
            index += 1
        pieces.append("(.+?)")
        definitions.append(_RegexDefinition(capture, capture_groups))
        capture_groups += 1

    return "^" + "".join(pieces) + "$", definitions


def _merge_empty_reading_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for token in tokens:
        if not token["text"]:
            continue
        if (
            merged
            and token["reading"] is None
            and merged[-1]["reading"] is None
        ):
            merged[-1]["text"] += token["text"]
        else:
            merged.append({"text": token["text"], "reading": token["reading"]})
    return merged


class FuriganaGenerator:
    """Genera lecturas con la misma logica que JapaneseFurigana."""

    def __init__(self, dictionary_dir: str | None = None) -> None:
        _require_dependencies()
        self.dictionary_dir = dictionary_dir or ipadic.DICDIR
        self._tagger = None

    def _get_tagger(self):
        if self._tagger is None:
            arguments = (
                f'-r "{os.devnull}" -d "{self.dictionary_dir}"'
            )
            try:
                tagger = MeCab.Tagger(arguments)
                tagger.parse("")
            except Exception as exc:
                raise FuriganaError(
                    "No se pudo inicializar MeCab con el diccionario IPADIC. "
                    f"Detalle: {exc}"
                ) from exc
            self._tagger = tagger
        return self._tagger

    def generate_line(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return [{"text": "", "reading": None}]

        tagger = self._get_tagger()
        escaped = text.replace(" ", ASCII_SPACE_TOKEN)
        try:
            node = tagger.parseToNode(escaped)
        except Exception as exc:
            raise FuriganaError(f"MeCab no pudo analizar la linea: {exc}") from exc

        tokens: list[dict[str, Any]] = []
        while node is not None:
            surface = node.surface
            if surface:
                tokens.extend(self._tokens_for_node(node, surface))
            node = node.next

        tokens = _merge_empty_reading_tokens(tokens)

        for token in tokens:
            token["text"] = token["text"].replace(ASCII_SPACE_TOKEN, " ")

        if "".join(token["text"] for token in tokens) != text:
            # Nunca se debe corromper el texto original. Si una construccion
            # exotica no puede reconstruirse, se conserva sin Furigana.
            return [{"text": text, "reading": None}]

        return tokens

    def _tokens_for_node(self, node, surface: str) -> list[dict[str, Any]]:
        features = node.feature.split(",") if node.feature else []
        reading = features[7] if len(features) > 7 else ""
        reading = "" if reading in ("", "*") else reading

        if node.stat == MECAB_UNK_NODE or not reading:
            return [{"text": surface, "reading": None}]

        hiragana = convert_to_hiragana(reading)
        if hiragana == convert_to_hiragana(surface):
            return [{"text": surface, "reading": None}]

        # El addon ignora los numeros por defecto.
        if surface in "一二三四五六七八九十０１２３４５６７８９":
            return [{"text": surface, "reading": None}]

        pattern, definitions = _kanji_to_regex(surface)
        match = re.search(pattern, hiragana)
        if match is None:
            return [{"text": surface, "reading": None}]

        tokens: list[dict[str, Any]] = []
        for definition in definitions:
            if definition.regex_group_index is None:
                tokens.append({"text": definition.text, "reading": None})
            else:
                group = match.group(definition.regex_group_index + 1)
                tokens.append({"text": definition.text, "reading": group})
        return tokens

    def generate_lines(
        self, lines: Iterable[str]
    ) -> list[list[dict[str, Any]]]:
        return [self.generate_line(line) for line in lines]


@lru_cache(maxsize=1)
def get_generator() -> FuriganaGenerator:
    return FuriganaGenerator()


def generate_furigana(lines: Iterable[str]) -> list[list[dict[str, Any]]]:
    return get_generator().generate_lines(lines)


def render_ruby(tokens: Iterable[dict[str, Any]]) -> str:
    """Representacion HTML de los tokens, usada en pruebas y utilidades."""

    output: list[str] = []
    for token in tokens:
        text = html.escape(token["text"], quote=False)
        reading = token.get("reading")
        if reading:
            output.append(
                f"<ruby>{text}<rt>{html.escape(reading, quote=False)}</rt></ruby>"
            )
        else:
            output.append(text)
    return "".join(output)
