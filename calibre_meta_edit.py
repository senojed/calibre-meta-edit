# Skript pripravi nahled odkazu na Databazi knih a bezpecne je vlozi do komentaru knih v Calibre.

from __future__ import annotations

import argparse
import csv
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


def overview_to_book_url(url: str) -> str:
    clean = url.split("#", 1)[0].split("?", 1)[0]
    if clean.startswith("/"):
        clean = BASE_URL + clean
    clean = clean.replace("http://www.databazeknih.cz/", "https://www.databazeknih.cz/", 1)
    return clean.replace(BASE_URL + "/prehled-knihy/", BASE_URL + "/knihy/", 1)


def build_search_url(title: str, authors: Sequence[str]) -> str:
    query = title + " " + " ".join(authors)
    return SEARCH_URL + urllib.parse.quote_plus(query.strip())


def format_link_html(url: str) -> str:
    return f'<div>\n<p><a href="{url}" target="_blank"><span style="color: #6cb4ee">{url}</span></a></p></div>'


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
    return url.startswith(BASE_URL + "/knihy/")


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
) -> ApplyResult:
    if row.status != "approve":
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")
    if not is_valid_apply_url(row.chosen_url):
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "invalid-url")

    current_comment = get_current_comment(library, row.book_id)
    if comment_has_databaze_link(current_comment):
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")

    new_comment = build_new_comment(row.chosen_url, current_comment)
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + new_comment,
    ]
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error)
    return ApplyResult(row.book_id, row.title, "updated", row.chosen_url, "")


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

    rows = select_match_rows(read_matches_csv(MATCHES_PATH), book_id=args.book_id, limit=args.limit)
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
    counts = {status: sum(1 for result in results if result.status == status) for status in ("updated", "skipped", "failed")}
    print(f"Vysledek: {results_path}")
    print(f"updated={counts['updated']} skipped={counts['skipped']} failed={counts['failed']}")
    return 1 if counts["failed"] else 0


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.book_id is not None:
        args.limit = None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
