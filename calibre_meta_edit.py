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
DEFAULT_LIBRARY = r"\\192.168.0.101\data\books"
CALIBREDB_FALLBACK = r"C:\Program Files\Calibre2\calibredb.exe"
USER_AGENT = "calibre-meta-edit/1.0"
MATCHES_PATH = Path("matches.csv")
APPLY_RESULTS_DIR = Path("apply-results")
MATCHES_FIELDS = [
    "book_id",
    "title",
    "authors",
    "status",
    "chosen_url",
    "candidate_urls",
    "confidence",
    "reason",
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


@dataclass(frozen=True)
class BookDetailMetadata:
    published_year: str = ""
    publisher: str = ""
    tags: list[str] | None = None
    rating_percent: str = ""
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
        if tag.lower() == "a" and "/prehled-knihy/" in attrs_dict.get("href", ""):
            self._finish_current()
            self._current = {
                "url": overview_to_book_url(attrs_dict["href"]),
                "title": "",
                "parts": [],
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

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        title = str(self._current.get("title") or "").strip()
        url = str(self._current.get("url") or "").strip()
        parts = self._current.get("parts") or []
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
    """Parser seznamu vydani. Bere jen bloky, kde je odkaz na nakladatelstvi."""

    def __init__(self) -> None:
        super().__init__()
        self.editions: list[EditionMetadata] = []
        self._last_overview_url = ""
        self._block_url = ""
        self._block_parts: list[str] = []
        self._block_depth = 0
        self._block_has_publisher = False
        self._block_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        lowered_tag = tag.lower()
        href = attrs_dict.get("href", "")

        if self._block_depth and self._block_tag == "p" and lowered_tag in {"div", "hr"}:
            self._finish_block()

        if lowered_tag == "a" and "bigger" in classes and "/prehled-knihy/" in href:
            self._last_overview_url = databaze_absolute_url(href)

        if self._block_depth:
            self._block_depth += 1
            if lowered_tag == "a" and "/nakladatelstvi/" in href:
                self._block_has_publisher = True
            return

        is_current_publication = lowered_tag == "div" and {"lora", "lineHeightMid"}.issubset(classes)
        is_edition_publication = lowered_tag == "p" and {"new", "odtopm"}.issubset(classes)
        if is_current_publication or is_edition_publication:
            self._block_depth = 1
            self._block_tag = lowered_tag
            self._block_url = self._last_overview_url
            self._block_parts = []
            self._block_has_publisher = False

    def handle_endtag(self, tag: str) -> None:
        if not self._block_depth:
            return
        self._block_depth -= 1
        if self._block_depth:
            return
        self._finish_block()

    def _finish_block(self) -> None:
        edition = _publication_metadata_from_text(" ".join(self._block_parts), self._block_url)
        if self._block_has_publisher and edition.published_year:
            self.editions.append(edition)
        self._block_depth = 0
        self._block_tag = ""
        self._block_url = ""
        self._block_parts = []
        self._block_has_publisher = False

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


def _candidate_urls(candidates: Sequence[Candidate]) -> str:
    urls = [candidate.url for candidate in candidates[:5]]
    return "|".join(urls)


def match_book(book: Book, candidates: Sequence[Candidate]) -> MatchRow:
    authors_text = " & ".join(book.authors)
    if comment_has_databaze_link(book.comment):
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "skip",
            extract_first_databaze_link(book.comment),
            "",
            "none",
            "already-linked",
        )

    if not candidates:
        return MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "no-candidates")

    normalized_title = normalize_text(book.title)
    title_matches = [candidate for candidate in candidates if normalize_text(candidate.title) == normalized_title]
    exact_author_matches = [
        candidate
        for candidate in title_matches
        if any(normalize_text(author) in normalize_text(candidate.text) for author in book.authors)
    ]

    if len(exact_author_matches) == 1 and len(title_matches) == 1:
        candidate = exact_author_matches[0]
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "approve",
            candidate.url,
            _candidate_urls(candidates),
            "exact-title-author",
            "exact-title-author",
        )
    if len(exact_author_matches) > 1 or len(title_matches) > 1:
        chosen = title_matches[0] if title_matches else exact_author_matches[0]
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            chosen.url,
            _candidate_urls(candidates),
            "multiple-title-matches",
            "multiple-title-matches",
        )
    if len(title_matches) == 1:
        candidate = title_matches[0]
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "title-only",
            "title-only",
        )

    partial_matches = [
        candidate
        for candidate in candidates
        if normalized_title in normalize_text(candidate.title) or normalize_text(candidate.title) in normalized_title
    ]
    if partial_matches:
        candidate = partial_matches[0]
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "partial-title",
            "partial-title",
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


def select_books(books: Sequence[Book], book_id: int | None = None, limit: int | None = None) -> list[Book]:
    if book_id is not None:
        return [book for book in books if book.id == book_id]
    selected = list(books)
    return selected[:limit] if limit is not None else selected


def select_match_rows(rows: Sequence[MatchRow], book_id: int | None = None, limit: int | None = None) -> list[MatchRow]:
    if book_id is not None:
        return [row for row in rows if row.book_id == book_id]
    selected = list(rows)
    return selected[:limit] if limit is not None else selected


def filter_new_books(books: Sequence[Book], existing_rows: Sequence[MatchRow]) -> list[Book]:
    """Vrati jen knihy, ktere jeste nejsou ulozene v matches.csv."""
    existing_book_ids = {row.book_id for row in existing_rows}
    return [book for book in books if book.id not in existing_book_ids]


def is_valid_apply_url(url: str) -> bool:
    clean = databaze_absolute_url(url)
    return clean.startswith(BASE_URL + "/knihy/") or clean.startswith(BASE_URL + "/prehled-knihy/")


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
) -> ApplyResult:
    if row.status != "approve":
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")
    if not is_valid_apply_url(row.chosen_url):
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
            rows.append(match_book(book, parse_search_results(html)))
        except Exception:
            authors_text = " & ".join(book.authors)
            rows.append(MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "http-error"))
    return rows


def run_preview(args: argparse.Namespace) -> int:
    output = MATCHES_PATH
    incremental = output.exists() and not args.overwrite
    existing_rows = read_matches_csv(output) if incremental else []

    books = read_books(args.library, book_id=args.book_id, limit=args.limit)
    books_to_preview = filter_new_books(books, existing_rows) if incremental else books
    if incremental and not books_to_preview:
        print("Zadne nove knihy. matches.csv zustava beze zmeny.")
        return 0

    try:
        rows = preview_books(books_to_preview, sleep_seconds=args.sleep)
    except Exception as exc:
        print(f"Preview selhalo: {exc}")
        return 1

    all_rows = existing_rows + rows if incremental else rows
    write_matches_csv(output, all_rows, overwrite=args.overwrite or incremental)
    if incremental:
        print(f"Hotovo preview: pridano {len(rows)} novych radku, celkem {len(all_rows)} -> {output}")
    else:
        print(f"Hotovo preview: {len(rows)} radku -> {output}")
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
    writable_rows = [row for row in rows if row.status == "approve" and is_valid_apply_url(row.chosen_url)]
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
