"""Extraccion de subtitulos japoneses e ingleses desde SakuraTips.

Se trabaja siempre sobre el DOM con BeautifulSoup. No se aplican expresiones
regulares al HTML completo; solo se normaliza el texto de cada fragmento.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

JAPANESE_HEADING = "にほんご"
ENGLISH_HEADING = "English"

SAKURATIPS_HOSTS = {"sakuratips.com", "www.sakuratips.com"}
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
NO_TRANSCRIPT_PATTERN = re.compile(r"no\s+transcripts?", re.IGNORECASE)
EPISODE_NUMBER_PATTERN = re.compile(r"#\s*(\d+)")

DEFAULT_TIMEOUT = 30
USER_AGENT = (
    "SakuraTipsPodcastsReader/0.1 (+https://github.com/J053Fabi0/"
    "SakuraTipsPodcastsReader)"
)

_ASCII_WHITESPACE = re.compile(r"[ \t\r\n\f\v\u00a0]+")


class ScraperError(Exception):
    """No se pudo obtener o interpretar la pagina de SakuraTips."""


class SubtitleMismatchError(ScraperError):
    """Las secciones japonesa e inglesa no tienen la misma cantidad de lineas."""

    def __init__(self, japanese_count: int, english_count: int) -> None:
        self.japanese_count = japanese_count
        self.english_count = english_count
        super().__init__(
            "La cantidad de lineas no coincide "
            f"(japones: {japanese_count}, ingles: {english_count})."
        )


def normalize_text(text: str) -> str:
    """Normaliza whitespace ASCII/NBSP preservando el espacio ideografico U+3000."""

    return _ASCII_WHITESPACE.sub(" ", text).strip()


def extract_episode_number(title: str | None) -> int | None:
    """Extrae el numero de episodio de un titulo como ``... #92``."""

    if not title:
        return None
    match = EPISODE_NUMBER_PATTERN.search(title)
    if match is None:
        return None
    return int(match.group(1))


def description_says_no_transcript(description: str) -> bool:
    return bool(NO_TRANSCRIPT_PATTERN.search(description or ""))


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_PATTERN.findall(text or ""):
        cleaned = match.rstrip(".,;:!?)]}'\"")
        if cleaned and cleaned not in urls:
            urls.append(cleaned)
    return urls


def _is_sakuratips_post(url: str) -> bool:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in SAKURATIPS_HOSTS:
        return False
    path = parsed.path.rstrip("/")
    if not path or path in ("/", "/category/pod-cast"):
        return False
    return not any(
        marker in path
        for marker in ("/category/", "/tag/", "/author/", "/feed", "/wp-")
    )


def _matches_episode_number(url: str, episode_number: int) -> bool:
    path = urlparse(url).path.rstrip("/")
    return path.endswith(f"/{episode_number}")


def extract_transcript_url_from_description(
    description: str,
    episode_number: int | None,
) -> str | None:
    """Busca una URL directa de transcripcion en la descripcion del video."""

    if not description or description_says_no_transcript(description):
        return None

    urls = [
        url
        for url in _extract_urls(description)
        if _is_sakuratips_post(url)
    ]
    if not urls:
        return None

    if episode_number is not None:
        for url in urls:
            if _matches_episode_number(url, episode_number):
                return url

    # Si no hay numero en el titulo, se acepta la URL que aparezca en una
    # linea de "Transcript" (la URL puede estar en la linea siguiente).
    lines = description.splitlines()
    for index, line in enumerate(lines):
        if "transcript" not in line.lower():
            continue
        context = "\n".join(lines[index : index + 3])
        for url in _extract_urls(context):
            if _is_sakuratips_post(url):
                return url
    return None


def search_sakuratips_transcript(
    episode_number: int,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str | None:
    """Busca en SakuraTips la entrada cuyo path termina en ``/<numero>``."""

    http = session or requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"}
    try:
        response = http.get(
            "https://sakuratips.com/",
            params={"s": str(episode_number)},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(
            f"No se pudo buscar el episodio {episode_number} en SakuraTips: {exc}"
        ) from exc

    _ensure_html_content_type(response)
    soup = BeautifulSoup(response.content, "html.parser")
    for anchor in soup.find_all("a", href=True):
        url = urljoin("https://sakuratips.com/", anchor["href"])
        if not _is_sakuratips_post(url):
            continue
        if _matches_episode_number(url, episode_number):
            return url
    return None


def _find_article(soup: BeautifulSoup) -> Tag:
    for selector in (
        '[itemprop="articleBody"]',
        ".entry-content",
        "article.cps-post",
        "article",
    ):
        found = soup.select_one(selector)
        if found is not None:
            return found
    raise ScraperError(
        "No se encontro el contenedor del articulo en la pagina de SakuraTips."
    )


def _heading_text(heading: Tag) -> str:
    return heading.get_text(strip=True)


def _headings(article: Tag, text: str) -> list[Tag]:
    return [h2 for h2 in article.find_all("h2") if _heading_text(h2) == text]


def _paragraph_lines(paragraph: Tag) -> list[str]:
    """Divide un parrafo en lineas por cada ``<br>`` y conserva el texto interno."""

    raw_lines: list[str] = []
    current: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, NavigableString):
            current.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        if node.name == "br":
            raw_lines.append("".join(current))
            current.clear()
            return
        for child in node.children:
            walk(child)

    walk(paragraph)
    raw_lines.append("".join(current))

    return [line for line in (normalize_text(raw) for raw in raw_lines) if line]


def _collect_section(
    heading: Tag,
    *,
    stop_at_english: bool,
) -> list[str]:
    lines: list[str] = []

    for sibling in heading.next_siblings:
        if isinstance(sibling, NavigableString):
            continue
        if not isinstance(sibling, Tag):
            continue

        if sibling.name == "h2":
            text = _heading_text(sibling)
            if stop_at_english:
                if text == ENGLISH_HEADING:
                    return lines
                raise ScraperError(
                    "Se encontro un encabezado <h2> inesperado dentro de los "
                    f"subtitulos: {text!r}."
                )
            # La seccion inglesa termina en el siguiente encabezado.
            return lines

        if sibling.name == "p":
            lines.extend(_paragraph_lines(sibling))

    if stop_at_english:
        raise ScraperError(
            f"No se encontro el encabezado <h2>{ENGLISH_HEADING}</h2> despues "
            f"de <h2>{JAPANESE_HEADING}</h2>."
        )
    return lines


def parse_subtitles(html: str | bytes) -> tuple[list[str], list[str]]:
    """Extrae y valida las lineas japonesas e inglesas de un HTML."""

    soup = BeautifulSoup(html, "html.parser")
    article = _find_article(soup)

    japanese_headings = _headings(article, JAPANESE_HEADING)
    english_headings = _headings(article, ENGLISH_HEADING)

    if not japanese_headings:
        raise ScraperError(
            f"No se encontro el encabezado <h2>{JAPANESE_HEADING}</h2>."
        )
    if not english_headings:
        raise ScraperError(
            f"No se encontro el encabezado <h2>{ENGLISH_HEADING}</h2>."
        )

    japanese_heading = japanese_headings[0]
    english_heading = english_headings[0]

    if japanese_heading.sourceline is not None and english_heading.sourceline is not None:
        if english_heading.sourceline <= japanese_heading.sourceline:
            raise ScraperError(
                "El encabezado English aparece antes que el encabezado にほんご."
            )

    japanese = _collect_section(japanese_heading, stop_at_english=True)
    english = _collect_section(english_heading, stop_at_english=False)

    if len(japanese) != len(english):
        raise SubtitleMismatchError(len(japanese), len(english))

    return japanese, english


def _ensure_html_content_type(response: requests.Response) -> None:
    content_type = response.headers.get("Content-Type", "")
    if content_type and "html" not in content_type.lower():
        raise ScraperError(
            "La URL de SakuraTips no devolvio HTML "
            f"(Content-Type: {content_type!r})."
        )


def fetch_subtitles(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[list[str], list[str]]:
    """Descarga la pagina y devuelve los subtitulos validados."""

    http = session or requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"}
    try:
        response = http.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(
            f"No se pudo descargar la pagina de SakuraTips: {exc}"
        ) from exc

    _ensure_html_content_type(response)
    raw_html = getattr(response, "content", None)
    if raw_html is None:
        raw_html = response.text
    return parse_subtitles(raw_html)


def lines_from_html_fragment(html: str) -> tuple[list[str], list[str]]:
    """Alias de ``parse_subtitles`` usado por tests y utilidades."""

    return parse_subtitles(html)
