# Skript pripravi nahled odkazu na Databazi knih a bezpecne zapise metadata do Calibre.

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import html
import json
import logging
import os
import posixpath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Sequence


# Logger pro diagnostiku (hlavne AI import). Defaultne tichy; appka/CLI mu da handler.
logger = logging.getLogger("calibre_meta")

BASE_URL = "https://www.databazeknih.cz"
SEARCH_URL = BASE_URL + "/vyhledavani/knihy?q="
LEGIE_BASE_URL = "https://www.legie.info"
LEGIE_SEARCH_URL = LEGIE_BASE_URL + "/index.php?search_text="
GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_BASE = "https://openlibrary.org"
OPEN_LIBRARY_SEARCH_API = OPEN_LIBRARY_BASE + "/search.json"
DEFAULT_LIBRARY = r"\\192.168.0.101\data\books"
CALIBREDB_FALLBACK = r"C:\Program Files\Calibre2\calibredb.exe"
# Jeden zdroj pravdy: vsechny pripony podporovane importem a jejich UI popisky.
BOOK_IMPORT_FORMATS = (
    (".epub", "EPUB"),
    (".mobi", "MOBI"),
    (".azw3", "AZW3"),
    (".pdb", "PDB"),
)
# Pripony, ktere se ctou pres Calibre nastroje (ebook-meta/convert), ne stdlib EPUB cestou.
EBOOK_TOOL_FORMATS = {extension for extension, _label in BOOK_IMPORT_FORMATS if extension != ".epub"}
USER_AGENT = "calibre-meta-edit/1.0"
MATCHES_PATH = Path("matches.db")
LEGACY_MATCHES_CSV_PATH = Path("matches.csv")
APPLY_RESULTS_DIR = Path("apply-results")
LEGIE_FALLBACK_REASONS = {"no-candidates", "title-only", "multiple-title-matches", "partial-title", "http-error"}
HTML_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
EPUB_TEXT_ITEM_MAX_BYTES = 1_000_000
MOJIBAKE_REPLACEMENTS = {
    "p\u00b2": "p\u0159",
    "\u256a": "\u011b",
    "\u2563": "\u016f",
    "\u00de": "\u0161",
    "\u010e": "\u011b",
}
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
    "cover_urls",
    "selected_cover_url",
    "cover_reason",
    "review_published_year",
    "review_publisher",
    "review_tags",
    "review_rating_percent",
    "review_original_title",
    "review_original_publication",
    "review_original_publisher",
]
APPLY_RESULTS_FIELDS = ["book_id", "title", "status", "chosen_url", "error", "cover_status"]


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
    cover_urls: str = ""
    selected_cover_url: str = ""
    cover_reason: str = ""
    review_published_year: str = ""
    review_publisher: str = ""
    review_tags: str = ""
    review_rating_percent: str = ""
    review_original_title: str = ""
    review_original_publication: str = ""
    review_original_publisher: str = ""


@dataclass(frozen=True)
class BookDetailMetadata:
    published_year: str = ""
    publisher: str = ""
    series: str = ""
    series_index: str = ""
    tags: list[str] | None = None
    rating_percent: str = ""
    original_title: str = ""
    original_publication: str = ""
    original_publisher: str = ""
    about_text: str = ""
    cover_url: str = ""


@dataclass(frozen=True)
class CurrentBookMetadata:
    published_year: str = ""
    publisher: str = ""
    tags: list[str] | None = None
    comment: str = ""


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
    cover_url: str = ""


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
    cover_status: str = "not-requested"


@dataclass(frozen=True)
class CoverCandidate:
    book_id: int
    title: str
    source_url: str


@dataclass(frozen=True)
class ImportSourceSignal:
    source: str
    title: str = ""
    authors: str = ""
    language: str = ""
    publisher: str = ""
    published_year: str = ""
    text: str = ""
    confidence: int = 0


@dataclass(frozen=True)
class AIBookIdentity:
    """Vysledek AI extrakce nazvu a autora z textu knihy."""
    title: str = ""
    author: str = ""
    confidence: int = 0


@dataclass(frozen=True)
class EpubMetadata:
    title: str = ""
    authors: str = ""
    language: str = ""
    publisher: str = ""
    published_year: str = ""


@dataclass(frozen=True)
class ImportCandidate:
    source: str
    title: str
    authors: str
    url: str
    score: int = 0
    reason: str = ""
    work_type: str = ""
    evidence_text: str = ""
    detail: BookDetailMetadata | None = None


@dataclass(frozen=True)
class AIImportChoice:
    url: str
    confidence: int = 0
    reason: str = ""


@dataclass(frozen=True)
class DuplicateCandidate:
    book_id: int
    title: str
    authors: str
    series: str = ""
    score: int = 0
    reason: str = ""
    strong: bool = False


@dataclass(frozen=True)
class ImportPreview:
    title: str = ""
    authors: str = ""
    series: str = ""
    series_index: str = ""
    published_year: str = ""
    publisher: str = ""
    tags: str = ""
    url: str = ""
    source: str = ""
    work_type: str = ""
    rating_percent: str = ""
    original_title: str = ""
    original_publication: str = ""
    original_publisher: str = ""
    comment: str = ""
    selected_cover_url: str = ""
    cover_bytes: bytes = b""
    allow_strong_duplicate: bool = False


@dataclass(frozen=True)
class ImportAnalysis:
    epub_path: str
    signals: list[ImportSourceSignal]
    candidates: list[ImportCandidate]
    recommended: ImportCandidate | None
    duplicates: list[DuplicateCandidate]
    preview: ImportPreview
    messages: list[str]


@dataclass(frozen=True)
class ImportApplyResult:
    book_id: int
    status: str
    error: str = ""
    backup_path: str = ""


MULTIIMPORT_BATCH_STATUSES = (
    "pending",
    "analyzing",
    "ready",
    "needs_review",
    "duplicate_warning",
    "analysis_error",
    "skipped",
    "writing",
    "written",
    "write_error",
)


@dataclass
class MultiImportBatchItem:
    source_path: Path
    display_name: str
    checked_for_import: bool = False
    status: str = "pending"
    error_message: str = ""
    analysis: ImportAnalysis | None = None
    current_preview: ImportPreview | None = None
    selected_candidate: ImportCandidate | None = None
    # True, kdyz uzivatel rucne vybral kandidata/odkaz a potvrdil import i bez
    # 100% shody. Odemyka zapis u polozek, ktere by jinak zustaly "ke kontrole".
    manually_confirmed: bool = False
    duplicates: list[DuplicateCandidate] = field(default_factory=list)
    write_result: ImportApplyResult | None = None
    calibre_id: int | None = None


@dataclass(frozen=True)
class MultiImportValidationIssue:
    item: MultiImportBatchItem | None
    reason: str


@dataclass(frozen=True)
class MultiImportValidationResult:
    valid_items: list[MultiImportBatchItem]
    issues: list[MultiImportValidationIssue]

    @property
    def ok(self) -> bool:
        return bool(self.valid_items) and not self.issues


@dataclass(frozen=True)
class MultiImportWriteSummary:
    validation: MultiImportValidationResult
    attempted: int
    succeeded: int
    failed: int

    @property
    def ok(self) -> bool:
        return self.attempted > 0 and self.failed == 0 and self.validation.ok


@dataclass(frozen=True)
class CoverOption:
    url: str
    source: str
    label: str = ""


def is_valid_import_preview(preview: ImportPreview) -> bool:
    return bool(preview.title.strip() and preview.authors.strip())


def validate_multiimport_checked_items(
    items: Iterable[MultiImportBatchItem],
) -> MultiImportValidationResult:
    checked_items = [item for item in items if item.checked_for_import]
    if not checked_items:
        return MultiImportValidationResult([], [MultiImportValidationIssue(None, "no_checked_items")])

    valid_items = []
    issues = []
    for item in checked_items:
        reason = ""
        if item.status == "duplicate_warning" or item.duplicates:
            reason = "duplicate_warning"
        elif item.status == "analysis_error" or item.error_message:
            reason = "analysis_error"
        elif item.analysis is None:
            reason = "missing_analysis"
        elif item.current_preview is None:
            reason = "missing_preview"
        elif item.selected_candidate is None:
            reason = "missing_candidate"
        elif not is_valid_import_preview(item.current_preview):
            reason = "invalid_preview"
        elif item.status != "ready" and not item.manually_confirmed:
            # Rucne potvrzena polozka smi projit i pod 100 %; jinak zustava
            # blokovana duvodem z prechecku (napr. nizke skore).
            precheck_issues = multiimport_precheck_issues(item.analysis)
            reason = precheck_issues[0] if precheck_issues else "status_not_ready"

        if reason:
            issues.append(MultiImportValidationIssue(item, reason))
        else:
            valid_items.append(item)
    return MultiImportValidationResult(valid_items, issues)


def run_multiimport_batch_write(
    items: Iterable[MultiImportBatchItem],
    write_one: Callable[[ImportPreview, Path], ImportApplyResult],
    *,
    progress_callback: Callable[[int, int, MultiImportBatchItem], None] | None = None,
) -> MultiImportWriteSummary:
    batch = list(items)
    validation = validate_multiimport_checked_items(batch)
    if not validation.ok:
        return MultiImportWriteSummary(validation, attempted=0, succeeded=0, failed=0)

    succeeded = 0
    failed = 0
    total = len(validation.valid_items)
    for index, item in enumerate(validation.valid_items, start=1):
        item.status = "writing"
        try:
            result = write_one(item.current_preview, item.source_path)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            result = ImportApplyResult(book_id=0, status="failed", error=error)
        item.write_result = result
        item.calibre_id = result.book_id if result.book_id > 0 else None
        if result.status == "updated":
            item.status = "written"
            succeeded += 1
        else:
            item.status = "write_error"
            failed += 1
        item.checked_for_import = False
        if progress_callback is not None:
            progress_callback(index, total, item)

    return MultiImportWriteSummary(
        validation,
        attempted=total,
        succeeded=succeeded,
        failed=failed,
    )


def is_supported_import_file(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    return any(suffix == extension for extension, _label in BOOK_IMPORT_FORMATS)


@dataclass(frozen=True)
class ImportFolderScanResult:
    files: tuple[Path, ...]
    skipped_directories: tuple[Path, ...]


def is_import_directory_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _sorted_unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    unique: dict[str, Path] = {}
    for path in paths:
        absolute = Path(os.path.abspath(path))
        unique.setdefault(os.path.normcase(str(absolute)), absolute)
    return tuple(sorted(unique.values(), key=lambda path: str(path).casefold()))


def scan_import_files_from_folder(
    folder: Path,
    recursive: bool = False,
    walk_func: Callable[..., Iterable[tuple[str, list[str], list[str]]]] | None = None,
) -> ImportFolderScanResult:
    root = Path(os.path.abspath(folder))
    if not root.is_dir():
        return ImportFolderScanResult((), (root,))

    files: list[Path] = []
    skipped: list[Path] = []
    if not recursive:
        try:
            files.extend(path for path in root.iterdir() if is_supported_import_file(path))
        except OSError:
            skipped.append(root)
        return ImportFolderScanResult(_sorted_unique_paths(files), _sorted_unique_paths(skipped))

    def record_error(error: OSError) -> None:
        skipped.append(Path(error.filename) if error.filename else root)

    walker = walk_func or os.walk
    for current, directory_names, file_names in walker(
        root,
        topdown=True,
        onerror=record_error,
        followlinks=False,
    ):
        current_path = Path(current)
        allowed_directories: list[str] = []
        for name in directory_names:
            candidate = current_path / name
            try:
                if not is_import_directory_link(candidate):
                    allowed_directories.append(name)
            except OSError:
                skipped.append(candidate)
        directory_names[:] = allowed_directories
        for name in file_names:
            candidate = current_path / name
            try:
                if is_supported_import_file(candidate):
                    files.append(candidate)
            except OSError:
                continue

    return ImportFolderScanResult(_sorted_unique_paths(files), _sorted_unique_paths(skipped))


def collect_import_files_from_paths(paths: Iterable[Path]) -> list[Path]:
    return sorted(
        (path for path in paths if is_supported_import_file(path)),
        key=lambda path: str(path).casefold(),
    )


def collect_import_files_from_folder(folder: Path) -> list[Path]:
    return list(scan_import_files_from_folder(folder).files)


def build_multiimport_batch_items(paths: Iterable[Path]) -> list[MultiImportBatchItem]:
    return [MultiImportBatchItem(source_path=path, display_name=path.name) for path in paths]


def multiimport_precheck_issues(analysis: ImportAnalysis) -> list[str]:
    issues = []
    recommended = analysis.recommended
    if recommended is None:
        return ["missing_candidate"]
    if recommended.score < 100:
        issues.append("candidate_score_below_100")
    if analysis.duplicates:
        issues.append("duplicate_warning")
    if not is_valid_import_preview(analysis.preview):
        issues.append("invalid_preview")
    preview_url = analysis.preview.url.strip()
    recommended_url = recommended.url.strip()
    if not preview_url:
        issues.append("missing_preview_url")
    if not recommended_url:
        issues.append("missing_candidate_url")
    if preview_url and recommended_url and preview_url != recommended_url:
        issues.append("preview_url_mismatch")
    hundred_score_urls = {
        candidate.url.strip()
        for candidate in analysis.candidates
        if candidate.score >= 100 and candidate.url.strip()
    }
    if len(hundred_score_urls) > 1:
        issues.append("multiple_100_candidate_urls")
    elif recommended_url and hundred_score_urls != {recommended_url}:
        issues.append("recommended_not_unique_100_candidate")
    return issues


def is_safe_multiimport_precheck(analysis: ImportAnalysis) -> bool:
    return not multiimport_precheck_issues(analysis)


def run_multiimport_batch_analysis(
    items: Iterable[MultiImportBatchItem],
    analyze_one: Callable[[Path], ImportAnalysis],
    *,
    precheck_safe_matches: bool = False,
    progress_callback: Callable[[int, int, MultiImportBatchItem], None] | None = None,
    max_workers: int = 1,
) -> list[MultiImportBatchItem]:
    """Zanalyzuje davku knih.

    `max_workers` > 1 pusti analyzy soubezne v poolu. Analyza ceka skoro jen na
    sit, takze se cekani prekryva. Vysledky se do polozek zapisuji az tady, ve
    volajicim vlakne, takze polozky ani `progress_callback` nikdo nesaha
    soubezne. Poradi `batch` zustava zachovane, meni se jen poradi hlaseni
    postupu (podle toho, co driv dobehne).
    """
    batch = list(items)
    total = len(batch)

    def start(item: MultiImportBatchItem) -> None:
        item.status = "analyzing"
        item.error_message = ""
        item.checked_for_import = False
        item.manually_confirmed = False

    def store_failure(item: MultiImportBatchItem, exc: BaseException) -> None:
        item.analysis = None
        item.current_preview = None
        item.selected_candidate = None
        item.duplicates = []
        item.error_message = str(exc) or type(exc).__name__
        item.status = "analysis_error"

    def store_analysis(item: MultiImportBatchItem, analysis: ImportAnalysis) -> None:
        item.analysis = analysis
        item.current_preview = analysis.preview
        item.selected_candidate = analysis.recommended
        item.duplicates = list(analysis.duplicates)
        safe_match = is_safe_multiimport_precheck(analysis)
        if item.duplicates:
            item.status = "duplicate_warning"
        elif safe_match:
            item.status = "ready"
        else:
            item.status = "needs_review"
        item.checked_for_import = precheck_safe_matches and safe_match

    if max_workers <= 1 or total <= 1:
        for index, item in enumerate(batch, start=1):
            start(item)
            try:
                analysis = analyze_one(item.source_path)
            except Exception as exc:
                store_failure(item, exc)
            else:
                store_analysis(item, analysis)
            if progress_callback is not None:
                progress_callback(index, total, item)
        return batch

    for item in batch:
        start(item)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending = {pool.submit(analyze_one, item.source_path): item for item in batch}
        for done, future in enumerate(concurrent.futures.as_completed(pending), start=1):
            item = pending[future]
            try:
                analysis = future.result()
            except Exception as exc:
                store_failure(item, exc)
            else:
                store_analysis(item, analysis)
            if progress_callback is not None:
                progress_callback(done, total, item)
    return batch


def _epub_opf_path(archive: zipfile.ZipFile) -> str:
    try:
        container = archive.read("META-INF/container.xml")
    except KeyError as exc:
        raise ValueError("epub-missing-container") from exc
    root = ET.fromstring(container)
    namespace = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = root.find(".//c:rootfile", namespace)
    if rootfile is None:
        raise ValueError("epub-missing-rootfile")
    full_path = rootfile.attrib.get("full-path", "").strip()
    if not full_path:
        raise ValueError("epub-empty-rootfile")
    return full_path


def _opf_text(root: ET.Element, tag: str) -> str:
    namespace = {"dc": "http://purl.org/dc/elements/1.1/"}
    value = root.findtext(f".//dc:{tag}", default="", namespaces=namespace)
    return html.unescape(value or "").strip()


def _opf_texts(root: ET.Element, tag: str) -> list[str]:
    namespace = {"dc": "http://purl.org/dc/elements/1.1/"}
    values: list[str] = []
    for element in root.findall(f".//dc:{tag}", namespace):
        value = html.unescape(element.text or "").strip()
        if value:
            values.append(value)
    return values


def extract_year(text: str) -> str:
    return _first_reasonable_year(text or "")


def read_epub_metadata(path: str | Path) -> EpubMetadata:
    with zipfile.ZipFile(path) as archive:
        opf_path = _epub_opf_path(archive)
        root = ET.fromstring(archive.read(opf_path))
    return EpubMetadata(
        title=_opf_text(root, "title"),
        authors=" & ".join(_opf_texts(root, "creator")),
        language=_opf_text(root, "language"),
        publisher=_opf_text(root, "publisher"),
        published_year=extract_year(_opf_text(root, "date")),
    )


def parse_ebook_meta_output(text: str) -> EpubMetadata:
    """Prevede vypis 'ebook-meta <soubor>' na EpubMetadata.

    Cte radky tvaru 'Label : hodnota'. Nezname/chybejici labely ignoruje.
    U autoru odstrani razici tvar v hranatych zavorkach (napr. '[Asimov, Isaac]').
    Cista funkce - zadny subprocess, snadno testovatelna.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z()/ ]+?)\s*:\s*(.*)$", line)
        if not match:
            continue
        label = match.group(1).strip().lower()
        value = match.group(2).strip()
        if label and value and label not in fields:
            fields[label] = value
    authors = re.sub(r"\s*\[[^\]]*\]", "", fields.get("author(s)", "")).strip()
    language = fields.get("languages", "").split(",")[0].split("&")[0].strip()
    return EpubMetadata(
        title=fields.get("title", ""),
        authors=authors,
        language=language,
        publisher=fields.get("publisher", ""),
        published_year=extract_year(fields.get("published", "")),
    )


def read_book_metadata_with_ebook_meta(
    path: str | Path,
    ebook_meta_path: str,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
) -> EpubMetadata:
    """Spusti 'ebook-meta <soubor>' a vrati metadata.

    Pri nenulovem navratu (rozbity/neznamy soubor) vrati prazdne metadata -
    import jede dal na jmenu souboru + online (chybejici metadata neni pad).
    """
    command_runner = runner or run_command
    result = command_runner([ebook_meta_path, str(path)])
    if result.returncode != 0:
        return EpubMetadata()
    return parse_ebook_meta_output(result.stdout)


def extract_book_start_text_with_convert(
    path: str | Path,
    ebook_convert_path: str,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
    limit: int = 5000,
) -> str:
    """Prevede knihu na docasny .txt pres 'ebook-convert' a vrati prvnich `limit` znaku.

    Pri selhani konverze vrati "" - text je jen slaby signal, import jede dal.
    Docasny soubor vzdy uklidi.
    """
    command_runner = runner or run_command
    handle, tmp_path = tempfile.mkstemp(suffix=".txt")
    os.close(handle)
    try:
        result = command_runner([ebook_convert_path, str(path), tmp_path])
        if result.returncode != 0:
            return ""
        return Path(tmp_path).read_text(encoding="utf-8", errors="replace")[:limit]
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


class PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            self.parts.append(clean)

    def text(self) -> str:
        return "\n".join(self.parts)


def _epub_spine_item_paths(archive: zipfile.ZipFile, opf_path: str, root: ET.Element) -> list[str]:
    namespace = {"opf": "http://www.idpf.org/2007/opf"}
    manifest: dict[str, str] = {}
    base = urllib.parse.quote(str(Path(opf_path).parent).replace("\\", "/").rstrip("/") + "/")
    for item in root.findall(".//opf:manifest/opf:item", namespace):
        item_id = item.attrib.get("id", "")
        href = item.attrib.get("href", "")
        media_type = item.attrib.get("media-type", "")
        if item_id and href and "html" in media_type:
            joined = urllib.parse.urljoin(base if base != "./" else "", href)
            clean = urllib.parse.unquote(urllib.parse.urldefrag(joined).url)
            manifest[item_id] = posixpath.normpath(clean)
    paths: list[str] = []
    for itemref in root.findall(".//opf:spine/opf:itemref", namespace):
        href = manifest.get(itemref.attrib.get("idref", ""))
        if href and href in archive.namelist():
            paths.append(href)
    return paths


def _read_epub_text_item(archive: zipfile.ZipFile, item_path: str) -> str:
    info = archive.getinfo(item_path)
    with archive.open(info) as item:
        return item.read(min(info.file_size, EPUB_TEXT_ITEM_MAX_BYTES)).decode("utf-8", errors="replace")


def extract_epub_start_text(path: str | Path, limit: int = 5000) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        opf_path = _epub_opf_path(archive)
        root = ET.fromstring(archive.read(opf_path))
        for item_path in _epub_spine_item_paths(archive, opf_path, root):
            html_text = _read_epub_text_item(archive, item_path)
            if not html_text:
                continue
            parser = PlainTextHTMLParser()
            parser.feed(html_text)
            texts.append(parser.text())
            joined = "\n".join(texts).strip()
            if len(joined) >= limit:
                return joined[:limit]
    return "\n".join(texts).strip()[:limit]


def repair_filename_text(text: str) -> str:
    repaired = text.replace("_", " ")
    for broken, fixed in MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(broken, fixed)
    repaired = re.sub(r"\s+", " ", repaired)
    return repaired.strip(" -_.")


def split_author_title_from_filename(stem: str) -> tuple[str, str]:
    clean = repair_filename_text(stem)
    parts = [part.strip() for part in re.split(r"\s+-\s+", clean, maxsplit=1)]
    if len(parts) != 2:
        return clean, ""
    left, right = parts
    words = left.split()
    if len(words) == 2:
        author = f"{words[1]} {words[0]}"
    else:
        author = left
    return right, author


# Obecne slozky co nejsou autor; porovnava se normalizovany token.
_FOLDER_AUTHOR_STOPWORDS = {
    "knihy", "kniha", "books", "book", "ebooks", "ebook", "audiobooks",
    "audioknihy", "kindle", "calibre", "library", "knihovna", "komiksy",
    "stahnute", "downloads", "temp", "tmp", "authors", "various",
}


def folder_author_hint(parent_name: str) -> str:
    """Vrati autora ze jmena slozky kdyz vypada jako jmeno osoby, jinak "".

    Konzervativni: presne dve slova, obe pismenna (vc. diakritiky a teckovych
    iniciel), zacinaji velkym pismenem, zadne stopword. Poradi jmeno/prijmeni
    nehadame - online nalez kanonicky tvar opravi.
    """
    repaired = repair_filename_text(parent_name)
    tokens = repaired.split()
    if len(tokens) != 2:
        return ""
    if {normalize_text(token) for token in tokens} & _FOLDER_AUTHOR_STOPWORDS:
        return ""
    for token in tokens:
        core = token.rstrip(".")
        if not core or not core[0].isupper() or not all(ch.isalpha() or ch in "-." for ch in token):
            return ""
    return repaired


def import_signal_from_path(path: str | Path) -> ImportSourceSignal:
    file_path = Path(path)
    title, authors = split_author_title_from_filename(file_path.stem)
    if not authors and len(file_path.parts) >= 2:
        authors = folder_author_hint(file_path.parts[-2])
    folder_text = repair_filename_text(" ".join(part for part in file_path.parts[:-1] if part))
    return ImportSourceSignal(
        source="filename",
        title=title,
        authors=authors,
        text=folder_text,
        confidence=30,
    )


METADATA_SIGNAL_SOURCES = {"epub-metadata", "ebook-meta"}


def import_signal_from_book_metadata(metadata: EpubMetadata, source: str = "ebook-meta") -> ImportSourceSignal:
    return ImportSourceSignal(
        source=source,
        title=metadata.title,
        authors=metadata.authors,
        language=metadata.language,
        publisher=metadata.publisher,
        published_year=metadata.published_year,
        confidence=60 if metadata.title and metadata.authors else 30,
    )


def import_signal_from_epub_metadata(metadata: EpubMetadata) -> ImportSourceSignal:
    return import_signal_from_book_metadata(metadata, source="epub-metadata")


def import_signal_from_epub_text(text: str) -> ImportSourceSignal:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ImportSourceSignal(source="epub-text", text="\n".join(lines[:20]), confidence=20)


def import_signal_from_ai_extraction(identity: AIBookIdentity) -> ImportSourceSignal | None:
    """Z AI extrakce udela signal s nejvyssi prioritou; bez nazvu vrati None."""
    if not identity.title.strip():
        return None
    return ImportSourceSignal(
        source="ai-text",
        title=_sentence_case_if_all_caps(identity.title.strip()),
        authors=normalize_author_display_names(identity.author.strip()),
        confidence=max(0, min(identity.confidence, 100)),
    )


def has_known_mojibake(text: str) -> bool:
    return any(broken in text for broken in MOJIBAKE_REPLACEMENTS)


# Pripony jmena (Jr., III, PhD); za carkou nejde o krestni jmeno -> neprehazovat.
_AUTHOR_NAME_SUFFIXES = {
    "jr", "sr", "ii", "iii", "iv", "v", "phd", "md", "dds", "esq",
}

# Slova typicka pro firmu/organizaci; takove nazvy nikdy neprehazujeme.
_AUTHOR_ORG_KEYWORDS = {
    "inc", "ltd", "llc", "gmbh", "co", "corp", "corporation", "company",
    "press", "verlag", "publishing", "publishers", "books", "edition",
    "editions", "foundation", "association", "university", "institute",
    "society", "group", "team",
}


def _looks_like_name_suffix(text: str) -> bool:
    return text.replace(".", "").strip().lower() in _AUTHOR_NAME_SUFFIXES


def _looks_like_organization(text: str) -> bool:
    tokens = {token.strip(".,").lower() for token in text.split()}
    return bool(tokens & _AUTHOR_ORG_KEYWORDS)


def _is_all_caps(text: str) -> bool:
    """Pozna text psany jen velkymi pismeny (ma pismena, zadne male)."""
    return any(char.isalpha() for char in text) and not any(char.islower() for char in text)


def _fix_all_caps_name(name: str) -> str:
    """Cele velkymi psane osobni jmeno prevede na 'Jmeno Prijmeni'. Firmy necha."""
    if _is_all_caps(name) and not _looks_like_organization(name):
        return name.title()
    return name


def _sentence_case_if_all_caps(title: str) -> str:
    """Cele velkymi psany nazev prevede na vetnou podobu (jen prvni pismeno velke)."""
    if not _is_all_caps(title):
        return title
    lowered = title.lower()
    return lowered[:1].upper() + lowered[1:]


def normalize_author_display_name(name: str) -> str:
    """Prevede jednoho autora z razeneho tvaru 'Prijmeni, Jmeno' na 'Jmeno Prijmeni'.

    Konzervativni: prehodi jen jednoznacne osobni jmeno s prave jednou carkou.
    Nejasne pripady (vic carek, pripona za carkou, firma, prazdne) necha beze zmeny.
    Cele velkymi psane jmeno navic prevede na spravne psani (JULES VERNE -> Jules Verne).
    """
    stripped = _fix_all_caps_name(name.strip())
    if stripped.count(",") != 1:
        return stripped
    last, first = (part.strip() for part in stripped.split(","))
    if not last or not first:
        return stripped
    if _looks_like_name_suffix(first):
        return stripped
    if _looks_like_organization(last) or _looks_like_organization(first):
        return stripped
    return f"{first} {last}"


def normalize_author_display_names(authors: str) -> str:
    """Normalizuje cely retezec autoru oddeleny ' & ' na zobrazeny tvar."""
    if not authors.strip():
        return authors
    # Delic autoru je ampersand obklopeny mezerami (" & "); bare "&" uvnitr slov
    # (AT&T, R&D) neni delic a zustane soucasti jmena.
    parts = [part.strip() for part in re.split(r"\s+&\s+", authors) if part.strip()]
    return " & ".join(normalize_author_display_name(part) for part in parts)


def is_junk_signal(signal: ImportSourceSignal) -> bool:
    """Pozna signal jehoz nazev vypada jako z nazvu souboru (junk).

    Marker: podtrzitko v nazvu. Realne nazvy knih '_' nemaji, filename-derived ano.
    """
    return "_" in signal.title


def signal_preview_quality(signal: ImportSourceSignal) -> tuple[int, int, int, int]:
    preview_text = " ".join(part for part in (signal.title, signal.authors) if part.strip())
    clean_bonus = 100 if preview_text and not has_known_mojibake(preview_text) else 0
    completeness = int(bool(signal.title.strip())) + int(bool(signal.authors.strip()))
    not_junk = 0 if (is_junk_signal(signal) or not signal.title.strip()) else 1
    return not_junk, completeness, clean_bonus, signal.confidence


def choose_initial_import_preview(signals: Sequence[ImportSourceSignal]) -> ImportPreview:
    preview_signal = max(signals, key=_import_selection_key) if signals else ImportSourceSignal(source="")
    metadata_signal = next((signal for signal in signals if signal.source in METADATA_SIGNAL_SOURCES), None)
    return ImportPreview(
        title=preview_signal.title,
        authors=normalize_author_display_names(preview_signal.authors),
        published_year=metadata_signal.published_year if metadata_signal else "",
        publisher=metadata_signal.publisher if metadata_signal else "",
    )


def import_preview_from_candidate(candidate: ImportCandidate | None, fallback: ImportPreview) -> ImportPreview:
    if candidate is None:
        return fallback
    return replace(
        fallback,
        title=candidate.title or fallback.title,
        authors=normalize_author_display_names(candidate.authors or fallback.authors),
        url=candidate.url,
        source=candidate.source,
        work_type=candidate.work_type,
    )


def build_manual_import_candidate(url: str, item: MultiImportBatchItem) -> ImportCandidate:
    """Vytvori "rucniho" kandidata z URL, kterou uzivatel zna jako spravnou.

    Nazev a autory prebira z aktualniho nahledu polozky (nic se nestahuje);
    slouzi jen k tomu, aby se do nahledu propsal zvoleny odkaz.
    """
    preview = item.current_preview or ImportPreview()
    return ImportCandidate(
        source="manual",
        title=preview.title,
        authors=preview.authors,
        url=url.strip(),
        score=0,
        reason="manual",
    )


def select_multiimport_candidate(
    item: MultiImportBatchItem,
    candidate: ImportCandidate,
) -> None:
    """Rucne vybere kandidata pro polozku a potvrdi ji pro import.

    Prepocita jen nahled (`current_preview`) podle kandidata a nastavi
    `manually_confirmed`, takze polozka smi projit zapisem i bez 100% shody.
    Nic nezapisuje. U polozek s chybou analyzy nedela nic.
    """
    if item.status == "analysis_error" or item.analysis is None:
        return
    fallback = item.current_preview or item.analysis.preview
    item.selected_candidate = candidate
    item.current_preview = import_preview_from_candidate(candidate, fallback)
    item.manually_confirmed = True


class DisabledAIResolver:
    """Vypnuta AI vrstva: nikdy nevybira kandidata."""

    def resolve(self, signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> AIImportChoice | None:
        return None

    def extract(self, text: str) -> AIBookIdentity:
        return AIBookIdentity()


def _extract_json_object(raw: str) -> str:
    """Z odpovedi modelu vytahne cisty JSON objekt.

    Modely casto obali JSON do markdown plotu (```json ... ```) nebo pridaji text.
    Vezmeme od prvni '{' po posledni '}'.
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


class OllamaAIResolver:
    """Volitelna lokalni AI vrstva pres Ollama; pri chybe tise ustoupi."""

    def __init__(
        self,
        model: str = "llama3",
        requester: Callable[[str, bytes, dict[str, str]], str] | None = None,
        timeout: int = 120,
    ) -> None:
        self.model = model.strip() or "llama3"
        self.requester = requester or self._request
        # Vyssi default kvuli cold startu: prvni dotaz nacita model do pameti,
        # u vetsich modelu (14B) to klidne presahne 20 s.
        self.timeout = timeout

    def _request(self, url: str, payload: bytes, headers: dict[str, str]) -> str:
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def resolve(self, signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> AIImportChoice | None:
        compact_candidates = [
            {
                "source": candidate.source,
                "title": candidate.title,
                "authors": candidate.authors,
                "url": candidate.url,
                "score": candidate.score,
                "reason": candidate.reason,
                "work_type": candidate.work_type,
                "evidence_text": candidate.evidence_text[:500],
            }
            for candidate in candidates[:5]
        ]
        prompt = {
            "task": "Choose the correct book candidate. Return JSON only: {\"url\":\"...\",\"confidence\":0-100,\"reason\":\"...\"}.",
            "signals": [signal.__dict__ for signal in signals],
            "candidates": compact_candidates,
        }
        try:
            raw = self.requester(
                "http://127.0.0.1:11434/api/generate",
                json.dumps({"model": self.model, "prompt": json.dumps(prompt, ensure_ascii=False), "stream": False}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
            data = json.loads(raw)
            answer = json.loads(_extract_json_object(str(data.get("response", "{}"))))
            return AIImportChoice(
                url=str(answer.get("url", "")),
                confidence=int(answer.get("confidence", 0) or 0),
                reason=str(answer.get("reason", "")),
            )
        except Exception:
            return None

    def extract(self, text: str) -> AIBookIdentity:
        """Z textu zacatku knihy vytahne skutecny nazev a autora. Pri chybe vrati prazdny."""
        prompt = {
            "task": "Extract the real book title and author from this book opening text. The real title and author usually appear near the top, before any filename-derived noise. Return JSON only: {\"title\":\"...\",\"author\":\"...\",\"confidence\":0-100}.",
            "text": text[:4000],
        }
        logger.info("AI extrakce: model=%s, delka textu=%d znaku", self.model, len(text))
        try:
            raw = self.requester(
                "http://127.0.0.1:11434/api/generate",
                json.dumps({"model": self.model, "prompt": json.dumps(prompt, ensure_ascii=False), "stream": False}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
            data = json.loads(raw)
            answer = json.loads(_extract_json_object(str(data.get("response", "{}"))))
            identity = AIBookIdentity(
                title=str(answer.get("title", "")),
                author=str(answer.get("author", "")),
                confidence=int(answer.get("confidence", 0) or 0),
            )
            logger.info(
                "AI extrakce vysledek: nazev=%r autor=%r confidence=%d",
                identity.title, identity.author, identity.confidence,
            )
            return identity
        except Exception as exc:
            logger.warning("AI extrakce selhala: %s", exc)
            return AIBookIdentity()


class _CloudAIResolver:
    """Spolecny zaklad pro cloudove AI (Anthropic, OpenAI).

    Stejne prompty a stejne zpracovani odpovedi jako Ollama, jen jiny transport.
    Podtrida dodava default_model, endpoint, hlavicky a zpusob slozeni payloadu
    pres metodu _complete(): ta posle prompt a vrati cisty text odpovedi modelu.

    Bez API klice nikdy nevola sit: extract vrati prazdny vysledek, resolve None.
    Pri jakekoli chybe tise ustoupi (jako Ollama), aby import nespadl.
    """

    default_model = ""

    def __init__(
        self,
        model: str = "",
        api_key: str = "",
        requester: Callable[[str, bytes, dict[str, str]], str] | None = None,
        timeout: int = 120,
    ) -> None:
        self.model = model.strip() or self.default_model
        self.api_key = (api_key or "").strip()
        self.requester = requester or self._request
        self.timeout = timeout

    def _request(self, url: str, payload: bytes, headers: dict[str, str]) -> str:
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def _complete(self, prompt: dict) -> str:
        """Podtrida: posle prompt na cloud a vrati cisty text odpovedi modelu."""
        raise NotImplementedError

    def extract(self, text: str) -> AIBookIdentity:
        """Z textu zacatku knihy vytahne nazev a autora. Pri chybe/bez klice prazdny."""
        if not self.api_key:
            logger.warning("AI extrakce preskocena: chybi API klic pro %s", type(self).__name__)
            return AIBookIdentity()
        prompt = {
            "task": "Extract the real book title and author from this book opening text. The real title and author usually appear near the top, before any filename-derived noise. Keep the title in the SAME LANGUAGE as the text - do NOT translate it and do NOT replace a translated work's title with its original-language title. Only fix garbling, OCR errors, and capitalization, using the author's bibliography to recognize the correct spelling of that same title. Return JSON only: {\"title\":\"...\",\"author\":\"...\",\"confidence\":0-100}.",
            "text": text[:4000],
        }
        logger.info("AI extrakce: model=%s, delka textu=%d znaku", self.model, len(text))
        try:
            answer = json.loads(_extract_json_object(self._complete(prompt)))
            identity = AIBookIdentity(
                title=str(answer.get("title", "")),
                author=str(answer.get("author", "")),
                confidence=int(answer.get("confidence", 0) or 0),
            )
            logger.info(
                "AI extrakce vysledek: nazev=%r autor=%r confidence=%d",
                identity.title, identity.author, identity.confidence,
            )
            return identity
        except Exception as exc:
            logger.warning("AI extrakce selhala: %s", exc)
            return AIBookIdentity()

    def resolve(self, signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> AIImportChoice | None:
        if not self.api_key:
            return None
        compact_candidates = [
            {
                "source": candidate.source,
                "title": candidate.title,
                "authors": candidate.authors,
                "url": candidate.url,
                "score": candidate.score,
                "reason": candidate.reason,
                "work_type": candidate.work_type,
                "evidence_text": candidate.evidence_text[:500],
            }
            for candidate in candidates[:5]
        ]
        prompt = {
            "task": "Choose the correct book candidate. Return JSON only: {\"url\":\"...\",\"confidence\":0-100,\"reason\":\"...\"}.",
            "signals": [signal.__dict__ for signal in signals],
            "candidates": compact_candidates,
        }
        try:
            answer = json.loads(_extract_json_object(self._complete(prompt)))
            return AIImportChoice(
                url=str(answer.get("url", "")),
                confidence=int(answer.get("confidence", 0) or 0),
                reason=str(answer.get("reason", "")),
            )
        except Exception:
            return None


class AnthropicAIResolver(_CloudAIResolver):
    """Cloud AI pres Anthropic Messages API (Claude)."""

    default_model = "claude-sonnet-4-6"

    def _complete(self, prompt: dict) -> str:
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        }).encode("utf-8")
        raw = self.requester(
            "https://api.anthropic.com/v1/messages",
            payload,
            {
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        data = json.loads(raw)
        blocks = data.get("content", []) if isinstance(data, dict) else []
        return "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")


class OpenAIAIResolver(_CloudAIResolver):
    """Cloud AI pres OpenAI Chat Completions API (GPT)."""

    default_model = "gpt-4o"

    def _complete(self, prompt: dict) -> str:
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        }).encode("utf-8")
        raw = self.requester(
            "https://api.openai.com/v1/chat/completions",
            payload,
            {
                "content-type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        data = json.loads(raw)
        return str(data["choices"][0]["message"]["content"])


# Mapa provideru na jmeno promenne prostredi, kde hledame jeho API klic.
AI_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Precte jednoduchy .env soubor (KEY=VALUE na radek). Chybejici soubor = prazdno.

    Ignoruje prazdne radky a komentare (#). Hodnotu zbavi mezer a uvozovek.
    """
    values: dict[str, str] = {}
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'").strip()
    return values


def read_api_key(
    provider: str,
    environ: dict[str, str] | None = None,
    env_path: Path | None = None,
) -> str:
    """Vrati API klic pro daneho cloud providera.

    Priorita: promenna prostredi > soubor .env v korenu projektu. Kdyz nic, "".
    Klic se zamerne necte ze settings.json, aby neskoncil v souboru nastaveni.
    """
    env_name = AI_PROVIDER_ENV_VARS.get(provider)
    if not env_name:
        return ""
    environ = os.environ if environ is None else environ
    from_env = (environ.get(env_name) or "").strip()
    if from_env:
        return from_env
    env_path = env_path if env_path is not None else Path(__file__).resolve().parent / ".env"
    return _parse_env_file(env_path).get(env_name, "").strip()


def build_ai_resolver(
    provider: str,
    model: str = "",
    timeout: int = 120,
    api_key: str | None = None,
    key_reader: Callable[[str], str] | None = None,
) -> object:
    """Podle nazvu providera slozi odpovidajici resolver.

    Pro cloud providery vezme klic z api_key, nebo (kdyz je None) ho precte
    pres key_reader (default read_api_key). Neznamy/vypnuty provider -> Disabled.
    """
    if provider == "ollama":
        return OllamaAIResolver(model, timeout=timeout)
    if provider in ("anthropic", "openai"):
        reader = key_reader or read_api_key
        key = reader(provider) if api_key is None else api_key
        cls = AnthropicAIResolver if provider == "anthropic" else OpenAIAIResolver
        return cls(model, api_key=key, timeout=timeout)
    return DisabledAIResolver()


def extract_ai_identity(text: str, resolver: object | None) -> AIBookIdentity:
    """Bezpecne zavola AI extraktor; pri vypnute AI nebo chybe vrati prazdny vysledek."""
    extractor = getattr(resolver, "extract", None) if resolver else None
    if not callable(extractor):
        logger.info("AI extrakce preskocena: AI vypnuta nebo bez extraktoru")
        return AIBookIdentity()
    if not text.strip():
        logger.info("AI extrakce preskocena: prazdny text knihy")
        return AIBookIdentity()
    try:
        result = extractor(text)
    except Exception as exc:
        logger.warning("AI extrakce selhala: %s", exc)
        return AIBookIdentity()
    return result if isinstance(result, AIBookIdentity) else AIBookIdentity()


def resolve_import_candidate_with_ai(
    signals: Sequence[ImportSourceSignal],
    candidates: Sequence[ImportCandidate],
    resolver: object | None = None,
    minimum_score: int = 80,
    ai_override_margin: int = 30,
) -> ImportCandidate | None:
    if not candidates:
        return None
    best_score = max(candidate.score for candidate in candidates)
    # Jedina jasna 100% shoda: AI se neptame vubec. Je to nejdrazsi cast analyzy
    # (~47 % casu) a rozhodovat neni o cem. Kdyz je 100% shod vic (ruzne URL),
    # nebo nejlepsi shoda neni 100%, AI dal rozhoduje jako driv.
    hundred_urls = {
        candidate.url.strip()
        for candidate in candidates
        if candidate.score >= 100 and candidate.url.strip()
    }
    if candidates[0].score >= 100 and len(hundred_urls) == 1:
        return candidates[0]
    ai_resolver = resolver or DisabledAIResolver()
    try:
        choice = ai_resolver.resolve(signals, candidates) if hasattr(ai_resolver, "resolve") else None
    except Exception:
        choice = None
    try:
        confidence = int(getattr(choice, "confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(confidence, 100))
    if choice and confidence >= 80:
        for candidate in candidates:
            # AI smi rozhodnout jen tesny souboj. Kdyz je jeho kandidat o hodne
            # slabsi nez nejlepsi online shoda (napr. 11 vs 100), nesmi ji prebit.
            if candidate.url == getattr(choice, "url", "") and (best_score - candidate.score) <= ai_override_margin:
                reason = f"{candidate.reason};ai={confidence}"
                choice_reason = str(getattr(choice, "reason", ""))
                if choice_reason:
                    reason = f"{reason}:{choice_reason}"
                return replace(candidate, reason=reason)
    return candidates[0] if candidates[0].score >= minimum_score else None


def analyze_book_for_import(
    path: str | Path,
    library: str | Path,
    settings: dict[str, object],
    online_lookup: Callable[[Sequence[ImportSourceSignal]], list[ImportCandidate]] | None = None,
    ai_resolver: object | None = None,
    epub_metadata_reader: Callable[..., EpubMetadata] = read_epub_metadata,
    epub_text_reader: Callable[..., str] = extract_epub_start_text,
    ebook_metadata_reader: Callable[..., EpubMetadata] = read_book_metadata_with_ebook_meta,
    ebook_text_reader: Callable[..., str] = extract_book_start_text_with_convert,
) -> ImportAnalysis:
    """Analyza importu podle pripony souboru.

    .epub jede stdlib cestou (beze zmeny). .mobi/.azw3/.pdb pres Calibre nastroje.
    Jine pripony vyhodi ValueError - picker je nepusti, tady jen ciste selze.
    Spolecna cast (online lookup, scoring, AI, preview) je pro vsechny stejna.
    """
    book_path = Path(path)
    suffix = book_path.suffix.lower()
    limit = int(settings.get("epub_text_limit", 5000) or 5000)
    if suffix == ".epub":
        metadata = epub_metadata_reader(book_path)
        text = epub_text_reader(book_path, limit=limit)
    elif suffix in EBOOK_TOOL_FORMATS:
        metadata = ebook_metadata_reader(book_path, str(settings.get("ebook_meta_path", "ebook-meta")))
        text = ebook_text_reader(book_path, str(settings.get("ebook_convert_path", "ebook-convert")), limit=limit)
    else:
        raise ValueError("unsupported-format")
    signals = [
        import_signal_from_book_metadata(metadata, source="epub-metadata" if suffix == ".epub" else "ebook-meta"),
        import_signal_from_epub_text(text),
        import_signal_from_path(book_path),
    ]
    ai_signal = import_signal_from_ai_extraction(extract_ai_identity(text, ai_resolver))
    if ai_signal:
        signals.insert(0, ai_signal)
    try:
        candidates = score_import_candidates(signals, online_lookup(signals)) if online_lookup else lookup_import_candidates(signals)
    except Exception:
        candidates = []
    recommended = resolve_import_candidate_with_ai(signals, candidates, ai_resolver)
    fallback_preview = choose_initial_import_preview(signals)
    preview = import_preview_from_candidate(recommended, fallback_preview)
    return ImportAnalysis(
        epub_path=str(book_path),
        signals=signals,
        candidates=candidates,
        recommended=recommended,
        duplicates=[],
        preview=preview,
        messages=[],
    )


def analyze_epub_for_import(
    path: str | Path,
    library: str | Path,
    settings: dict[str, object],
    online_lookup: Callable[[Sequence[ImportSourceSignal]], list[ImportCandidate]] | None = None,
    ai_resolver: object | None = None,
) -> ImportAnalysis:
    """Zpetne kompatibilni vstup pro EPUB; deleguje na analyze_book_for_import."""
    return analyze_book_for_import(path, library, settings, online_lookup, ai_resolver)


def copy_cover_fields(source: MatchRow, target: MatchRow) -> MatchRow:
    """Prenese stav obalek ze stareho radku do noveho radku."""
    same_url = source.chosen_url.strip() == target.chosen_url.strip()
    return replace(
        target,
        cover_urls=source.cover_urls if same_url else "",
        selected_cover_url=source.selected_cover_url if same_url else "",
        cover_reason=source.cover_reason if same_url else "",
        review_published_year=source.review_published_year,
        review_publisher=source.review_publisher,
        review_tags=source.review_tags,
        review_rating_percent=source.review_rating_percent,
        review_original_title=source.review_original_title,
        review_original_publication=source.review_original_publication,
        review_original_publisher=source.review_original_publisher,
    )


def normalize_text(text: str) -> str:
    """Sjednoti text pro porovnani nazvu a autoru."""
    without_series_number = re.sub(r"\(\s*\d+\s*\)", " ", text)
    decomposed = unicodedata.normalize("NFKD", without_series_number)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_punctuation = re.sub(r"[^a-z0-9]+", " ", without_marks.lower())
    normalized_spaces = re.sub(r"\s+", " ", without_punctuation)
    return normalized_spaces.strip()


# Priorita zdroju pro vyber nazvu/autora a nahledu.
# Vyssi cislo = duveryhodnejsi zdroj. Text z AI extrakce je nejjistejsi,
# pak metadata v souboru, pak nazev souboru/slozky, pak holy text.
_SOURCE_PRIORITY = {
    "ai-text": 4,
    "ebook-meta": 3,
    "epub-metadata": 3,
    "filename": 2,
    "epub-text": 1,
}


def _source_priority(signal: ImportSourceSignal) -> int:
    return _SOURCE_PRIORITY.get(signal.source, 0)


def _import_selection_key(signal: ImportSourceSignal) -> tuple[int, int, int, int, int, int]:
    """Klic pro vyber nejlepsiho signalu.

    Poradi vah:
    1. not_junk - junk/prazdny nazev nikdy nevyhraje (zamcene chovani)
    2. ai_is_top - AI extrakce z textu je nejjistejsi, prebije i uplnost
    3. completeness - uplnejsi zaznam (nazev+autor) pred neuplnym
    4. clean_bonus - cisty text pred mojibake
    5. source_priority - mezi zbytkem: metadata pred nazvem souboru
    6. confidence - posledni rozhodci
    """
    not_junk, completeness, clean_bonus, confidence = signal_preview_quality(signal)
    ai_is_top = 1 if signal.source == "ai-text" else 0
    return (not_junk, ai_is_top, completeness, clean_bonus, _source_priority(signal), confidence)


def _best_normalized_title(signals: Sequence[ImportSourceSignal]) -> str:
    title_signals = [signal for signal in signals if signal.title.strip()]
    if not title_signals:
        return ""
    return max(title_signals, key=_import_selection_key).title


def _best_normalized_authors(signals: Sequence[ImportSourceSignal]) -> str:
    author_signals = [signal for signal in signals if signal.authors.strip()]
    if not author_signals:
        return ""
    return max(author_signals, key=_import_selection_key).authors


def _signal_book(signals: Sequence[ImportSourceSignal]) -> Book:
    title = _best_normalized_title(signals)
    authors = [part.strip() for part in _best_normalized_authors(signals).split("&") if part.strip()]
    return Book(0, title, authors)


def _conventional_signal_book(signals: Sequence[ImportSourceSignal]) -> Book:
    """Dotaz z klasickych zdroju (nazev souboru, metadata) - bez AI extrakce."""
    conventional = [signal for signal in signals if signal.source != "ai-text"]
    return _signal_book(conventional)


def _ai_signal_book(signals: Sequence[ImportSourceSignal]) -> Book:
    """Dotaz z AI extrakce; prazdny Book kdyz zadny ai-text signal neni."""
    ai_signals = [signal for signal in signals if signal.source == "ai-text"]
    return _signal_book(ai_signals) if ai_signals else Book(0, "", [])


def _import_query_seeds(signals: Sequence[ImportSourceSignal]) -> list[Book]:
    """Postavi seedy pro online hledani: AI dotaz + klasicky dotaz.

    Shodne seedy (po normalizaci) sloucime, at AI ktera souhlasi nestoji navic.
    Kdyz oba prazdne, vrati jeden fallback z best signalu.
    """
    seeds: list[Book] = []
    seen: set[tuple[str, str]] = set()
    for book in (_ai_signal_book(signals), _conventional_signal_book(signals)):
        if not book.title.strip():
            continue
        key = (normalize_text(book.title), normalize_text(" ".join(book.authors)))
        if key in seen:
            continue
        seen.add(key)
        seeds.append(book)
    return seeds or [_signal_book(signals)]


def _word_overlap_score(left: str, right: str) -> int:
    left_words = set(normalize_text(left).split())
    right_words = set(normalize_text(right).split())
    if not left_words or not right_words:
        return 0
    overlap = left_words & right_words
    if len(overlap) == 1 and max(len(left_words), len(right_words)) > 1:
        return 10
    return int(60 * len(overlap) / max(len(left_words), len(right_words)))


def _terminal_inflection_title_variant(title: str) -> str:
    """Vrati uzky fallback pro ceskou koncovku posledniho slova a/e."""
    match = re.match(r"^(.*\s)([^\W\d_]{6,})$", title.strip(), flags=re.UNICODE)
    if not match or not match.group(2).casefold().endswith("a"):
        return ""
    word = match.group(2)
    replacement = "E" if word[-1].isupper() else "e"
    return match.group(1) + word[:-1] + replacement


def _titles_match_terminal_inflection(left: str, right: str) -> bool:
    left_words = normalize_text(left).split()
    right_words = normalize_text(right).split()
    if len(left_words) < 3 or len(left_words) != len(right_words) or left_words[:-1] != right_words[:-1]:
        return False
    left_last = left_words[-1]
    right_last = right_words[-1]
    return (
        len(left_last) >= 6
        and len(left_last) == len(right_last)
        and left_last[:-1] == right_last[:-1]
        and {left_last[-1], right_last[-1]} == {"a", "e"}
    )


def _authors_text(authors: Sequence[str] | str) -> str:
    if isinstance(authors, str):
        return authors
    return " & ".join(authors)


def duplicate_score(preview: ImportPreview, book: Book) -> tuple[int, str]:
    book_authors = _authors_text(book.authors)
    title_score = (
        100
        if normalize_text(preview.title) == normalize_text(book.title)
        else _word_overlap_score(preview.title, book.title)
    )
    author_score = (
        100
        if normalize_text(preview.authors) == normalize_text(book_authors)
        else _word_overlap_score(preview.authors, book_authors)
    )
    if author_score >= 80 and title_score >= 80:
        return 100, "title-author"
    if author_score >= 50 and title_score >= 50:
        return 70, "similar-title-author"
    if title_score >= 80 and author_score < 50:
        return 55, "same-title-different-author"
    return 0, ""


def find_import_duplicates(preview: ImportPreview, books: Sequence[Book]) -> list[DuplicateCandidate]:
    duplicates: list[DuplicateCandidate] = []
    for book in books:
        score, reason = duplicate_score(preview, book)
        if score <= 0:
            continue
        duplicates.append(
            DuplicateCandidate(
                book_id=book.id,
                title=book.title,
                authors=_authors_text(book.authors),
                score=score,
                reason=reason,
                strong=score >= 90,
            )
        )
    return sorted(duplicates, key=lambda item: item.score, reverse=True)


def parse_calibredb_add_book_ids(output: str) -> list[int]:
    match = re.search(r"Added book ids?:\s*([0-9,\s]+)", output or "", re.IGNORECASE)
    if not match:
        return []
    return [int(value) for value in re.findall(r"\d+", match.group(1))]


def read_calibre_book_ids(library: str | Path) -> set[int]:
    with open_calibre_db_readonly(library) as connection:
        return {int(row["id"]) for row in connection.execute("select id from books").fetchall()}


def _import_set_metadata_args(calibredb_path: str, library: str | Path, book_id: int, preview: ImportPreview) -> list[str]:
    args = [
        calibredb_path,
        "set_metadata",
        str(book_id),
        "--with-library",
        str(library),
        "--field",
        "title:" + preview.title,
        "--field",
        "authors:" + preview.authors,
    ]
    if preview.title:
        args.extend(["--field", "title_sort:" + preview.title])
    if preview.comment:
        args.extend(["--field", "comments:" + preview.comment])
    if preview.published_year:
        args.extend(["--field", "pubdate:" + calibre_pubdate_value(preview.published_year)])
    if preview.publisher:
        args.extend(["--field", "publisher:" + preview.publisher])
    if preview.tags:
        args.extend(["--field", "tags:" + preview.tags])
    if preview.series:
        args.extend(["--field", "series:" + preview.series])
    if preview.series_index:
        args.extend(["--field", "series_index:" + preview.series_index])
    return args


def import_preview_to_match_row(book_id: int, preview: ImportPreview) -> MatchRow:
    return MatchRow(
        book_id,
        preview.title,
        preview.authors,
        "review",
        preview.url,
        "",
        "imported",
        "imported",
        preview.source or source_and_work_type_for_url(preview.url)[0],
        preview.work_type,
        "",
        preview.selected_cover_url,
        "",
        preview.published_year,
        preview.publisher,
        preview.tags,
        preview.rating_percent,
        preview.original_title,
        preview.original_publication,
        preview.original_publisher,
    )


def apply_import_preview(
    preview: ImportPreview,
    epub_path: str | Path,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
    existing_ids_reader: Callable[[str | Path], set[int]] = read_calibre_book_ids,
    duplicate_reader: Callable[[str | Path, ImportPreview], list[DuplicateCandidate]] | None = None,
    backup_func: Callable[[str | Path, Path], Path] | None = None,
    rows_reader: Callable[[Path], list[MatchRow]] | None = None,
    rows_writer: Callable[[Path, Iterable[MatchRow], bool], None] | None = None,
    quit_func: Callable[[bool], int] | None = None,
    allow_force: bool = True,
    matches_path: Path = MATCHES_PATH,
) -> ImportApplyResult:
    command_runner = runner or run_command
    read_duplicates = duplicate_reader or find_calibre_import_duplicates
    create_backup_func = backup_func or create_backup
    read_rows = rows_reader or read_matches_csv
    write_rows = rows_writer or write_matches_csv
    if not is_valid_import_preview(preview):
        return ImportApplyResult(0, "failed", "missing-title-or-author")
    if any(item.strong for item in read_duplicates(library, preview)) and not preview.allow_strong_duplicate:
        return ImportApplyResult(0, "failed", "strong-duplicate")
    quit_runner = quit_func or (lambda force: 0)
    quit_result = quit_runner(allow_force)
    if quit_result != 0:
        return ImportApplyResult(0, "failed", "quit-calibre-failed")
    backup_path = create_backup_func(library, Path("backups"))
    before_ids = existing_ids_reader(library)
    fresh_duplicates = read_duplicates(library, preview)
    if any(item.strong for item in fresh_duplicates) and not preview.allow_strong_duplicate:
        return ImportApplyResult(0, "failed", "strong-duplicate-after-close", str(backup_path))
    add_result = command_runner([calibredb_path, "add", str(epub_path), "--with-library", str(library)])
    if add_result.returncode != 0:
        return ImportApplyResult(0, "failed", (add_result.stderr or add_result.stdout).strip(), str(backup_path))
    new_ids = parse_calibredb_add_book_ids(add_result.stdout + "\n" + add_result.stderr)
    if len(new_ids) != 1:
        new_ids = sorted(existing_ids_reader(library) - before_ids)
    if len(new_ids) != 1:
        return ImportApplyResult(0, "failed", "new-book-id-not-unique", str(backup_path))
    book_id = new_ids[0]
    metadata_result = run_metadata_command_with_cover(
        _import_set_metadata_args(calibredb_path, library, book_id, preview),
        preview.selected_cover_url,
        command_runner,
        cover_bytes=preview.cover_bytes,
    )
    if metadata_result.returncode != 0:
        return ImportApplyResult(book_id, "failed", (metadata_result.stderr or metadata_result.stdout).strip(), str(backup_path))
    rows = read_rows(matches_path) if matches_storage_exists(matches_path) else []
    write_rows(matches_path, [*rows, import_preview_to_match_row(book_id, preview)], True)
    return ImportApplyResult(book_id, "updated", "", str(backup_path))


def delete_books_from_calibre(
    library: str | Path,
    book_ids: set[int],
    calibredb_path: str,
    matches_path: Path = MATCHES_PATH,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
    read_rows: Callable[[Path], list[MatchRow]] | None = None,
    write_rows: Callable[[Path, Sequence[MatchRow], bool], object] | None = None,
    storage_exists: Callable[[Path], bool] | None = None,
) -> int:
    """Trvale smaze knihy z Calibre (calibredb remove) a vyhodi je z pracovnich dat.

    Vraci 0 pri uspechu, jinak navratovy kod calibredb. Soubory knih jsou pryc
    natrvalo - tohle neni vratitelne pres rollback metadata.db.
    """
    runner = runner or run_command
    read_rows = read_rows or read_matches_csv
    write_rows = write_rows or write_matches_csv
    storage_exists = storage_exists or matches_storage_exists
    ids = sorted({int(book_id) for book_id in book_ids})
    if not ids:
        return 0
    result = runner([calibredb_path, "remove", ",".join(str(i) for i in ids), "--with-library", str(library)])
    if result.returncode != 0:
        print((result.stderr or result.stdout or "calibredb remove selhalo").strip())
        return result.returncode
    rows = read_rows(matches_path) if storage_exists(matches_path) else []
    id_set = set(ids)
    write_rows(matches_path, [row for row in rows if row.book_id not in id_set], True)
    print(f"Smazano z Calibre: {len(ids)} knih")
    return 0


def _title_similarity_score(left: str, right: str) -> int:
    if (normalize_text(left) == normalize_text(right) or _titles_match_terminal_inflection(left, right)) and left:
        return 70
    return min(70, int(_word_overlap_score(left, right) * 70 / 60))


def _author_similarity_score(signals_author: str, candidate: ImportCandidate) -> int:
    if candidate.source in {"databazeknih", "legie"}:
        if signals_author and candidate.evidence_text and _author_matches_text(signals_author, candidate.evidence_text):
            return 30
        return 0
    if normalize_text(candidate.authors) == normalize_text(signals_author) and signals_author:
        return 30
    if candidate.authors:
        return min(30, int(_word_overlap_score(signals_author, candidate.authors) * 30 / 60))
    return 0


def _score_candidate_for(
    title: str,
    authors: str,
    signals: Sequence[ImportSourceSignal],
    candidate: ImportCandidate,
) -> ImportCandidate:
    """Ohodnoti kandidata proti danemu dotazu (nazev+autor), ne proti vsem signalum."""
    title_score = _title_similarity_score(title, candidate.title)
    author_score = _author_similarity_score(authors, candidate)
    score = title_score + author_score
    reason = f"title={title_score};author={author_score}"
    return replace(candidate, score=score, reason=reason)


def score_import_candidate(signals: Sequence[ImportSourceSignal], candidate: ImportCandidate) -> ImportCandidate:
    return _score_candidate_for(
        _best_normalized_title(signals),
        _best_normalized_authors(signals),
        signals,
        candidate,
    )


def _dedupe_candidates_by_url(candidates: Sequence[ImportCandidate]) -> list[ImportCandidate]:
    """Slouci kandidaty se stejnym URL, nechá ten s nejvyssim skore. Zachova poradi."""
    best: dict[str, ImportCandidate] = {}
    order: list[str] = []
    for candidate in candidates:
        key = candidate.url
        if key not in best:
            best[key] = candidate
            order.append(key)
        elif candidate.score > best[key].score:
            best[key] = candidate
    return [best[key] for key in order]


def score_import_candidates(signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> list[ImportCandidate]:
    scored = [score_import_candidate(signals, candidate) for candidate in candidates]
    return sorted(scored, key=lambda candidate: candidate.score, reverse=True)


def import_lookup_sources(signals: Sequence[ImportSourceSignal]) -> list[str]:
    languages = [signal.language.lower().strip() for signal in signals if signal.language.strip()]
    language_set = set(languages)
    text = normalize_text(" ".join([signal.title + " " + signal.authors + " " + signal.text for signal in signals]))
    if len(languages) >= 2 and language_set == {"cs"}:
        return ["databazeknih", "legie"]
    if len(languages) >= 2 and language_set == {"en"}:
        return ["googlebooks", "openlibrary"]
    if "prelozil" in text or "vydalo" in text:
        return ["databazeknih", "legie"]
    return ["databazeknih", "legie", "googlebooks", "openlibrary"]


def import_candidate_from_search_candidate(
    source: str,
    candidate: Candidate,
    signals: Sequence[ImportSourceSignal],
    work_type: str = "",
) -> ImportCandidate:
    authors = candidate.text.strip() if source in {"googlebooks", "openlibrary"} else ""
    return ImportCandidate(
        source=source,
        title=candidate.title,
        authors=authors,
        url=candidate.url,
        work_type=work_type,
        evidence_text=candidate.text,
    )


def _lookup_import_source(
    source: str,
    book: Book,
    signals: Sequence[ImportSourceSignal],
    fetch: Callable[[str], str],
) -> list[ImportCandidate]:
    if source == "databazeknih":
        html_text = fetch(build_search_url(book.title, book.authors))
        found = [
            import_candidate_from_search_candidate("databazeknih", item, signals)
            for item in parse_search_results(html_text)
        ]
        if found:
            return found
        variant = _terminal_inflection_title_variant(book.title)
        if not variant:
            return []
        fallback_html = fetch(build_search_url(variant, book.authors))
        return [
            import_candidate_from_search_candidate("databazeknih", item, signals)
            for item in parse_search_results(fallback_html)
        ]
    if source == "legie":
        html_text = fetch(build_legie_search_url(book.title, book.authors))
        return [
            import_candidate_from_search_candidate("legie", item, signals, "povidka")
            for item in parse_legie_search_results(html_text)
        ]
    if source == "googlebooks":
        json_text = fetch(build_google_books_search_url(book.title, book.authors))
        return [
            import_candidate_from_search_candidate("googlebooks", item, signals)
            for item in parse_google_books_search_results(json_text)
        ]
    if source == "openlibrary":
        json_text = fetch(build_openlibrary_search_url(book.title, book.authors))
        return [
            import_candidate_from_search_candidate("openlibrary", item, signals)
            for item in parse_openlibrary_search_results(json_text)
        ]
    return []


def lookup_import_candidates(
    signals: Sequence[ImportSourceSignal],
    fetcher: Callable[[str], str] | None = None,
    sleep_seconds: float = 0.0,
) -> list[ImportCandidate]:
    fetch = fetcher or fetch_text
    sources = import_lookup_sources(signals)
    scored: list[ImportCandidate] = []
    for seed in _import_query_seeds(signals):
        seed_authors = " & ".join(seed.authors)
        logger.info("Online hledani: seed nazev=%r autor=%r", seed.title, seed_authors)
        for source in sources:
            try:
                found = _lookup_import_source(source, seed, signals, fetch)
            except Exception:
                found = []
            # Kazdeho kandidata hodnotime proti dotazu, ktery ho nasel.
            scored.extend(_score_candidate_for(seed.title, seed_authors, signals, item) for item in found)
            if sleep_seconds:
                time.sleep(sleep_seconds)
    deduped = _dedupe_candidates_by_url(scored)
    return sorted(deduped, key=lambda candidate: candidate.score, reverse=True)


def lookup_import_candidates_for_query(
    title: str,
    authors: str,
    fetcher: Callable[[str], str] | None = None,
    sleep_seconds: float = 0.0,
) -> list[ImportCandidate]:
    """Online hledani podle rucne zadaneho nazvu a autora (pro 'Hledat znovu')."""
    signal = ImportSourceSignal(source="manual", title=title, authors=authors)
    return lookup_import_candidates([signal], fetcher=fetcher, sleep_seconds=sleep_seconds)


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


def google_books_url(volume_id: str) -> str:
    """Vytvori stabilni Google Books odkaz z volume ID."""
    return "https://books.google.com/books?id=" + urllib.parse.quote(volume_id.strip())


def google_books_volume_id_from_url(url: str) -> str:
    """Vytahne Google Books volume ID z odkazu nebo API URL."""
    parsed = urllib.parse.urlparse(url.strip())
    query_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
    if query_id:
        return query_id
    match = re.search(r"/volumes/([^/?#]+)", url)
    return urllib.parse.unquote(match.group(1)) if match else ""


def is_valid_google_books_url(url: str) -> bool:
    """Pozna Google Books odkaz, ze ktereho umime ziskat volume ID."""
    host = urllib.parse.urlparse(url.strip()).netloc.lower()
    return host.startswith("books.google.") and bool(google_books_volume_id_from_url(url))


def build_google_books_search_url(title: str, authors: Sequence[str]) -> str:
    """Sestavi Google Books API dotaz pro anglicke knihy."""
    query_parts = [f"intitle:{title.strip()}"]
    if authors:
        query_parts.append(f"inauthor:{authors[0].strip()}")
    return GOOGLE_BOOKS_API + "?" + urllib.parse.urlencode(
        {"q": " ".join(query_parts), "printType": "books", "maxResults": "10"}
    )


def openlibrary_edition_key_from_url(url: str) -> str:
    """Vytahne Open Library edition key typu OL123M."""
    match = re.search(r"/books/(OL\d+M)\b", urllib.parse.urlparse(url.strip()).path)
    return match.group(1) if match else ""


def openlibrary_url(edition_key: str) -> str:
    """Vrati webovy Open Library odkaz na edici."""
    return OPEN_LIBRARY_BASE + "/books/" + urllib.parse.quote(edition_key.strip())


def is_valid_openlibrary_url(url: str) -> bool:
    """Pozna Open Library edition URL."""
    host = urllib.parse.urlparse(url.strip()).netloc.lower()
    return host == "openlibrary.org" and bool(openlibrary_edition_key_from_url(url))


def build_openlibrary_search_url(title: str, authors: Sequence[str]) -> str:
    """Sestavi Open Library search API dotaz."""
    params = {"title": title.strip(), "limit": "10"}
    if authors:
        params["author"] = authors[0].strip()
    return OPEN_LIBRARY_SEARCH_API + "?" + urllib.parse.urlencode(params)


def overview_to_book_url(url: str) -> str:
    clean = databaze_absolute_url(url)
    return clean.replace(BASE_URL + "/prehled-knihy/", BASE_URL + "/knihy/", 1)


def book_url_to_overview_url(url: str) -> str:
    clean = databaze_absolute_url(url)
    return clean.replace(BASE_URL + "/knihy/", BASE_URL + "/prehled-knihy/", 1)


def databaze_editions_url(detail_url: str, explicit_url: str = "") -> str:
    """Vrati bezpecny explicitni nebo deterministicky odvozeny odkaz na DK vydani."""
    clean_detail = databaze_absolute_url(detail_url)
    book_id = databaze_book_id_from_url(clean_detail)
    clean_explicit = databaze_absolute_url(explicit_url)
    parsed_explicit = urllib.parse.urlparse(clean_explicit)
    if (
        book_id
        and parsed_explicit.netloc.lower() == "www.databazeknih.cz"
        and parsed_explicit.path.startswith("/dalsi-vydani/")
        and databaze_book_id_from_url(clean_explicit) == book_id
    ):
        return clean_explicit
    for prefix in (BASE_URL + "/prehled-knihy/", BASE_URL + "/knihy/"):
        if clean_detail.startswith(prefix) and book_id:
            return BASE_URL + "/dalsi-vydani/" + clean_detail[len(prefix) :]
    return ""


def canonical_detail_output_url(selected_url: str, resolved_url: str) -> str:
    """Pro DK zachova uzivatelem vybrany odkaz; ostatni zdroje nemeni."""
    selected = selected_url.strip()
    return selected if is_valid_apply_url(selected) else resolved_url


def databaze_book_id_from_url(url: str) -> str:
    """Vytahne ciselne ID knihy z konce DK URL."""
    match = re.search(r"-(\d+)(?:/)?$", databaze_absolute_url(url))
    return match.group(1) if match else ""


def databaze_more_info_url(book_id: str) -> str:
    """Endpoint pro rozbalene DK pole Vice info."""
    return BASE_URL + "/book-detail-more-info/" + book_id


def build_search_url(title: str, authors: Sequence[str]) -> str:
    # Autor pred nazvem: databazeknih fulltext je citlivy na poradi a 'autor nazev'
    # vraci spravny hlavni zaznam, ktery 'nazev autor' casto vynecha.
    query = " ".join(authors) + " " + title
    return SEARCH_URL + urllib.parse.quote_plus(query.strip())


def search_variants(title: str, authors: Sequence[str]) -> list[tuple[str, list[str]]]:
    """Vrati puvodni hledani a fallback bez diakritiky/interpunkce."""
    variants: list[tuple[str, list[str]]] = [(title, list(authors))]
    plain_title = normalize_text(title)
    plain_authors = [normalize_text(author) for author in authors if normalize_text(author)]
    original_title = re.sub(r"\s+", " ", title.strip().lower())
    original_authors = [re.sub(r"\s+", " ", author.strip().lower()) for author in authors]
    if plain_title and (plain_title != original_title or plain_authors != original_authors):
        variants.append((plain_title, plain_authors))
    return variants


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


def legie_book_id_from_url(url: str) -> str:
    """Vytahne ID knihy z kanonickeho Legie book URL nebo jeho podstranky."""
    match = re.search(r"/kniha/(\d+)(?:[-/]|$)", urllib.parse.urlparse(legie_absolute_url(url)).path)
    return match.group(1) if match else ""


def legie_editions_url(detail_url: str, explicit_url: str = "") -> str:
    """Vrati bezpecny explicitni nebo odvozeny Legie odkaz na vydani knihy."""
    clean_detail = legie_absolute_url(detail_url)
    parsed_detail = urllib.parse.urlparse(clean_detail)
    detail_match = re.fullmatch(r"/kniha/(\d+)(?:-[^/]+)?/?", parsed_detail.path)
    if parsed_detail.netloc.lower() != "www.legie.info" or not detail_match:
        return ""
    clean_explicit = legie_absolute_url(explicit_url)
    parsed_explicit = urllib.parse.urlparse(clean_explicit)
    explicit_match = re.fullmatch(r"/kniha/(\d+)(?:-[^/]+)?/vydani/?", parsed_explicit.path)
    if (
        parsed_explicit.netloc.lower() == "www.legie.info"
        and explicit_match
        and explicit_match.group(1) == detail_match.group(1)
    ):
        return clean_explicit.rstrip("/")
    return clean_detail.rstrip("/") + "/vydani"


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
    facts = []
    if detail.original_title:
        facts.append(f"Originalni nazev: {detail.original_title}")
    if detail.original_publication:
        facts.append(f"Originalne vyslo: {detail.original_publication}")
    if facts:
        parts.append("<p>" + "<br />".join(html.escape(item) for item in facts) + "</p>")
    if detail.about_text:
        parts.append(f"<p>{html.escape(detail.about_text)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def _review_tags(value: str) -> list[str] | None:
    tags = [item.strip() for item in value.split(",") if item.strip()]
    return tags if tags else None


def apply_review_overrides(row: MatchRow, detail: BookDetailMetadata) -> BookDetailMetadata:
    """Prekryje web metadata rucne upravenymi hodnotami z Review tabu."""
    return BookDetailMetadata(
        published_year=row.review_published_year.strip() or detail.published_year,
        publisher=row.review_publisher.strip() or detail.publisher,
        series=detail.series,
        series_index=detail.series_index,
        tags=_review_tags(row.review_tags) or detail.tags,
        rating_percent=row.review_rating_percent.strip() or detail.rating_percent,
        original_title=row.review_original_title.strip() or detail.original_title,
        original_publication=row.review_original_publication.strip() or detail.original_publication,
        original_publisher=row.review_original_publisher.strip() or detail.original_publisher,
        about_text=detail.about_text,
        cover_url=detail.cover_url,
    )


def clear_review_overrides(row: MatchRow) -> MatchRow:
    """Smaze rucne/pracovne nactene Review hodnoty, kdyz se zmeni zdroj metadat."""
    return replace(
        row,
        review_published_year="",
        review_publisher="",
        review_tags="",
        review_rating_percent="",
        review_original_title="",
        review_original_publication="",
        review_original_publisher="",
    )


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


class DatabazeMoreInfoParser(HTMLParser):
    """Parser DK bloku Vice info s dvojicemi dt/dd."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}
        self._current_label = ""
        self._parts: list[str] = []
        self._mode = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"dt", "dd"}:
            self._mode = lowered
            self._parts = []
            self._depth = 1
        elif self._depth:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        self._depth -= 1
        if self._depth:
            return
        text = _clean_text(" ".join(self._parts))
        if self._mode == "dt":
            self._current_label = text
        elif self._mode == "dd" and self._current_label:
            self.fields[self._current_label] = text
        self._mode = ""
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._depth and data.strip():
            self._parts.append(data.strip())


def parse_databaze_more_info_fields(html: str) -> dict[str, str]:
    parser = DatabazeMoreInfoParser()
    parser.feed(html)
    parser.close()
    return parser.fields


def is_databaze_audiobook_more_info(html: str) -> bool:
    form = parse_databaze_more_info_fields(html).get("Forma", "")
    return "audiokniha" in normalize_text(form)


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


def _series_metadata_from_blocks(blocks: Sequence[tuple[list[str], str]]) -> tuple[str, str]:
    """Vrati serii z jednoho jednoznacneho DK bloku nad titulkem."""
    if len(blocks) != 1:
        return "", ""
    links, block_text = blocks[0]
    if len(links) != 1:
        return "", ""
    series = _clean_text(links[0])
    if not series:
        return "", ""
    indices = re.findall(r"\b(\d+)\s*\.\s*d[ií]l\b", block_text, flags=re.IGNORECASE)
    if len(indices) > 1:
        return "", ""
    return series, indices[0] if indices else ""


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
        self.cover_url = ""
        self.cover_urls: list[str] = []
        self.main_cover_urls: list[str] = []
        self.visible_text_parts: list[str] = []
        self.detail_fields: list[tuple[str, str]] = []
        self.series_blocks_before_title: list[tuple[list[str], str]] = []

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
        self._inside_detail_label = False
        self._inside_detail_value = False
        self._detail_label_parts: list[str] = []
        self._detail_value_parts: list[str] = []
        self._current_detail_label = ""
        self._title_seen = False
        self._series_block_depth = 0
        self._series_block_parts: list[str] = []
        self._series_links: list[str] = []
        self._series_link_parts: list[str] = []
        self._inside_series_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        lowered_tag = tag.lower()
        href = attrs_dict.get("href", "")

        if lowered_tag == "h1":
            self._title_seen = True

        if not self._title_seen and lowered_tag == "div" and "book_detail_serie_info" in classes:
            if self._series_block_depth:
                self._series_block_depth += 1
            else:
                self._series_block_depth = 1
                self._series_block_parts = []
                self._series_links = []
            return
        if self._series_block_depth:
            self._series_block_depth += 1
            if lowered_tag == "a" and "/serie/" in href:
                self._inside_series_link = True
                self._series_link_parts = []

        if lowered_tag == "script" and attrs_dict.get("type", "").lower() == "application/ld+json":
            self._inside_json_ld = True
            self._json_parts = []
            return

        if not self.editions_url and "/dalsi-vydani/" in href:
            self.editions_url = databaze_absolute_url(href)

        image_url = attrs_dict.get("content", "") if lowered_tag == "meta" else attrs_dict.get("src", "")
        image_key = " ".join(
            part
            for part in (
                attrs_dict.get("property", ""),
                attrs_dict.get("name", ""),
                attrs_dict.get("itemprop", ""),
                attrs_dict.get("class", ""),
                attrs_dict.get("alt", ""),
            )
            if part
        ).lower()
        if not self.cover_url and image_url and _looks_like_cover_image(image_url, image_key):
            normalized = normalize_image_url(image_url)
            self.cover_url = normalized
            self.cover_urls.append(normalized)
        elif image_url and _looks_like_cover_image(image_url, image_key):
            normalized = normalize_image_url(image_url)
            if normalized not in self.cover_urls:
                self.cover_urls.append(normalized)
        if image_url and _looks_like_cover_image(image_url, image_key) and (
            (lowered_tag == "meta" and attrs_dict.get("property", "").lower() == "og:image")
            or attrs_dict.get("itemprop", "").lower() == "image"
        ):
            normalized = normalize_image_url(image_url)
            if normalized not in self.main_cover_urls:
                self.main_cover_urls.append(normalized)

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

        if lowered_tag == "dt":
            self._inside_detail_label = True
            self._detail_label_parts = []

        if lowered_tag == "dd":
            self._inside_detail_value = True
            self._detail_value_parts = []

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()

        if lowered_tag == "a" and self._inside_series_link:
            series = _clean_text(" ".join(self._series_link_parts))
            if series:
                self._series_links.append(series)
            self._series_link_parts = []
            self._inside_series_link = False

        if self._series_block_depth:
            self._series_block_depth -= 1
            if self._series_block_depth == 0 and not self._title_seen:
                self.series_blocks_before_title.append((self._series_links, _clean_text(" ".join(self._series_block_parts))))

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

        if lowered_tag == "dt" and self._inside_detail_label:
            self._current_detail_label = _clean_text(" ".join(self._detail_label_parts))
            self._inside_detail_label = False

        if lowered_tag == "dd" and self._inside_detail_value:
            value = _clean_text(" ".join(self._detail_value_parts))
            if self._current_detail_label and value:
                self.detail_fields.append((self._current_detail_label, value))
            self._inside_detail_value = False

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.visible_text_parts.append(data.strip())
        if self._series_block_depth:
            self._series_block_parts.append(data)
        if self._inside_series_link:
            self._series_link_parts.append(data)
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
        if self._inside_detail_label:
            self._detail_label_parts.append(data)
        if self._inside_detail_value:
            self._detail_value_parts.append(data)


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


def normalize_image_url(url: str) -> str:
    """Prevede relativni URL obrazku na absolutni URL."""
    clean = html.unescape(url.strip())
    if clean.startswith("//"):
        clean = "https:" + clean
    return urllib.parse.urljoin(BASE_URL + "/", clean)


def normalize_legie_image_url(url: str) -> str:
    """Prevede relativni URL obrazku z Legie na absolutni URL."""
    clean = html.unescape(url.strip())
    if clean.startswith("//"):
        clean = "https:" + clean
    return urllib.parse.urljoin(LEGIE_BASE_URL + "/", clean)


def _looks_like_cover_image(url: str, context: str = "") -> bool:
    lowered = (url + " " + context).lower()
    if not url.strip() or lowered.startswith("data:"):
        return False
    if any(skip in lowered for skip in ("blank", "placeholder", "no-cover", "nocover", "avatar", "logo")):
        return False
    if "og:image" in lowered or "itemprop image" in lowered:
        return True
    return any(word in lowered for word in ("obal", "cover", "/img/books", "/knihy/")) and re.search(
        r"\.(jpe?g|png|webp)(?:[?#].*)?$", url, flags=re.IGNORECASE
    ) is not None


def _image_url_from_json(value: object) -> str:
    if isinstance(value, str) and _looks_like_cover_image(value, "json image"):
        return normalize_image_url(value)
    if isinstance(value, dict):
        for key in ("url", "contentUrl"):
            candidate = value.get(key)
            if isinstance(candidate, str) and _looks_like_cover_image(candidate, "json image"):
                return normalize_image_url(candidate)
    if isinstance(value, list):
        for item in value:
            candidate = _image_url_from_json(item)
            if candidate:
                return candidate
    return ""


def _html_to_plain_text(value: str) -> str:
    """Prevede kratky HTML popis z API na citelny text."""
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(html.unescape(text))


def _google_books_image_url(image_links: object) -> str:
    """Vybere nejlepsi dostupnou obalku z Google Books."""
    if not isinstance(image_links, dict):
        return ""
    for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
        value = image_links.get(key)
        if isinstance(value, str) and value.strip():
            return value.replace("http://", "https://", 1)
    return ""


def parse_google_books_volume_metadata(json_text: str) -> tuple[str, BookDetailMetadata]:
    """Prevede Google Books volume JSON na metadata a web odkaz."""
    raw = json.loads(json_text)
    volume_id = str(raw.get("id") or "")
    info = raw.get("volumeInfo") if isinstance(raw, dict) else {}
    if not isinstance(info, dict):
        info = {}
    published = str(info.get("publishedDate") or "")
    rating = ""
    if info.get("averageRating"):
        rating = str(info.get("averageRating")).replace(".", ",") + " / 5"
        if info.get("ratingsCount"):
            rating += f" ({info.get('ratingsCount')} hodnoceni)"
    description = info.get("description") if isinstance(info.get("description"), str) else ""
    categories = info.get("categories") if isinstance(info.get("categories"), list) else []
    tags = _dedupe_tags(str(item) for item in categories if str(item).strip())
    detail = BookDetailMetadata(
        published_year=_first_reasonable_year(published),
        publisher=str(info.get("publisher") or ""),
        tags=tags,
        rating_percent=rating,
        about_text=_html_to_plain_text(description),
        cover_url=_google_books_image_url(info.get("imageLinks")),
    )
    return google_books_url(volume_id), detail


def parse_google_books_search_results(json_text: str) -> list[Candidate]:
    """Vytahne kandidaty z Google Books search odpovedi."""
    raw = json.loads(json_text)
    items = raw.get("items") if isinstance(raw, dict) else []
    if not isinstance(items, list):
        return []
    candidates: list[Candidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        volume_id = str(item.get("id") or "")
        info = item.get("volumeInfo")
        if not volume_id or not isinstance(info, dict):
            continue
        title = str(info.get("title") or "")
        subtitle = str(info.get("subtitle") or "")
        full_title = f"{title}: {subtitle}" if subtitle else title
        authors = info.get("authors") if isinstance(info.get("authors"), list) else []
        text = " ".join(str(author) for author in authors)
        if full_title:
            candidates.append(Candidate(full_title, text, google_books_url(volume_id)))
    return candidates


def _openlibrary_cover_url(covers: object) -> str:
    """Vrati Open Library cover URL z prvniho cover ID."""
    if not isinstance(covers, list) or not covers:
        return ""
    cover_id = str(covers[0]).strip()
    return f"https://covers.openlibrary.org/b/id/{urllib.parse.quote(cover_id)}-L.jpg" if cover_id else ""


def _openlibrary_description(value: object) -> str:
    """Open Library description muze byt string nebo dict s value."""
    if isinstance(value, str):
        return _html_to_plain_text(value)
    if isinstance(value, dict) and isinstance(value.get("value"), str):
        return _html_to_plain_text(value["value"])
    return ""


def parse_openlibrary_edition_metadata(json_text: str) -> tuple[str, BookDetailMetadata]:
    """Prevede Open Library edition JSON na metadata."""
    raw = json.loads(json_text)
    if not isinstance(raw, dict):
        raw = {}
    key = str(raw.get("key") or "")
    edition_key = key.rsplit("/", 1)[-1] if key else ""
    publishers = raw.get("publishers") if isinstance(raw.get("publishers"), list) else []
    subjects = raw.get("subjects") if isinstance(raw.get("subjects"), list) else []
    publish_date = str(raw.get("publish_date") or "")
    detail = BookDetailMetadata(
        published_year=_first_reasonable_year(publish_date),
        publisher=str(publishers[0]) if publishers else "",
        tags=_dedupe_tags(str(subject) for subject in subjects if str(subject).strip()),
        about_text=_openlibrary_description(raw.get("description")),
        cover_url=_openlibrary_cover_url(raw.get("covers")),
    )
    return openlibrary_url(edition_key), detail


def parse_openlibrary_search_results(json_text: str) -> list[Candidate]:
    """Vytahne kandidaty z Open Library search API."""
    raw = json.loads(json_text)
    docs = raw.get("docs") if isinstance(raw, dict) else []
    if not isinstance(docs, list):
        return []
    candidates: list[Candidate] = []
    for item in docs:
        if not isinstance(item, dict):
            continue
        edition_key = ""
        editions = item.get("edition_key")
        if isinstance(editions, list) and editions:
            edition_key = str(editions[0])
        title = str(item.get("title") or "")
        authors = item.get("author_name") if isinstance(item.get("author_name"), list) else []
        text = " ".join(str(author) for author in authors)
        if title and edition_key:
            candidates.append(Candidate(title, text, openlibrary_url(edition_key)))
    return candidates


def _image_urls_from_json(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str) and _looks_like_cover_image(value, "json image"):
        urls.append(normalize_image_url(value))
    elif isinstance(value, dict):
        for key in ("url", "contentUrl"):
            candidate = value.get(key)
            if isinstance(candidate, str) and _looks_like_cover_image(candidate, "json image"):
                urls.append(normalize_image_url(candidate))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_image_urls_from_json(item))
    return list(dict.fromkeys(urls))


def _dedupe_cover_options(options: Sequence[CoverOption]) -> list[CoverOption]:
    seen: set[str] = set()
    result: list[CoverOption] = []
    for option in options:
        if option.url and option.url not in seen:
            seen.add(option.url)
            result.append(option)
    return result


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


def _split_original_title_and_publication(value: str) -> tuple[str, str]:
    """Rozdeli text DK originalniho nazvu na nazev a datum/rok."""
    cleaned = _clean_text(value).strip(" ,")
    match = re.search(r"\(([^)]*(?:\d{4}|\d{1,2}/\d{4})[^)]*)\)\s*$", cleaned)
    if match:
        return cleaned[: match.start()].strip(" ,"), match.group(1).strip()
    match = re.search(r"\b(\d{1,2}/\d{4}|\d{4})\s*$", cleaned)
    if match:
        return cleaned[: match.start()].strip(" ,"), match.group(1).strip()
    return cleaned, ""


def _detail_label_kind(label: str) -> str:
    """Rozpozna DK Vice info popisek bez zavislosti na diakritice."""
    lowered = label.casefold()
    normalized = normalize_text(label)
    has_original = "original" in normalized or "origin" in lowered
    if has_original and ("nazev" in normalized or "zev" in lowered):
        return "original_title"
    if has_original and ("vydavatel" in normalized or "publisher" in normalized):
        return "original_publisher"
    if has_original and ("vysel" in normalized or "rok" in normalized or "vydani" in normalized or ("vy" in lowered and "el" in lowered)):
        return "original_publication"
    if ("puvod" in normalized or "p vod" in normalized) and "vydani" in normalized:
        return "original_publication"
    if "rok" in normalized and "1" in normalized and "vydani" in normalized:
        return "original_publication"
    return ""


def _original_metadata_from_detail_fields(fields: Sequence[tuple[str, str]]) -> tuple[str, str, str]:
    """Vezme originalni udaje z DK Vice info dvojic dt/dd."""
    original_title = ""
    original_publication = ""
    original_publisher = ""
    for label, value in fields:
        kind = _detail_label_kind(label)
        if kind == "original_title":
            original_title, inline_publication = _split_original_title_and_publication(value)
            original_publication = original_publication or inline_publication
        elif kind == "original_publication":
            original_publication = _clean_text(value).strip(" ,")
        elif kind == "original_publisher":
            original_publisher = _clean_text(value).strip(" ,")
    return original_title, original_publication, original_publisher


DK_MORE_INFO_STOP_LABELS = (
    "Autor",
    "PÅ™eklad",
    "Preklad",
    "PoÄet",
    "Pocet",
    "Jazyk",
    "Forma",
    "Vazba",
    "Å½Ã¡nr",
    "Zanr",
    "SÃ©rie",
    "Serie",
    "Rok vydÃ¡nÃ­",
    "VydÃ¡no",
    "Vydano",
    "OriginÃ¡lnÃ­ nÃ¡zev",
    "Originalni nazev",
    "OriginÃ¡l vyÅ¡el",
    "Original vysel",
    "OriginÃ¡lnÃ­ rok vydÃ¡nÃ­",
    "Originalni rok vydani",
    "PÅ¯vodnÃ­ vydÃ¡nÃ­",
    "Puvodni vydani",
    "ISBN",
    "Å tÃ­tky",
    "Stitky",
    "HodnocenÃ­",
    "Hodnoceni",
    "O knize",
)


def _detail_field_value(text: str, labels: Sequence[str]) -> str:
    """Vytahne hodnotu za jednim DK Vice info popiskem."""
    labels_pattern = "|".join(re.escape(label) for label in labels)
    stop_pattern = "|".join(re.escape(label) for label in DK_MORE_INFO_STOP_LABELS)
    match = re.search(
        rf"(?:{labels_pattern}):?\s*(.*?)(?=\s+(?:{stop_pattern})\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_text(match.group(1)).strip(" ,") if match else ""


def _original_metadata_from_text(text: str) -> tuple[str, str]:
    """Najde DK pole Originalni nazev z viditelneho textu stranky."""
    normalized = _clean_text(text)
    match = re.search(
        r"Originální\s+n[áa]zev:?\s*(.*?)(?=\s+(?:Autor|Překlad|Preklad|Počet|Pocet|Jazyk|Forma|Vazba|Žánr|Zanr|Série|Serie|Rok vydání|Vydáno|Vydano|ISBN|Štítky|Stitky|Hodnocení|Hodnoceni|O knize)\b|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return "", ""
    return _split_original_title_and_publication(match.group(1))


def _original_metadata_from_text(text: str) -> tuple[str, str]:
    """Najde DK originalni nazev a samostatny originalni rok z Vice info."""
    normalized = _clean_text(text)
    title_value = _detail_field_value(normalized, ("OriginÃ¡lnÃ­ nÃ¡zev", "Originalni nazev"))
    if not title_value:
        match = re.search(
            r"OriginÃ¡lnÃ­\s+n[Ã¡a]zev:?\s*(.*?)(?=\s+(?:Autor|PÅ™eklad|Preklad|PoÄet|Pocet|Jazyk|Forma|Vazba|Å½Ã¡nr|Zanr|SÃ©rie|Serie|Rok vydÃ¡nÃ­|VydÃ¡no|Vydano|ISBN|Å tÃ­tky|Stitky|HodnocenÃ­|Hodnoceni|O knize)\b|$)",
            normalized,
            flags=re.IGNORECASE,
        )
        title_value = match.group(1) if match else ""
    original_title, original_publication = _split_original_title_and_publication(title_value) if title_value else ("", "")
    if not original_publication:
        original_publication = _detail_field_value(
            normalized,
            (
                "OriginÃ¡l vyÅ¡el",
                "Original vysel",
                "OriginÃ¡lnÃ­ rok vydÃ¡nÃ­",
                "Originalni rok vydani",
                "PÅ¯vodnÃ­ vydÃ¡nÃ­",
                "Puvodni vydani",
            ),
        )
    return original_title, _clean_text(original_publication).strip(" ,")


ASCII_DETAIL_STOP_LABELS = (
    "autor",
    "preklad",
    "pocet",
    "jazyk",
    "forma",
    "vazba",
    "zanr",
    "serie",
    "rok vydani",
    "vydano",
    "originalni nazev",
    "original vysel",
    "originalni rok vydani",
    "puvodni vydani",
    "isbn",
    "stitky",
    "hodnoceni",
    "o knize",
)


def _ascii_detail_field_value(text: str, labels: Sequence[str]) -> str:
    """Najde hodnotu DK Vice info podle accent-insensitive popisku."""
    parts = _clean_text(text).split(" ")
    ascii_text = " ".join(normalize_text(part) for part in parts)
    stop_pattern = "|".join(re.escape(label) for label in ASCII_DETAIL_STOP_LABELS)
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}:?\s*(.*?)(?=\s+(?:{stop_pattern})\b|$)",
            ascii_text,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        start = len(ascii_text[: match.start(1)].split(" "))
        end = start + len(match.group(1).split(" "))
        return _clean_text(" ".join(parts[start:end])).strip(" ,")
    return ""


def _original_metadata_from_text(text: str) -> tuple[str, str]:
    """Najde DK originalni nazev i samostatny originalni rok bez zavislosti na diakritice."""
    match = re.search(r"Origin\S*\s+n\S*zev:?\s*(.*)$", _clean_text(text), flags=re.IGNORECASE)
    title_value = match.group(1) if match else _ascii_detail_field_value(text, ("originalni nazev",))
    original_title, original_publication = _split_original_title_and_publication(title_value) if title_value else ("", "")
    if not original_publication:
        original_publication = _ascii_detail_field_value(
            text,
            ("original vysel", "originalni rok vydani", "puvodni vydani"),
        )
    return original_title, _clean_text(original_publication).strip(" ,")


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
    original_title, original_publication, original_publisher = _original_metadata_from_detail_fields(parser.detail_fields)
    if not (original_title or original_publication):
        original_title, original_publication = _original_metadata_from_text(" ".join(parser.visible_text_parts))
    series, series_index = _series_metadata_from_blocks(parser.series_blocks_before_title)

    return BookDetailMetadata(
        published_year=published_year,
        publisher=_publisher_name(book_json.get("publisher")),
        series=series,
        series_index=series_index,
        tags=tags,
        rating_percent=rating,
        original_title=original_title,
        original_publication=original_publication,
        original_publisher=original_publisher,
        about_text=about_text,
        cover_url=_image_url_from_json(book_json.get("image")) or parser.cover_url,
    )


def _databaze_cover_book_id_from_url(url: str) -> str:
    """Vrati ID knihy vlozene v ceste DK obrazku obalky."""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    match = re.search(r"/img/books/(?:\d+_/)?(\d+)(?:/|[_-])", path, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _normalize_databaze_cover_url(url: str) -> str:
    """Sjednoti stabilni DK varianty URL jedne obalky."""
    parsed = urllib.parse.urlparse(normalize_image_url(url))
    if parsed.netloc.lower() not in {"www.databazeknih.cz", "img.databazeknih.cz"}:
        return urllib.parse.urlunparse(parsed)
    path = re.sub(r"(?<=/)bmid_", "", parsed.path, count=1, flags=re.IGNORECASE)
    return urllib.parse.urlunparse(parsed._replace(path=path, query="", fragment=""))


def _dedupe_databaze_cover_options(options: Sequence[CoverOption]) -> list[CoverOption]:
    normalized = (
        CoverOption(_normalize_databaze_cover_url(option.url), option.source, option.label)
        for option in options
    )
    return _dedupe_cover_options(normalized)


class DatabazeEditionCoverParser(HTMLParser):
    """Parser tiskovych obalek z duveryhodnych radku dalsich vydani DK."""

    def __init__(self) -> None:
        super().__init__()
        self.cover_urls: list[str] = []
        self._content_depth = 0
        self._entry_book_id = ""
        self._entry_cover_url = ""
        self._entry_is_audiobook = False

    def _finish_entry(self) -> None:
        if self._entry_cover_url and not self._entry_is_audiobook:
            self.cover_urls.append(self._entry_cover_url)
        self._entry_book_id = ""
        self._entry_cover_url = ""
        self._entry_is_audiobook = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if not self._content_depth:
            if lowered_tag == "div" and attrs_dict.get("id", "").lower() == "left":
                self._content_depth = 1
            return
        classes = set(attrs_dict.get("class", "").split())
        if lowered_tag == "hr" and "oddown" in classes:
            self._finish_entry()
            return
        if lowered_tag not in HTML_VOID_TAGS:
            self._content_depth += 1
        href = attrs_dict.get("href", "")
        if lowered_tag == "a" and href.startswith(("/prehled-knihy/", BASE_URL + "/prehled-knihy/")):
            linked_book_id = databaze_book_id_from_url(href)
            if linked_book_id and linked_book_id != self._entry_book_id:
                self._finish_entry()
                self._entry_book_id = linked_book_id
        context = " ".join(attrs_dict.values()).lower()
        if self._entry_book_id and any(
            marker in context for marker in ("audiokniha", "audiobook", "format_audio", "img_100_left_audiobook")
        ):
            self._entry_is_audiobook = True
        if lowered_tag != "img":
            return
        if "img_100_left" not in classes or "img_100_left_audiobook" in classes:
            return
        url = normalize_image_url(attrs_dict.get("src", ""))
        host = urllib.parse.urlparse(url).netloc.lower()
        if host not in {"www.databazeknih.cz", "img.databazeknih.cz"}:
            return
        if _databaze_cover_book_id_from_url(url) == self._entry_book_id:
            self._entry_cover_url = url

    def handle_endtag(self, tag: str) -> None:
        if not self._content_depth or tag.lower() in HTML_VOID_TAGS:
            return
        if self._content_depth == 1:
            self._finish_entry()
        self._content_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._entry_book_id and any(marker in data.lower() for marker in ("audiokniha", "audiobook")):
            self._entry_is_audiobook = True


def parse_databaze_edition_cover_options(html_text: str) -> list[CoverOption]:
    """Vrati pouze tiskove obalky z explicitniho seznamu dalsich vydani DK."""
    parser = DatabazeEditionCoverParser()
    parser.feed(html_text)
    parser.close()
    return _dedupe_databaze_cover_options(
        CoverOption(url, "databazeknih", "Databaze knih") for url in parser.cover_urls
    )


def parse_databaze_cover_options(html_text: str, selected_book_id: str = "") -> list[CoverOption]:
    """Vrati vsechny rozpoznane kandidatni obalky z detailu Databaze knih."""
    parser = BookDetailParser()
    parser.feed(html_text)
    parser.close()
    book_json = _book_json_from_blocks(parser.json_ld_blocks)
    urls = _image_urls_from_json(book_json.get("image")) + parser.main_cover_urls
    if selected_book_id:
        urls.extend(
            url for url in parser.cover_urls if _databaze_cover_book_id_from_url(url) == selected_book_id
        )
    else:
        urls.extend(parser.cover_urls)
    return _dedupe_databaze_cover_options(
        CoverOption(url, "databazeknih", "Databaze knih") for url in urls
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
        self.cover_url = ""
        self.cover_urls: list[str] = []

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
        classes = set(attrs_dict.get("class", "").split())
        src = attrs_dict.get("src", "")

        if not self.cover_url and lowered_tag == "img" and "obal_kniha" in classes and src:
            normalized = normalize_legie_image_url(src)
            self.cover_url = normalized
            self.cover_urls.append(normalized)
        elif lowered_tag == "img" and "obal_kniha" in classes and src:
            normalized = normalize_legie_image_url(src)
            if normalized not in self.cover_urls:
                self.cover_urls.append(normalized)

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
        cover_url=parser.cover_url,
    )


def parse_legie_cover_options(html_text: str) -> list[CoverOption]:
    """Vrati vsechny obalky z Legie detailu povidky."""
    parser = LegieStoryParser()
    parser.feed(html_text)
    parser.close()
    return _dedupe_legie_cover_options(
        CoverOption(url, "legie", f"Legie {index}") for index, url in enumerate(parser.cover_urls, start=1)
    )


def _normalize_legie_cover_url(url: str) -> str:
    """Sjednoti stabilni Legie varianty URL jedne obalky."""
    parsed = urllib.parse.urlparse(normalize_legie_image_url(url))
    if parsed.netloc.lower() != "www.legie.info":
        return urllib.parse.urlunparse(parsed)
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


def _dedupe_legie_cover_options(options: Iterable[CoverOption]) -> list[CoverOption]:
    normalized = (
        CoverOption(_normalize_legie_cover_url(option.url), option.source, option.label)
        for option in options
    )
    return _dedupe_cover_options(normalized)


def _renumber_legie_edition_labels(options: Iterable[CoverOption]) -> list[CoverOption]:
    """Precisluje zachovane Legie edition labely po odstraneni duplicit."""
    result: list[CoverOption] = []
    edition_number = 0
    for option in options:
        if option.source == "legie" and option.label.startswith("Legie vydani "):
            edition_number += 1
            option = CoverOption(option.url, option.source, f"Legie vydani {edition_number}")
        result.append(option)
    return result


class LegieEditionCoverParser(HTMLParser):
    """Parser obalek z duveryhodnych polozek seznamu vydani Legie."""

    def __init__(self) -> None:
        super().__init__()
        self.cover_urls: list[str] = []
        self._content_depth = 0
        self._entry_depth = 0
        self._entry_cover_url = ""
        self._entry_is_audio = False

    def _finish_entry(self) -> None:
        if self._entry_cover_url and not self._entry_is_audio:
            self.cover_urls.append(self._entry_cover_url)
        self._entry_cover_url = ""
        self._entry_is_audio = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if not self._content_depth:
            if lowered_tag == "div" and attrs_dict.get("id", "").lower() == "vycet_vydani":
                self._content_depth = 1
            return
        if lowered_tag not in HTML_VOID_TAGS:
            self._content_depth += 1
        if not self._entry_depth:
            if lowered_tag != "div" or "vydani" not in classes:
                return
            self._entry_depth = 1
            self._entry_cover_url = ""
            self._entry_is_audio = False
        elif lowered_tag not in HTML_VOID_TAGS:
            self._entry_depth += 1
        context = " ".join(attrs_dict.values()).lower()
        if any(marker in context for marker in ("audio", "audiokniha", "audiobook")):
            self._entry_is_audio = True
        if lowered_tag != "img" or "obalk" not in classes:
            return
        url = normalize_legie_image_url(attrs_dict.get("src", ""))
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.lower() == "www.legie.info" and parsed.path.startswith("/images/kniha-small/"):
            self._entry_cover_url = url

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        if not self._content_depth or lowered_tag in HTML_VOID_TAGS:
            return
        if self._entry_depth:
            self._entry_depth -= 1
            if not self._entry_depth:
                self._finish_entry()
        self._content_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._entry_depth and any(marker in data.lower() for marker in ("audio", "audiokniha", "audiobook")):
            self._entry_is_audio = True


def parse_legie_edition_cover_options(html_text: str) -> list[CoverOption]:
    """Vrati tiskove obalky z vyctu vydani Legie."""
    parser = LegieEditionCoverParser()
    parser.feed(html_text)
    parser.close()
    return _dedupe_legie_cover_options(
        CoverOption(url, "legie", f"Legie vydani {index}")
        for index, url in enumerate(parser.cover_urls, start=1)
    )


class LegieEditionsLinkParser(HTMLParser):
    """Najde prvni explicitni Legie odkaz na vydani knihy."""

    def __init__(self, book_id: str = "") -> None:
        super().__init__()
        self.editions_url = ""
        self.book_id = book_id

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.editions_url or tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        if (
            re.search(r"/vydani(?:[/?#]|$)", "/" + href.lstrip("/"), flags=re.IGNORECASE)
            and (not self.book_id or legie_book_id_from_url(href) == self.book_id)
        ):
            self.editions_url = legie_absolute_url(href)


def parse_legie_editions_link(html_text: str, book_id: str = "") -> str:
    parser = LegieEditionsLinkParser(book_id)
    parser.feed(html_text)
    parser.close()
    return parser.editions_url


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


def filter_databaze_audiobook_candidates(
    candidates: Sequence[Candidate],
    fetcher: Callable[[str], str],
) -> list[Candidate]:
    """Vyhodi DK kandidaty, ktere jsou ve Vice info oznacene jako audiokniha."""
    filtered: list[Candidate] = []
    for candidate in candidates:
        if not is_valid_apply_url(candidate.url):
            filtered.append(candidate)
            continue
        book_id = databaze_book_id_from_url(candidate.url)
        if not book_id:
            filtered.append(candidate)
            continue
        try:
            more_info_html = fetcher(databaze_more_info_url(book_id))
        except Exception:
            filtered.append(candidate)
            continue
        if not is_databaze_audiobook_more_info(more_info_html):
            filtered.append(candidate)
    return filtered


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


def find_databaze_book(
    book: Book,
    fetcher: Callable[[str], str],
    sleeper: Callable[[float], None],
    sleep_seconds: float,
) -> MatchRow:
    """Najde knihu na Databazi knih, s fallbackem bez diakritiky/interpunkce."""
    best_row: MatchRow | None = None
    last_error: Exception | None = None
    for title, authors in search_variants(book.title, book.authors):
        sleeper(sleep_seconds)
        try:
            html = fetcher(build_search_url(title, authors))
        except Exception as exc:
            last_error = exc
            continue
        candidates = filter_databaze_audiobook_candidates(parse_search_results(html), fetcher)
        row = match_book(book, candidates)
        if best_row is None or (not best_row.chosen_url and row.chosen_url):
            best_row = row
        if not should_try_legie(row):
            return row
    if best_row is not None:
        return best_row
    if last_error is not None:
        raise last_error
    return match_book(book, [])


def source_and_work_type_for_url(url: str) -> tuple[str, str]:
    """Urci zdroj a typ prace podle odkazu z vyhledavani."""
    if is_valid_legie_story_url(url):
        return "legie", "povidka"
    if is_valid_databaze_story_url(url):
        return "databazeknih", "povidka"
    if is_valid_google_books_url(url):
        return "googlebooks", ""
    if is_valid_openlibrary_url(url):
        return "openlibrary", ""
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


def likely_english_book(book: Book) -> bool:
    """Hruby filtr: anglicke nazvy/autori jsou bez ceske diakritiky a skoro cele ASCII."""
    title = book.title.strip()
    if not title:
        return False
    letters = [char for char in title if char.isalpha()]
    if not letters:
        return False
    ascii_letters = [char for char in letters if ord(char) < 128]
    if len(ascii_letters) / len(letters) <= 0.98:
        return False
    words = set(normalize_text(title).split())
    english_signals = {
        "and",
        "the",
        "this",
        "that",
        "there",
        "your",
        "you",
        "mind",
        "diet",
        "change",
        "turn",
        "coat",
        "life",
        "fungi",
        "worlds",
        "make",
        "exercised",
        "something",
        "new",
        "antimemetics",
        "division",
        "history",
        "stories",
        "book",
    }
    return bool(words & english_signals)


def match_google_books(book: Book, candidates: Sequence[Candidate]) -> MatchRow:
    """Vybere Google Books kandidata jen pri shode nazvu a autora."""
    authors_text = " & ".join(book.authors)
    if not candidates:
        return MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "googlebooks-no-candidates", "googlebooks")

    normalized_title = normalize_text(book.title)
    title_matches = [candidate for candidate in candidates if normalize_text(candidate.title) == normalized_title]
    author_matches = [
        candidate
        for candidate in title_matches
        if any(_author_matches_text(author, candidate.text) for author in book.authors)
    ]
    if len(author_matches) == 1:
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            author_matches[0].url,
            _candidate_urls(candidates),
            "googlebooks-title-author",
            "googlebooks-title-author",
            "googlebooks",
            "",
        )
    if title_matches:
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            title_matches[0].url,
            _candidate_urls(candidates),
            "googlebooks-title-only",
            "googlebooks-title-only",
            "googlebooks",
            "",
        )
    return MatchRow(book.id, book.title, authors_text, "skip", "", _candidate_urls(candidates), "none", "googlebooks-no-match", "googlebooks")


def match_openlibrary_book(book: Book, candidates: Sequence[Candidate]) -> MatchRow:
    """Vybere Open Library kandidata pri shode nazvu a autora."""
    authors_text = " & ".join(book.authors)
    if not candidates:
        return MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "openlibrary-no-candidates", "openlibrary")
    normalized_title = normalize_text(book.title)
    title_matches = [candidate for candidate in candidates if normalize_text(candidate.title) == normalized_title]
    author_matches = [
        candidate
        for candidate in title_matches
        if any(_author_matches_text(author, candidate.text) for author in book.authors)
    ]
    if len(author_matches) == 1:
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            author_matches[0].url,
            _candidate_urls(candidates),
            "openlibrary-title-author",
            "openlibrary-title-author",
            "openlibrary",
            "",
        )
    if title_matches:
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            title_matches[0].url,
            _candidate_urls(candidates),
            "openlibrary-title-only",
            "openlibrary-title-only",
            "openlibrary",
            "",
        )
    return MatchRow(book.id, book.title, authors_text, "skip", "", _candidate_urls(candidates), "none", "openlibrary-no-match", "openlibrary")


def find_google_books_book(
    book: Book,
    fetcher: Callable[[str], str],
    sleeper: Callable[[float], None],
    sleep_seconds: float,
) -> MatchRow:
    """Najde anglickou knihu pres Google Books API."""
    sleeper(sleep_seconds)
    html = fetcher(build_google_books_search_url(book.title, book.authors))
    return match_google_books(book, parse_google_books_search_results(html))


def find_openlibrary_book(
    book: Book,
    fetcher: Callable[[str], str],
    sleeper: Callable[[float], None],
    sleep_seconds: float,
) -> MatchRow:
    """Najde anglickou knihu pres Open Library API."""
    sleeper(sleep_seconds)
    html = fetcher(build_openlibrary_search_url(book.title, book.authors))
    return match_openlibrary_book(book, parse_openlibrary_search_results(html))


def find_english_book(
    book: Book,
    fetcher: Callable[[str], str],
    sleeper: Callable[[float], None],
    sleep_seconds: float,
) -> MatchRow:
    """Zkusi Google Books, pak Open Library."""
    google_row: MatchRow | None = None
    try:
        google_row = find_google_books_book(book, fetcher, sleeper, sleep_seconds)
    except Exception:
        google_row = None
    if google_row is not None and google_row.chosen_url:
        return google_row
    try:
        openlibrary_row = find_openlibrary_book(book, fetcher, sleeper, sleep_seconds)
    except Exception:
        openlibrary_row = None
    if openlibrary_row is not None and openlibrary_row.chosen_url:
        return openlibrary_row
    return google_row or openlibrary_row or MatchRow(book.id, book.title, " & ".join(book.authors), "skip", "", "", "none", "english-no-candidates", "openlibrary")


def _match_row_from_dict(raw: dict[str, str]) -> MatchRow:
    """Prevede radek z CSV nebo SQLite na MatchRow."""
    return MatchRow(
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
        raw.get("cover_urls") or "",
        raw.get("selected_cover_url") or "",
        raw.get("cover_reason") or "",
        raw.get("review_published_year") or "",
        raw.get("review_publisher") or "",
        raw.get("review_tags") or "",
        raw.get("review_rating_percent") or "",
        raw.get("review_original_title") or "",
        raw.get("review_original_publication") or "",
        raw.get("review_original_publisher") or "",
    )


def _legacy_matches_path(path: Path) -> Path:
    """Vrati stary CSV soubor vedle nove SQLite databaze."""
    return path.with_name(LEGACY_MATCHES_CSV_PATH.name)


def matches_storage_exists(path: Path) -> bool:
    """Pozna nove SQLite uloziste i stary matches.csv pred migraci."""
    return path.exists() or (path.suffix.casefold() == ".db" and _legacy_matches_path(path).exists())


def _ensure_matches_db_schema(connection: sqlite3.Connection) -> None:
    """Vytvori tabulku pracovnich radku appky."""
    columns = ", ".join(f"{field} text not null default ''" for field in MATCHES_FIELDS if field != "book_id")
    connection.execute(
        f"""
        create table if not exists match_rows (
            book_id integer primary key,
            sort_order integer not null,
            {columns}
        )
        """
    )
    existing_columns = {
        str(row[1])
        for row in connection.execute("pragma table_info(match_rows)").fetchall()
    }
    if "sort_order" not in existing_columns:
        connection.execute("alter table match_rows add column sort_order integer not null default 0")
    for field in MATCHES_FIELDS:
        if field not in existing_columns:
            if field == "book_id":
                continue
            connection.execute(f"alter table match_rows add column {field} text not null default ''")


def _write_matches_db(path: Path, rows: Iterable[MatchRow], overwrite: bool) -> None:
    """Zapise pracovni radky do SQLite databaze aplikace."""
    rows_list = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        _ensure_matches_db_schema(connection)
        existing_count = connection.execute("select count(*) from match_rows").fetchone()[0]
        if existing_count and not overwrite:
            raise FileExistsError(path)
        connection.execute("delete from match_rows")
        placeholders = ", ".join("?" for _field in ["sort_order", *MATCHES_FIELDS])
        columns = ", ".join(["sort_order", *MATCHES_FIELDS])
        values = [
            tuple([index, *[getattr(row, field) for field in MATCHES_FIELDS]])
            for index, row in enumerate(rows_list)
        ]
        connection.executemany(f"insert into match_rows ({columns}) values ({placeholders})", values)
        connection.commit()
    finally:
        connection.close()


def _read_matches_db(path: Path) -> list[MatchRow]:
    """Precte pracovni radky ze SQLite databaze aplikace."""
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        _ensure_matches_db_schema(connection)
        rows = connection.execute(
            f"select {', '.join(MATCHES_FIELDS)} from match_rows order by sort_order"
        ).fetchall()
    finally:
        connection.close()
    return [_match_row_from_dict(dict(row)) for row in rows]


def write_matches_csv(path: Path, rows: Iterable[MatchRow], overwrite: bool) -> None:
    if path.suffix.casefold() == ".db":
        _write_matches_db(path, rows, overwrite)
        return
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATCHES_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def read_matches_csv(path: Path) -> list[MatchRow]:
    if path.suffix.casefold() == ".db":
        if path.exists():
            return _read_matches_db(path)
        legacy_path = _legacy_matches_path(path)
        if legacy_path.exists():
            return read_matches_csv(legacy_path)
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for raw in reader:
            rows.append(_match_row_from_dict(raw))
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
    """Zkopiruje stare pracovni uloziste pred rebuildem, aby slo vratit rucni upravy."""
    source = matches_path
    if not source.exists() and matches_path.suffix.casefold() == ".db":
        source = _legacy_matches_path(matches_path)
    if not source.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"{source.stem}-{stamp}{source.suffix}"
    shutil.copy2(source, target)
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


def find_ebook_tool(
    name: str,
    which_func: Callable[[str], str | None] = shutil.which,
    exists_func: Callable[[str], bool] | None = None,
) -> str | None:
    """Najde Calibre CLI nastroj (ebook-meta/ebook-convert) stejne jako calibredb.

    Nejdriv PATH (which), pak sourozenec ve slozce s calibredb fallbackem.
    Vrati None kdyz neni - volajici to resi ciste, nepada.
    """
    found = which_func(name)
    if found:
        return found
    exists = exists_func or (lambda path: Path(path).exists())
    sibling = str(Path(CALIBREDB_FALLBACK).with_name(name + ".exe"))
    return sibling if exists(sibling) else None


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


def prune_missing_book_rows(rows: Sequence[MatchRow], books: Sequence[Book]) -> list[MatchRow]:
    """Odstrani pracovni radky, ktere uz nejsou v Calibre knihovne."""
    book_ids = {book.id for book in books}
    return [row for row in rows if row.book_id in book_ids]


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
        merged.append(copy_cover_fields(row, replacement))
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


def is_valid_legie_book_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(legie_absolute_url(url))
    return parsed.netloc.lower() == "www.legie.info" and re.fullmatch(
        r"/kniha/\d+(?:-[^/]+)?/?", parsed.path
    ) is not None


def is_manual_external_url(row: MatchRow) -> bool:
    """Pozna rucni odkaz mimo podporovane zdroje, ktery se ma zapsat jen jako link."""
    clean = row.chosen_url.strip().lower()
    return row.reason == "manual" and clean.startswith(("http://", "https://"))


def is_writable_match_row(row: MatchRow) -> bool:
    if row.status != "approve":
        return False
    if not row.chosen_url.strip():
        return False
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


def find_calibre_import_duplicates(
    library: str | Path,
    preview: ImportPreview,
    books_reader: Callable[[str | Path], list[Book]] = read_books,
) -> list[DuplicateCandidate]:
    return find_import_duplicates(preview, books_reader(library))


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


def _year_from_calibre_pubdate(value: str | None) -> str:
    match = re.search(r"\b(1\d{3}|20\d{2})\b", value or "")
    return match.group(1) if match else ""


def get_current_book_metadata(library: str | Path, book_id: int) -> CurrentBookMetadata:
    """Precte aktualni metadata z Calibre DB pro pravy panel appky."""
    connection = open_calibre_db_readonly(library)
    try:
        row = connection.execute(
            """
            select b.pubdate, coalesce(c.text, '') as comment
            from books b
            left join comments c on c.book = b.id
            where b.id = ?
            """,
            (book_id,),
        ).fetchone()
        publisher_row = connection.execute(
            """
            select p.name
            from publishers p
            join books_publishers_link bpl on bpl.publisher = p.id
            where bpl.book = ?
            order by p.name
            limit 1
            """,
            (book_id,),
        ).fetchone()
        tag_rows = connection.execute(
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
    if row is None:
        return CurrentBookMetadata(tags=[])
    return CurrentBookMetadata(
        published_year=_year_from_calibre_pubdate(row["pubdate"]),
        publisher="" if publisher_row is None else publisher_row["name"] or "",
        tags=[tag["name"] for tag in tag_rows],
        comment=row["comment"] or "",
    )


def get_cover_flags(library: str | Path, book_ids: set[int] | None = None) -> dict[int, bool]:
    """Read-only zjisti, ktere knihy uz maji v Calibre obalku."""
    query = "select id, has_cover from books"
    params: list[object] = []
    if book_ids:
        placeholders = ",".join("?" for _ in book_ids)
        query += f" where id in ({placeholders})"
        params.extend(sorted(book_ids))
    connection = open_calibre_db_readonly(library)
    try:
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    return {int(row["id"]): bool(row["has_cover"]) for row in rows}


def get_local_cover_path(library: str | Path, book_id: int) -> Path | None:
    """Vrati lokalni cover.jpg, pokud Calibre hlasi obalku a soubor existuje."""
    connection = open_calibre_db_readonly(library)
    try:
        row = connection.execute("select path, has_cover from books where id = ?", (book_id,)).fetchone()
    finally:
        connection.close()
    if row is None or not row["has_cover"]:
        return None
    cover_path = Path(library) / row["path"] / "cover.jpg"
    return cover_path if cover_path.exists() else None


def cover_candidate_rows(
    rows: Sequence[MatchRow],
    library: str | Path,
    book_ids: set[int] | None = None,
    cover_flags_reader: Callable[[str | Path, set[int] | None], dict[int, bool]] = get_cover_flags,
) -> list[CoverCandidate]:
    """Vybere radky, ktere maji podporovany odkaz a v Calibre nemaji obalku."""
    selected_rows = select_match_rows(rows, book_ids=book_ids) if book_ids else list(rows)
    supported_rows = [
        row
        for row in selected_rows
        if row.status != "review"
        and row.chosen_url.strip()
        and (
            is_valid_apply_url(row.chosen_url)
            or is_valid_legie_story_url(row.chosen_url)
            or is_valid_legie_book_url(row.chosen_url)
            or is_valid_google_books_url(row.chosen_url)
            or is_valid_openlibrary_url(row.chosen_url)
        )
    ]
    if not supported_rows:
        return []
    flags = cover_flags_reader(library, {row.book_id for row in supported_rows})
    return [
        CoverCandidate(
            row.book_id,
            row.title,
            legie_absolute_url(row.chosen_url)
            if is_valid_legie_story_url(row.chosen_url) or is_valid_legie_book_url(row.chosen_url)
            else row.chosen_url
            if is_valid_google_books_url(row.chosen_url) or is_valid_openlibrary_url(row.chosen_url)
            else book_url_to_overview_url(row.chosen_url),
        )
        for row in supported_rows
        if not flags.get(row.book_id, False)
    ]


def cover_options_for_url(url: str, fetcher: Callable[[str], str] | None = None) -> list[CoverOption]:
    """Stahne detail podporovaneho zdroje a vrati kandidatni obalky."""
    fetch = fetcher or fetch_text
    if is_valid_legie_book_url(url):
        detail_url = legie_absolute_url(url)
        detail_html = fetch(detail_url)
        options = parse_legie_cover_options(detail_html)
        editions_url = legie_editions_url(
            detail_url,
            parse_legie_editions_link(detail_html, legie_book_id_from_url(detail_url)),
        )
        if editions_url:
            try:
                options.extend(parse_legie_edition_cover_options(fetch(editions_url)))
            except Exception:
                pass
        return _renumber_legie_edition_labels(_dedupe_legie_cover_options(options))
    if is_valid_legie_story_url(url):
        return parse_legie_cover_options(fetch(legie_absolute_url(url)))
    if is_valid_google_books_url(url):
        _written_url, detail = fetch_google_books_detail_metadata(url, fetch)
        return [CoverOption(detail.cover_url, "googlebooks", "Google Books")] if detail.cover_url else []
    if is_valid_openlibrary_url(url):
        _written_url, detail = fetch_openlibrary_detail_metadata(url, fetch)
        return [CoverOption(detail.cover_url, "openlibrary", "Open Library")] if detail.cover_url else []
    if is_valid_apply_url(url):
        detail_url = book_url_to_overview_url(url)
        detail_html = fetch(detail_url)
        options = parse_databaze_cover_options(detail_html, databaze_book_id_from_url(detail_url))
        parser = BookDetailParser()
        parser.feed(detail_html)
        parser.close()
        editions_url = databaze_editions_url(detail_url, parser.editions_url)
        parsed_editions_url = urllib.parse.urlparse(editions_url)
        if (
            parsed_editions_url.netloc.lower() == "www.databazeknih.cz"
            and parsed_editions_url.path.startswith("/dalsi-vydani/")
        ):
            try:
                options.extend(parse_databaze_edition_cover_options(fetch(editions_url)))
            except Exception:
                pass
        return _dedupe_databaze_cover_options(options)
    return []


def cover_options_for_urls(
    source_urls: Sequence[str],
    fetcher: Callable[[str], str] | None = None,
) -> list[CoverOption]:
    """Spoji hotove source-specific obalky v poradi zdroju a odstrani duplicity."""
    options: list[CoverOption] = []
    for index, source_url in enumerate(source_urls):
        try:
            options.extend(cover_options_for_url(source_url, fetcher))
        except Exception:
            if index == 0:
                raise
    return _dedupe_cover_options(options)


def _cover_source_urls_for_row(row: MatchRow) -> list[str]:
    """Vrati primarni a prvni existujici opacny DK/Legie book zdroj radku."""
    primary_url = row.chosen_url.strip()
    primary_source = (
        "databazeknih"
        if is_valid_apply_url(primary_url)
        else "legie"
        if is_valid_legie_book_url(primary_url)
        else ""
    )
    if not primary_source:
        return [primary_url]
    for candidate_url in row.candidate_urls.split("|"):
        candidate_url = candidate_url.strip()
        candidate_source = (
            "databazeknih"
            if is_valid_apply_url(candidate_url)
            else "legie"
            if is_valid_legie_book_url(candidate_url)
            else ""
        )
        if candidate_source and candidate_source != primary_source:
            return [primary_url, candidate_url]
    return [primary_url]


def _cover_urls_text(options: Sequence[CoverOption]) -> str:
    return "|".join(option.url for option in options)


def _cover_url_comparison_key(url: str) -> str:
    """Normalizuje URL obalky pro bezpecne porovnani existujiciho vyberu."""
    parsed = urllib.parse.urlparse(html.unescape(url.strip()))
    host = parsed.netloc.lower()
    if host in {"www.databazeknih.cz", "img.databazeknih.cz"}:
        return _normalize_databaze_cover_url(url)
    if host == "www.legie.info":
        return _normalize_legie_cover_url(url)
    normalized = urllib.parse.urlparse(normalize_image_url(url))
    return urllib.parse.urlunparse(
        normalized._replace(scheme=normalized.scheme.lower(), netloc=normalized.netloc.lower(), fragment="")
    )


def _preserved_selected_cover_url(selected_cover_url: str, options: Sequence[CoverOption]) -> str:
    """Zachova existujici vyber, pokud stale odpovida aktualnimu kandidatovi."""
    selected = selected_cover_url.strip()
    if not selected:
        return ""
    selected_key = _cover_url_comparison_key(selected)
    return selected if any(_cover_url_comparison_key(option.url) == selected_key for option in options) else ""


def with_cover_fields(
    row: MatchRow,
    cover_urls: str,
    selected_cover_url: str,
    cover_reason: str,
    status: str | None = None,
) -> MatchRow:
    """Vrati radek se zmenenym stavem obalek."""
    return replace(
        row,
        status=status or row.status,
        cover_urls=cover_urls,
        selected_cover_url=selected_cover_url,
        cover_reason=cover_reason,
    )


def audit_cover_rows(
    rows: Sequence[MatchRow],
    library: str | Path,
    cover_flags_reader: Callable[[str | Path, set[int] | None], dict[int, bool]] = get_cover_flags,
    fetcher: Callable[[str], str] | None = None,
    include_existing_covers: bool = False,
) -> list[MatchRow]:
    """Najde kandidatni obalky a ulozi je do radku bez zapisu do Calibre."""
    flags = cover_flags_reader(library, {row.book_id for row in rows})
    updated: list[MatchRow] = []
    for row in rows:
        if flags.get(row.book_id, False) and not include_existing_covers:
            updated.append(row)
            continue
        if not (
            is_valid_apply_url(row.chosen_url)
            or is_valid_legie_story_url(row.chosen_url)
            or is_valid_legie_book_url(row.chosen_url)
            or is_valid_google_books_url(row.chosen_url)
            or is_valid_openlibrary_url(row.chosen_url)
        ):
            updated.append(row)
            continue
        try:
            options = cover_options_for_urls(_cover_source_urls_for_row(row), fetcher)
        except Exception:
            updated.append(with_cover_fields(row, "", "", "cover-fetch-error"))
            continue
        if not options:
            updated.append(with_cover_fields(row, "", "", "cover-not-found"))
            continue
        urls_text = _cover_urls_text(options)
        preserved_selection = _preserved_selected_cover_url(row.selected_cover_url, options)
        if len(options) == 1:
            updated.append(
                with_cover_fields(
                    row,
                    urls_text,
                    preserved_selection or options[0].url,
                    "single-cover-candidate",
                )
            )
            continue
        updated.append(
            with_cover_fields(
                row,
                urls_text,
                preserved_selection,
                "multiple-cover-candidates",
                status="review",
            )
        )
    return updated


def fetch_binary(url: str, timeout: int = 30) -> bytes:
    """Stahne binarni soubor se stejnym User-Agentem jako HTML."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _cover_suffix(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(suffix):
            return suffix
    return ".jpg"


def apply_cover_candidate(
    candidate: CoverCandidate,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
    fetcher: Callable[[str], str] | None = None,
    binary_fetcher: Callable[[str], bytes] | None = None,
) -> ApplyResult:
    """Najde obalku na Databazi knih a zapise ji do Calibre."""
    run = runner or run_command
    fetch_detail = fetcher or fetch_text
    fetch_cover = binary_fetcher or fetch_binary
    try:
        if is_valid_legie_story_url(candidate.source_url):
            detail_html = fetch_detail(candidate.source_url)
            cover_url = parse_legie_story_detail(detail_html, candidate.source_url).cover_url
        elif is_valid_legie_book_url(candidate.source_url):
            detail_html = fetch_detail(candidate.source_url)
            options = parse_legie_cover_options(detail_html)
            cover_url = options[0].url if options else ""
        elif is_valid_google_books_url(candidate.source_url):
            cover_url = fetch_google_books_detail_metadata(candidate.source_url, fetch_detail)[1].cover_url
        elif is_valid_openlibrary_url(candidate.source_url):
            cover_url = fetch_openlibrary_detail_metadata(candidate.source_url, fetch_detail)[1].cover_url
        else:
            detail_html = fetch_detail(candidate.source_url)
            cover_url = parse_book_detail_metadata(detail_html).cover_url
    except Exception as exc:
        return ApplyResult(candidate.book_id, candidate.title, "failed", candidate.source_url, f"detail-fetch-error: {exc}")
    if not cover_url:
        return ApplyResult(candidate.book_id, candidate.title, "skipped", candidate.source_url, "cover-not-found")
    try:
        cover_bytes = fetch_cover(cover_url)
    except Exception as exc:
        return ApplyResult(candidate.book_id, candidate.title, "failed", cover_url, f"cover-fetch-error: {exc}")
    if not cover_bytes:
        return ApplyResult(candidate.book_id, candidate.title, "failed", cover_url, "cover-empty")

    with tempfile.TemporaryDirectory(prefix="calibre-meta-cover-") as tmp:
        cover_path = Path(tmp) / ("cover" + _cover_suffix(cover_url))
        cover_path.write_bytes(cover_bytes)
        result = run(
            [
                calibredb_path,
                "set_metadata",
                str(candidate.book_id),
                "--with-library",
                str(library),
                "--field",
                "cover:" + str(cover_path),
            ]
        )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(candidate.book_id, candidate.title, "failed", cover_url, error)
    return ApplyResult(candidate.book_id, candidate.title, "updated", cover_url, "")


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


def run_metadata_command_with_cover(
    args: Sequence[str],
    selected_cover_url: str,
    runner: Callable[[Sequence[str]], CommandResult],
    cover_fetcher: Callable[[str], bytes] = fetch_binary,
    cover_bytes: bytes = b"",
    cover_suffix: str = ".jpg",
) -> CommandResult:
    """Spusti calibredb a volitelne prida vybranou obalku z docasneho souboru."""
    cover_url = selected_cover_url.strip()
    bytes_to_write = cover_bytes
    allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    suffix = cover_suffix.lower() if cover_suffix.lower() in allowed_suffixes else ".jpg"
    if cover_url and not bytes_to_write:
        try:
            bytes_to_write = cover_fetcher(cover_url)
        except Exception as exc:
            return CommandResult(1, "", f"cover-fetch-error: {exc}")
        suffix = _cover_suffix(cover_url)
    if not cover_url and not bytes_to_write:
        return runner(args)
    if not bytes_to_write:
        return CommandResult(1, "", "cover-empty")
    with tempfile.TemporaryDirectory() as tmp:
        cover_path = Path(tmp) / ("cover" + suffix)
        cover_path.write_bytes(bytes_to_write)
        args_with_cover = list(args) + ["--field", "cover:" + str(cover_path)]
        return runner(args_with_cover)


def fetch_databaze_book_detail_metadata(
    url: str,
    fetcher: Callable[[str], str] | None = None,
) -> tuple[str, BookDetailMetadata]:
    """Nacte DK detail stejne jako zapis: hlavni detail, Vice info a nejstarsi vydani."""
    detail_fetcher = fetcher or fetch_text
    detail_url = book_url_to_overview_url(url)
    try:
        detail_html = detail_fetcher(detail_url)
    except Exception as exc:
        raise RuntimeError(f"detail-fetch-error: {exc}") from exc

    detail_extra_html = ""
    book_id = databaze_book_id_from_url(detail_url)
    if book_id:
        try:
            detail_extra_html = detail_fetcher(databaze_more_info_url(book_id))
        except Exception:
            detail_extra_html = ""

    detail = parse_book_detail_metadata(detail_html + detail_extra_html)
    written_url = detail_url
    editions_url = extract_editions_url(detail_html)
    if editions_url:
        try:
            oldest_edition = parse_oldest_edition_metadata(detail_fetcher(editions_url))
        except Exception as exc:
            raise RuntimeError(f"editions-fetch-error: {exc}") from exc
        if not (oldest_edition.published_year or oldest_edition.publisher):
            raise RuntimeError("editions-parse-error")
        detail = BookDetailMetadata(
            published_year=oldest_edition.published_year or detail.published_year,
            publisher=oldest_edition.publisher or detail.publisher,
            series=detail.series,
            series_index=detail.series_index,
            tags=detail.tags,
            rating_percent=detail.rating_percent,
            original_title=detail.original_title,
            original_publication=detail.original_publication,
            original_publisher=detail.original_publisher,
            about_text=detail.about_text,
            cover_url=detail.cover_url,
        )
        written_url = oldest_edition.url or detail_url
    return written_url, detail


def fetch_google_books_detail_metadata(
    url: str,
    detail_fetcher: Callable[[str], str] | None = None,
) -> tuple[str, BookDetailMetadata]:
    """Stahne detail Google Books podle volume ID z odkazu."""
    volume_id = google_books_volume_id_from_url(url)
    if not volume_id:
        raise RuntimeError("googlebooks-missing-volume-id")
    fetch = detail_fetcher or fetch_text
    return parse_google_books_volume_metadata(fetch(GOOGLE_BOOKS_API + "/" + urllib.parse.quote(volume_id)))


def fetch_openlibrary_detail_metadata(
    url: str,
    detail_fetcher: Callable[[str], str] | None = None,
) -> tuple[str, BookDetailMetadata]:
    """Stahne detail Open Library edice."""
    edition_key = openlibrary_edition_key_from_url(url)
    if not edition_key:
        raise RuntimeError("openlibrary-missing-edition-key")
    fetch = detail_fetcher or fetch_text
    return parse_openlibrary_edition_metadata(fetch(openlibrary_url(edition_key) + ".json"))


def fetch_import_detail_for_url(
    url: str,
    fetcher: Callable[[str], str] | None = None,
) -> tuple[str, BookDetailMetadata]:
    """Stahne detail metadat z rucne vlozeneho odkazu podle jeho zdroje.

    Vybere spravny parser (Google Books / Open Library / Databaze knih) a vrati
    (kanonicky_url, detail). Pro 'Pouzit odkaz' v import dialogu.
    """
    if is_valid_google_books_url(url):
        return fetch_google_books_detail_metadata(url, fetcher)
    if is_valid_openlibrary_url(url):
        return fetch_openlibrary_detail_metadata(url, fetcher)
    return fetch_databaze_book_detail_metadata(url, fetcher)


def parse_databaze_book_identity(html_text: str) -> tuple[str, str]:
    """Z HTML detailu Databaze knih vytahne nazev (h1) a autory (odkazy /autori/)."""
    title = ""
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
    authors: list[str] = []
    for author_match in re.finditer(r'href="/autori/[^"]+"[^>]*>([^<]{2,60})</a>', html_text, re.IGNORECASE):
        name = html.unescape(author_match.group(1)).strip()
        if name and name not in authors:
            authors.append(name)
    return title, " & ".join(authors)


def fetch_import_identity(url: str, fetcher: Callable[[str], str] | None = None) -> tuple[str, str]:
    """Z rucne vlozeneho odkazu zjisti katalogovy nazev a autora podle zdroje."""
    fetch = fetcher or fetch_text
    if is_valid_google_books_url(url):
        volume_id = google_books_volume_id_from_url(url)
        if not volume_id:
            return "", ""
        raw = json.loads(fetch(GOOGLE_BOOKS_API + "/" + urllib.parse.quote(volume_id)))
        info = raw.get("volumeInfo", {}) if isinstance(raw, dict) else {}
        authors = info.get("authors") if isinstance(info.get("authors"), list) else []
        return str(info.get("title") or ""), " & ".join(str(a) for a in authors if str(a).strip())
    if is_valid_openlibrary_url(url):
        edition_key = openlibrary_edition_key_from_url(url)
        if not edition_key:
            return "", ""
        raw = json.loads(fetch(openlibrary_url(edition_key) + ".json"))
        return str(raw.get("title") or ""), ""
    return parse_databaze_book_identity(fetch(book_url_to_overview_url(url)))


def fetch_import_link_data(
    url: str,
    fetcher: Callable[[str], str] | None = None,
) -> tuple[str, str, str, BookDetailMetadata]:
    """Pro 'Pouzit odkaz': vrati (nazev, autori, kanonicky_url, detail) z odkazu."""
    written_url, detail = fetch_import_detail_for_url(url, fetcher)
    written_url = canonical_detail_output_url(url, written_url)
    title, authors = fetch_import_identity(url, fetcher)
    return title, authors, written_url, detail


def apply_match_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
    fetcher: Callable[[str], str] | None = None,
    identifiers_reader: Callable[[str | Path, int], dict[str, str]] = get_current_identifiers,
    tags_reader: Callable[[str | Path, int], list[str]] = get_current_tags,
    cover_fetcher: Callable[[str], bytes] = fetch_binary,
    write_cover: bool = True,
) -> ApplyResult:
    selected_cover_requested = bool(row.selected_cover_url.strip())

    def with_cover_status(result: ApplyResult) -> ApplyResult:
        if not selected_cover_requested:
            cover_status = "not-requested"
        elif not write_cover:
            cover_status = "overwrite-declined"
        elif result.status == "updated":
            cover_status = "written"
        elif result.status == "failed":
            cover_status = "failed"
        else:
            cover_status = "not-requested"
        return replace(result, cover_status=cover_status)

    if row.status != "approve":
        return with_cover_status(ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, ""))
    if not row.chosen_url.strip():
        return with_cover_status(ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "empty-url"))
    if not write_cover and row.selected_cover_url:
        row = replace(row, selected_cover_url="")
    if row.source == "legie" or is_valid_legie_story_url(row.chosen_url):
        return with_cover_status(
            apply_legie_story_row(
                row,
                library,
                calibredb_path,
                runner,
                fetcher or fetch_text,
                identifiers_reader,
                tags_reader,
                cover_fetcher,
            )
        )
    if row.source == "googlebooks" or is_valid_google_books_url(row.chosen_url):
        try:
            written_url, detail = fetch_google_books_detail_metadata(row.chosen_url, fetcher or fetch_text)
        except RuntimeError as exc:
            return with_cover_status(ApplyResult(row.book_id, row.title, "failed", row.chosen_url, str(exc)))
        detail = apply_review_overrides(row, detail)
        args = [
            calibredb_path,
            "set_metadata",
            str(row.book_id),
            "--with-library",
            str(library),
            "--field",
            "comments:" + format_enriched_comment(written_url, detail),
        ]
        if detail.published_year:
            args.extend(["--field", "pubdate:" + calibre_pubdate_value(detail.published_year)])
        if detail.publisher:
            args.extend(["--field", "publisher:" + detail.publisher])
        if detail.tags:
            args.extend(["--field", "tags:" + ",".join(detail.tags)])
        result = run_metadata_command_with_cover(args, row.selected_cover_url, runner, cover_fetcher)
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "calibredb failed").strip()
            return with_cover_status(ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error))
        return with_cover_status(ApplyResult(row.book_id, row.title, "updated", written_url, ""))
    if row.source == "openlibrary" or is_valid_openlibrary_url(row.chosen_url):
        try:
            written_url, detail = fetch_openlibrary_detail_metadata(row.chosen_url, fetcher or fetch_text)
        except RuntimeError as exc:
            return with_cover_status(ApplyResult(row.book_id, row.title, "failed", row.chosen_url, str(exc)))
        detail = apply_review_overrides(row, detail)
        args = [
            calibredb_path,
            "set_metadata",
            str(row.book_id),
            "--with-library",
            str(library),
            "--field",
            "comments:" + format_enriched_comment(written_url, detail),
        ]
        if detail.published_year:
            args.extend(["--field", "pubdate:" + calibre_pubdate_value(detail.published_year)])
        if detail.publisher:
            args.extend(["--field", "publisher:" + detail.publisher])
        if detail.tags:
            args.extend(["--field", "tags:" + ",".join(detail.tags)])
        result = run_metadata_command_with_cover(args, row.selected_cover_url, runner, cover_fetcher)
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "calibredb failed").strip()
            return with_cover_status(ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error))
        return with_cover_status(ApplyResult(row.book_id, row.title, "updated", written_url, ""))
    if is_valid_databaze_story_url(row.chosen_url):
        return with_cover_status(apply_manual_link_row(row, library, calibredb_path, runner, cover_fetcher))
    if not is_valid_apply_url(row.chosen_url):
        if is_manual_external_url(row):
            return with_cover_status(apply_manual_link_row(row, library, calibredb_path, runner, cover_fetcher))
        return with_cover_status(ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "invalid-url"))

    try:
        written_url, detail = fetch_databaze_book_detail_metadata(row.chosen_url, fetcher or fetch_text)
    except RuntimeError as exc:
        return with_cover_status(ApplyResult(row.book_id, row.title, "failed", row.chosen_url, str(exc)))
    detail = apply_review_overrides(row, detail)
    canonical_url = canonical_detail_output_url(row.chosen_url, written_url)

    new_comment = format_enriched_comment(canonical_url, detail)
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + new_comment,
    ]
    if row.title:
        args.extend(["--field", "title_sort:" + row.title])
    if detail.published_year:
        args.extend(["--field", "pubdate:" + calibre_pubdate_value(detail.published_year)])
    if detail.publisher:
        args.extend(["--field", "publisher:" + detail.publisher])
    if detail.tags:
        args.extend(["--field", "tags:" + ",".join(detail.tags)])
    if detail.series:
        args.extend(["--field", "series:" + detail.series])
    if detail.series_index:
        args.extend(["--field", "series_index:" + detail.series_index])
    result = run_metadata_command_with_cover(args, row.selected_cover_url, runner, cover_fetcher)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return with_cover_status(ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error))
    return with_cover_status(ApplyResult(row.book_id, row.title, "updated", canonical_url, ""))


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
    cover_fetcher: Callable[[str], bytes] = fetch_binary,
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
    result = run_metadata_command_with_cover(args, row.selected_cover_url, runner, cover_fetcher)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error)
    return ApplyResult(row.book_id, row.title, "updated", row.chosen_url, "")


def apply_manual_link_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult],
    cover_fetcher: Callable[[str], bytes] = fetch_binary,
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
    result = run_metadata_command_with_cover(args, row.selected_cover_url, runner, cover_fetcher)
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
    searchable_books = [book for book in books if not comment_has_databaze_link(book.comment) and not likely_english_book(book)]
    if searchable_books:
        if not robots_checker():
            raise RuntimeError("robots-blocked")

    searched = 0
    for book in books:
        if comment_has_databaze_link(book.comment):
            rows.append(match_book(book, []))
            continue
        searched += 1
        try:
            if likely_english_book(book):
                row = find_english_book(book, fetcher, sleeper, sleep_seconds)
            else:
                row = find_databaze_book(book, fetcher, sleeper, sleep_seconds)
        except Exception:
            authors_text = " & ".join(book.authors)
            row = MatchRow(book.id, book.title, authors_text, "skip", "", "", "none", "http-error")
        if not likely_english_book(book) and should_try_legie(row):
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
        if row.reason == "manual" and row.chosen_url.strip():
            updated.append(row)
            continue
        authors = [part.strip() for part in row.authors.split("&") if part.strip()]
        book = Book(row.book_id, row.title, authors, "")
        if likely_english_book(book):
            if is_valid_openlibrary_url(row.chosen_url):
                fixed = replace(row, status="review", source="openlibrary", work_type="")
                updated.append(clear_review_overrides(fixed) if row.source != "openlibrary" else fixed)
                continue
            if is_valid_google_books_url(row.chosen_url):
                fixed = replace(row, status="review", source="googlebooks", work_type="")
                updated.append(clear_review_overrides(fixed) if row.source != "googlebooks" else fixed)
                continue
            try:
                english_row = find_english_book(book, fetcher, sleeper, sleep_seconds)
            except Exception:
                english_row = None
            if english_row is not None and english_row.chosen_url:
                updated.append(english_row)
            elif row.source == "databazeknih" and row.chosen_url:
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
            continue
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
        databaze_row = None
        databaze_failed = False
        try:
            databaze_row = find_databaze_book(book, fetcher, sleeper, sleep_seconds)
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
    incremental = matches_storage_exists(output) and not args.overwrite
    existing_rows = read_matches_csv(output) if incremental else []
    selected_book_ids = set(getattr(args, "book_ids", None) or [])
    refresh_selected = args.book_id is None and bool(selected_book_ids)

    read_limit = None if refresh_selected else args.limit
    books = read_books(args.library, book_id=args.book_id, limit=read_limit)
    if incremental and books and not refresh_selected and args.book_id is None and args.limit is None:
        pruned_rows = prune_missing_book_rows(existing_rows, books)
        if len(pruned_rows) != len(existing_rows):
            write_matches_csv(output, pruned_rows, overwrite=True)
            existing_rows = pruned_rows
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
        print(f"Zaloha pracovnich dat: {backup_path}")
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
            cover_updates: dict[str, str] = {}
            if getattr(result, "cover_status", "not-requested") == "written":
                cover_updates = {"selected_cover_url": "", "cover_reason": ""}
            elif getattr(result, "cover_status", "not-requested") == "overwrite-declined":
                cover_updates = {
                    "selected_cover_url": "",
                    "cover_reason": "cover-overwrite-declined",
                }
            updated_rows.append(
                replace(
                    row,
                    status="skip",
                    chosen_url=result.chosen_url or row.chosen_url,
                    **cover_updates,
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
    skip_cover_book_ids = set(getattr(args, "skip_cover_book_ids", None) or [])
    skipped_cover_count = sum(
        1 for row in writable_rows if row.book_id in skip_cover_book_ids and row.selected_cover_url.strip()
    )
    for row in rows:
        if row.status != "approve":
            results.append(ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "status-not-approve"))
            continue
        if row.book_id in skip_cover_book_ids:
            result = apply_match_row(row, library, calibredb_path, write_cover=False)
        else:
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
    if skipped_cover_count:
        print(f"Obalky preskoceny: {skipped_cover_count}")
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


def run_covers(args: argparse.Namespace) -> int:
    """Doplni obalky jen kniham, ktere v Calibre zatim obalku nemaji."""
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
    selected_ids = {int(book_id) for book_id in getattr(args, "book_ids", None) or []}
    if getattr(args, "book_id", None) is not None:
        selected_ids = {int(args.book_id)}
    candidates = cover_candidate_rows(all_rows, library, selected_ids or None)
    if getattr(args, "limit", None) is not None:
        candidates = candidates[: int(args.limit)]
    if not candidates:
        print("Neni co doplnovat. updated=0")
        return 0

    backup_path = create_backup(library, Path("backups"))
    print(f"Zaloha: {backup_path}")

    results: list[ApplyResult] = []
    for candidate in candidates:
        result = apply_cover_candidate(candidate, library, calibredb_path)
        results.append(result)
        if result.status == "failed" and _is_global_calibredb_error(result.error):
            print("Globalni chyba knihovny. Batch zastaven.")
            break
        if getattr(args, "sleep", 0):
            time.sleep(float(args.sleep))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    results_path = apply_results_path(stamp)
    write_apply_results(results_path, results)
    counts = {status: sum(1 for result in results if result.status == status) for status in ("updated", "skipped", "failed")}
    print(f"Vysledek: {results_path}")
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

    preview = subparsers.add_parser("preview", help="Vytvori pracovni matches.db bez zapisu do Calibre.")
    preview.add_argument("--library", default=DEFAULT_LIBRARY)
    preview.add_argument("--limit", type=int)
    preview.add_argument("--book-id", type=int)
    preview.add_argument("--sleep", type=float, default=1.0)
    preview.add_argument("--overwrite", action="store_true")
    preview.set_defaults(func=run_preview)

    apply_parser = subparsers.add_parser("apply", help="Zapise schvalene radky z pracovni databaze.")
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
    legie_audit.add_argument("--book-ids", type=int, nargs="*")
    legie_audit.add_argument("--sleep", type=float, default=1.0)
    legie_audit.set_defaults(func=run_legie_audit)

    repair_parser = subparsers.add_parser("repair-links", help="Opravi stare Databaze knih odkazy v komentarich.")
    repair_parser.add_argument("--library", default=DEFAULT_LIBRARY)
    repair_parser.add_argument("--limit", type=int)
    repair_parser.add_argument("--book-id", type=int)
    repair_parser.add_argument("--sleep", type=float, default=1.0)
    repair_parser.add_argument("--overwrite", action="store_true")
    repair_parser.set_defaults(func=run_repair_links)

    covers_parser = subparsers.add_parser("covers", help="Doplni obalky kniham bez obalky z Databaze knih nebo Legie.")
    covers_parser.add_argument("--library", default=DEFAULT_LIBRARY)
    covers_parser.add_argument("--limit", type=int)
    covers_parser.add_argument("--book-id", type=int)
    covers_parser.add_argument("--sleep", type=float, default=1.0)
    covers_parser.set_defaults(func=run_covers)

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
