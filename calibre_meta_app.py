# Desktop appka pro pohodlne schvalovani pracovnich metadat bez Excelu.

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import threading
import webbrowser
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import calibre_meta_edit as cme


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.4.5"
SETTINGS_PATH = APP_DIR / "settings.json"
BACKUPS_DIR = APP_DIR / "backups"
VALID_STATUSES = ("approve", "review", "skip")
TABLE_COLUMNS = ("book_id", "title", "authors", "status", "source", "work_type", "chosen_url", "reason")
BUTTON_COLOR_MAP = {
    "approve": {"bg": "#2e7d32", "fg": "white", "activebackground": "#1b5e20", "activeforeground": "white"},
    "review": {"bg": "#ef6c00", "fg": "white", "activebackground": "#bf5b00", "activeforeground": "white"},
    "skip": {"bg": "#757575", "fg": "white", "activebackground": "#616161", "activeforeground": "white"},
    "story": {"bg": "#1565c0", "fg": "white", "activebackground": "#0d47a1", "activeforeground": "white"},
    "update": {"bg": "#1565c0", "fg": "white", "activebackground": "#0d47a1", "activeforeground": "white"},
    "apply": {"bg": "#c62828", "fg": "white", "activebackground": "#8e0000", "activeforeground": "white"},
    "rebuild": {"bg": "#c62828", "fg": "white", "activebackground": "#8e0000", "activeforeground": "white"},
    "rollback": {"bg": "#c62828", "fg": "white", "activebackground": "#8e0000", "activeforeground": "white"},
}
TOOLBAR_SPACING = {"before_approve": 54, "between_status": 6, "after_skip": 54, "after_update": 18}
PRIMARY_TOOLBAR_LABELS = ("Nacist data", "Nacist nove knihy", "Audit odkazu", "Ulozit data")
BOTTOM_LIBRARY_BAR_LABELS = ("Zmenit", "Pouzit z Calibre", "Update vybrane", "Rebuild data", "Rollback")
URL_BAR_BUTTON_LABELS = ("Pouzit odkaz", "Otevrit odkaz")
CLEAR_BUTTON_LABEL = "X"


def button_colors(kind: str) -> dict[str, str]:
    """Vrati barvy pro barevna tlacitka v appce."""
    return dict(BUTTON_COLOR_MAP[kind])


def toolbar_spacing() -> dict[str, int]:
    """Vrati mezery mezi hlavnim toolbar tlacitky."""
    return dict(TOOLBAR_SPACING)


def primary_toolbar_order() -> tuple[str, ...]:
    """Vrati poradi hlavnich tlacitek v prvni radce."""
    return PRIMARY_TOOLBAR_LABELS


def bottom_library_bar_order() -> tuple[str, ...]:
    """Vrati poradi tlacitek ve spodni radce u pole Knihovna."""
    return BOTTOM_LIBRARY_BAR_LABELS


def url_bar_button_order() -> tuple[str, ...]:
    """Vrati poradi tlacitek u pole s odkazem."""
    return URL_BAR_BUTTON_LABELS


def clear_text_var(text_var: object) -> None:
    """Vymaze text v navazanem vstupnim poli."""
    text_var.set("")


def open_url_in_new_window(url: str, opener: Callable[[str], bool] = webbrowser.open_new) -> bool:
    """Otevre odkaz v novem okne prohlizece, pokud to prohlizec dovoli."""
    return opener(url)


def bind_default_dialog_actions(
    dialog: object,
    confirm: Callable[[], None],
    cancel: Callable[[], None],
    default_button: object,
) -> None:
    """Nastavi Enter na potvrzeni a Escape na zruseni dialogu."""
    default_button.focus_set()
    dialog.bind("<Return>", lambda event: confirm())
    dialog.bind("<Escape>", lambda event: cancel())


def app_title() -> str:
    """Vrati titulek hlavniho okna vcetne verze."""
    return f"Calibre Meta Edit {APP_VERSION}"


def apply_confirmation_message() -> str:
    """Text potvrzeni zapisu do Calibre."""
    return (
        "Appka udela:\n"
        "1. ulozi pracovni data\n"
        "2. pokusi se zavrit Calibre\n"
        "3. vytvori zalohu metadata.db\n"
        "4. u approve radku stahne prehled a zalozku Vydani z Databaze knih\n"
        "5. zapise komentar, vydano, vydavatele a stitky do Calibre\n"
        "6. hotove radky zmeni na skip a ulozi pracovni data\n"
        "7. nacte nove knihy a spusti Audit odkazu"
    )


def schedule_startup_preview(root: object, preview_func: Callable[[], object]) -> None:
    """Po startu automaticky spusti nacitani novych knih."""
    root.after(250, preview_func)


def calibre_config_path(appdata: str | None = None) -> Path | None:
    """Najde soubor, kam si Calibre uklada aktualni knihovnu."""
    root = appdata or os.environ.get("APPDATA")
    if not root:
        return None
    return Path(root) / "calibre" / "global.py.json"


def read_library_path_from_json(path: Path) -> str | None:
    """Precte `library_path` z maleho JSON configu."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("library_path") if isinstance(data, dict) else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def read_calibre_library_path(config_path: Path | None = None) -> str | None:
    """Vrati knihovnu, kterou ma aktualne nastavenou Calibre."""
    path = config_path if config_path is not None else calibre_config_path()
    if path is None:
        return None
    return read_library_path_from_json(path)


def initial_library_path(
    settings_path: Path = SETTINGS_PATH,
    calibre_global_config_path: Path | None = None,
) -> str:
    """Vybere knihovnu pro start appky: nase nastaveni, Calibre config, fallback."""
    saved = read_library_path_from_json(settings_path)
    if saved:
        return saved
    calibre_library = read_calibre_library_path(calibre_global_config_path)
    return calibre_library or cme.DEFAULT_LIBRARY


def save_library_path(library: str, settings_path: Path = SETTINGS_PATH) -> None:
    """Ulozi vybranou knihovnu pro dalsi spusteni appky."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"library_path": library}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_script_args(library: str, overwrite: bool = False) -> SimpleNamespace:
    """Sestavi parametry pro backend skript ze zvolene knihovny."""
    return SimpleNamespace(
        library=library,
        book_id=None,
        book_ids=None,
        limit=None,
        sleep=1.0,
        overwrite=overwrite,
    )


def make_legie_audit_args(library: str, book_ids: set[int] | None = None) -> SimpleNamespace:
    """Sestavi parametry pro Legie audit; bez vyberu projede vsechny radky."""
    args = make_script_args(library)
    args.book_ids = sorted(book_ids) if book_ids else None
    return args


def make_cover_args(
    library: str,
    book_ids: set[int] | None = None,
    include_existing_covers: bool = False,
) -> SimpleNamespace:
    """Argumenty pro doplneni obalek."""
    args = SimpleNamespace(
        library=library,
        book_id=None,
        limit=None,
        sleep=1.0,
        include_existing_covers=include_existing_covers,
    )
    if book_ids:
        args.book_ids = sorted(book_ids)
    return args


def cover_overwrite_book_ids(
    rows: Sequence[cme.MatchRow],
    library: str | Path,
    cover_flags_reader: Callable[[str | Path, set[int] | None], dict[int, bool]] = cme.get_cover_flags,
) -> set[int]:
    """Vrati zapisovatelne radky, jejichz pripravena obalka by prepsala existujici."""
    candidates = {
        row.book_id
        for row in rows
        if cme.is_writable_match_row(row) and row.selected_cover_url.strip()
    }
    if not candidates:
        return set()
    flags = cover_flags_reader(library, candidates)
    return {book_id for book_id in candidates if flags.get(book_id, False)}


def match_row_book_ids(matches_path: Path) -> set[int]:
    """Precte Calibre ID z pracovniho uloziste; kdyz soubor neni, vrati prazdno."""
    if not cme.matches_storage_exists(matches_path):
        return set()
    return {row.book_id for row in cme.read_matches_csv(matches_path)}


def set_audit_book_ids(args: SimpleNamespace, book_ids: set[int]) -> SimpleNamespace:
    """Nastavi backend args tak, aby Legie audit resil jen dane knihy."""
    args.book_id = None
    args.book_ids = sorted(book_ids)
    args.limit = None
    return args


def center_dialog(dialog: object, parent: object) -> None:
    """Umisti dialog doprostred hlavniho okna appky."""
    dialog.update_idletasks()
    x = parent.winfo_rootx() + max((parent.winfo_width() - dialog.winfo_width()) // 2, 0)
    y = parent.winfo_rooty() + max((parent.winfo_height() - dialog.winfo_height()) // 2, 0)
    dialog.geometry(f"+{x}+{y}")


def update_row(
    row: cme.MatchRow,
    status: str,
    chosen_url: str,
    *,
    manual_selection: bool = False,
) -> cme.MatchRow:
    """Vrati upraveny radek, ale zachova vsechny ostatni hodnoty."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Neznamy status: {status}")
    url = chosen_url.strip()
    source = row.source
    work_type = row.work_type
    confidence = row.confidence
    reason = row.reason
    original_source = source
    if cme.is_valid_legie_story_url(url):
        source = "legie"
        work_type = "povidka"
    elif cme.is_valid_databaze_story_url(url):
        source = "databazeknih"
        work_type = "povidka"
    elif cme.is_valid_apply_url(url):
        source = "databazeknih"
        work_type = ""
    elif cme.is_valid_google_books_url(url):
        source = "googlebooks"
        work_type = ""
    elif cme.is_valid_openlibrary_url(url):
        source = "openlibrary"
        work_type = ""
    url_changed = url != row.chosen_url.strip()
    if url_changed or manual_selection:
        confidence = "manual"
        reason = "manual"
    clear_review = url_changed or source != original_source
    updated = replace(row, status=status, chosen_url=url, confidence=confidence, reason=reason, source=source, work_type=work_type)
    if url_changed:
        updated = replace(updated, cover_urls="", selected_cover_url="", cover_reason="")
    if not clear_review:
        return updated
    return replace(
        updated,
        review_published_year="",
        review_publisher="",
        review_tags="",
        review_rating_percent="",
        review_original_title="",
        review_original_publication="",
        review_original_publisher="",
    )


def update_rows_status(rows: Sequence[cme.MatchRow], book_ids: set[int], status: str) -> list[cme.MatchRow]:
    """Zmeni status u vsech vybranych knih podle jejich Calibre ID."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Neznamy status: {status}")
    return [update_row(row, status, row.chosen_url) if row.book_id in book_ids else row for row in rows]


def update_rows_url(rows: Sequence[cme.MatchRow], book_ids: set[int], chosen_url: str) -> list[cme.MatchRow]:
    """Pouzije stejny odkaz pro vsechny vybrane knihy."""
    return [
        update_row(row, row.status, chosen_url, manual_selection=True)
        if row.book_id in book_ids
        else row
        for row in rows
    ]


def cover_urls_from_row(row: cme.MatchRow) -> list[str]:
    """Vrati ulozene kandidatni obalky z jednoho CSV radku."""
    return [url.strip() for url in row.cover_urls.split("|") if url.strip()]


def update_rows_selected_cover(rows: Sequence[cme.MatchRow], book_id: int, selected_cover_url: str) -> list[cme.MatchRow]:
    """Ulozi vybranou obalku jen pokud je mezi kandidatnimi obalkami radku."""
    updated: list[cme.MatchRow] = []
    for row in rows:
        if row.book_id != book_id:
            updated.append(row)
            continue
        cover_urls = cover_urls_from_row(row)
        if selected_cover_url not in cover_urls:
            raise ValueError("Vybrana obalka neni mezi kandidaty.")
        updated.append(replace(row, selected_cover_url=selected_cover_url))
    return updated


REVIEW_OVERRIDE_FIELDS = {
    "Rok vydani": "review_published_year",
    "Vydavatel": "review_publisher",
    "Tagy": "review_tags",
    "Hodnoceni": "review_rating_percent",
    "Originalni nazev": "review_original_title",
    "Originalne vyslo": "review_original_publication",
    "Originalni vydavatel": "review_original_publisher",
}


def update_row_review_override(row: cme.MatchRow, field: str, value: str) -> cme.MatchRow:
    """Ulozi rucni hodnotu z Review tabu do jednoho radku."""
    attr = REVIEW_OVERRIDE_FIELDS.get(field)
    if attr is None:
        raise ValueError(f"Neznamy Review field: {field}")
    return replace(row, **{attr: value.strip()})


def update_rows_review_override(rows: Sequence[cme.MatchRow], book_id: int, field: str, value: str) -> list[cme.MatchRow]:
    """Ulozi rucni hodnotu z Review tabu do vybrane knihy."""
    return [update_row_review_override(row, field, value) if row.book_id == book_id else row for row in rows]


def rows_missing_cover_choice(rows: Sequence[cme.MatchRow], book_ids: set[int]) -> list[cme.MatchRow]:
    """Najde vybrane radky, kde je vice obalek a zadna neni vybrana."""
    missing: list[cme.MatchRow] = []
    for row in rows:
        if row.book_id not in book_ids:
            continue
        if len(cover_urls_from_row(row)) > 1 and not row.selected_cover_url.strip():
            missing.append(row)
    return missing


def sync_single_selected_url(rows: Sequence[cme.MatchRow], book_ids: set[int], edit_url: str) -> list[cme.MatchRow]:
    """U jednoho vybraneho radku pouzije aktualni text z pole Odkaz."""
    if len(book_ids) != 1:
        return list(rows)
    book_id = next(iter(book_ids))
    return [update_row(row, row.status, edit_url) if row.book_id == book_id else row for row in rows]


def mark_rows_as_story(rows: Sequence[cme.MatchRow], book_ids: set[int]) -> list[cme.MatchRow]:
    """Oznaci vybrane radky jako povidky a posle je na rucni kontrolu."""
    updated: list[cme.MatchRow] = []
    for row in rows:
        if row.book_id not in book_ids:
            updated.append(row)
            continue
        source = row.source
        if cme.is_valid_legie_story_url(row.chosen_url):
            source = "legie"
        elif cme.is_valid_databaze_story_url(row.chosen_url):
            source = "databazeknih"
        updated.append(replace(row, status="review", source=source, work_type="povidka"))
    return updated


def sort_rows(rows: Sequence[cme.MatchRow], column: str, descending: bool) -> list[cme.MatchRow]:
    """Seradi radky podle sloupce stejne, jak to pak ukaze tabulka."""
    if column not in TABLE_COLUMNS:
        raise ValueError(f"Neznamy sloupec: {column}")

    def key(row: cme.MatchRow) -> object:
        value = getattr(row, column)
        return value if column == "book_id" else str(value).casefold()

    return sorted(rows, key=key, reverse=descending)


def filter_rows(rows: Sequence[cme.MatchRow], title_filter: str, author_filter: str) -> list[cme.MatchRow]:
    """Vrati radky odpovidajici filtru knihy a autora."""
    title_query = cme.normalize_text(title_filter)
    author_query = cme.normalize_text(author_filter)
    filtered: list[cme.MatchRow] = []
    for row in rows:
        if title_query and title_query not in cme.normalize_text(row.title):
            continue
        if author_query and author_query not in cme.normalize_text(row.authors):
            continue
        filtered.append(row)
    return filtered


def find_row_index(rows: Sequence[cme.MatchRow], book_id: int) -> int | None:
    """Najde pozici knihy v nactenych radcich podle Calibre ID."""
    for index, row in enumerate(rows):
        if row.book_id == book_id:
            return index
    return None


def status_summary(rows: Sequence[cme.MatchRow]) -> str:
    """Spocte radky podle statusu pro spodni stavovy text."""
    counts = {status: 0 for status in VALID_STATUSES}
    for row in rows:
        if row.status in counts:
            counts[row.status] += 1
    return (
        f"Celkem {len(rows)} | approve {counts['approve']} | "
        f"review {counts['review']} | skip {counts['skip']}"
    )


def quit_calibre(
    runner: Callable[[Sequence[str]], cme.CommandResult] = cme.run_command,
    allow_force: bool = False,
) -> int:
    """Pozada Windows o ukonceni Calibre; /F pouzije jen po povoleni v appce."""
    tasklist = runner(["tasklist", "/FI", "IMAGENAME eq calibre.exe"])
    tasklist_text = (tasklist.stdout + tasklist.stderr).lower()
    if tasklist.returncode != 0:
        print((tasklist.stderr or tasklist.stdout or "tasklist failed").strip())
        return tasklist.returncode
    if "calibre.exe" not in tasklist_text:
        print("Calibre nebezi.")
        return 0

    print("Ukoncuju Calibre...")
    taskkill = runner(["taskkill", "/IM", "calibre.exe", "/T"])
    output = (taskkill.stdout or taskkill.stderr or "").strip()
    if taskkill.returncode != 0 and allow_force:
        print("Normalni ukonceni selhalo. Vynucuju zavreni Calibre pres /F...")
        forced = runner(["taskkill", "/IM", "calibre.exe", "/T", "/F"])
        forced_output = (forced.stdout or forced.stderr or "").strip()
        if forced.returncode != 0 and output:
            print(output)
        if forced_output:
            print(forced_output)
        return forced.returncode
    if output:
        print(output)
    return taskkill.returncode


def format_failed_apply_results(path: Path) -> str:
    """Z apply-results CSV udela citelny seznam neuspesnych zapisu."""
    failed_rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") == "failed":
                failed_rows.append(row)

    if not failed_rows:
        return "Failed zapisy: 0"

    lines = ["Failed zapisy:"]
    for row in failed_rows:
        book_id = row.get("book_id", "")
        title = row.get("title", "")
        error = row.get("error", "") or "bez detailu"
        lines.append(f"- {book_id} {title}: {error}")
    return "\n".join(lines)


def format_new_failed_apply_results(base_dir: Path, known_paths: set[Path]) -> str:
    """Najde novy apply-results soubor a vrati seznam failed radku."""
    results_dir = base_dir / cme.APPLY_RESULTS_DIR
    new_paths = [path for path in results_dir.glob("apply-results-*.csv") if path not in known_paths]
    if not new_paths:
        return ""
    newest = max(new_paths, key=lambda path: path.stat().st_mtime)
    return format_failed_apply_results(newest)


def run_apply_then_preview(
    quit_func: Callable[[], int],
    apply_func: Callable[[], int],
    preview_func: Callable[[], int],
    failed_summary_func: Callable[[], str] | None = None,
) -> int:
    """Provede zapisovy workflow: zavrit Calibre, zapsat metadata, nacist nove knihy."""
    quit_result = quit_func()
    if quit_result != 0:
        return quit_result

    apply_result = apply_func()
    if failed_summary_func is not None:
        failed_summary = failed_summary_func()
        if failed_summary:
            print(failed_summary)
    if apply_result != 0:
        return apply_result

    return preview_func()


def run_preview_then_legie_audit(
    preview_func: Callable[[], int],
    audit_func: Callable[[], int],
) -> int:
    """Nejdriv nacte nove knihy, potom spusti Legie audit."""
    preview_result = preview_func()
    if preview_result != 0:
        return preview_result
    return audit_func()


def run_preview_audit_then_cover_audit(
    preview_func: Callable[[], int],
    link_audit_func: Callable[[], int],
    cover_audit_func: Callable[[], int],
) -> int:
    """Nejdriv odkazy, potom kandidatni obalky. Obalky nic nezapisuji do Calibre."""
    preview_result = preview_func()
    if preview_result != 0:
        return preview_result
    link_result = link_audit_func()
    if link_result != 0:
        return link_result
    return cover_audit_func()


def make_preview_with_legie_audit_action(
    args: SimpleNamespace,
    matches_path: Path = cme.MATCHES_PATH,
    preview_runner: Callable[[SimpleNamespace], int] = cme.run_preview,
    audit_runner: Callable[[SimpleNamespace], int] = cme.run_legie_audit,
) -> Callable[[], int]:
    """Pripravi nacitani novych knih vcetne automatickeho Legie auditu."""
    def action() -> int:
        selected_ids = set(getattr(args, "book_ids", None) or [])
        before_ids = match_row_book_ids(matches_path)
        preview_result = preview_runner(args)
        if preview_result != 0:
            return preview_result
        if selected_ids:
            return audit_runner(set_audit_book_ids(args, selected_ids))
        new_ids = match_row_book_ids(matches_path) - before_ids
        if not new_ids:
            print("Audit odkazu: zadne nove radky.")
            return 0
        return audit_runner(set_audit_book_ids(args, new_ids))

    return action


def make_cover_audit_action(
    args: SimpleNamespace,
    matches_path: Path = cme.MATCHES_PATH,
    audit_func: Callable[..., list[cme.MatchRow]] = cme.audit_cover_rows,
) -> Callable[[], int]:
    """Pripravi audit kandidatnich obalek bez zapisu do Calibre."""
    def action() -> int:
        if not cme.matches_storage_exists(matches_path):
            print("Audit obalek: pracovni data neexistuji.")
            return 0
        rows = cme.read_matches_csv(matches_path)
        selected_ids = set(getattr(args, "book_ids", None) or [])
        selected_rows = cme.select_match_rows(rows, book_ids=selected_ids) if selected_ids else rows
        audited_selected = audit_func(
            selected_rows,
            args.library,
            include_existing_covers=bool(getattr(args, "include_existing_covers", False)),
        )
        if selected_ids:
            replacements = {row.book_id: row for row in audited_selected}
            updated_rows = [replacements.get(row.book_id, row) for row in rows]
        else:
            updated_rows = audited_selected
        changed = sum(1 for old, new in zip(rows, updated_rows) if old != new)
        if changed:
            cme.write_matches_csv(matches_path, updated_rows, overwrite=True)
        print(f"Audit obalek: zmeneno {changed} radku")
        return 0

    return action


def make_preview_with_audits_action(
    args: SimpleNamespace,
    matches_path: Path = cme.MATCHES_PATH,
    preview_runner: Callable[[SimpleNamespace], int] = cme.run_preview,
    link_audit_runner: Callable[[SimpleNamespace], int] = cme.run_legie_audit,
    cover_audit_factory: Callable[[SimpleNamespace, Path], Callable[[], int]] | None = None,
) -> Callable[[], int]:
    """Pripravi startup workflow: nove knihy, audit odkazu, audit obalek."""
    preview_with_links = make_preview_with_legie_audit_action(
        args=args,
        matches_path=matches_path,
        preview_runner=preview_runner,
        audit_runner=link_audit_runner,
    )
    cover_factory = cover_audit_factory or make_cover_audit_action
    return lambda: run_preview_audit_then_cover_audit(
        preview_func=lambda: preview_with_links(),
        link_audit_func=lambda: 0,
        cover_audit_func=cover_factory(args, matches_path),
    )


def make_apply_action(
    args: SimpleNamespace,
    allow_force: bool,
    base_dir: Path = APP_DIR,
    matches_path: Path = cme.MATCHES_PATH,
    quit_runner: Callable[[bool], int] | None = None,
    apply_runner: Callable[[SimpleNamespace], int] | None = None,
    preview_runner: Callable[[SimpleNamespace], int] | None = None,
    audit_runner: Callable[[SimpleNamespace], int] | None = None,
) -> Callable[[], int]:
    """Pripravi zapisovy workflow a zapamatuje apply-results soubory pred zapisem."""
    results_dir = base_dir / cme.APPLY_RESULTS_DIR
    known_apply_results = set(results_dir.glob("apply-results-*.csv"))
    quit_action = quit_runner or (lambda force: quit_calibre(allow_force=force))
    apply_action = apply_runner or cme.run_apply
    preview_action = preview_runner or cme.run_preview
    audit_action = audit_runner or cme.run_legie_audit
    preview_with_audit_action = make_preview_with_legie_audit_action(
        args=args,
        matches_path=matches_path,
        preview_runner=preview_action,
        audit_runner=audit_action,
    )

    return lambda: run_apply_then_preview(
        quit_func=lambda: quit_action(allow_force),
        apply_func=lambda: apply_action(args),
        preview_func=preview_with_audit_action,
        failed_summary_func=lambda: format_new_failed_apply_results(base_dir, known_apply_results),
    )


def make_cover_action(
    args: SimpleNamespace,
    allow_force: bool,
    quit_runner: Callable[[bool], int] | None = None,
    cover_runner: Callable[[SimpleNamespace], int] = cme.run_covers,
) -> Callable[[], int]:
    """Pripravi zapis obalek: nejdriv zavre Calibre, potom spusti cover workflow."""
    quit_action = quit_runner or (lambda force: quit_calibre(allow_force=force))

    def action() -> int:
        quit_result = quit_action(allow_force)
        if quit_result != 0:
            return quit_result
        return cover_runner(args)

    return action


def make_rebuild_action(
    args: SimpleNamespace,
    matches_path: Path,
    backups_dir: Path = APP_DIR / "backups" / "matches",
    backup_func: Callable[[Path, Path], Path | None] = cme.backup_matches_csv,
    preview_runner: Callable[[SimpleNamespace], int] = cme.run_preview,
) -> Callable[[], int]:
    """Pripravi rebuild pracovnich dat: zaloha stareho uloziste a novy preview od nuly."""
    args.overwrite = True

    def action() -> int:
        backup_path = backup_func(matches_path, backups_dir)
        if backup_path is None:
            print("Zaloha pracovnich dat: neni co zalohovat.")
        else:
            print(f"Zaloha pracovnich dat: {backup_path}")
        return preview_runner(args)

    return action


def make_legie_audit_action(
    args: SimpleNamespace,
    audit_runner: Callable[[SimpleNamespace], int] = cme.run_legie_audit,
) -> Callable[[], int]:
    """Pripravi audit odkazu nad pracovnimi daty."""
    return lambda: audit_runner(args)


def make_rollback_action(
    library: str,
    backup_path: Path,
    allow_force: bool,
    quit_runner: Callable[[bool], int] | None = None,
    restore_runner: Callable[[str, Path], Path] | None = None,
) -> Callable[[], int]:
    """Pripravi rollback: zavre Calibre a obnovi metadata.db ze zalohy."""
    quit_action = quit_runner or (lambda force: quit_calibre(allow_force=force))

    def action() -> int:
        quit_result = quit_action(allow_force)
        if quit_result != 0:
            return quit_result
        if restore_runner is None:
            return cme.run_restore_backup(SimpleNamespace(library=library, backup=backup_path))

        safety_backup = restore_runner(library, backup_path)
        print(f"Obnoveno z: {backup_path}")
        print(f"Nouzova zaloha pred rollbackem: {safety_backup}")
        return 0

    return action


class CalibreMetaApp:
    def __init__(self, root: tk.Tk, matches_path: Path | None = None) -> None:
        self.root = root
        self.matches_path = matches_path or (APP_DIR / cme.MATCHES_PATH)
        self.rows: list[cme.MatchRow] = []
        self.buttons: list[tk.Widget] = []
        self.sort_descending: dict[str, bool] = {}
        self.worker_running = False

        self.status_var = tk.StringVar(value="Pripraveno")
        self.edit_url_var = tk.StringVar(value="")
        self.filter_title_var = tk.StringVar(value="")
        self.filter_author_var = tk.StringVar(value="")
        self.library_var = tk.StringVar(value=initial_library_path())

        self.root.title(app_title())
        self.root.geometry("1200x760")
        self._build_ui()
        self.filter_title_var.trace_add("write", lambda *_args: self._refresh_table())
        self.filter_author_var.trace_add("write", lambda *_args: self._refresh_table())
        self.load_csv(show_message=True)
        schedule_startup_preview(self.root, self.run_preview)

    def _build_ui(self) -> None:
        toolbar_container = ttk.Frame(self.root, padding=8)
        toolbar_container.pack(fill=tk.X)

        toolbar = ttk.Frame(toolbar_container)
        toolbar.pack(fill=tk.X)

        self._add_button(toolbar, PRIMARY_TOOLBAR_LABELS[0], self.load_csv).pack(side=tk.LEFT, padx=(0, 6))
        self._add_button(toolbar, PRIMARY_TOOLBAR_LABELS[1], self.run_preview).pack(side=tk.LEFT, padx=(0, 6))
        self._add_button(toolbar, PRIMARY_TOOLBAR_LABELS[2], self.run_legie_audit).pack(side=tk.LEFT, padx=(0, 6))
        self._add_button(toolbar, PRIMARY_TOOLBAR_LABELS[3], self.save_csv).pack(side=tk.LEFT, padx=(0, 6))
        spacing = toolbar_spacing()
        ttk.Frame(toolbar, width=spacing["before_approve"]).pack(side=tk.LEFT)
        self._add_colored_button(toolbar, "Approve", lambda: self.set_selected_status("approve"), "approve").pack(side=tk.LEFT, padx=(0, spacing["between_status"]))
        self._add_colored_button(toolbar, "Review", lambda: self.set_selected_status("review"), "review").pack(side=tk.LEFT, padx=(0, spacing["between_status"]))
        self._add_colored_button(toolbar, "Skip", lambda: self.set_selected_status("skip"), "skip").pack(side=tk.LEFT, padx=(0, spacing["after_skip"]))
        self._add_colored_button(toolbar, "Povidka", self.mark_selected_story, "story").pack(side=tk.LEFT, padx=(0, 6))
        self._add_colored_button(toolbar, "Zapsat do Calibre", self.run_apply, "apply").pack(side=tk.RIGHT)

        url_bar = ttk.Frame(toolbar_container)
        url_bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(url_bar, text="Odkaz").pack(side=tk.LEFT, padx=(0, 6))
        url_entry = ttk.Entry(url_bar, textvariable=self.edit_url_var)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._add_button(url_bar, CLEAR_BUTTON_LABEL, lambda: clear_text_var(self.edit_url_var)).pack(side=tk.LEFT, padx=(0, 8))
        self._add_button(url_bar, URL_BAR_BUTTON_LABELS[0], self.apply_selected_url).pack(side=tk.LEFT, padx=(0, 6))
        self._add_button(url_bar, URL_BAR_BUTTON_LABELS[1], self.open_selected_url).pack(side=tk.LEFT)

        filter_bar = ttk.Frame(toolbar_container)
        filter_bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(filter_bar, text="Filter knih").pack(side=tk.LEFT, padx=(0, 6))
        title_filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_title_var, width=34)
        title_filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._add_button(filter_bar, CLEAR_BUTTON_LABEL, lambda: clear_text_var(self.filter_title_var)).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(filter_bar, text="Filter autoru").pack(side=tk.LEFT, padx=(0, 6))
        author_filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_author_var, width=28)
        author_filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._add_button(filter_bar, CLEAR_BUTTON_LABEL, lambda: clear_text_var(self.filter_author_var)).pack(side=tk.LEFT)

        table_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        table_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(table_frame, columns=TABLE_COLUMNS, show="headings", selectmode="extended")
        vertical_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        horizontal_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set)

        widths = {
            "book_id": 70,
            "title": 260,
            "authors": 190,
            "status": 90,
            "source": 90,
            "work_type": 90,
            "chosen_url": 420,
            "reason": 160,
        }
        headings = {
            "book_id": "ID",
            "title": "Kniha",
            "authors": "Autor",
            "status": "Status",
            "source": "Zdroj",
            "work_type": "Typ",
            "chosen_url": "Odkaz",
            "reason": "Duvod",
        }
        for column in TABLE_COLUMNS:
            self.tree.heading(column, text=headings[column], command=lambda selected_column=column: self.sort_by_column(selected_column))
            self.tree.column(column, width=widths[column], minwidth=widths[column], stretch=column in {"title", "chosen_url"})

        self.tree.tag_configure("approve", background="#e8f5e9")
        self.tree.tag_configure("review", background="#fff8e1")
        self.tree.tag_configure("skip", background="#f5f5f5")
        self.tree.bind("<<TreeviewSelect>>", self.on_row_selected)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        output_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        output_frame.pack(fill=tk.BOTH)
        self.output = tk.Text(output_frame, height=7, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True)

        status_bar = ttk.Label(self.root, textvariable=self.status_var, padding=(8, 4))
        status_bar.pack(fill=tk.X)

        library_bar = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        library_bar.pack(fill=tk.X)
        ttk.Label(library_bar, text="Knihovna").pack(side=tk.LEFT, padx=(0, 6))
        library_entry = ttk.Entry(library_bar, textvariable=self.library_var, state="readonly")
        library_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._add_button(library_bar, BOTTOM_LIBRARY_BAR_LABELS[0], self.choose_library).pack(side=tk.LEFT, padx=(0, 6))
        self._add_button(library_bar, BOTTOM_LIBRARY_BAR_LABELS[1], self.use_calibre_library).pack(side=tk.LEFT, padx=(0, 18))
        self._add_colored_button(library_bar, BOTTOM_LIBRARY_BAR_LABELS[2], self.run_update_selected, "update").pack(side=tk.LEFT, padx=(0, spacing["after_update"]))
        self._add_colored_button(library_bar, BOTTOM_LIBRARY_BAR_LABELS[3], self.run_rebuild, "rebuild").pack(side=tk.LEFT, padx=(0, 6))
        self._add_colored_button(library_bar, BOTTOM_LIBRARY_BAR_LABELS[4], self.run_rollback, "rollback").pack(side=tk.LEFT)

    def _add_button(self, parent: tk.Widget, text: str, command: Callable[[], object]) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        self.buttons.append(button)
        return button

    def _add_colored_button(self, parent: tk.Widget, text: str, command: Callable[[], object], kind: str) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            padx=10,
            pady=3,
            relief=tk.RAISED,
            borderwidth=1,
            **button_colors(kind),
        )
        self.buttons.append(button)
        return button

    def library_path(self) -> str:
        """Vrati aktualni knihovnu z pole Knihovna."""
        return self.library_var.get().strip() or cme.DEFAULT_LIBRARY

    def choose_library(self) -> None:
        current = self.library_path()
        initial_dir = current if Path(current).exists() else str(Path.home())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Vyber Calibre knihovnu",
            initialdir=initial_dir,
        )
        if selected:
            self.set_library_path(selected)

    def use_calibre_library(self) -> None:
        library = read_calibre_library_path()
        if not library:
            messagebox.showerror("Calibre", "Nenasel jsem aktualni knihovnu v Calibre configu.")
            return
        self.set_library_path(library)

    def set_library_path(self, library: str) -> bool:
        library = library.strip()
        if not library:
            messagebox.showerror("Knihovna", "Cesta ke knihovne je prazdna.")
            return False
        if not cme.metadata_db_path(library).exists():
            messagebox.showerror("Knihovna", f"Ve slozce nevidim metadata.db:\n{library}")
            return False
        save_library_path(library)
        self.library_var.set(library)
        self._set_status(f"Knihovna: {library}")
        return True

    def ask_yes_no(self, title: str, message: str, default_yes: bool = True) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        result = {"confirmed": False}
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=message, justify=tk.LEFT).pack(anchor="w")

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(14, 0))

        def confirm() -> None:
            result["confirmed"] = True
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        no_button = ttk.Button(buttons, text="Ne", command=cancel)
        no_button.pack(side=tk.RIGHT, padx=(6, 0))
        yes_button = ttk.Button(buttons, text="Ano", command=confirm)
        yes_button.pack(side=tk.RIGHT)
        default_button = yes_button if default_yes else no_button
        default_button.focus_set()
        dialog.bind("<Return>", lambda event: confirm() if default_yes else cancel())
        dialog.bind("<Escape>", lambda event: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        center_dialog(dialog, self.root)
        dialog.wait_window()
        return result["confirmed"]

    def load_csv(self, show_message: bool = True) -> None:
        if not cme.matches_storage_exists(self.matches_path):
            self.rows = []
            self._refresh_table()
            self._set_status(f"Soubor nenalezen: {self.matches_path}")
            return
        try:
            self.rows = cme.read_matches_csv(self.matches_path)
        except Exception as exc:
            messagebox.showerror("Chyba", f"Pracovni data nejde nacist:\n{exc}")
            return
        self._refresh_table()
        self._set_status(status_summary(self.rows))
        if show_message:
            self._write_output(f"Nacteno: {self.matches_path}\n{status_summary(self.rows)}")

    def save_csv(self, show_message: bool = True) -> bool:
        try:
            cme.write_matches_csv(self.matches_path, self.rows, overwrite=True)
        except Exception as exc:
            messagebox.showerror("Chyba", f"Pracovni data nejde ulozit:\n{exc}")
            return False
        self._set_status(f"Ulozeno. {status_summary(self.rows)}")
        if show_message:
            self._write_output(f"Ulozeno: {self.matches_path}")
        return True

    def _refresh_table(self) -> None:
        selected_ids = self._selected_book_ids()
        self.tree.delete(*self.tree.get_children())
        visible_rows = filter_rows(self.rows, self.filter_title_var.get(), self.filter_author_var.get())
        for row in visible_rows:
            values = tuple(getattr(row, column) for column in TABLE_COLUMNS)
            self.tree.insert("", tk.END, iid=str(row.book_id), values=values, tags=(row.status,))
        for selected in selected_ids:
            if self.tree.exists(str(selected)):
                self.tree.selection_add(str(selected))
                self.tree.see(str(selected))

    def _selected_book_ids(self) -> set[int]:
        selection = self.tree.selection() if hasattr(self, "tree") else ()
        selected: set[int] = set()
        for item in selection:
            try:
                selected.add(int(item))
            except ValueError:
                continue
        return selected

    def _selected_book_id(self) -> int | None:
        selected = sorted(self._selected_book_ids())
        if not selected:
            return None
        return selected[0]

    def _selected_index(self) -> int | None:
        selected = self._selected_book_id()
        if selected is None:
            return None
        return find_row_index(self.rows, selected)

    def on_row_selected(self, event: tk.Event | None = None) -> None:
        index = self._selected_index()
        if index is None:
            return
        row = self.rows[index]
        self.edit_url_var.set(row.chosen_url)

    def sort_by_column(self, column: str) -> None:
        descending = not self.sort_descending.get(column, False)
        self.sort_descending[column] = descending
        self.rows = sort_rows(self.rows, column, descending)
        self._refresh_table()
        self._set_status(status_summary(self.rows))

    def set_selected_status(self, status: str) -> None:
        selected = self._selected_book_ids()
        if not selected:
            messagebox.showinfo("Vyber radek", "Nejdriv vyber knihu v tabulce.")
            return
        missing_cover = rows_missing_cover_choice(self.rows, selected) if status == "approve" else []
        if missing_cover:
            titles = "\n".join(f"- {row.book_id} {row.title}" for row in missing_cover[:8])
            messagebox.showinfo("Vyber obalku", "Nejdriv vyber jednu obalku:\n" + titles)
            return
        try:
            self.rows = update_rows_status(self.rows, selected, status)
        except ValueError as exc:
            messagebox.showerror("Chyba", str(exc))
            return
        self._refresh_table()
        self._set_status(status_summary(self.rows))

    def mark_selected_story(self) -> None:
        selected = self._selected_book_ids()
        if not selected:
            messagebox.showinfo("Vyber radek", "Nejdriv vyber knihu v tabulce.")
            return
        self.rows = mark_rows_as_story(self.rows, selected)
        self._refresh_table()
        self._set_status(status_summary(self.rows))

    def apply_selected_url(self) -> None:
        selected = self._selected_book_ids()
        if not selected:
            messagebox.showinfo("Vyber radek", "Nejdriv vyber knihu v tabulce.")
            return
        self.rows = update_rows_url(self.rows, selected, self.edit_url_var.get())
        self._refresh_table()
        self._set_status(status_summary(self.rows))

    def open_selected_url(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Vyber radek", "Nejdriv vyber knihu v tabulce.")
            return
        url = self.rows[index].chosen_url.strip()
        if not url:
            messagebox.showinfo("Bez odkazu", "Vybrany radek nema odkaz.")
            return
        open_url_in_new_window(url)

    def run_preview(self) -> None:
        if not self.save_csv(show_message=False):
            return
        args = make_script_args(self.library_path())
        action = make_preview_with_audits_action(args, matches_path=self.matches_path)
        self._run_background("Nacitani novych knih + Audit odkazu + Audit obalek", action, reload_after=True)

    def run_update_selected(self) -> None:
        selected = self._selected_book_ids()
        if not selected:
            messagebox.showinfo("Vyber radek", "Nejdriv vyber knihu v tabulce.")
            return
        if not self.save_csv(show_message=False):
            return
        args = make_script_args(self.library_path())
        args.book_ids = sorted(selected)
        action = make_preview_with_audits_action(args, matches_path=self.matches_path)
        self._run_background("Update vybranych + Audit odkazu + Audit obalek", action, reload_after=True)

    def run_rebuild(self) -> None:
        message = (
            "Rebuild prepise pracovni data.\n"
            "Stara pracovni data ulozim do backups\\matches.\n"
            "Knihy s existujicim odkazem nebudu hledat znovu.\n"
            "Pokracovat?"
        )
        if not self.ask_yes_no("Rebuild data", message, default_yes=False):
            return
        args = make_script_args(self.library_path(), overwrite=True)
        action = make_rebuild_action(args, self.matches_path)
        self._run_background("Rebuild data", action, reload_after=True)

    def run_legie_audit(self) -> None:
        selected = self._selected_book_ids()
        self.rows = sync_single_selected_url(self.rows, selected, self.edit_url_var.get())
        self._refresh_table()
        if not self.save_csv(show_message=False):
            return
        args = make_legie_audit_args(self.library_path(), selected if selected else None)
        action = make_legie_audit_action(args)
        self._run_background("Audit odkazu", action, reload_after=True)

    def run_apply(self) -> None:
        confirmed, allow_force = self.ask_apply_confirmation()
        if not confirmed:
            return
        if not self.save_csv(show_message=False):
            return
        args = make_script_args(self.library_path())
        action = make_apply_action(args=args, allow_force=allow_force, matches_path=self.matches_path)
        self._run_background("Zapis do Calibre", action, reload_after=True)

    def choose_rollback_backup(self) -> Path | None:
        """Necha uzivatele vybrat metadata.db zalohu pro rollback."""
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Vyber zalohu metadata.db",
            initialdir=BACKUPS_DIR,
            filetypes=[
                ("Calibre metadata zalohy", "metadata*.db"),
                ("SQLite DB", "*.db"),
                ("Vsechny soubory", "*.*"),
            ],
        )
        return Path(selected) if selected else None

    def run_rollback(self) -> None:
        backup_path = self.choose_rollback_backup()
        if backup_path is None:
            return
        confirmed, allow_force = self.ask_rollback_confirmation(backup_path)
        if not confirmed:
            return
        action = make_rollback_action(
            library=self.library_path(),
            backup_path=backup_path,
            allow_force=allow_force,
        )
        self._run_background("Rollback zalohy", action, reload_after=False)

    def ask_apply_confirmation(self) -> tuple[bool, bool]:
        dialog = tk.Toplevel(self.root)
        dialog.title("Zapsat do Calibre")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        allow_force_var = tk.BooleanVar(value=True)
        result = {"confirmed": False}

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=apply_confirmation_message(), justify=tk.LEFT).pack(anchor="w")
        ttk.Checkbutton(
            body,
            text="Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F",
            variable=allow_force_var,
        ).pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(14, 0))

        def confirm() -> None:
            result["confirmed"] = True
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        cancel_button = ttk.Button(buttons, text="Zrusit", command=cancel)
        cancel_button.pack(side=tk.RIGHT, padx=(6, 0))
        confirm_button = ttk.Button(buttons, text="Pokracovat", command=confirm)
        confirm_button.pack(side=tk.RIGHT)
        bind_default_dialog_actions(dialog, confirm, cancel, confirm_button)
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        center_dialog(dialog, self.root)
        dialog.wait_window()
        return result["confirmed"], bool(allow_force_var.get())

    def ask_rollback_confirmation(self, backup_path: Path) -> tuple[bool, bool]:
        dialog = tk.Toplevel(self.root)
        dialog.title("Rollback zalohy")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        allow_force_var = tk.BooleanVar(value=True)
        result = {"confirmed": False}

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        message = (
            "Appka udela:\n"
            "1. pokusi se zavrit Calibre\n"
            "2. ulozi aktualni metadata.db jako nouzovou zalohu\n"
            "3. obnovi vybranou zalohu:\n"
            f"{backup_path}"
        )
        ttk.Label(body, text=message, justify=tk.LEFT).pack(anchor="w")
        ttk.Checkbutton(
            body,
            text="Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F",
            variable=allow_force_var,
        ).pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(14, 0))

        def confirm() -> None:
            result["confirmed"] = True
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        cancel_button = ttk.Button(buttons, text="Zrusit", command=cancel)
        cancel_button.pack(side=tk.RIGHT, padx=(6, 0))
        confirm_button = ttk.Button(buttons, text="Obnovit", command=confirm)
        confirm_button.pack(side=tk.RIGHT)
        # Rollback je destruktivni, proto Enter nechava bezpecnou volbu Zrusit.
        cancel_button.focus_set()
        dialog.bind("<Return>", lambda event: cancel())
        dialog.bind("<Escape>", lambda event: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        center_dialog(dialog, self.root)
        dialog.wait_window()
        return result["confirmed"], bool(allow_force_var.get())

    def _run_background(self, title: str, action: Callable[[], int], reload_after: bool) -> None:
        if self.worker_running:
            messagebox.showinfo("Bezi akce", "Pockej, az skonci aktualni akce.")
            return
        self.worker_running = True
        self._set_buttons_enabled(False)
        self._write_output(f"{title}...")
        self._set_status(title)

        def worker() -> None:
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    result = action()
                text = buffer.getvalue().strip()
            except Exception as exc:
                result = 1
                text = f"Chyba: {exc}"
            self.root.after(0, lambda: self._finish_background(title, result, text, reload_after))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_background(self, title: str, result: int, text: str, reload_after: bool) -> None:
        self.worker_running = False
        self._set_buttons_enabled(True)
        if reload_after and result == 0:
            self.load_csv(show_message=False)
        suffix = "OK" if result == 0 else "CHYBA"
        output = text or "(bez vystupu)"
        self._write_output(f"{title}: {suffix}\n\n{output}")
        self._set_status(f"{title}: {suffix}. {status_summary(self.rows)}")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in self.buttons:
            button.configure(state=state)

    def _write_output(self, text: str) -> None:
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)


def main() -> int:
    # Dvojklik na .py nemusi startovat ve slozce projektu, proto se sem prepneme.
    os.chdir(APP_DIR)
    root = tk.Tk()
    CalibreMetaApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
