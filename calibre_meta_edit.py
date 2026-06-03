# Skript pripravi nahled odkazu na Databazi knih a bezpecne zapise metadata do Calibre.

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Sequence


BASE_URL = "https://www.databazeknih.cz"
SEARCH_URL = BASE_URL + "/vyhledavani/knihy?q="
LEGIE_BASE_URL = "https://www.legie.info"
LEGIE_SEARCH_URL = LEGIE_BASE_URL + "/index.php?search_text="
DEFAULT_LIBRARY = r"\\192.168.0.101\data\books"
CALIBREDB_FALLBACK = r"C:\Program Files\Calibre2\calibredb.exe"
USER_AGENT = "calibre-meta-edit/1.0"
MATCHES_PATH = Path("matches.csv")
APPLY_RESULTS_DIR = Path("apply-results")
LEGIE_FALLBACK_REASONS = {"no-candidates", "title-only", "multiple-title-matches", "partial-title", "http-error"}
HTML_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
MATCHES_FIELDS = [
    "book_id",
    "title",
    "authors",
    "status",
    "chosen_url",
    "candidate_urls",
    "confidence",
    "reason",
    "source",
    "work_type",
]
APPLY_RESULTS_FIELDS = ["book_id", "title", "status", "chosen_url", "error"]


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    authors: list[str]
    comment: str = ""


@dataclass(frozen=True)
class Candidate:
    title: str
    text: str
    url: str


@dataclass(frozen=True)
class MatchRow:
    book_id: int
    title: str
    authors: str
    status: str
    chosen_url: str
    candidate_urls: str
    confidence: str
    reason: str
    source: str = "databazeknih"
    work_type: str = ""


@dataclass(frozen=True)
class BookDetailMetadata:
    published_year: str = ""
    publisher: str = ""
    tags: list[str] | None = None
    rating_percent: str = ""
    about_text: str = ""


@dataclass(frozen=True)
class LegieStoryMetadata:
    legie_id: str = ""
    title: str = ""
    author: str = ""
    category: str = ""
    rating_percent: str = ""
    rating_count: str = ""
    original_title: str = ""
    original_publication: str = ""
    czech_publication: str = ""
    about_text: str = ""


@dataclass(frozen=True)
class EditionMetadata:
    published_year: str = ""
    publisher: str = ""
    url: str = ""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ApplyResult:
    book_id: int
    title: str
    status: str
    chosen_url: str
    error: str = ""


def normalize_text(text: str) -> str:
    """Sjednoti text pro porovnani nazvu a autoru."""
    without_series_number = re.sub(r"\(\s*\d+\s*\)", " ", text)
    decomposed = unicodedata.normalize("NFKD", without_series_number)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    normalized_spaces = re.sub(r"\s+", " ", without_marks.lower())
    return normalized_spaces.strip()


def metadata_db_path(library: str | Path) -> Path:
    return Path(library) / "metadata.db"


def build_sqlite_readonly_uri(library: str | Path) -> str:
    """Vytvori SQLite URI pro read-only otevreni databaze."""
    raw_path = str(metadata_db_path(library)).replace("\\", "/")
    quoted_path = urllib.parse.quote(raw_path, safe="/:")
    if raw_path.startswith("//"):
        return "file://" + quoted_path + "?mode=ro"
    return "file:///" + quoted_path + "?mode=ro"


def databaze_absolute_url(url: str) -> str:
    """Prevede relativni odkaz z Databaze knih na cistou absolutni URL."""
    clean = url.strip().split("#", 1)[0].split("?", 1)[0]
    if clean.startswith("/"):
        clean = BASE_URL + clean
    return clean.replace("http://www.databazeknih.cz/", "https://www.databazeknih.cz/", 1)


def overview_to_book_url(url: str) -> str:
    clean = databaze_absolute_url(url)
    return clean.replace(BASE_URL + "/prehled-knihy/", BASE_URL + "/knihy/", 1)


def book_url_to_overview_url(url: str) -> str:
    clean = databaze_absolute_url(url)
    return clean.replace(BASE_URL + "/knihy/", BASE_URL + "/prehled-knihy/", 1)


def build_search_url(title: str, authors: Sequence[str]) -> str:
    query = title + " " + " ".join(authors)
    return SEARCH_URL + urllib.parse.quote_plus(query.strip())


def legie_absolute_url(url: str) -> str:
    """Prevede Legie odkaz na cistou absolutni URL bez parametru."""
    clean = url.strip().split("#", 1)[0].split("?", 1)[0]
    if clean.startswith("//www.legie.info/"):
        clean = "https:" + clean
    elif clean.startswith("/"):
        clean = LEGIE_BASE_URL + "/" + clean.lstrip("/")
    if clean.startswith(("povidka/", "kniha/", "autor/")):
        clean = LEGIE_BASE_URL + "/" + clean
    clean = clean.replace("http://www.legie.info/", "https://www.legie.info/", 1)
    return re.sub(r"^https://www\.legie\.info/+", LEGIE_BASE_URL + "/", clean)


def legie_id_from_url(url: str) -> str:
    match = re.search(r"/povidka/(\d+)", legie_absolute_url(url))
    return match.group(1) if match else ""


def format_link_html(url: str) -> str:
    return f'<div>\n<p><a href="{url}" target="_blank"><span style="color: #6cb4ee">{url}</span></a></p></div>'


def format_enriched_comment(url: str, detail: BookDetailMetadata) -> str:
    """Vytvori novy Calibre komentar: odkaz, hodnoceni a text O knize."""
    safe_url = html.escape(url, quote=True)
    parts = [
        "<div>",
        f'<p><a href="{safe_url}" target="_blank"><span style="color: #6cb4ee">{safe_url}</span></a></p>',
    ]
    if detail.rating_percent:
        parts.append(f"<p><strong>{html.escape(detail.rating_percent)}</strong></p>")
    if detail.about_text:
        parts.append(f"<p>{html.escape(detail.about_text)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def add_target_blank_to_databaze_links(comment: str | None) -> str:
    """Doplni target blank jen k existujicim odkazum na Databazi knih."""
    text = comment or ""

    def repair_anchor(match: re.Match[str]) -> str:
        tag = match.group(0)
        href = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE)
        if href is None or "databazeknih.cz" not in href.group(2).lower():
            return tag
        if re.search(r"\btarget\s*=", tag, flags=re.IGNORECASE):
            return tag
        return tag[:-1] + ' target="_blank">'

    return re.sub(r"<a\b[^>]*>", repair_anchor, text, flags=re.IGNORECASE)


def comment_has_databaze_link(comment: str | None) -> bool:
    return "databazeknih.cz" in (comment or "").lower()


class _FirstDatabazeLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.url or tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value and "databazeknih.cz" in value:
                self.url = value
                return


def extract_first_databaze_link(comment: str | None) -> str:
    parser = _FirstDatabazeLinkParser()
    parser.feed(comment or "")
    if parser.url:
        return parser.url
    match = re.search(r"https?://www\.databazeknih\.cz/\S+", comment or "")
    return match.group(0).rstrip('">)') if match else ""


def build_new_comment(url: str, current_comment: str | None) -> str:
    link_html = format_link_html(url)
    current = (current_comment or "").lstrip()
    if not current:
        return link_html
    return link_html + "\n" + current


class DatabazeSearchParser(HTMLParser):
    """Jednoduchy parser vysledku hledani. Kdyz HTML zmeni tvar, vrati mene kandidatu."""

    def __init__(self) -> None:
        super().__init__()
        self._current: dict[str, object] | None = None
        self._inside_book_anchor = False
        self.candidates: list[Candidate] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        href = attrs_dict.get("href", "")
        if tag.lower() == "a" and ("/prehled-knihy/" in href or "/povidky/" in href):
            self._finish_current()
            url = databaze_absolute_url(href) if "/povidky/" in href else overview_to_book_url(href)
            self._current = {
                "url": url,
                "title": "",
                "parts": [],
                "anchor_parts": [],
            }
            self._inside_book_anchor = True
            return
        if tag.lower() == "img" and self._current is not None and self._inside_book_anchor:
            title = attrs_dict.get("title") or attrs_dict.get("alt", "").replace("Obálka knihy ", "")
            if title:
                self._current["title"] = title.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._inside_book_anchor:
            self._inside_book_anchor = False

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = data.strip()
        if text:
            parts = self._current["parts"]
            assert isinstance(parts, list)
            parts.append(text)
            if self._inside_book_anchor:
                anchor_parts = self._current["anchor_parts"]
                assert isinstance(anchor_parts, list)
                anchor_parts.append(text)

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        title = str(self._current.get("title") or "").strip()
        url = str(self._current.get("url") or "").strip()
        parts = self._current.get("parts") or []
        anchor_parts = self._current.get("anchor_parts") or []
        if not title:
            title = _clean_text(" ".join(str(part) for part in anchor_parts))
        text = " ".join(str(part) for part in parts)
        if url:
            self.candidates.append(Candidate(title, text, url))
        self._current = None
        self._inside_book_anchor = False


def parse_search_results(html: str) -> list[Candidate]:
    parser = DatabazeSearchParser()
    parser.feed(html)
    parser.close()
    return parser.candidates


def build_legie_search_url(title: str, authors: Sequence[str]) -> str:
    query = title + " " + " ".join(authors)
    return LEGIE_SEARCH_URL + urllib.parse.quote_plus(query.strip())


def short_legie_title_query(title: str, max_words: int = 4) -> str:
    """Zkrati dlouhy nazev pro Legii, kdyz plny dotaz nic nevrati."""
    words = [part.strip(" ,;:.!?()[]\"'") for part in title.split()]
    words = [word for word in words if word]
    if len(words) <= max_words:
        return ""
    return " ".join(words[:max_words])


class LegieSearchParser(HTMLParser):
    """Parser vysledku hledani na Legii pro odkazy na povidky."""

    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[Candidate] = []
        self._current: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        href = attrs_dict.get("href", "")
        if tag.lower() == "a" and "povidka/" in href:
            self._finish_current()
            self._current = {"url": legie_absolute_url(href), "parts": []}

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._current is not None:
            parts = self._current["parts"]
            assert isinstance(parts, list)
            parts.append(text)
        elif self.candidates:
            last = self.candidates.pop()
            joined_text = _clean_text(last.text + " " + text)
            self.candidates.append(Candidate(last.title, joined_text, last.url))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._finish_current()

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        parts = [str(part) for part in self._current.get("parts", [])]
        title = _clean_text(parts[0]) if parts else ""
        text = _clean_text(" ".join(parts))
        url = str(self._current.get("url") or "")
        if title and url:
            self.candidates.append(Candidate(title, text, url))
        self._current = None


def parse_legie_search_results(html_text: str) -> list[Candidate]:
    detail = parse_legie_story_detail(html_text, _legie_story_url_from_detail_html(html_text))
    if detail.title and detail.legie_id:
        text = _clean_text(" ".join(part for part in (detail.title, detail.author) if part))
        return [Candidate(detail.title, text, LEGIE_BASE_URL + "/povidka/" + detail.legie_id)]

    parser = LegieSearchParser()
    parser.feed(html_text)
    parser.close()
    return parser.candidates


def _legie_story_url_from_detail_html(html_text: str) -> str:
    """Najde ID povidky v HTML detailu nebo zalozek Legie."""
    match = re.search(r'\bdata-kasp-id=["\'](\d+)["\']\s+data-kasp=["\']p["\']', html_text)
    if match:
        return LEGIE_BASE_URL + "/povidka/" + match.group(1)
    match = re.search(r'["\'](?:https?://www\.legie\.info/)?povidka/(\d+)(?:/[^"\']*)?["\']', html_text)
    return LEGIE_BASE_URL + "/povidka/" + match.group(1) if match else ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class BookDetailParser(HTMLParser):
    """Parser detailu knihy. JSON-LD bere pro metadata, HTML pro plny text O knize."""

    def __init__(self) -> None:
        super().__init__()
        self.json_ld_blocks: list[str] = []
        self.rating_percent = ""
        self.about_text = ""
        self.publication_info = ""
        self.editions_url = ""
        self.user_tags: list[str] = []

        self._json_parts: list[str] = []
        self._inside_json_ld = False
        self._rating_parts: list[str] = []
        self._rating_depth = 0
        self._h2_parts: list[str] = []
        self._inside_h2 = False
        self._about_heading_seen = False
        self._about_parts: list[str] = []
        self._about_depth = 0
        self._skip_depth = 0
        self._tag_parts: list[str] = []
        self._inside_user_tag = False
        self._publication_parts: list[str] = []
        self._publication_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        lowered_tag = tag.lower()
        href = attrs_dict.get("href", "")

        if lowered_tag == "script" and attrs_dict.get("type", "").lower() == "application/ld+json":
            self._inside_json_ld = True
            self._json_parts = []
            return

        if not self.editions_url and "/dalsi-vydani/" in href:
            self.editions_url = databaze_absolute_url(href)

        if "ratValue" in classes:
            self._rating_depth = 1
            self._rating_parts = []
            return
        if self._rating_depth:
            self._rating_depth += 1

        if lowered_tag == "h2":
            self._inside_h2 = True
            self._h2_parts = []

        if lowered_tag == "div" and {"lora", "lineHeightMid"}.issubset(classes):
            self._publication_depth = 1
            self._publication_parts = []
            return
        if self._publication_depth:
            self._publication_depth += 1

        if self._about_heading_seen and lowered_tag == "p" and not self.about_text:
            self._about_depth = 1
            self._about_parts = []
            self._about_heading_seen = False
            return
        if self._about_depth:
            self._about_depth += 1
            if lowered_tag == "a" and "show_hide_more" in classes:
                self._skip_depth = 1
                return
        if self._skip_depth:
            self._skip_depth += 1

        if lowered_tag == "a" and "tag" in classes:
            self._inside_user_tag = True
            self._tag_parts = []

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()

        if lowered_tag == "script" and self._inside_json_ld:
            self.json_ld_blocks.append("".join(self._json_parts))
            self._inside_json_ld = False
            self._json_parts = []
            return

        if self._rating_depth:
            self._rating_depth -= 1
            if self._rating_depth == 0:
                self.rating_percent = _clean_text(" ".join(self._rating_parts))

        if lowered_tag == "h2" and self._inside_h2:
            if "O knize" in _clean_text(" ".join(self._h2_parts)):
                self._about_heading_seen = True
            self._inside_h2 = False

        if self._publication_depth:
            self._publication_depth -= 1
            if self._publication_depth == 0:
                self.publication_info = _clean_text(" ".join(self._publication_parts))

        if self._skip_depth:
            self._skip_depth -= 1

        if self._about_depth:
            self._about_depth -= 1
            if self._about_depth == 0:
                self.about_text = _clean_text(" ".join(self._about_parts))

        if lowered_tag == "a" and self._inside_user_tag:
            tag_text = _clean_text(" ".join(self._tag_parts))
            if tag_text:
                self.user_tags.append(tag_text)
            self._inside_user_tag = False

    def handle_data(self, data: str) -> None:
        if self._inside_json_ld:
            self._json_parts.append(data)
        if self._rating_depth:
            self._rating_parts.append(data)
        if self._inside_h2:
            self._h2_parts.append(data)
        if self._publication_depth:
            self._publication_parts.append(data)
        if self._about_depth and not self._skip_depth:
            self._about_parts.append(data)
        if self._inside_user_tag:
            self._tag_parts.append(data)


class EditionListParser(HTMLParser):
    """Parser seznamu vydani. Rok staci, vydavatel na webu nekdy chybi."""

    def __init__(self) -> None:
        super().__init__()
        self.editions: list[EditionMetadata] = []
        self._last_overview_url = ""
        self._block_url = ""
        self._block_parts: list[str] = []
        self._block_depth = 0
        self._block_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        lowered_tag = tag.lower()
        href = attrs_dict.get("href", "")

        if self._block_depth and self._block_tag == "p" and lowered_tag in {"div", "hr"}:
            self._finish_block()

        if lowered_tag == "a" and "/prehled-knihy/" in href:
            self._last_overview_url = databaze_absolute_url(href)

        if self._block_depth:
            if lowered_tag not in HTML_VOID_TAGS:
                self._block_depth += 1
            return

        is_current_publication = lowered_tag == "div" and {"lora", "lineHeightMid"}.issubset(classes)
        is_edition_publication = lowered_tag == "p" and {"new", "odtopm"}.issubset(classes)
        if is_current_publication or is_edition_publication:
            self._block_depth = 1
            self._block_tag = lowered_tag
            self._block_url = self._last_overview_url if is_edition_publication else ""
            self._block_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in HTML_VOID_TAGS:
            return
        if not self._block_depth:
            return
        self._block_depth -= 1
        if self._block_depth:
            return
        self._finish_block()

    def _finish_block(self) -> None:
        edition = _publication_metadata_from_text(" ".join(self._block_parts), self._block_url)
        if edition.published_year:
            self.editions.append(edition)
        self._block_depth = 0
        self._block_tag = ""
        self._block_url = ""
        self._block_parts = []

    def handle_data(self, data: str) -> None:
        if self._block_depth:
            self._block_parts.append(data)


def _json_type_is_book(value: object) -> bool:
    if isinstance(value, str):
        return value == "Book"
    if isinstance(value, list):
        return "Book" in value
    return False


def _iter_json_dicts(value: object) -> Iterable[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if isinstance(item, dict):
                    yield item
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield from _iter_json_dicts(item)


def _book_json_from_blocks(blocks: Sequence[str]) -> dict[str, object]:
    for block in blocks:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in _iter_json_dicts(parsed):
            if _json_type_is_book(item.get("@type")):
                return item
    return {}


def _publisher_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        name = value.get("name")
        return name.strip() if isinstance(name, str) else ""
    if isinstance(value, list):
        for item in value:
            name = _publisher_name(item)
            if name:
                return name
    return ""


def _genre_tags(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _rating_from_json(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    try:
        rating_value = float(str(value.get("ratingValue", "")).replace(",", "."))
        best_rating = float(str(value.get("bestRating", "5")).replace(",", "."))
    except ValueError:
        return ""
    if best_rating <= 0:
        return ""
    return f"{round(rating_value / best_rating * 100)} %"


def _first_reasonable_year(text: str) -> str:
    for match in re.finditer(r"\b(1\d{3}|20\d{2})\b", text):
        return match.group(1)
    return ""


def _publication_metadata_from_text(text: str, url: str = "") -> EditionMetadata:
    match = re.search(r"\b(1\d{3}|20\d{2})\b", text)
    if match is None:
        return EditionMetadata()
    tail = text[match.end():]
    tail = re.split(r"\bISBN\b|Koupit|V\S* info", tail, maxsplit=1, flags=re.IGNORECASE)[0]
    tail = re.sub(r"\s*,\s*", ", ", tail)
    publisher = _clean_text(tail).strip(" ,")
    return EditionMetadata(match.group(1), publisher, url)


def _dedupe_tags(tags: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        cleaned = _clean_text(tag)
        key = normalize_text(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def extract_editions_url(html_text: str) -> str:
    parser = BookDetailParser()
    parser.feed(html_text)
    parser.close()
    return parser.editions_url


def parse_oldest_edition_metadata(html_text: str) -> EditionMetadata:
    parser = EditionListParser()
    parser.feed(html_text)
    parser.close()
    if not parser.editions:
        return EditionMetadata()
    return min(parser.editions, key=lambda edition: int(edition.published_year))


def parse_book_detail_metadata(html_text: str) -> BookDetailMetadata:
    parser = BookDetailParser()
    parser.feed(html_text)
    parser.close()

    book_json = _book_json_from_blocks(parser.json_ld_blocks)
    published = str(book_json.get("datePublished", ""))
    published_year = _first_reasonable_year(parser.publication_info) or _first_reasonable_year(published)
    description = book_json.get("description", "")
    about_text = parser.about_text or (_clean_text(description) if isinstance(description, str) else "")
    rating = parser.rating_percent or _rating_from_json(book_json.get("aggregateRating"))
    tags = _dedupe_tags(_genre_tags(book_json.get("genre")) + parser.user_tags)

    return BookDetailMetadata(
        published_year=published_year,
        publisher=_publisher_name(book_json.get("publisher")),
        tags=tags,
        rating_percent=rating,
        about_text=about_text,
    )


class LegieStoryParser(HTMLParser):
    """Parser detailu povidky na Legii."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.author = ""
        self.category = ""
        self.rating_percent = ""
        self.rating_count = ""
        self.original_title = ""
        self.original_publication = ""
        self.czech_publication = ""
        self.about_text = ""

        self._capture = ""
        self._parts: list[str] = []
        self._author_next = False
        self._inside_rating_value = False
        self._inside_rating_count = False
        self._inside_publications = False
        self._inside_about = False
        self._about_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        lowered_tag = tag.lower()
        element_id = attrs_dict.get("id", "")
        itemprop = attrs_dict.get("itemprop", "")

        if lowered_tag == "h3":
            self._author_next = True
        if lowered_tag == "h2" and element_id == "nazev_povidky":
            self._capture = "title"
            self._parts = []
        if lowered_tag == "p" and element_id == "jine_nazvy":
            self._capture = "other_names"
            self._parts = []
        if lowered_tag == "div" and element_id == "zarazena_do_knih":
            self._inside_publications = True
        if lowered_tag == "div" and element_id == "anotace":
            self._inside_about = True
            self._about_depth = 1
            self._parts = []
        elif self._inside_about and lowered_tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self._about_depth += 1
        if itemprop == "ratingValue":
            self._inside_rating_value = True
        if itemprop == "ratingCount":
            self._inside_rating_count = True

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        is_void_tag = lowered_tag in {"br", "hr", "img", "input", "meta", "link"}
        if self._capture == "title" and lowered_tag == "h2":
            self.title = _clean_text(" ".join(self._parts))
            self._capture = ""
        if self._capture == "other_names" and lowered_tag == "p":
            text = _clean_text(" ".join(self._parts))
            original = re.search(r"originální název:\s*(.*?)(?:\s*originál vyšel:|$)", text, flags=re.IGNORECASE)
            published = re.search(r"originál vyšel:\s*(.*)$", text, flags=re.IGNORECASE)
            self.original_title = original.group(1).strip() if original else ""
            self.original_publication = published.group(1).strip() if published else ""
            self._capture = ""
        if self._inside_publications and lowered_tag == "div":
            self._inside_publications = False
        if self._inside_about and not is_void_tag:
            self._about_depth -= 1
            if self._about_depth == 0:
                self.about_text = _clean_text(" ".join(self._parts))
                self._inside_about = False
        if self._inside_rating_value and lowered_tag == "span":
            self._inside_rating_value = False
        if self._inside_rating_count and lowered_tag == "span":
            self._inside_rating_count = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._author_next:
            self.author = text
            self._author_next = False
        if text.startswith("Kategorie:"):
            self.category = _clean_text(text.replace("Kategorie:", "", 1))
        if self._capture:
            self._parts.append(text)
        if self._inside_rating_value:
            self.rating_percent = _clean_text(text) + " %"
        if self._inside_rating_count:
            self.rating_count = _clean_text(text)
        if self._inside_publications and text != "Nachází se v těchto knihách:":
            self.czech_publication = text
        if self._inside_about:
            self._parts.append(text)


def parse_legie_story_detail(html_text: str, url: str) -> LegieStoryMetadata:
    parser = LegieStoryParser()
    parser.feed(html_text)
    parser.close()
    return LegieStoryMetadata(
        legie_id=legie_id_from_url(url),
        title=parser.title,
        author=parser.author,
        category=parser.category,
        rating_percent=parser.rating_percent,
        rating_count=parser.rating_count,
        original_title=parser.original_title,
        original_publication=parser.original_publication,
        czech_publication=parser.czech_publication,
        about_text=parser.about_text,
    )


def _candidate_urls(candidates: Sequence[Candidate]) -> str:
    urls = [candidate.url for candidate in candidates[:5]]
    return "|".join(urls)


def _titles_close(left: str, right: str) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if left_norm == right_norm or left_norm in right_norm or right_norm in left_norm:
        return True

    left_tokens = {token for token in left_norm.split() if len(token) > 2}
    right_tokens = {token for token in right_norm.split() if len(token) > 2}
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) >= 4 and len(overlap) / max(len(left_tokens), len(right_tokens)) >= 0.75


def _meaningful_partial_title_match(left: str, right: str) -> bool:
    """Vrati true jen pro opravdu blizky castecny nazev, ne pro jedno spolecne slovo."""
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm or left_norm == right_norm:
        return False

    left_tokens = {token for token in left_norm.split() if len(token) > 2}
    right_tokens = {token for token in right_norm.split() if len(token) > 2}
    if left_norm in right_norm or right_norm in left_norm:
        shorter_tokens = left_tokens if len(left_norm) <= len(right_norm) else right_tokens
        return len(shorter_tokens) >= 2

    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) >= 4 and len(overlap) / max(len(left_tokens), len(right_tokens)) >= 0.75


def _title_prefix_match(left: str, right: str) -> bool:
    """Povoli kratky nazev jako zacatek delsiho nazvu, treba Sapiens: podtitul."""
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm or left_norm == right_norm:
        return False
    if not right_norm.startswith(left_norm):
        return False
    return len(right_norm) > len(left_norm) and not right_norm[len(left_norm)].isalnum()


def _name_tokens(value: str) -> set[str]:
    """Rozbije jmeno na slova bez ohledu na carky a poradi."""
    return {token for token in re.findall(r"[a-z0-9]+", normalize_text(value)) if len(token) > 1}


def _author_matches_text(author: str, text: str) -> bool:
    """Porovna autora i kdyz web pise prijmeni pred jmenem."""
    author_tokens = _name_tokens(author)
    if not author_tokens:
        return False
    return author_tokens <= _name_tokens(text)


def match_legie_story(book: Book, candidates: Sequence[Candidate]) -> MatchRow | None:
    authors_text = " & ".join(book.authors)
    for candidate in candidates:
        if not _titles_close(book.title, candidate.title):
            continue
        if not any(_author_matches_text(author, candidate.text) for author in book.authors):
            continue
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "exact-title-author",
            "legie-story-candidate",
            "legie",
            "povidka",
        )
    return None


def find_legie_story(
    book: Book,
    fetcher: Callable[[str], str],
    sleeper: Callable[[float], None] = time.sleep,
    sleep_seconds: float = 1.0,
) -> MatchRow | None:
    """Hleda povidku na Legii: plny dotaz, pak kratsi zacatek nazvu."""
    searches: list[tuple[str, Sequence[str]]] = [(book.title, book.authors)]
    if book.authors:
        searches.append((book.title, []))
    short_title = short_legie_title_query(book.title)
    if short_title:
        searches.append((short_title, []))

    seen_urls: set[str] = set()
    for title, authors in searches:
        url = build_legie_search_url(title, authors)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sleeper(sleep_seconds)
        try:
            legie_html = fetcher(url)
            legie_row = match_legie_story(book, parse_legie_search_results(legie_html))
        except Exception:
            legie_row = None
        if legie_row is not None:
            return legie_row
    return None


def should_try_legie(row: MatchRow) -> bool:
    if row.source == "legie":
        return False
    if row.status == "approve" and row.reason == "exact-title-author":
        return False
    return row.reason in LEGIE_FALLBACK_REASONS


def source_and_work_type_for_url(url: str) -> tuple[str, str]:
    """Urci zdroj a typ prace podle odkazu z vyhledavani."""
    if is_valid_legie_story_url(url):
        return "legie", "povidka"
    if is_valid_databaze_story_url(url):
        return "databazeknih", "povidka"
    return "databazeknih", ""


def match_book(book: Book, candidates: Sequence[Candidate]) -> MatchRow:
    authors_text = " & ".join(book.authors)
    if comment_has_databaze_link(book.comment):
        url = extract_first_databaze_link(book.comment)
        source, work_type = source_and_work_type_for_url(url)
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "skip",
            url,
            "",
            "none",
            "already-linked",
            source,
            work_type,
        )

    if not candidates:
        return MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "no-candidates")

    normalized_title = normalize_text(book.title)
    title_matches = [candidate for candidate in candidates if normalize_text(candidate.title) == normalized_title]
    exact_author_matches = [
        candidate
        for candidate in title_matches
        if any(_author_matches_text(author, candidate.text) for author in book.authors)
    ]

    if len(exact_author_matches) == 1 and len(title_matches) == 1:
        candidate = exact_author_matches[0]
        source, work_type = source_and_work_type_for_url(candidate.url)
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "approve",
            candidate.url,
            _candidate_urls(candidates),
            "exact-title-author",
            "exact-title-author",
            source,
            work_type,
        )
    if len(exact_author_matches) > 1 or len(title_matches) > 1:
        chosen = title_matches[0] if title_matches else exact_author_matches[0]
        source, work_type = source_and_work_type_for_url(chosen.url)
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            chosen.url,
            _candidate_urls(candidates),
            "multiple-title-matches",
            "multiple-title-matches",
            source,
            work_type,
        )
    if len(title_matches) == 1:
        candidate = title_matches[0]
        source, work_type = source_and_work_type_for_url(candidate.url)
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "title-only",
            "title-only",
            source,
            work_type,
        )

    title_prefix_author_matches = [
        candidate
        for candidate in candidates
        if _title_prefix_match(book.title, candidate.title)
        and any(_author_matches_text(author, candidate.text) for author in book.authors)
    ]
    if len(title_prefix_author_matches) == 1:
        candidate = title_prefix_author_matches[0]
        source, work_type = source_and_work_type_for_url(candidate.url)
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "title-prefix-author",
            "title-prefix-author",
            source,
            work_type,
        )

    partial_matches = [
        candidate
        for candidate in candidates
        if _meaningful_partial_title_match(book.title, candidate.title)
    ]
    if partial_matches:
        candidate = partial_matches[0]
        source, work_type = source_and_work_type_for_url(candidate.url)
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "partial-title",
            "partial-title",
            source,
            work_type,
        )

    return MatchRow(book.id, book.title, authors_text, "skip", "", _candidate_urls(candidates), "none", "no-candidates")


def write_matches_csv(path: Path, rows: Iterable[MatchRow], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATCHES_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def read_matches_csv(path: Path) -> list[MatchRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for raw in reader:
            rows.append(
                MatchRow(
                    int(raw["book_id"]),
                    raw["title"],
                    raw["authors"],
                    raw["status"],
                    raw["chosen_url"],
                    raw["candidate_urls"],
                    raw["confidence"],
                    raw["reason"],
                    raw.get("source") or "databazeknih",
                    raw.get("work_type") or "",
                )
            )
    return rows


def create_backup(library: str | Path, backups_dir: Path, timestamp: str | None = None) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    source = metadata_db_path(library)
    target = backups_dir / f"metadata-{stamp}.db"
    shutil.copy2(source, target)
    return target


def restore_metadata_backup(
    library: str | Path,
    backup_path: str | Path,
    backups_dir: Path,
    timestamp: str | None = None,
) -> Path:
    """Obnovi metadata.db ze zalohy a nejdriv ulozi aktualni stav jako nouzovou zalohu."""
    source = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(source)

    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    current_db = metadata_db_path(library)
    safety_backup = backups_dir / f"metadata-before-restore-{stamp}.db"
    shutil.copy2(current_db, safety_backup)
    shutil.copy2(source, current_db)
    return safety_backup


def backup_matches_csv(matches_path: Path, backups_dir: Path, timestamp: str | None = None) -> Path | None:
    """Zkopiruje stary matches.csv pred rebuildem, aby slo vratit rucni upravy."""
    if not matches_path.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"{matches_path.stem}-{stamp}{matches_path.suffix}"
    shutil.copy2(matches_path, target)
    return target


def find_sqlite_sidecars(library: str | Path) -> list[Path]:
    base = metadata_db_path(library)
    return [Path(str(base) + suffix) for suffix in ("-wal", "-shm", "-journal") if Path(str(base) + suffix).exists()]


def find_calibredb(
    which_func: Callable[[str], str | None] = shutil.which,
    exists_func: Callable[[str], bool] | None = None,
) -> str | None:
    found = which_func("calibredb")
    if found:
        return found
    exists = exists_func or (lambda path: Path(path).exists())
    return CALIBREDB_FALLBACK if exists(CALIBREDB_FALLBACK) else None


def select_books(
    books: Sequence[Book],
    book_id: int | None = None,
    limit: int | None = None,
    book_ids: set[int] | list[int] | tuple[int, ...] | None = None,
) -> list[Book]:
    if book_id is not None:
        return [book for book in books if book.id == book_id]
    if book_ids is not None:
        selected_ids = set(book_ids)
        return [book for book in books if book.id in selected_ids]
    selected = list(books)
    return selected[:limit] if limit is not None else selected


def select_match_rows(
    rows: Sequence[MatchRow],
    book_id: int | None = None,
    limit: int | None = None,
    book_ids: set[int] | list[int] | tuple[int, ...] | None = None,
) -> list[MatchRow]:
    if book_id is not None:
        return [row for row in rows if row.book_id == book_id]
    if book_ids is not None:
        selected_ids = set(book_ids)
        return [row for row in rows if row.book_id in selected_ids]
    selected = list(rows)
    return selected[:limit] if limit is not None else selected


def filter_new_books(books: Sequence[Book], existing_rows: Sequence[MatchRow]) -> list[Book]:
    """Vrati jen knihy, ktere jeste nejsou ulozene v matches.csv."""
    existing_book_ids = {row.book_id for row in existing_rows}
    return [book for book in books if book.id not in existing_book_ids]


def replace_match_rows(existing_rows: Sequence[MatchRow], refreshed_rows: Sequence[MatchRow]) -> list[MatchRow]:
    """Nahradi v CSV jen znovu nactene radky a ostatni necha beze zmeny."""
    replacements = {row.book_id: row for row in refreshed_rows}
    replaced_ids: set[int] = set()
    merged: list[MatchRow] = []
    for row in existing_rows:
        replacement = replacements.get(row.book_id)
        if replacement is None:
            merged.append(row)
            continue
        merged.append(replacement)
        replaced_ids.add(row.book_id)
    merged.extend(row for row in refreshed_rows if row.book_id not in replaced_ids)
    return merged


def is_valid_apply_url(url: str) -> bool:
    clean = databaze_absolute_url(url)
    return clean.startswith(BASE_URL + "/knihy/") or clean.startswith(BASE_URL + "/prehled-knihy/")


def is_valid_databaze_story_url(url: str) -> bool:
    return databaze_absolute_url(url).startswith(BASE_URL + "/povidky/")


def is_valid_legie_story_url(url: str) -> bool:
    return legie_absolute_url(url).startswith(LEGIE_BASE_URL + "/povidka/")


def is_manual_external_url(row: MatchRow) -> bool:
    """Pozna rucni odkaz mimo podporovane zdroje, ktery se ma zapsat jen jako link."""
    clean = row.chosen_url.strip().lower()
    return row.reason == "manual" and clean.startswith(("http://", "https://"))


def is_writable_match_row(row: MatchRow) -> bool:
    if row.status != "approve":
        return False
    if not row.chosen_url.strip():
        return True
    if row.source == "legie" or is_valid_legie_story_url(row.chosen_url):
        return is_valid_legie_story_url(row.chosen_url)
    return is_valid_apply_url(row.chosen_url) or is_valid_databaze_story_url(row.chosen_url) or is_manual_external_url(row)


def calibre_pubdate_value(year: str) -> str:
    """Calibre z hodnoty ROK-00-00 ulozi realne datum ROK-01-01."""
    return f"{year}-00-00"


def open_calibre_db_readonly(library: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(build_sqlite_readonly_uri(library), uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def read_books(library: str | Path, book_id: int | None = None, limit: int | None = None) -> list[Book]:
    query = """
        select b.id, b.title, coalesce(c.text, '') as comment, group_concat(a.name, ' & ') as authors
        from books b
        left join comments c on c.book = b.id
        left join books_authors_link bal on bal.book = b.id
        left join authors a on a.id = bal.author
    """
    params: list[object] = []
    if book_id is not None:
        query += " where b.id = ?"
        params.append(book_id)
    query += " group by b.id order by b.id"
    if book_id is None and limit is not None:
        query += " limit ?"
        params.append(limit)

    connection = open_calibre_db_readonly(library)
    try:
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    books = []
    for row in rows:
        authors = [author.strip() for author in (row["authors"] or "").split(" & ") if author.strip()]
        books.append(Book(int(row["id"]), row["title"], authors, row["comment"] or ""))
    return books


def get_current_comment(library: str | Path, book_id: int) -> str:
    connection = open_calibre_db_readonly(library)
    try:
        row = connection.execute("select text from comments where book = ?", (book_id,)).fetchone()
    finally:
        connection.close()
    return "" if row is None else row["text"] or ""


def get_current_identifiers(library: str | Path, book_id: int) -> dict[str, str]:
    connection = open_calibre_db_readonly(library)
    try:
        rows = connection.execute("select type, val from identifiers where book = ?", (book_id,)).fetchall()
    finally:
        connection.close()
    return {row["type"]: row["val"] for row in rows}


def get_current_tags(library: str | Path, book_id: int) -> list[str]:
    connection = open_calibre_db_readonly(library)
    try:
        rows = connection.execute(
            """
            select t.name
            from tags t
            join books_tags_link btl on btl.tag = t.id
            where btl.book = ?
            order by t.name
            """,
            (book_id,),
        ).fetchall()
    finally:
        connection.close()
    return [row["name"] for row in rows]


def format_legie_comment(url: str, detail: LegieStoryMetadata) -> str:
    """Vytvori Calibre komentar pro povidku z Legie."""
    safe_url = html.escape(url, quote=True)
    parts = [
        "<div>",
        f'<p><a href="{safe_url}" target="_blank"><span style="color: #6cb4ee">{safe_url}</span></a></p>',
    ]
    if detail.rating_percent:
        rating = html.escape(detail.rating_percent)
        if detail.rating_count:
            rating += f" ({html.escape(detail.rating_count)} hodnoceni)"
        parts.append(f"<p><strong>{rating}</strong></p>")
    facts = []
    if detail.original_title:
        facts.append(f"Originalni nazev: {detail.original_title}")
    if detail.original_publication:
        facts.append(f"Originalne vyslo: {detail.original_publication}")
    if detail.czech_publication:
        facts.append(f"Cesky vyslo: {detail.czech_publication}")
    if facts:
        parts.append("<p>" + "<br />".join(html.escape(item) for item in facts) + "</p>")
    if detail.about_text:
        parts.append(f"<p>{html.escape(detail.about_text)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def identifiers_field_value(identifiers: dict[str, str]) -> str:
    return ",".join(f"{key}:{value}" for key, value in identifiers.items() if key and value)


def subprocess_window_options(create_no_window: int | None = getattr(subprocess, "CREATE_NO_WINDOW", None)) -> dict[str, int]:
    """Na Windows schova konzolova okna spoustenych programu."""
    if create_no_window is None:
        return {}
    return {"creationflags": create_no_window}


def run_command(args: Sequence[str]) -> CommandResult:
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **subprocess_window_options(),
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def apply_match_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
    fetcher: Callable[[str], str] | None = None,
    identifiers_reader: Callable[[str | Path, int], dict[str, str]] = get_current_identifiers,
    tags_reader: Callable[[str | Path, int], list[str]] = get_current_tags,
) -> ApplyResult:
    if row.status != "approve":
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")
    if not row.chosen_url.strip():
        return clear_comment_row(row, library, calibredb_path, runner)
    if row.source == "legie" or is_valid_legie_story_url(row.chosen_url):
        return apply_legie_story_row(
            row,
            library,
            calibredb_path,
            runner,
            fetcher or fetch_text,
            identifiers_reader,
            tags_reader,
        )
    if is_valid_databaze_story_url(row.chosen_url):
        return apply_manual_link_row(row, library, calibredb_path, runner)
    if not is_valid_apply_url(row.chosen_url):
        if is_manual_external_url(row):
            return apply_manual_link_row(row, library, calibredb_path, runner)
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "invalid-url")

    detail_url = book_url_to_overview_url(row.chosen_url)
    detail_fetcher = fetcher or fetch_text
    try:
        detail_html = detail_fetcher(detail_url)
    except Exception as exc:
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, f"detail-fetch-error: {exc}")

    detail = parse_book_detail_metadata(detail_html)
    written_url = detail_url
    editions_url = extract_editions_url(detail_html)
    if editions_url:
        try:
            oldest_edition = parse_oldest_edition_metadata(detail_fetcher(editions_url))
        except Exception as exc:
            return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, f"editions-fetch-error: {exc}")
        if not (oldest_edition.published_year or oldest_edition.publisher):
            return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, "editions-parse-error")
        detail = BookDetailMetadata(
            published_year=oldest_edition.published_year or detail.published_year,
            publisher=oldest_edition.publisher or detail.publisher,
            tags=detail.tags,
            rating_percent=detail.rating_percent,
            about_text=detail.about_text,
        )
        written_url = oldest_edition.url or detail_url

    new_comment = format_enriched_comment(written_url, detail)
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + new_comment,
    ]
    if detail.published_year:
        args.extend(["--field", "pubdate:" + calibre_pubdate_value(detail.published_year)])
    if detail.publisher:
        args.extend(["--field", "publisher:" + detail.publisher])
    if detail.tags:
        args.extend(["--field", "tags:" + ",".join(detail.tags)])
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error)
    return ApplyResult(row.book_id, row.title, "updated", written_url, "")


def clear_comment_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult],
) -> ApplyResult:
    """Vymaze komentar u knihy, kdyz je schvaleny prazdny odkaz."""
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:",
    ]
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", "", error)
    return ApplyResult(row.book_id, row.title, "updated", "", "")


def apply_legie_story_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult],
    fetcher: Callable[[str], str],
    identifiers_reader: Callable[[str | Path, int], dict[str, str]],
    tags_reader: Callable[[str | Path, int], list[str]],
) -> ApplyResult:
    if row.status != "approve":
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")
    if not is_valid_legie_story_url(row.chosen_url):
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "invalid-url")
    try:
        detail = parse_legie_story_detail(fetcher(row.chosen_url), row.chosen_url)
    except Exception as exc:
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, f"legie-detail-fetch-error: {exc}")

    identifiers = dict(identifiers_reader(library, row.book_id))
    identifiers["legie"] = detail.legie_id or legie_id_from_url(row.chosen_url)
    tags = _dedupe_tags(tags_reader(library, row.book_id) + [detail.category, "povidka"])
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + format_legie_comment(row.chosen_url, detail),
        "--field",
        "tags:" + ",".join(tags),
        "--field",
        "identifiers:" + identifiers_field_value(identifiers),
    ]
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error)
    return ApplyResult(row.book_id, row.title, "updated", row.chosen_url, "")


def apply_manual_link_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult],
) -> ApplyResult:
    """Zapise jen rucne zadany odkaz, bez stahovani detailu a dalsich metadat."""
    url = databaze_absolute_url(row.chosen_url) if "databazeknih.cz" in row.chosen_url.lower() else row.chosen_url.strip()
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + format_link_html(url),
    ]
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", url, error)
    return ApplyResult(row.book_id, row.title, "updated", url, "")


def repair_book_comment_target(
    book: Book,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
) -> ApplyResult:
    """Opravi jeden stary komentar tak, aby odkaz na Databazi knih mel target blank."""
    repaired_comment = add_target_blank_to_databaze_links(book.comment)
    url = extract_first_databaze_link(book.comment)
    if repaired_comment == (book.comment or ""):
        return ApplyResult(book.id, book.title, "skipped", url, "")

    args = [
        calibredb_path,
        "set_metadata",
        str(book.id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + repaired_comment,
    ]
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(book.id, book.title, "failed", url, error)
    return ApplyResult(book.id, book.title, "updated", url, "")


def write_apply_results(path: Path, rows: Iterable[ApplyResult]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=APPLY_RESULTS_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def apply_results_path(timestamp: str, base_dir: Path = Path(".")) -> Path:
    """Vrati cestu pro vysledek zapisu a vytvori slozku apply-results."""
    directory = base_dir / APPLY_RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"apply-results-{timestamp}.csv"


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def robots_allows_search() -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(BASE_URL + "/robots.txt")
    parser.read()
    return parser.can_fetch(USER_AGENT, BASE_URL + "/vyhledavani/knihy")


def run_calibredb_smoke(calibredb_path: str, library: str | Path) -> CommandResult:
    return run_command([calibredb_path, "list", "--with-library", str(library), "--limit", "1"])


def preview_books(
    books: Sequence[Book],
    fetcher: Callable[[str], str] = fetch_text,
    robots_checker: Callable[[], bool] = robots_allows_search,
    sleeper: Callable[[float], None] = time.sleep,
    sleep_seconds: float = 1.0,
) -> list[MatchRow]:
    rows: list[MatchRow] = []
    searchable_books = [book for book in books if not comment_has_databaze_link(book.comment)]
    if searchable_books:
        if not robots_checker():
            raise RuntimeError("robots-blocked")

    searched = 0
    for book in books:
        if comment_has_databaze_link(book.comment):
            rows.append(match_book(book, []))
            continue
        # robots.txt byl predchozi HTTP pozadavek, proto pauza patri i pred prvni hledani.
        sleeper(sleep_seconds)
        searched += 1
        try:
            html = fetcher(build_search_url(book.title, book.authors))
            row = match_book(book, parse_search_results(html))
        except Exception:
            authors_text = " & ".join(book.authors)
            row = MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "http-error")
        if should_try_legie(row):
            legie_row = find_legie_story(book, fetcher, sleeper, sleep_seconds)
            if legie_row is not None:
                row = legie_row
        rows.append(row)
    return rows


def audit_legie_rows(
    rows: Sequence[MatchRow],
    fetcher: Callable[[str], str] = fetch_text,
    sleeper: Callable[[float], None] = time.sleep,
    sleep_seconds: float = 1.0,
) -> list[MatchRow]:
    updated: list[MatchRow] = []
    for row in rows:
        if row.status == "approve" and not should_try_legie(row):
            updated.append(row)
            continue
        if is_valid_legie_story_url(row.chosen_url):
            updated.append(
                MatchRow(
                    row.book_id,
                    row.title,
                    row.authors,
                    "review",
                    row.chosen_url,
                    row.candidate_urls,
                    row.confidence,
                    "legie-story-candidate",
                    "legie",
                    "povidka",
                )
            )
            continue
        if not should_try_legie(row) and row.reason != "already-linked":
            updated.append(row)
            continue
        authors = [part.strip() for part in row.authors.split("&") if part.strip()]
        book = Book(row.book_id, row.title, authors, "")
        databaze_row = None
        databaze_failed = False
        sleeper(sleep_seconds)
        try:
            databaze_html = fetcher(build_search_url(book.title, book.authors))
            databaze_row = match_book(book, parse_search_results(databaze_html))
        except Exception:
            databaze_failed = True
            databaze_row = None
        if databaze_row is not None and databaze_row.chosen_url and not should_try_legie(databaze_row):
            updated.append(databaze_row)
            continue
        legie_row = find_legie_story(book, fetcher, sleeper, sleep_seconds)
        if legie_row is not None:
            updated.append(legie_row)
        elif databaze_row is not None and databaze_row.chosen_url:
            updated.append(databaze_row)
        elif row.reason == "already-linked" and row.chosen_url and not databaze_failed:
            updated.append(
                MatchRow(
                    row.book_id,
                    row.title,
                    row.authors,
                    "review",
                    "",
                    row.candidate_urls,
                    "none",
                    "stale-already-linked",
                    row.source,
                    row.work_type,
                )
            )
        else:
            updated.append(row)
    return updated


def run_preview(args: argparse.Namespace) -> int:
    output = MATCHES_PATH
    incremental = output.exists() and not args.overwrite
    existing_rows = read_matches_csv(output) if incremental else []
    selected_book_ids = set(getattr(args, "book_ids", None) or [])
    refresh_selected = args.book_id is None and bool(selected_book_ids)

    read_limit = None if refresh_selected else args.limit
    books = read_books(args.library, book_id=args.book_id, limit=read_limit)
    if refresh_selected:
        books = select_books(books, book_ids=selected_book_ids)
    books_to_preview = books if refresh_selected or not incremental else filter_new_books(books, existing_rows)
    if incremental and not books_to_preview:
        if refresh_selected:
            print("Zadne vybrane knihy k update. matches.csv zustava beze zmeny.")
        else:
            print("Zadne nove knihy. matches.csv zustava beze zmeny.")
        return 0

    try:
        rows = preview_books(books_to_preview, sleep_seconds=args.sleep)
    except Exception as exc:
        print(f"Preview selhalo: {exc}")
        return 1

    if incremental and refresh_selected:
        all_rows = replace_match_rows(existing_rows, rows)
    elif incremental:
        all_rows = existing_rows + rows
    else:
        all_rows = rows
    write_matches_csv(output, all_rows, overwrite=args.overwrite or incremental)
    if incremental and refresh_selected:
        print(f"Hotovo preview: update {len(rows)} vybranych radku, celkem {len(all_rows)} -> {output}")
    elif incremental:
        print(f"Hotovo preview: pridano {len(rows)} novych radku, celkem {len(all_rows)} -> {output}")
    else:
        print(f"Hotovo preview: {len(rows)} radku -> {output}")
    return 0


def run_legie_audit(args: argparse.Namespace) -> int:
    rows = read_matches_csv(MATCHES_PATH)
    selected_rows = select_match_rows(
        rows,
        book_id=args.book_id,
        limit=args.limit,
        book_ids=getattr(args, "book_ids", None),
    )
    selected_ids = {row.book_id for row in selected_rows}
    audited = audit_legie_rows(selected_rows, sleep_seconds=args.sleep)
    replacements = {row.book_id: row for row in audited}
    merged = [replacements.get(row.book_id, row) if row.book_id in selected_ids else row for row in rows]
    backup_path = backup_matches_csv(MATCHES_PATH, MATCHES_PATH.parent / "backups" / "matches")
    if backup_path:
        print(f"Zaloha matches.csv: {backup_path}")
    write_matches_csv(MATCHES_PATH, merged, overwrite=True)
    changed = sum(1 for old, new in zip(rows, merged) if old != new)
    print(f"Audit odkazu: zmeneno {changed} radku")
    return 0


def _is_global_calibredb_error(error: str) -> bool:
    lowered = error.lower()
    return any(word in lowered for word in ("lock", "locked", "spuštěn jiný", "database is locked", "library"))


def _is_finished_apply_result(result: ApplyResult) -> bool:
    """Pozna vysledek, ktery uz neni potreba znovu zkouset."""
    return result.status == "updated" or (result.status == "skipped" and not result.error)


def mark_finished_apply_rows_skipped(rows: Sequence[MatchRow], results: Sequence[ApplyResult]) -> list[MatchRow]:
    """Po zapisu prepne hotove approve radky na skip, aby se priste znovu nenabizely."""
    finished_results = {result.book_id: result for result in results if _is_finished_apply_result(result)}
    updated_rows: list[MatchRow] = []
    for row in rows:
        if row.status == "approve" and row.book_id in finished_results:
            result = finished_results[row.book_id]
            updated_rows.append(
                MatchRow(
                    row.book_id,
                    row.title,
                    row.authors,
                    "skip",
                    result.chosen_url or row.chosen_url,
                    row.candidate_urls,
                    row.confidence,
                    row.reason,
                    row.source,
                    row.work_type,
                )
            )
            continue
        updated_rows.append(row)
    return updated_rows


def run_apply(args: argparse.Namespace) -> int:
    library = Path(args.library)
    sidecars = find_sqlite_sidecars(library)
    if sidecars:
        print("Databaze ma vedlejsi SQLite soubory. Zavri Calibre a zkus znovu:")
        for sidecar in sidecars:
            print(f"- {sidecar}")
        return 1

    calibredb_path = find_calibredb()
    if not calibredb_path:
        print("calibredb nenalezen. Nainstaluj Calibre nebo pridej calibredb do PATH.")
        return 1

    smoke = run_calibredb_smoke(calibredb_path, library)
    if smoke.returncode != 0:
        print("calibredb neumi pristoupit ke knihovne. Zavri Calibre nebo pouzij namapovanou cestu.")
        print((smoke.stderr or smoke.stdout).strip())
        return 1

    all_rows = read_matches_csv(MATCHES_PATH)
    rows = select_match_rows(all_rows, book_id=args.book_id, limit=args.limit)
    writable_rows = [row for row in rows if is_writable_match_row(row)]
    if not writable_rows:
        print("Neni co zapisovat. updated=0")
        return 0

    backup_path = create_backup(library, Path("backups"))
    print(f"Zaloha: {backup_path}")

    results: list[ApplyResult] = []
    for row in rows:
        if row.status != "approve":
            results.append(ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "status-not-approve"))
            continue
        result = apply_match_row(row, library, calibredb_path)
        results.append(result)
        if result.status == "failed" and _is_global_calibredb_error(result.error):
            print("Globalni chyba knihovny. Batch zastaven.")
            break

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    results_path = apply_results_path(stamp)
    write_apply_results(results_path, results)
    updated_all_rows = mark_finished_apply_rows_skipped(all_rows, results)
    changed_rows = sum(1 for old, new in zip(all_rows, updated_all_rows) if old.status != new.status)
    if changed_rows:
        write_matches_csv(MATCHES_PATH, updated_all_rows, overwrite=True)
        print(f"matches.csv: {changed_rows} hotovych radku zmeneno na skip")
    counts = {status: sum(1 for result in results if result.status == status) for status in ("updated", "skipped", "failed")}
    print(f"Vysledek: {results_path}")
    print(f"updated={counts['updated']} skipped={counts['skipped']} failed={counts['failed']}")
    return 1 if counts["failed"] else 0


def run_repair_links(args: argparse.Namespace) -> int:
    """Opravi stare Databaze knih odkazy v Calibre komentarich."""
    library = Path(args.library)
    sidecars = find_sqlite_sidecars(library)
    if sidecars:
        print("Databaze ma vedlejsi SQLite soubory. Zavri Calibre a zkus znovu:")
        for sidecar in sidecars:
            print(f"- {sidecar}")
        return 1

    calibredb_path = find_calibredb()
    if not calibredb_path:
        print("calibredb nenalezen. Nainstaluj Calibre nebo pridej calibredb do PATH.")
        return 1

    smoke = run_calibredb_smoke(calibredb_path, library)
    if smoke.returncode != 0:
        print("calibredb neumi pristoupit ke knihovne. Zavri Calibre nebo pouzij namapovanou cestu.")
        print((smoke.stderr or smoke.stdout).strip())
        return 1

    books = read_books(args.library, book_id=args.book_id, limit=args.limit)
    repairable_books = [
        book
        for book in books
        if add_target_blank_to_databaze_links(book.comment) != (book.comment or "")
    ]
    if not repairable_books:
        print("Neni co opravovat. updated=0")
        return 0

    backup_path = create_backup(library, Path("backups"))
    print(f"Zaloha: {backup_path}")

    results = [repair_book_comment_target(book, library, calibredb_path) for book in repairable_books]
    counts = {status: sum(1 for result in results if result.status == status) for status in ("updated", "skipped", "failed")}
    print(f"updated={counts['updated']} skipped={counts['skipped']} failed={counts['failed']}")
    return 1 if counts["failed"] else 0


def run_restore_backup(args: argparse.Namespace) -> int:
    """Obnovi Calibre metadata.db z vybrane zalohy."""
    library = Path(args.library)
    sidecars = find_sqlite_sidecars(library)
    if sidecars:
        print("Databaze ma vedlejsi SQLite soubory. Zavri Calibre a zkus znovu:")
        for sidecar in sidecars:
            print(f"- {sidecar}")
        return 1

    try:
        safety_backup = restore_metadata_backup(library, Path(args.backup), Path("backups"))
    except Exception as exc:
        print(f"Rollback selhal: {exc}")
        return 1

    print(f"Obnoveno z: {Path(args.backup)}")
    print(f"Nouzova zaloha pred rollbackem: {safety_backup}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Doplni do Calibre komentaru odkazy na Databazi knih.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview = subparsers.add_parser("preview", help="Vytvori matches.csv bez zapisu do Calibre.")
    preview.add_argument("--library", default=DEFAULT_LIBRARY)
    preview.add_argument("--limit", type=int)
    preview.add_argument("--book-id", type=int)
    preview.add_argument("--sleep", type=float, default=1.0)
    preview.add_argument("--overwrite", action="store_true")
    preview.set_defaults(func=run_preview)

    apply_parser = subparsers.add_parser("apply", help="Zapise schvalene odkazy z matches.csv.")
    apply_parser.add_argument("--library", default=DEFAULT_LIBRARY)
    apply_parser.add_argument("--limit", type=int)
    apply_parser.add_argument("--book-id", type=int)
    apply_parser.add_argument("--sleep", type=float, default=1.0)
    apply_parser.add_argument("--overwrite", action="store_true")
    apply_parser.set_defaults(func=run_apply)

    legie_audit = subparsers.add_parser("legie-audit", help="Najde mozne povidky na Legii a da je do review.")
    legie_audit.add_argument("--library", default=DEFAULT_LIBRARY)
    legie_audit.add_argument("--limit", type=int)
    legie_audit.add_argument("--book-id", type=int)
    legie_audit.add_argument("--sleep", type=float, default=1.0)
    legie_audit.set_defaults(func=run_legie_audit)

    repair_parser = subparsers.add_parser("repair-links", help="Opravi stare Databaze knih odkazy v komentarich.")
    repair_parser.add_argument("--library", default=DEFAULT_LIBRARY)
    repair_parser.add_argument("--limit", type=int)
    repair_parser.add_argument("--book-id", type=int)
    repair_parser.add_argument("--sleep", type=float, default=1.0)
    repair_parser.add_argument("--overwrite", action="store_true")
    repair_parser.set_defaults(func=run_repair_links)

    restore_parser = subparsers.add_parser("restore-backup", help="Obnovi metadata.db z vybrane zalohy.")
    restore_parser.add_argument("--library", default=DEFAULT_LIBRARY)
    restore_parser.add_argument("--backup", required=True)
    restore_parser.set_defaults(func=run_restore_backup)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.book_id is not None:
        args.limit = None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
