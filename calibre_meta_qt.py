# Qt desktop appka pro pohodlne schvalovani metadat v modernim Windows okne.

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import logging
import os
import socket
import threading
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import calibre_meta_app as shared
import calibre_meta_edit as cme


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.4.9"
PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
ICON_PATH = APP_DIR / "app_icon.svg"
ICON_DIR = APP_DIR / "icons"
ASSETS_ICON_DIR = APP_DIR / "assets" / "icons"
TABLE_COLUMNS = ("ID", "Kniha", "Autor", "Status", "Zdroj", "Typ", "Odkaz", "Duvod")
REQUIRED_COLUMN_INDEXES = {0, 1, 2}
MIN_COLUMN_WIDTH = 36
STATUS_FILTER_VALUES = ("approve", "review", "skip")
DEFAULT_STATUS_FILTER_VALUES = {"approve", "review"}
SOURCE_FILTER_VALUES = ("databazeknih", "legie", "googlebooks", "openlibrary")
TYPE_FILTER_VALUES = ("", "povidka")
THEME_VALUES = ("system", "light", "dark")
AI_PROVIDER_VALUES = ("off", "ollama", "anthropic", "openai")
REVIEW_EDITABLE_FIELDS = (
    "Rok vydani",
    "Vydavatel",
    "Tagy",
    "Hodnoceni",
    "Originalni nazev",
    "Originalne vyslo",
)
AUTO_SETTING_DEFAULTS = {
    "startup_preview": True,
    "auto_link_audit": True,
    "auto_cover_audit": True,
}
AI_SETTING_DEFAULTS = {
    "provider": "off",
    "model": "llama3.1:8b",
    "text_limit": 5000,
    "timeout": 120,
    # Kolik knih se pri multiimportu analyzuje soubezne. 5 je zmerene optimum
    # pro cloud (4.0x) i pro Ollamu (3.13x). Drzime strop nizko: kandidati se
    # tahaji z databazeknih a nechceme jim delat zatez.
    "workers": 5,
}
MULTIIMPORT_WORKERS_MIN = 1
MULTIIMPORT_WORKERS_MAX = 8
UNIFIED_IMPORT_LAST_FOLDER_KEY = "unified_import_last_folder"
UNIFIED_IMPORT_DIALOG_STATE_KEY = "unified_import_dialog_state"
# Default model pro kazdeho providera; pouzije se, kdyz uzivatel nechal pole prazdne.
# Ollama: `llama3.1:8b` je overeny na extrakci nazvu/autora z textu knihy
# (drivejsi `llama3` byl obecny tag, ktery uzivatel nemusi mit stazeny).
AI_PROVIDER_DEFAULT_MODELS = {
    "off": "llama3.1:8b",
    "ollama": "llama3.1:8b",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
}


def app_title() -> str:
    """Vrati titulek hlavniho okna vcetne verze."""
    return f"Calibre Meta Edit {APP_VERSION}"


def asset_icon_path(name: str) -> Path | None:
    """Najde SVG ikonu v assets/icons podle jmena bez pripony.

    Vrati cestu jen kdyz soubor existuje; jinak None, aby app pri chybejici
    ikone nespadla a mohla pouzit zalozni ikonu.
    """
    path = ASSETS_ICON_DIR / f"{name}.svg"
    return path if path.exists() else None


def book_import_file_filter() -> str:
    """Slozi filtr pro vyber knihy z podporovanych pripon (epub + Calibre nastroje)."""
    patterns = " ".join("*" + extension for extension, _label in sorted(cme.BOOK_IMPORT_FORMATS))
    epub_label = next(label for extension, label in cme.BOOK_IMPORT_FORMATS if extension == ".epub")
    return f"Knihy ({patterns});;{epub_label} (*.epub);;Vsechny soubory (*.*)"


def is_probably_online(timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
            return True
    except OSError:
        return False


def multiimport_analysis_summary(items: Sequence[cme.MultiImportBatchItem]) -> str:
    counts = {
        status: sum(item.status == status for item in items)
        for status in ("ready", "needs_review", "duplicate_warning", "analysis_error")
    }
    successful = counts["ready"] + counts["needs_review"] + counts["duplicate_warning"]
    return "\n".join(
        (
            "Multiimport analyza dokoncena.",
            "",
            f"Podporovane soubory: {len(items)}",
            f"Analyzovano uspesne: {successful}",
            f"Pripraveno: {counts['ready']}",
            f"Vyzaduje kontrolu: {counts['needs_review']}",
            f"Varovani na duplicitu: {counts['duplicate_warning']}",
            f"Chyby: {counts['analysis_error']}",
            "",
            "Nic nebylo importovano.",
        )
    )


def multiimport_status_label(status: str) -> str:
    labels = {
        "pending": "Čeká",
        "analyzing": "Analyzuje se",
        "ready": "Připraveno",
        "needs_review": "Ke kontrole",
        "duplicate_warning": "Možná duplicita",
        "analysis_error": "Chyba analýzy",
        "skipped": "Přeskočeno",
        "writing": "Zapisuje se",
        "written": "Zapsáno",
        "write_error": "Chyba zápisu",
    }
    return labels.get(status, f"Neznámý stav: {status}")


def multiimport_compact_status_label(status: str) -> str:
    labels = {
        "ready": "✓",
        "needs_review": "👁",
        "duplicate_warning": "⧉",
        "analysis_error": "✕",
        "writing": "↻",
        "written": "✓",
        "write_error": "✕",
    }
    return labels.get(status, multiimport_status_label(status))


def multiimport_status_tooltip(status: str) -> str:
    labels = {
        "ready": "OK",
        "needs_review": "Kontrola",
        "duplicate_warning": "Duplicita",
        "analysis_error": "Chyba",
        "writing": "Zápis",
        "written": "Hotovo",
        "write_error": "Chyba zápisu",
    }
    return labels.get(status, multiimport_status_label(status))


def multiimport_row_status_symbol(item: cme.MultiImportBatchItem) -> str:
    """Symbol do sloupce Stav; rucne potvrzena polozka ma vlastni znacku."""
    if item.manually_confirmed and item.status not in ("written", "write_error", "writing"):
        return "W"
    return multiimport_compact_status_label(item.status)


def multiimport_row_status_tooltip(item: cme.MultiImportBatchItem) -> str:
    if item.manually_confirmed and item.status not in ("written", "write_error", "writing"):
        return "Ručně potvrzeno k importu"
    return multiimport_status_tooltip(item.status)


def multiimport_item_matches_filter(
    item: cme.MultiImportBatchItem,
    *,
    name_query: str = "",
    statuses: set[str] | None = None,
    checked: bool | None = None,
) -> bool:
    """Rozhodne, zda polozka projde filtry v okne vysledku multiimportu.

    `name_query` prazdny = bez omezeni. `statuses` None = vsechny stavy,
    jinak projdou jen polozky se stavem v mnozine (zaskrtavatka). `checked`
    filtruje podle zaskrtnuti pro import (None = obojii).
    """
    if name_query and cme.normalize_text(name_query) not in cme.normalize_text(item.display_name):
        return False
    if statuses is not None and item.status not in statuses:
        return False
    if checked is not None and bool(item.checked_for_import) != checked:
        return False
    return True


def multiimport_write_error_label(error: str) -> str:
    """Prelozi znamy kod chyby zapisu do lidske vety; neznamy vrati jak je."""
    labels = {
        "strong-duplicate": "Kniha už v Calibre je (silná duplicita).",
        "strong-duplicate-after-close": (
            "Kniha už v Calibre je (duplicita zjištěná po zavření Calibre)."
        ),
        "missing-title-or-author": "Chybí název nebo autor.",
        "quit-calibre-failed": "Nepodařilo se zavřít Calibre.",
        "new-book-id-not-unique": "Nepodařilo se určit ID nově přidané knihy.",
        "write-failed": "Zápis selhal.",
    }
    return labels.get(error.strip(), error.strip())


def multiimport_write_error_text(item: cme.MultiImportBatchItem) -> str:
    """Lidsky duvod, proc u polozky selhal zapis (prazdny, kdyz zadny neni).

    Duvod bereme z `write_result`, ne z `error_message`: to je vyhrazene chybam
    analyzy a validace podle nej polozku blokuje.
    """
    if item.status != "write_error" or item.write_result is None:
        return ""
    return multiimport_write_error_label(item.write_result.error or item.write_result.status)


def multiimport_write_failures_text(items: Sequence[cme.MultiImportBatchItem]) -> str:
    """Vypis knih, u kterych zapis selhal, i s duvodem."""
    failed = [item for item in items if item.status == "write_error"]
    if not failed:
        return ""
    lines = ["", "Nepodařilo se naimportovat:"]
    for item in failed:
        reason = multiimport_write_error_text(item)
        lines.append(f"- {item.display_name}: {reason}" if reason else f"- {item.display_name}")
    return "\n".join(lines)


def multiimport_validation_reason_label(reason: str) -> str:
    labels = {
        "no_checked_items": "Není vybraná žádná položka.",
        "status_not_ready": "Položka není ve stavu Připraveno.",
        "missing_analysis": "Chybí analýza.",
        "missing_preview": "Chybí náhled importu.",
        "missing_candidate": "Chybí vybraný kandidát.",
        "duplicate_warning": "Položka má varování na duplicitu.",
        "analysis_error": "Položka má chybu analýzy.",
        "invalid_preview": "Náhled importu není validní: chybí název nebo autor.",
        "candidate_score_below_100": "Doporučený kandidát nemá 100% shodu.",
        "missing_preview_url": "Náhled nemá zdrojový odkaz.",
        "missing_candidate_url": "Doporučený kandidát nemá odkaz.",
        "preview_url_mismatch": "Odkaz náhledu neodpovídá doporučenému kandidátovi.",
        "multiple_100_candidate_urls": (
            "Existuje více různých kandidátů se 100% shodou; aplikace nemůže "
            "bezpečně vybrat jednu Databáze knih URL. Ponechte položku ke kontrole "
            "a použijte jednopoložkový ruční postup."
        ),
        "recommended_not_unique_100_candidate": "Doporučený kandidát není jediná 100% shoda.",
    }
    return labels.get(reason, f"Neznámý důvod: {reason}")


def multiimport_validation_summary_text(result: cme.MultiImportValidationResult) -> str:
    if result.ok:
        return (
            "Výběr je validní. "
            f"Položek připravených k budoucímu importu: {len(result.valid_items)}. "
            "Nic nebylo importováno."
        )

    lines = [
        "Výběr není validní.",
        f"Položek připravených k budoucímu importu: {len(result.valid_items)}",
        f"Blokující problémy: {len(result.issues)}",
    ]
    for issue in result.issues:
        prefix = f"{issue.item.display_name}: " if issue.item is not None else ""
        lines.append(f"- {prefix}{multiimport_validation_reason_label(issue.reason)}")
    lines.extend(("", "Nic nebylo importováno."))
    return "\n".join(lines)


def multiimport_item_row_text(item: cme.MultiImportBatchItem) -> str:
    parts = [
        item.display_name,
        multiimport_status_label(item.status),
        f"Predvybrano: {'ano' if item.checked_for_import else 'ne'}",
        f"Duplicity: {len(item.duplicates)}",
    ]
    if item.error_message:
        parts.append(item.error_message)
    return " | ".join(parts)


def multiimport_item_detail_text(item: cme.MultiImportBatchItem) -> str:
    preview = item.current_preview or cme.ImportPreview()
    lines = [
        f"Stav: {multiimport_status_label(item.status)}",
        f"Predvybrano: {'ano' if item.checked_for_import else 'ne'}",
        f"Rucne potvrzeno: {'ano' if item.manually_confirmed else 'ne'}",
        "",
        f"Nazev: {preview.title}",
        f"Autori: {preview.authors}",
        f"Zdroj: {preview.source}",
        f"Odkaz: {preview.url}",
    ]
    if item.selected_candidate is not None:
        candidate = item.selected_candidate
        lines.extend(
            (
                "",
                "Doporuceny kandidat:",
                f"{candidate.title} / {candidate.authors} / {candidate.score}%",
                f"{candidate.source}: {candidate.url}",
            )
        )
    # Precheck popisuje puvodni automatickou analyzu. Po rucnim potvrzeni uz
    # neplati (napr. "chybi kandidat", kdyz si ho uzivatel prave vybral).
    if item.status == "needs_review" and item.analysis is not None and not item.manually_confirmed:
        issues = cme.multiimport_precheck_issues(item.analysis)
        if issues:
            lines.extend(("", "Důvod kontroly:"))
            lines.extend(f"- {multiimport_validation_reason_label(reason)}" for reason in issues)
        if "multiple_100_candidate_urls" in issues:
            candidates = []
            seen_urls = set()
            for candidate in item.analysis.candidates:
                url = candidate.url.strip()
                if candidate.score < 100 or not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append(candidate)
            if candidates:
                lines.extend(("", "Konfliktní 100% kandidáti:"))
                lines.extend(f"- {candidate.title}: {candidate.url}" for candidate in candidates)
            lines.extend(
                (
                    "",
                    "Automatický import je zablokován, protože nelze bezpečně vybrat jednu URL.",
                    "Ponechte řádek ke kontrole a použijte jednopoložkový ruční postup.",
                )
            )
    lines.extend(("", f"Duplicity: {len(item.duplicates)}"))
    for duplicate in item.duplicates:
        lines.append(f"ID {duplicate.book_id}: {duplicate.title} / {duplicate.authors} / {duplicate.score}%")
    if item.error_message:
        lines.extend(("", f"Chyba: {item.error_message}"))
    write_error = multiimport_write_error_text(item)
    if write_error:
        lines.extend(("", f"Import selhal: {write_error}"))
    return "\n".join(lines)


MULTIIMPORT_EXPORT_COLUMNS = (
    "file",
    "status",
    "status_label",
    "checked_for_import",
    "preview_title",
    "preview_authors",
    "preview_source",
    "preview_url",
    "recommended_title",
    "recommended_authors",
    "recommended_url",
    "recommended_score",
    "duplicate_count",
    "error_message",
)


def multiimport_export_rows(items: Iterable[cme.MultiImportBatchItem]) -> list[dict[str, str]]:
    rows = []
    for item in items:
        preview = item.current_preview
        candidate = item.selected_candidate
        rows.append(
            {
                "file": item.display_name,
                "status": item.status,
                "status_label": multiimport_status_label(item.status),
                "checked_for_import": "true" if item.checked_for_import else "false",
                "preview_title": preview.title if preview is not None else "",
                "preview_authors": preview.authors if preview is not None else "",
                "preview_source": preview.source if preview is not None else "",
                "preview_url": preview.url if preview is not None else "",
                "recommended_title": candidate.title if candidate is not None else "",
                "recommended_authors": candidate.authors if candidate is not None else "",
                "recommended_url": candidate.url if candidate is not None else "",
                "recommended_score": str(candidate.score) if candidate is not None else "",
                "duplicate_count": str(len(item.duplicates)),
                "error_message": item.error_message,
            }
        )
    return rows


def write_multiimport_csv_report(path: Path, items: Iterable[cme.MultiImportBatchItem]) -> None:
    rows = multiimport_export_rows(items)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MULTIIMPORT_EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def filter_rows(
    rows: Sequence[cme.MatchRow],
    title: str = "",
    author: str = "",
    statuses: set[str] | None = None,
    sources: set[str] | None = None,
    work_types: set[str] | None = None,
) -> list[cme.MatchRow]:
    """Vrati jen radky, ktere odpovidaji filtrum v horni liste."""
    title_query = cme.normalize_text(title)
    author_query = cme.normalize_text(author)
    result: list[cme.MatchRow] = []
    for row in rows:
        if title_query and title_query not in cme.normalize_text(row.title):
            continue
        if author_query and author_query not in cme.normalize_text(row.authors):
            continue
        if statuses is not None and row.status not in statuses:
            continue
        if sources is not None and row.source not in sources:
            continue
        if work_types is not None and row.work_type not in work_types:
            continue
        result.append(row)
    return result


def statusbar_text(status: str, calibre_running: bool, csv_loaded: bool) -> str:
    """Slozi kratky text do spodni status listy."""
    csv_text = "pracovni data nactena" if csv_loaded else "pracovni data nenactena"
    return f"{status} | {csv_text} | {APP_VERSION}"


def filter_label(value: str) -> str:
    """Zobrazi prazdnou hodnotu filtru lidsky."""
    return value or "bez typu"


def default_filter_checked(values: Sequence[str], value: str) -> bool:
    """Vrati vychozi zaskrtnuti filtru po startu appky."""
    if tuple(values) == STATUS_FILTER_VALUES:
        return value in DEFAULT_STATUS_FILTER_VALUES
    return True


def should_enable_skip_filter(
    rows: Sequence[cme.MatchRow],
    filtered_rows: Sequence[cme.MatchRow],
    title: str,
    author: str,
    statuses: set[str] | None,
    sources: set[str] | None,
    work_types: set[str] | None,
) -> bool:
    """Zapne skip jen kdyz vychozi pohled nema nic k reseni."""
    if filtered_rows or title.strip() or author.strip():
        return False
    if statuses != DEFAULT_STATUS_FILTER_VALUES:
        return False
    if sources is not None or work_types is not None:
        return False
    return any(row.status == "skip" for row in rows)


def selection_title(rows: Sequence[cme.MatchRow]) -> str:
    """Vrati text nad status tlacitka podle vyberu."""
    if not rows:
        return "Bez vyberu"
    if len(rows) == 1:
        row = rows[0]
        return f"{row.book_id} - {row.title}"
    return f"Vybrano {len(rows)} polozek"


def selection_link_text(rows: Sequence[cme.MatchRow]) -> str:
    """Vrati odkaz pro vyber; pri ruznych adresach vrati informacni text."""
    urls = {row.chosen_url.strip() for row in rows}
    if not rows:
        return ""
    if len(urls) == 1:
        return next(iter(urls))
    return "Ruzne adresy"


def selection_link_actions_enabled(rows: Sequence[cme.MatchRow]) -> bool:
    """Link tlacitka maji smysl jen pro jeden odkaz."""
    return bool(rows) and selection_link_text(rows) != "Ruzne adresy"


def use_link_enabled(rows: Sequence[cme.MatchRow], link_text: str) -> bool:
    """Pouzit odkaz jde i pro prazdny text, ale ne pro informacni text."""
    return bool(rows) and link_text.strip() != "Ruzne adresy"


def open_link_enabled(rows: Sequence[cme.MatchRow], link_text: str) -> bool:
    """Otevrit odkaz jde jen kdyz existuje jeden konkretni odkaz."""
    return use_link_enabled(rows, link_text) and bool(link_text.strip())


def current_data_fields(rows: Sequence[cme.MatchRow], metadata: cme.CurrentBookMetadata | None = None) -> list[tuple[str, str]]:
    """Vrati data pro zalozku Aktualni data z Calibre."""
    if not rows:
        return [("Vyber", "bez vyberu")]
    if len(rows) > 1:
        return [("Vyber", f"vybrano {len(rows)} knih")]
    row = rows[0]
    metadata = metadata or cme.CurrentBookMetadata(tags=[])
    return [
        ("ID", str(row.book_id)),
        ("Kniha", row.title),
        ("Autor", row.authors),
        ("Status", row.status),
        ("Zdroj", row.source),
        ("Typ", row.work_type or "kniha"),
        ("Rok vydani", metadata.published_year or "nenacteno"),
        ("Vydavatel", metadata.publisher or "nenacteno"),
        ("Tagy", ", ".join(metadata.tags or []) or "nenacteno"),
        ("Obalka", "nenacteno"),
    ]


def review_data_fields(
    rows: Sequence[cme.MatchRow],
    written_url: str = "",
    detail: cme.BookDetailMetadata | None = None,
    error: str = "",
) -> list[tuple[str, str]]:
    """Vrati data pro zalozku Review, tedy co se bude zapisovat."""
    if not rows:
        return [("Vyber", "bez vyberu")]
    if len(rows) > 1:
        return [("Vyber", f"vybrano {len(rows)} knih")]
    row = rows[0]
    if detail is None:
        return [
            ("Status", row.status),
            ("Zdroj", row.source),
            ("Typ", row.work_type or "kniha"),
        ]
    detail = cme.apply_review_overrides(row, detail)
    return [
        ("Status", row.status),
        ("Zdroj", row.source),
        ("Typ", row.work_type or "kniha"),
        ("Rok vydani", detail.published_year or "nenacteno"),
        ("Vydavatel", detail.publisher or "nenacteno"),
        ("Serie", detail.series or "nenacteno"),
        ("Cislo serie", detail.series_index or "nenacteno"),
        ("Tagy", ", ".join(detail.tags or []) or "nenacteno"),
        ("Hodnoceni", detail.rating_percent or "nenacteno"),
        ("Originalni nazev", detail.original_title or "nenacteno"),
        ("Originalne vyslo", detail.original_publication or "nenacteno"),
    ]


def is_calibre_running(runner: Callable[[Sequence[str]], cme.CommandResult] = cme.run_command) -> bool:
    """Zjisti, jestli bezi Calibre GUI."""
    result = runner(["tasklist", "/FI", "IMAGENAME eq calibre.exe"])
    text = (result.stdout + result.stderr).lower()
    return result.returncode == 0 and "calibre.exe" in text


def normalize_theme(value: str) -> str:
    """Vrati platny nazev vzhledu."""
    normalized = value.strip().casefold()
    return normalized if normalized in THEME_VALUES else "system"


def normalize_auto_settings(raw: Any) -> dict[str, bool]:
    """Vrati nastaveni automatickych akci s rozumnymi vychozimi hodnotami."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        key: raw.get(key) if isinstance(raw.get(key), bool) else default
        for key, default in AUTO_SETTING_DEFAULTS.items()
    }


def normalize_ai_settings(raw: Any) -> dict[str, str | int]:
    """Vrati platne nastaveni volitelne AI vrstvy pro import."""
    ai_raw = raw.get("ai") if isinstance(raw, dict) else {}
    if not isinstance(ai_raw, dict):
        ai_raw = {}
    provider = str(ai_raw.get("provider", AI_SETTING_DEFAULTS["provider"])).strip().casefold()
    if provider not in AI_PROVIDER_VALUES:
        provider = str(AI_SETTING_DEFAULTS["provider"])
    default_model = AI_PROVIDER_DEFAULT_MODELS.get(provider, str(AI_SETTING_DEFAULTS["model"]))
    model = str(ai_raw.get("model", default_model)).strip() or default_model
    try:
        text_limit = int(ai_raw.get("text_limit", AI_SETTING_DEFAULTS["text_limit"]))
    except (TypeError, ValueError):
        text_limit = int(AI_SETTING_DEFAULTS["text_limit"])
    try:
        timeout = int(ai_raw.get("timeout", AI_SETTING_DEFAULTS["timeout"]))
    except (TypeError, ValueError):
        timeout = int(AI_SETTING_DEFAULTS["timeout"])
    try:
        workers = int(ai_raw.get("workers", AI_SETTING_DEFAULTS["workers"]))
    except (TypeError, ValueError):
        workers = int(AI_SETTING_DEFAULTS["workers"])
    return {
        "provider": provider,
        "model": model,
        "text_limit": max(500, min(text_limit, 50000)),
        "timeout": max(10, min(timeout, 600)),
        "workers": max(MULTIIMPORT_WORKERS_MIN, min(workers, MULTIIMPORT_WORKERS_MAX)),
    }


def auto_workflow_title(auto_settings: dict[str, bool]) -> str:
    """Slozi titulek background akce podle zapnutych automatickych kroku."""
    parts = ["Nacitani novych knih"]
    if auto_settings.get("auto_link_audit", True):
        parts.append("Audit odkazu")
    if auto_settings.get("auto_cover_audit", True):
        parts.append("Audit obalek")
    return " + ".join(parts)


def read_app_settings(settings_path: Path | None = None) -> dict[str, Any]:
    """Precte nase nastaveni a ignoruje rozbite hodnoty."""
    settings_path = settings_path or shared.SETTINGS_PATH
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items()}


def save_app_settings(library: str, theme: str, settings_path: Path | None = None) -> None:
    """Ulozi knihovnu a vzhled, ale zachova dalsi nastaveni appky."""
    settings_path = settings_path or shared.SETTINGS_PATH
    settings = read_app_settings(settings_path)
    settings["library_path"] = library
    settings["theme"] = normalize_theme(theme)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def unified_import_start_folder(
    settings: dict[str, Any] | None = None,
    fallback: Path | None = None,
) -> Path:
    current_settings = read_app_settings() if settings is None else settings
    fallback_path = Path(os.path.abspath(fallback or Path.home()))
    if not fallback_path.is_dir():
        fallback_path = Path.cwd().absolute()
    raw = current_settings.get(UNIFIED_IMPORT_LAST_FOLDER_KEY, "")
    if isinstance(raw, str) and raw.strip():
        candidate = Path(os.path.abspath(Path(raw).expanduser()))
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            pass
    return fallback_path


def unified_import_tree_root(folder: Path) -> Path:
    candidate = Path(os.path.abspath(folder))
    anchor = Path(candidate.anchor) if candidate.anchor else candidate
    try:
        if anchor.is_dir():
            return anchor
    except OSError:
        pass
    return candidate


def save_unified_import_last_folder(
    folder: Path,
    settings_path: Path | None = None,
) -> None:
    target = settings_path or shared.SETTINGS_PATH
    settings = read_app_settings(target)
    settings[UNIFIED_IMPORT_LAST_FOLDER_KEY] = str(Path(os.path.abspath(folder)))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def unified_import_dialog_state(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    current_settings = read_app_settings() if settings is None else settings
    raw = current_settings.get(UNIFIED_IMPORT_DIALOG_STATE_KEY, {})
    if not isinstance(raw, dict):
        return {}
    state: dict[str, Any] = {}
    size = raw.get("size")
    if (
        isinstance(size, list)
        and len(size) == 2
        and all(isinstance(value, int) and value > 0 for value in size)
    ):
        state["size"] = size
    splitter_sizes = raw.get("splitter_sizes")
    if (
        isinstance(splitter_sizes, list)
        and len(splitter_sizes) == 2
        and all(isinstance(value, int) and value > 0 for value in splitter_sizes)
    ):
        state["splitter_sizes"] = splitter_sizes
    widths = raw.get("file_column_widths")
    if (
        isinstance(widths, list)
        and len(widths) == 3
        and all(isinstance(value, int) and value >= MIN_COLUMN_WIDTH for value in widths)
    ):
        state["file_column_widths"] = widths
    sort_column = raw.get("sort_column")
    sort_order = raw.get("sort_order")
    if isinstance(sort_column, int) and 0 <= sort_column <= 2 and sort_order in {"asc", "desc"}:
        state["sort_column"] = sort_column
        state["sort_order"] = sort_order
    return state


def save_unified_import_dialog_state(
    state: dict[str, Any],
    settings_path: Path | None = None,
) -> None:
    target = settings_path or shared.SETTINGS_PATH
    settings = read_app_settings(target)
    settings[UNIFIED_IMPORT_DIALOG_STATE_KEY] = unified_import_dialog_state(
        {UNIFIED_IMPORT_DIALOG_STATE_KEY: state}
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_unified_import_files(paths: Iterable[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for raw_path in paths:
        path = Path(os.path.abspath(raw_path))
        if not cme.is_supported_import_file(path):
            continue
        unique.setdefault(os.path.normcase(str(path)), path)
    return sorted(unique.values(), key=lambda path: str(path).casefold())


def should_auto_import(analysis: cme.ImportAnalysis) -> bool:
    """Auto-import jen pri jiste shode: nejlepsi kandidat 100 % a zadna duplicita.

    Provede totez co tlacitko Importovat (prida knihu do Calibre, status review),
    ale bez otevreni dialogu. Pri jakekoli duplicite radeji ukaze dialog.
    """
    candidates = list(getattr(analysis, "candidates", []) or [])
    duplicates = list(getattr(analysis, "duplicates", []) or [])
    if not candidates or duplicates:
        return False
    return max(candidate.score for candidate in candidates) >= 100


def run_import_analysis(
    epub_path: str | Path,
    library: str | Path,
    settings: dict[str, object] | None = None,
    analyze: Callable[..., cme.ImportAnalysis] = cme.analyze_epub_for_import,
    find_duplicates: Callable[..., list[cme.DuplicateCandidate]] = cme.find_calibre_import_duplicates,
    ai_resolver: object | None = None,
) -> cme.ImportAnalysis:
    """Spusti EPUB analyzu a doplni Calibre duplicity.

    Backend wiring layer: drzi analyze + find_duplicates pohromade,
    aby Qt vrstva videla jedno volani. Pri selhani hledani duplicit
    vrati analyzu bez duplicit, aby UI mohlo dat na vyber alespon
    preview a kandidaty.
    """
    settings = settings or {}
    analysis = analyze(epub_path, library, settings, ai_resolver=ai_resolver)
    try:
        duplicates = find_duplicates(library, analysis.preview)
    except Exception:
        duplicates = []
    return replace(analysis, duplicates=duplicates)


def normalize_column_settings(raw: Any) -> dict[str, dict[str, bool | int]]:
    """Vybere jen platne nastaveni sloupcu podle aktualni tabulky."""
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, bool | int]] = {}
    for column in TABLE_COLUMNS:
        value = raw.get(column)
        if not isinstance(value, dict):
            continue
        column_settings: dict[str, bool | int] = {}
        if isinstance(value.get("visible"), bool):
            column_settings["visible"] = value["visible"]
        if isinstance(value.get("width"), int) and value["width"] >= MIN_COLUMN_WIDTH:
            column_settings["width"] = value["width"]
        if column_settings:
            normalized[column] = column_settings
    return normalized


if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QDir, QEvent, QObject, QPoint, QSize, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFileSystemModel,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressBar,
        QListWidget,
        QListWidgetItem,
        QStyleFactory,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QStatusBar,
        QStyle,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QTreeView,
        QVBoxLayout,
        QWidget,
    )

    def schedule_qt_startup_preview(preview_func: Callable[[], object]) -> None:
        """Po startu Qt event loopu automaticky spusti nacitani novych knih."""
        QTimer.singleShot(250, preview_func)


    class FileSizeTableWidgetItem(QTableWidgetItem):
        def __init__(self, text: str, size: int | None) -> None:
            super().__init__(text)
            self._sort_size = -1 if size is None else size

        def __lt__(self, other) -> bool:
            if isinstance(other, FileSizeTableWidgetItem):
                return self._sort_size < other._sort_size
            return super().__lt__(other)


    class WorkerBridge(QObject):
        """Signalovy most z background threadu zpet do Qt event loopu."""

        finished = Signal(str, int, str, bool)
        cover_ready = Signal(int, str, str, str, bytes)
        review_ready = Signal(int, int, str, object, str)
        import_ready = Signal(object, str)
        apply_ready = Signal(object, str)


    class UnifiedImportDialog(QDialog):
        def __init__(
            self,
            initial_folder: Path,
            parent: QWidget | None = None,
            *,
            scan_folder: Callable[[Path, bool], cme.ImportFolderScanResult] | None = None,
            dialog_state: dict[str, Any] | None = None,
        ) -> None:
            super().__init__(parent)
            self._scan_folder = scan_folder or cme.scan_import_files_from_folder
            self._dialog_state = dialog_state if dialog_state is not None else unified_import_dialog_state()
            self._current_folder = Path(os.path.abspath(initial_folder))
            self._selected_files: tuple[Path, ...] = ()
            self._history: list[Path] = []
            self.setWindowTitle("Unified import")
            size = self._dialog_state.get("size")
            if isinstance(size, list) and len(size) == 2:
                self.resize(size[0], size[1])
            else:
                self.resize(900, 600)

            root = QVBoxLayout(self)
            navigation = QHBoxLayout()
            self.back_button = QPushButton("←")
            self.back_button.setToolTip("Zpět")
            self.back_button.setAutoDefault(False)
            self.back_button.clicked.connect(self._go_back)
            navigation.addWidget(self.back_button)
            self.up_button = QPushButton("↑")
            self.up_button.setToolTip("O úroveň výše")
            self.up_button.setAutoDefault(False)
            self.up_button.clicked.connect(self._go_up)
            navigation.addWidget(self.up_button)
            self.path_edit = QLineEdit()
            self.path_edit.setReadOnly(False)
            self.path_edit.installEventFilter(self)
            self.path_edit.returnPressed.connect(self._apply_path_edit)
            navigation.addWidget(self.path_edit, stretch=1)
            self.go_path_button = QPushButton("Přejít")
            self.go_path_button.setAutoDefault(False)
            self.go_path_button.clicked.connect(self._apply_path_edit)
            navigation.addWidget(self.go_path_button)
            self.refresh_button = QPushButton("Obnovit")
            self.refresh_button.setAutoDefault(False)
            self.refresh_button.clicked.connect(self._refresh_files)
            navigation.addWidget(self.refresh_button)
            root.addLayout(navigation)

            self.body_splitter = QSplitter()
            self.directory_model = QFileSystemModel(self)
            self.directory_model.setFilter(
                QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot
            )
            self.directory_model.setResolveSymlinks(False)
            tree_root = unified_import_tree_root(self._current_folder)
            self.directory_model.setRootPath(str(tree_root))
            self.folder_tree = QTreeView()
            self.folder_tree.setModel(self.directory_model)
            self.folder_tree.header().hide()
            self.folder_tree.setRootIndex(self.directory_model.index(str(tree_root)))
            for column in range(1, 4):
                self.folder_tree.hideColumn(column)
            self.folder_tree.clicked.connect(self._on_folder_clicked)
            self.body_splitter.addWidget(self.folder_tree)

            self.file_table = QTableWidget(0, 3)
            self.file_table.setHorizontalHeaderLabels(["Název", "Typ", "Velikost"])
            self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.file_table.verticalHeader().hide()
            self.file_table.setSortingEnabled(True)
            self.file_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.file_table.horizontalHeader().setStretchLastSection(False)
            self.file_table.itemSelectionChanged.connect(self._update_selected_button)
            self.body_splitter.addWidget(self.file_table)
            self.body_splitter.setStretchFactor(0, 1)
            self.body_splitter.setStretchFactor(1, 3)
            root.addWidget(self.body_splitter, stretch=1)

            formats = ", ".join("*" + suffix for suffix, _label in cme.BOOK_IMPORT_FORMATS)
            root.addWidget(QLabel(f"Podporované knihy: {formats}"))

            actions = QHBoxLayout()
            self.include_subfolders_check = QCheckBox("Včetně podsložek")
            self.include_subfolders_check.setChecked(False)
            actions.addWidget(self.include_subfolders_check)
            actions.addStretch(1)
            cancel_button = QPushButton("Zrušit")
            cancel_button.setAutoDefault(False)
            cancel_button.clicked.connect(self.reject)
            actions.addWidget(cancel_button)
            self.import_folder_button = QPushButton("Importovat tuto složku")
            self.import_folder_button.setAutoDefault(False)
            self.import_folder_button.clicked.connect(self._accept_current_folder)
            actions.addWidget(self.import_folder_button)
            self.import_selected_button = QPushButton("Importovat vybrané (0)")
            self.import_selected_button.setAutoDefault(False)
            self.import_selected_button.setEnabled(False)
            self.import_selected_button.clicked.connect(self._accept_selected_files)
            actions.addWidget(self.import_selected_button)
            root.addLayout(actions)

            self._apply_saved_layout_state()
            self._set_current_folder(self._current_folder, add_history=False)
            self._apply_saved_sort_state()

        @property
        def selected_files(self) -> tuple[Path, ...]:
            return self._selected_files

        @property
        def current_folder(self) -> Path:
            return self._current_folder

        def _apply_saved_layout_state(self) -> None:
            splitter_sizes = self._dialog_state.get("splitter_sizes")
            if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2:
                self.body_splitter.setSizes(splitter_sizes)
            widths = self._dialog_state.get("file_column_widths")
            if isinstance(widths, list) and len(widths) == 3:
                for column, width in enumerate(widths):
                    self.file_table.setColumnWidth(column, width)

        def _apply_saved_sort_state(self) -> None:
            sort_column = self._dialog_state.get("sort_column")
            sort_order = self._dialog_state.get("sort_order")
            if not isinstance(sort_column, int) or sort_order not in {"asc", "desc"}:
                return
            order = (
                Qt.SortOrder.DescendingOrder
                if sort_order == "desc"
                else Qt.SortOrder.AscendingOrder
            )
            self.file_table.sortItems(sort_column, order)

        def export_ui_state(self) -> dict[str, Any]:
            header = self.file_table.horizontalHeader()
            return {
                "size": [self.size().width(), self.size().height()],
                "splitter_sizes": self.body_splitter.sizes(),
                "file_column_widths": [
                    self.file_table.columnWidth(column)
                    for column in range(self.file_table.columnCount())
                ],
                "sort_column": header.sortIndicatorSection(),
                "sort_order": (
                    "desc"
                    if header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                    else "asc"
                ),
            }

        def _set_current_folder(self, folder: Path, *, add_history: bool = True) -> None:
            candidate = Path(os.path.abspath(folder))
            try:
                valid = candidate.is_dir()
            except OSError:
                valid = False
            if not valid:
                QMessageBox.warning(self, "Unified import", "Složka není dostupná.")
                return
            if add_history and candidate != self._current_folder:
                self._history.append(self._current_folder)
            self._current_folder = candidate
            self.path_edit.setText(str(candidate))
            tree_root = unified_import_tree_root(candidate)
            self.directory_model.setRootPath(str(tree_root))
            root_index = self.directory_model.index(str(tree_root))
            if root_index.isValid():
                self.folder_tree.setRootIndex(root_index)
            model_index = self.directory_model.index(str(candidate))
            if model_index.isValid():
                self.folder_tree.setCurrentIndex(model_index)
                self.folder_tree.scrollTo(model_index)
            self._refresh_files()
            self.back_button.setEnabled(bool(self._history))
            self.up_button.setEnabled(candidate.parent != candidate)

        def _apply_path_edit(self) -> None:
            text = self.path_edit.text().strip()
            if not text:
                self.path_edit.setText(str(self._current_folder))
                return
            requested = Path(text).expanduser()
            before = self._current_folder
            self._set_current_folder(requested)
            if self._current_folder == before and Path(os.path.abspath(requested)) != before:
                self.path_edit.setText(str(before))

        def keyPressEvent(self, event) -> None:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                text = self.path_edit.text().strip()
                if text and Path(os.path.abspath(Path(text).expanduser())) != self._current_folder:
                    self._apply_path_edit()
                    event.accept()
                    return
            super().keyPressEvent(event)

        def eventFilter(self, watched, event) -> bool:
            if (
                watched is self.path_edit
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            ):
                self._apply_path_edit()
                event.accept()
                return True
            return super().eventFilter(watched, event)

        def _on_folder_clicked(self, index) -> None:
            self._set_current_folder(Path(self.directory_model.filePath(index)))

        def _go_back(self) -> None:
            if not self._history:
                return
            self._set_current_folder(self._history.pop(), add_history=False)

        def _go_up(self) -> None:
            parent = self._current_folder.parent
            if parent != self._current_folder:
                self._set_current_folder(parent)

        def _refresh_files(self) -> None:
            result = self._scan_folder(self._current_folder, False)
            header = self.file_table.horizontalHeader()
            sort_column = header.sortIndicatorSection()
            sort_order = header.sortIndicatorOrder()
            self.file_table.setSortingEnabled(False)
            self.file_table.setRowCount(0)
            for path in result.files:
                row = self.file_table.rowCount()
                self.file_table.insertRow(row)
                name_item = QTableWidgetItem(path.name)
                name_item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.file_table.setItem(row, 0, name_item)
                self.file_table.setItem(row, 1, QTableWidgetItem(path.suffix.lstrip(".").upper()))
                try:
                    size = path.stat().st_size
                    size_text = self._format_size(size)
                except OSError:
                    size = None
                    size_text = "—"
                self.file_table.setItem(row, 2, FileSizeTableWidgetItem(size_text, size))
            self.file_table.setSortingEnabled(True)
            if 0 <= sort_column < self.file_table.columnCount():
                self.file_table.sortItems(sort_column, sort_order)
            self._update_selected_button()

        @staticmethod
        def _format_size(size: int) -> str:
            if size < 1024:
                return f"{size} B"
            if size < 1024 * 1024:
                return f"{size / 1024:.1f} kB"
            return f"{size / (1024 * 1024):.1f} MB"

        def _selected_table_files(self) -> list[Path]:
            rows = sorted({index.row() for index in self.file_table.selectionModel().selectedRows()})
            paths = [
                Path(self.file_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
                for row in rows
            ]
            return normalize_unified_import_files(paths)

        def _update_selected_button(self) -> None:
            count = len(self._selected_table_files())
            self.import_selected_button.setText(f"Importovat vybrané ({count})")
            self.import_selected_button.setEnabled(count > 0)

        def _accept_selected_files(self) -> None:
            files = self._selected_table_files()
            if not files:
                QMessageBox.warning(
                    self,
                    "Unified import",
                    "Vybrané soubory již nejsou dostupné.",
                )
                return
            self._selected_files = tuple(files)
            self.accept()

        def _accept_current_folder(self) -> None:
            result = self._scan_folder(
                self._current_folder,
                self.include_subfolders_check.isChecked(),
            )
            files = normalize_unified_import_files(result.files)
            if not files:
                if self._current_folder in result.skipped_directories:
                    QMessageBox.warning(
                        self,
                        "Unified import",
                        "Aktuální složku nelze přečíst.",
                    )
                    return
                QMessageBox.information(
                    self,
                    "Unified import",
                    "V této složce nebyly nalezeny podporované knihy.",
                )
                return
            if result.skipped_directories:
                answer = QMessageBox.question(
                    self,
                    "Některé složky nebylo možné přečíst",
                    f"Přeskočené složky: {len(result.skipped_directories)}\n\n"
                    "Pokračovat s nalezenými knihami?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self._selected_files = tuple(files)
            self.accept()


    class MultiImportProgressDialog(QDialog):
        """Jednoduchý nenativní průběh synchronního multiimportu.

        Bílé bliknutí těla okna vzniká tím, že se hned po ``show()`` spustí
        synchronní (blokující) práce a event loop nestihne okno vykreslit.
        Proto se těžká práce nespouští přímo, ale přes ``run_after_first_paint``:
        callback se odpálí až po prvním skutečném ``paintEvent`` (okno je tmavé,
        vykreslené), takže uživatel nevidí bílou plochu.
        """

        def __init__(
            self,
            total: int,
            parent: QWidget | None = None,
            *,
            title: str = "Průběh importu",
            initial_text: str = "Připravuji import…",
            progress_prefix: str = "Importuji",
        ) -> None:
            super().__init__(parent)
            self._initial_text = initial_text
            self._progress_prefix = progress_prefix
            self._first_paint_done = False
            self._after_first_paint: Callable[[], None] | None = None
            self.setWindowTitle(title)
            self.setModal(True)
            self.setMinimumWidth(420)
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            layout = QVBoxLayout(self)
            self.progress_label = QLabel()
            self.progress_label.setWordWrap(True)
            layout.addWidget(self.progress_label)
            self.progress_bar = QProgressBar()
            self.progress_bar.setFormat("%v / %m")
            self.progress_bar.setTextVisible(True)
            layout.addWidget(self.progress_bar)
            self.prepare(total)

        def prepare(self, total: int) -> None:
            self.progress_label.setText(self._initial_text)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)

        def show_prepared(self) -> None:
            self.ensurePolished()
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self.adjustSize()
            self.show()
            self.raise_()
            self.activateWindow()

        def run_after_first_paint(self, callback: Callable[[], None]) -> None:
            """Zaregistruje práci, která se spustí až po prvním vykreslení okna.

            Musí se volat před ``show_prepared()``/``exec()``. Zabraňuje bílému
            bliknutí: blokující práce nezačne dřív, než OS okno namaluje.
            """
            self._after_first_paint = callback

        def paintEvent(self, event) -> None:
            super().paintEvent(event)
            if self._first_paint_done:
                return
            self._first_paint_done = True
            callback = self._after_first_paint
            self._after_first_paint = None
            if callback is not None:
                # Ještě jeden tick event loopu, aby se právě dokončený paint
                # stihl prezentovat (Windows DWM) dřív, než práce zablokuje loop.
                QTimer.singleShot(0, callback)

        def update_progress(self, current: int, total: int, display_name: str) -> None:
            self.progress_label.setText(
                f"{self._progress_prefix} {current}/{total}: {display_name}"
            )
            self.progress_bar.setValue(current)


    class MultiImportResultsDialog(QDialog):
        """Read-only prehled vysledku analyzy vice knih."""

        def __init__(
            self,
            items: Sequence[cme.MultiImportBatchItem],
            parent: QWidget | None = None,
            *,
            write_one: Callable[[cme.ImportPreview, Path], cme.ImportApplyResult] | None = None,
            post_write_refresh: Callable[[cme.MultiImportWriteSummary], None] | None = None,
            prepare_backup: Callable[[bool], Path | None] | None = None,
            connectivity_check: Callable[[], bool] | None = None,
            duplicate_finder: Callable[[cme.ImportPreview], list[cme.DuplicateCandidate]] | None = None,
            link_data_func: Callable[[str], tuple[str, str, str, cme.BookDetailMetadata]] | None = None,
        ) -> None:
            super().__init__(parent)
            self.items = list(items)
            self.write_one = write_one or getattr(parent, "_write_multiimport_item", None)
            self.post_write_refresh = post_write_refresh or getattr(
                parent,
                "_refresh_after_multiimport_write",
                None,
            )
            self.prepare_backup = prepare_backup or getattr(
                parent,
                "prepare_multiimport_backup",
                None,
            )
            self.connectivity_check = connectivity_check or getattr(
                parent,
                "is_online_now",
                None,
            )
            self.duplicate_finder = duplicate_finder or getattr(
                parent,
                "_find_import_duplicates",
                None,
            )
            self.link_data_func = link_data_func or (lambda url: cme.fetch_import_link_data(url))
            self.setWindowTitle("Vysledky multiimport analyzy")
            self.resize(900, 600)

            root = QVBoxLayout(self)
            summary_label = QLabel(multiimport_analysis_summary(self.items))
            root.addWidget(summary_label)
            self.selected_summary_label = QLabel()
            root.addWidget(self.selected_summary_label)

            selection_buttons = QHBoxLayout()
            self.select_safe_button = QPushButton("Vybrat 100 %")
            self.select_safe_button.clicked.connect(self.select_safe_items)
            selection_buttons.addWidget(self.select_safe_button)
            self.select_all_button = QPushButton("Vybrat vše")
            self.select_all_button.clicked.connect(self.select_all_items)
            selection_buttons.addWidget(self.select_all_button)
            self.clear_selection_button = QPushButton("Vše odznačit")
            self.clear_selection_button.clicked.connect(self.clear_selected_items)
            selection_buttons.addWidget(self.clear_selection_button)
            selection_buttons.addStretch(1)
            root.addLayout(selection_buttons)

            filter_bar = QHBoxLayout()
            filter_bar.addWidget(QLabel("Filtr:"))
            self.name_filter = QLineEdit()
            self.name_filter.setPlaceholderText("Soubor")
            self.name_filter.setClearButtonEnabled(True)
            self.name_filter.textChanged.connect(self.apply_filters)
            filter_bar.addWidget(self.name_filter, stretch=1)

            filter_bar.addWidget(QLabel("Stav:"))
            self.status_checks: dict[str, QCheckBox] = {}
            for status in ("ready", "needs_review", "duplicate_warning",
                           "analysis_error", "written", "write_error"):
                check = QCheckBox(multiimport_status_label(status))
                check.setChecked(True)
                check.stateChanged.connect(lambda _state: self.apply_filters())
                filter_bar.addWidget(check)
                self.status_checks[status] = check

            self.checked_filter = QComboBox()
            self.checked_filter.addItem("Import: vše", None)
            self.checked_filter.addItem("Zaškrtnuté", True)
            self.checked_filter.addItem("Nezaškrtnuté", False)
            self.checked_filter.currentIndexChanged.connect(lambda _index: self.apply_filters())
            filter_bar.addWidget(self.checked_filter)
            root.addLayout(filter_bar)

            body = QHBoxLayout()
            root.addLayout(body, stretch=1)
            self.items_table = QTableWidget(len(self.items), 3)
            self.items_table.setHorizontalHeaderLabels(("Import", "Stav", "Soubor"))
            self.items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.items_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
            self.items_table.verticalHeader().setVisible(False)
            header = self.items_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            for row, item in enumerate(self.items):
                if item.status == "analysis_error":
                    item.checked_for_import = False
                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(
                    (checkbox_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    & ~Qt.ItemFlag.ItemIsEditable
                )
                if item.status == "analysis_error":
                    checkbox_item.setFlags(
                        checkbox_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
                    )
                checkbox_item.setCheckState(
                    Qt.CheckState.Checked if item.checked_for_import else Qt.CheckState.Unchecked
                )
                status_item = QTableWidgetItem(multiimport_row_status_symbol(item))
                status_item.setToolTip(multiimport_row_status_tooltip(item))
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                file_item = QTableWidgetItem(item.display_name)
                file_item.setFlags(file_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.items_table.setItem(row, 0, checkbox_item)
                self.items_table.setItem(row, 1, status_item)
                self.items_table.setItem(row, 2, file_item)
            body.addWidget(self.items_table, stretch=1)

            right_panel = QVBoxLayout()
            self.detail_text = QTextEdit()
            self.detail_text.setReadOnly(True)
            # Detail ma par radku pevneho textu, kandidatu byvaji desitky a scrolluje se
            # v nich. Stejny stretch je rozdeli napul misto drivejsiho pomeru 2:1, kde
            # detail zabiral vetsinu vysky prazdnym mistem.
            right_panel.addWidget(self.detail_text, stretch=1)

            right_panel.addWidget(QLabel("Nalezení kandidáti (ruční výběr):"))
            self.candidates_list = QListWidget()
            self.candidates_list.currentRowChanged.connect(
                lambda _row: self.update_candidate_buttons()
            )
            right_panel.addWidget(self.candidates_list, stretch=1)

            candidate_buttons = QHBoxLayout()
            self.use_candidate_button = QPushButton("Použít kandidáta")
            self.use_candidate_button.clicked.connect(self.use_selected_candidate)
            candidate_buttons.addWidget(self.use_candidate_button)
            self.open_link_button = QPushButton("Otevřít odkaz")
            self.open_link_button.clicked.connect(self.open_selected_candidate_link)
            candidate_buttons.addWidget(self.open_link_button)
            candidate_buttons.addStretch(1)
            right_panel.addLayout(candidate_buttons)

            manual_row = QHBoxLayout()
            self.manual_url_edit = QLineEdit()
            self.manual_url_edit.setPlaceholderText("Vlastní odkaz (URL), který znám jako správný")
            manual_row.addWidget(self.manual_url_edit, stretch=1)
            self.use_manual_url_button = QPushButton("Použít odkaz")
            self.use_manual_url_button.clicked.connect(self.use_manual_url)
            manual_row.addWidget(self.use_manual_url_button)
            right_panel.addLayout(manual_row)

            body.addLayout(right_panel, stretch=2)

            buttons = QHBoxLayout()
            self.backup_check = QCheckBox("Zálohovat databázi před importem")
            self.backup_check.setChecked(True)
            self.backup_check.setToolTip(
                "Před začátkem importu vytvoří jednu kopii metadata.db do složky backups."
            )
            buttons.addWidget(self.backup_check)
            buttons.addStretch(1)
            self.validate_button = QPushButton("Ověřit výběr")
            self.validate_button.clicked.connect(self.validate_selection)
            buttons.addWidget(self.validate_button)
            self.export_button = QPushButton("Exportovat CSV")
            self.export_button.clicked.connect(self.export_csv)
            buttons.addWidget(self.export_button)
            self.import_button = QPushButton("Importovat zaškrtnuté")
            self.import_button.setEnabled(False)
            self.import_button.clicked.connect(self.import_checked_items)
            buttons.addWidget(self.import_button)
            self.close_button = QPushButton("Zavrit")
            self.close_button.clicked.connect(self.accept)
            buttons.addWidget(self.close_button)
            root.addLayout(buttons)

            self._updating_check_state = False
            self.items_table.itemChanged.connect(self.update_item_checked)
            self.items_table.currentCellChanged.connect(
                lambda row, _column, _previous_row, _previous_column: self.show_item_details(row)
            )
            self.update_selected_summary()
            if self.items:
                self.items_table.setCurrentCell(0, 0)

        def update_item_checked(self, table_item: QTableWidgetItem) -> None:
            if self._updating_check_state or table_item.column() != 0:
                return
            row = table_item.row()
            if not 0 <= row < len(self.items):
                return
            item = self.items[row]
            self._updating_check_state = True
            try:
                if item.status == "analysis_error":
                    item.checked_for_import = False
                    table_item.setCheckState(Qt.CheckState.Unchecked)
                else:
                    item.checked_for_import = table_item.checkState() == Qt.CheckState.Checked
                self.update_selected_summary()
                if self.items_table.currentRow() == row:
                    self.show_item_details(row)
            finally:
                self._updating_check_state = False

        def update_selected_summary(self) -> None:
            selected = sum(item.checked_for_import for item in self.items)
            self.selected_summary_label.setText(f"Vybráno k importu: {selected}")
            self.update_import_button_enabled()

        def update_import_button_enabled(self) -> None:
            enabled = self.write_one is not None and any(item.checked_for_import for item in self.items)
            self.import_button.setEnabled(enabled)
            if self.write_one is None:
                tooltip = "Zápis není dostupný."
            elif enabled:
                tooltip = "Ověří výběr a importuje pouze bezpečně připravené položky."
            else:
                tooltip = "Vyberte alespoň jednu položku."
            self.import_button.setToolTip(tooltip)

        def _set_bulk_selection(
            self,
            should_check: Callable[[cme.MultiImportBatchItem, QTableWidgetItem], bool],
        ) -> None:
            current_row = self.items_table.currentRow()
            self._updating_check_state = True
            try:
                for row, item in enumerate(self.items):
                    checkbox_item = self.items_table.item(row, 0)
                    checked = should_check(item, checkbox_item)
                    item.checked_for_import = checked
                    checkbox_item.setCheckState(
                        Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                    )
                self.update_selected_summary()
                self.show_item_details(current_row)
            finally:
                self._updating_check_state = False

        def select_safe_items(self) -> None:
            def is_safe(item: cme.MultiImportBatchItem, checkbox_item: QTableWidgetItem) -> bool:
                if not checkbox_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    return False
                candidate = replace(item, checked_for_import=True)
                return cme.validate_multiimport_checked_items([candidate]).ok

            self._set_bulk_selection(is_safe)

        def select_all_items(self) -> None:
            self._set_bulk_selection(
                lambda _item, checkbox_item: bool(
                    checkbox_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                )
            )

        def clear_selected_items(self) -> None:
            self._set_bulk_selection(lambda _item, _checkbox_item: False)

        def export_csv(self) -> None:
            selected_path, _filter = QFileDialog.getSaveFileName(
                self,
                "Exportovat multiimport CSV",
                "multiimport-report.csv",
                "CSV soubory (*.csv)",
            )
            if not selected_path:
                return
            path = Path(selected_path)
            try:
                write_multiimport_csv_report(path, self.items)
            except Exception as exc:
                QMessageBox.warning(self, "Export CSV", f"Export se nepodaril:\n{exc}")
                return
            QMessageBox.information(self, "Export CSV", f"CSV ulozeno:\n{path}")

        def validate_selection(self) -> None:
            result = cme.validate_multiimport_checked_items(self.items)
            QMessageBox.information(
                self,
                "Ověření výběru",
                multiimport_validation_summary_text(result),
            )

        def refresh_item_row(self, item: cme.MultiImportBatchItem) -> None:
            row = next(
                (index for index, current in enumerate(self.items) if current is item),
                -1,
            )
            if row < 0:
                return
            self._updating_check_state = True
            try:
                checkbox_item = self.items_table.item(row, 0)
                checkbox_item.setCheckState(
                    Qt.CheckState.Checked
                    if item.checked_for_import
                    else Qt.CheckState.Unchecked
                )
                status_item = self.items_table.item(row, 1)
                status_item.setText(multiimport_row_status_symbol(item))
                status_item.setToolTip(multiimport_row_status_tooltip(item))
                if self.items_table.currentRow() == row:
                    self.show_item_details(row)
            finally:
                self._updating_check_state = False
            self.update_selected_summary()

        def import_checked_items(self) -> None:
            validation = cme.validate_multiimport_checked_items(self.items)
            if not validation.ok:
                QMessageBox.warning(
                    self,
                    "Multiimport",
                    multiimport_validation_summary_text(validation),
                )
                return
            if self.write_one is None:
                QMessageBox.warning(self, "Multiimport", "Zápis není dostupný.")
                return
            answer = QMessageBox.question(
                self,
                "Potvrdit multiimport",
                f"Naimportovat {len(validation.valid_items)} vybraných knih do Calibre?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

            # Import stahuje obalky a doplnuje udaje z webu; offline to muze
            # selhat. Varujeme az tady, aby se sonda nepoustela zbytecne.
            if self.connectivity_check is not None:
                try:
                    online = bool(self.connectivity_check())
                except Exception:
                    online = False
                if not online:
                    offline_answer = QMessageBox.question(
                        self,
                        "Bez připojení k internetu",
                        "Zdá se, že počítač není online. Zápis do Calibre proběhne, "
                        "ale stažení obálek a doplnění údajů z webu může selhat.\n\n"
                        "Chcete přesto importovat?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if offline_answer != QMessageBox.StandardButton.Yes:
                        return

            # Jedna zaloha metadata.db pred celou davkou. Kdyz ji uzivatel chce a
            # nepovede se, import radeji vubec nespoustime.
            if self.prepare_backup is not None:
                try:
                    self.prepare_backup(self.backup_check.isChecked())
                except Exception as exc:
                    QMessageBox.warning(
                        self,
                        "Záloha databáze",
                        f"Zálohu se nepodařilo vytvořit, import zrušen:\n{exc}",
                    )
                    return

            progress = MultiImportProgressDialog(len(validation.valid_items), self)
            progress.prepare(len(validation.valid_items))

            def update_progress(
                current: int,
                total: int,
                item: cme.MultiImportBatchItem,
            ) -> None:
                self.refresh_item_row(item)
                progress.update_progress(current, total, item.display_name)
                QApplication.processEvents()

            summaries: list[cme.MultiImportWriteSummary] = []
            errors: list[BaseException] = []

            def run_write() -> None:
                try:
                    summaries.append(
                        cme.run_multiimport_batch_write(
                            self.items,
                            self.write_one,
                            progress_callback=update_progress,
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    progress.accept()

            progress.run_after_first_paint(run_write)
            progress.show_prepared()
            progress.exec()
            try:
                if errors:
                    raise errors[0]
                if not summaries:
                    return
                summary = summaries[0]
            finally:
                progress.close()
                progress.deleteLater()
                QApplication.processEvents()

            if summary.succeeded > 0 and self.post_write_refresh is not None:
                self.post_write_refresh(summary)
            outcome = "Úspěch" if summary.ok else "Dokončeno s chybami"
            QMessageBox.information(
                self,
                "Výsledek multiimportu",
                f"{outcome}\n\n"
                f"Pokusů: {summary.attempted}\n"
                f"Úspěšně: {summary.succeeded}\n"
                f"Selhalo: {summary.failed}"
                f"{multiimport_write_failures_text(self.items)}",
            )
            self.update_import_button_enabled()
            if summary.ok and summary.attempted > 0:
                self.accept()

        def apply_filters(self) -> None:
            """Skryje radky, ktere neodpovidaji filtrum (soubor/stav/import)."""
            name_query = self.name_filter.text()
            statuses = {
                status for status, check in self.status_checks.items() if check.isChecked()
            }
            # Vse zaskrtnuto = bez omezeni (ukaz i pripadne jine stavy nez v liste).
            if statuses == set(self.status_checks):
                statuses = None
            checked = self.checked_filter.currentData()
            for row, item in enumerate(self.items):
                visible = multiimport_item_matches_filter(
                    item,
                    name_query=name_query,
                    statuses=statuses,
                    checked=checked,
                )
                self.items_table.setRowHidden(row, not visible)

        def show_item_details(self, row: int) -> None:
            if 0 <= row < len(self.items):
                self.detail_text.setPlainText(multiimport_item_detail_text(self.items[row]))
                self.populate_candidates(self.items[row])
            else:
                self.detail_text.clear()
                self.populate_candidates(None)

        def current_selected_item(self) -> "cme.MultiImportBatchItem | None":
            row = self.items_table.currentRow()
            if 0 <= row < len(self.items):
                return self.items[row]
            return None

        def populate_candidates(self, item: "cme.MultiImportBatchItem | None") -> None:
            """Naplni seznam kandidatu pro rucni vyber u vybrane knihy."""
            self.candidates_list.clear()
            can_edit = item is not None and item.status != "analysis_error"
            if item is not None and item.analysis is not None:
                for candidate in item.analysis.candidates:
                    label = (
                        f"{candidate.score}% | {candidate.source} | "
                        f"{candidate.title} / {candidate.authors}\n{candidate.url}"
                    )
                    list_item = QListWidgetItem(label)
                    list_item.setData(Qt.ItemDataRole.UserRole, candidate)
                    self.candidates_list.addItem(list_item)
            self.candidates_list.setEnabled(can_edit)
            self.manual_url_edit.setEnabled(can_edit)
            self.use_manual_url_button.setEnabled(can_edit)
            self.update_candidate_buttons()

        def selected_list_candidate(self) -> "cme.ImportCandidate | None":
            list_item = self.candidates_list.currentItem()
            if list_item is None:
                return None
            return list_item.data(Qt.ItemDataRole.UserRole)

        def update_candidate_buttons(self) -> None:
            has_candidate = self.selected_list_candidate() is not None
            enabled = self.candidates_list.isEnabled() and has_candidate
            self.use_candidate_button.setEnabled(enabled)
            self.open_link_button.setEnabled(enabled)

        def use_selected_candidate(self) -> None:
            item = self.current_selected_item()
            candidate = self.selected_list_candidate()
            if item is None or candidate is None:
                return
            cme.select_multiimport_candidate(item, candidate, self.duplicate_finder)
            if item.manually_confirmed:
                item.checked_for_import = True
            self.refresh_item_row(item)

        def open_selected_candidate_link(self) -> None:
            candidate = self.selected_list_candidate()
            url = (candidate.url if candidate is not None else "").strip()
            if not url:
                return
            QDesktopServices.openUrl(QUrl(url))

        def use_manual_url(self) -> None:
            item = self.current_selected_item()
            if item is None:
                return
            url = self.manual_url_edit.text().strip()
            if not url:
                QMessageBox.information(self, "Vlastní odkaz", "Zadejte URL odkazu.")
                return
            # Z odkazu stahneme nazev a autora (jako "Pouzit odkaz" u single
            # importu). Bez toho by u knihy, kde analyza autora nenasla, zustal
            # nahled nevalidni a import by se zablokoval.
            self.use_manual_url_button.setEnabled(False)
            self.use_manual_url_button.setText("Načítám...")
            QApplication.processEvents()
            try:
                title, authors, written_url, detail = self.link_data_func(url)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Použít odkaz",
                    f"Odkaz se nepodařilo načíst:\n{exc}",
                )
                return
            finally:
                self.use_manual_url_button.setEnabled(True)
                self.use_manual_url_button.setText("Použít odkaz")
            target_url = (written_url or url).strip()
            candidate = cme.build_manual_import_candidate(
                target_url,
                item,
                title=title,
                authors=authors,
                source=cme.source_and_work_type_for_url(target_url)[0],
                detail=detail,
            )
            cme.select_multiimport_candidate(item, candidate, self.duplicate_finder)
            if item.manually_confirmed:
                item.checked_for_import = True
            self.refresh_item_row(item)


    class ImportDialog(QDialog):
        """Modalni okno pro kontrolu jednoho EPUB importu pred zapisem."""

        # Vysledek vlakna "Hledat znovu": (kandidati|None, chyba).
        research_done = Signal(object, str)
        # Vysledek vlakna "Pouzit odkaz": ((url, zdroj, detail)|None, chyba).
        use_link_done = Signal(object, str)

        def __init__(
            self,
            analysis: cme.ImportAnalysis,
            parent: QWidget | None = None,
            search_func: Callable[[str, str], list[cme.ImportCandidate]] | None = None,
            runner: Callable[[Callable[[], None]], None] | None = None,
            link_data_func: Callable[[str], tuple[str, str, str, cme.BookDetailMetadata]] | None = None,
            duplicate_func: Callable[[cme.ImportPreview], list[cme.DuplicateCandidate]] | None = None,
        ) -> None:
            super().__init__(parent)
            self.analysis = analysis
            self.search_func = search_func or (lambda title, authors: cme.lookup_import_candidates_for_query(title, authors))
            self.research_runner = runner or (lambda target: threading.Thread(target=target, daemon=True).start())
            self.link_data_func = link_data_func or (lambda url: cme.fetch_import_link_data(url))
            self.duplicate_func = duplicate_func
            self.setWindowTitle("Import knihy")
            self.resize(1180, 720)
            root = QVBoxLayout(self)
            body = QHBoxLayout()
            root.addLayout(body, stretch=1)

            left = QVBoxLayout()
            body.addLayout(left, stretch=1)
            left.addWidget(QLabel("Soubor"))
            self.file_label = QLabel(analysis.epub_path)
            self.file_label.setWordWrap(True)
            left.addWidget(self.file_label)

            left.addWidget(QLabel("Signaly"))
            self.signals_list = QListWidget()
            for signal in analysis.signals:
                self.signals_list.addItem(f"{signal.source}: {signal.title} / {signal.authors}")
            left.addWidget(self.signals_list, stretch=1)

            left.addWidget(QLabel("Kandidati"))
            self.candidates_list = QListWidget()
            self.populate_candidates(analysis.candidates)
            left.addWidget(self.candidates_list, stretch=1)
            self.use_candidate_button = QPushButton("Pouzit kandidata")
            self.use_candidate_button.setEnabled(False)
            self.use_candidate_button.clicked.connect(self.apply_selected_candidate)
            self.candidates_list.currentItemChanged.connect(lambda _current, _previous: self.update_candidate_button_enabled())
            self.candidates_list.itemDoubleClicked.connect(lambda _item: self.apply_selected_candidate())
            left.addWidget(self.use_candidate_button)

            left.addWidget(QLabel("Duplicity"))
            self.duplicates_list = QListWidget()
            left.addWidget(self.duplicates_list, stretch=1)
            self.allow_duplicate_check = QCheckBox("Importovat i pres duplicitu")
            left.addWidget(self.allow_duplicate_check)
            self.populate_duplicates(analysis.duplicates)

            # Dialog je rozhodovaci/potvrzovaci, ne plny editor metadat.
            # Importovane radky jdou na review a doladi se pozdeji v hlavni tabulce,
            # takze tady drzime jen kompaktni nahled: nazev, autor, zdroj, odkaz.
            # Ostatni pole (serie, rok, vydavatel, tagy, komentar) se plni interne
            # z kandidata do self.current_preview, ale nezobrazuji se jako editovatelna.
            # base_preview je stabilni fallback z analyzy; kazdy kandidat se staví
            # z nej, aby skryta metadata jednoho kandidata neprosakla do dalsiho.
            self.base_preview = analysis.preview
            self.current_preview = analysis.preview

            right = QVBoxLayout()
            body.addLayout(right, stretch=1)
            right.addWidget(QLabel("Co se naimportuje"))
            form = QFormLayout()
            right.addLayout(form)
            self.title_edit = QLineEdit(analysis.preview.title)
            self.authors_edit = QLineEdit(analysis.preview.authors)
            form.addRow("Nazev", self.title_edit)
            form.addRow("Autor/autori", self.authors_edit)
            self.source_label = QLabel()
            self.source_label.setWordWrap(True)
            form.addRow("Zdroj", self.source_label)
            link_row = QHBoxLayout()
            self.url_edit = QLineEdit()
            self.url_edit.setPlaceholderText("nenacteno - muzes vlozit odkaz rucne")
            link_row.addWidget(self.url_edit, stretch=1)
            self.use_link_button = QPushButton("Pouzit odkaz")
            self.use_link_button.clicked.connect(self.start_use_link)
            link_row.addWidget(self.use_link_button)
            self.open_link_button = QPushButton("Otevrit odkaz")
            self.open_link_button.clicked.connect(self.open_current_url)
            link_row.addWidget(self.open_link_button)
            form.addRow("Odkaz", link_row)
            self.url_edit.textChanged.connect(lambda _text: self.open_link_button.setEnabled(bool(self.current_url())))
            self.research_button = QPushButton("Hledat znovu")
            self.research_button.clicked.connect(self.start_research)
            right.addWidget(self.research_button)
            right.addStretch(1)

            buttons = QHBoxLayout()
            root.addLayout(buttons)
            buttons.addStretch(1)
            self.import_button = QPushButton("Importovat")
            self.cancel_button = QPushButton("Zrusit")
            buttons.addWidget(self.import_button)
            buttons.addWidget(self.cancel_button)
            self.cancel_button.clicked.connect(self.reject)
            self.import_button.clicked.connect(self.accept)
            self.title_edit.textChanged.connect(self.update_import_enabled)
            self.authors_edit.textChanged.connect(self.update_import_enabled)
            self.research_done.connect(self.finish_research)
            self.use_link_done.connect(self.finish_use_link)
            self.update_candidate_button_enabled()
            self.refresh_preview_labels()
            self.update_import_enabled()

        def candidate_display_text(self, candidate: cme.ImportCandidate) -> str:
            return f"{candidate.score}% {candidate.source}: {candidate.title} / {candidate.authors}"

        def populate_candidates(self, candidates: Sequence[cme.ImportCandidate]) -> None:
            """Naplni seznam kandidatu (pri startu i po 'Hledat znovu')."""
            self.candidates_list.clear()
            for candidate in candidates:
                item = QListWidgetItem(self.candidate_display_text(candidate))
                item.setData(Qt.ItemDataRole.UserRole, candidate)
                self.candidates_list.addItem(item)

        def populate_duplicates(self, duplicates: Sequence[cme.DuplicateCandidate]) -> None:
            """Naplni seznam duplicit (pri startu i po prepoctu podle noveho nazvu/autora)."""
            self.duplicates_list.clear()
            for duplicate in duplicates:
                self.duplicates_list.addItem(f"{duplicate.score} {duplicate.book_id}: {duplicate.title} / {duplicate.authors}")
            # Zatrzitko "importovat i pres duplicitu" ma smysl jen kdyz duplicita je.
            # Volbu uzivatele NIKDY neodskrtavame - jinak by ji prepocet duplicit
            # (po 'Hledat znovu'/'Pouzit odkaz') tise zrusil a import by spadl.
            self.allow_duplicate_check.setEnabled(bool(duplicates))

        def refresh_duplicates(self) -> None:
            """Prepocita duplicity podle aktualniho nazvu/autora; pri chybe nechá puvodni."""
            if self.duplicate_func is None:
                return
            try:
                duplicates = self.duplicate_func(self.preview())
            except Exception:
                return
            self.populate_duplicates(duplicates)

        def start_research(self) -> None:
            """Spusti online hledani znovu podle rucne upraveneho nazvu/autora."""
            title = self.title_edit.text().strip()
            authors = self.authors_edit.text().strip()
            if not title:
                return
            self.research_button.setEnabled(False)
            self.research_button.setText("Hledam...")

            def worker() -> None:
                try:
                    candidates = self.search_func(title, authors)
                    self.research_done.emit(candidates, "")
                except Exception as exc:
                    self.research_done.emit(None, str(exc))

            self.research_runner(worker)

        def finish_research(self, candidates: object, error: str) -> None:
            """Zpracuje vysledek vlakna 'Hledat znovu' na UI threadu."""
            self.research_button.setEnabled(True)
            self.research_button.setText("Hledat znovu")
            if error or candidates is None:
                QMessageBox.warning(self, "Hledat znovu", error or "Hledani se nezdarilo.")
                return
            self.populate_candidates(candidates)
            self.update_candidate_button_enabled()
            self.refresh_duplicates()

        def start_use_link(self) -> None:
            """Stahne detail metadat z rucne vlozeneho odkazu (jako 'Pouzit kandidata')."""
            url = self.current_url()
            if not url:
                return
            self.use_link_button.setEnabled(False)
            self.use_link_button.setText("Nacitam...")

            def worker() -> None:
                try:
                    title, authors, written_url, detail = self.link_data_func(url)
                    source = cme.source_and_work_type_for_url(written_url)[0]
                    self.use_link_done.emit((title, authors, written_url, source, detail), "")
                except Exception as exc:
                    self.use_link_done.emit(None, str(exc))

            self.research_runner(worker)

        def finish_use_link(self, payload: object, error: str) -> None:
            """Z odkazu prida rok/vydavatele/komentar a opravi nazev/autora podle katalogu."""
            self.use_link_button.setEnabled(True)
            self.use_link_button.setText("Pouzit odkaz")
            if error or payload is None:
                QMessageBox.warning(self, "Pouzit odkaz", error or "Detail se nepodarilo nacist.")
                return
            title, authors, written_url, source, detail = payload
            updates: dict[str, str] = {"url": written_url, "source": source}
            if detail.published_year:
                updates["published_year"] = detail.published_year
            if detail.publisher:
                updates["publisher"] = detail.publisher
            if detail.series:
                updates["series"] = detail.series
            if detail.series_index:
                updates["series_index"] = detail.series_index
            if detail.tags:
                updates["tags"] = ", ".join(detail.tags)
            if detail.about_text or detail.rating_percent or detail.original_title or detail.original_publication:
                updates["comment"] = cme.format_enriched_comment(written_url, detail)
            if detail.cover_url:
                updates["selected_cover_url"] = detail.cover_url
            self.current_preview = replace(self.current_preview, **updates)
            # Nazev a autora opravime podle katalogu, kdyz je odkaz vrati.
            if title.strip():
                self.title_edit.setText(title.strip())
            if authors.strip():
                self.authors_edit.setText(authors.strip())
            self.refresh_preview_labels()
            self.update_import_enabled()
            # Po opraveni nazvu/autora automaticky prehledame (kandidati + duplicity).
            self.start_research()

        def selected_candidate(self) -> cme.ImportCandidate | None:
            item = self.candidates_list.currentItem()
            candidate = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            return candidate if isinstance(candidate, cme.ImportCandidate) else None

        def update_candidate_button_enabled(self) -> None:
            self.use_candidate_button.setEnabled(self.selected_candidate() is not None)

        def current_url(self) -> str:
            return (self.url_edit.text() or "").strip()

        def refresh_preview_labels(self) -> None:
            """Aktualizuje nahled zdroje a pole s odkazem podle current_preview."""
            self.source_label.setText(self.current_preview.source or "nenacteno")
            self.url_edit.setText((self.current_preview.url or "").strip())
            self.open_link_button.setEnabled(bool(self.current_url()))

        def open_current_url(self) -> None:
            url = self.current_url()
            if not url:
                return
            QDesktopServices.openUrl(QUrl(url))

        def apply_selected_candidate(self) -> None:
            candidate = self.selected_candidate()
            if candidate is None:
                return
            # Stavime vzdy ze stabilniho base_preview, ne z current_preview, aby
            # skryta metadata predchoziho kandidata neprosakla do noveho.
            enriched = cme.import_preview_from_candidate(candidate, self.base_preview)
            detail = candidate.detail
            if detail is not None:
                updates: dict[str, str] = {}
                if detail.published_year:
                    updates["published_year"] = detail.published_year
                if detail.publisher:
                    updates["publisher"] = detail.publisher
                if detail.series:
                    updates["series"] = detail.series
                if detail.series_index:
                    updates["series_index"] = detail.series_index
                if detail.tags:
                    updates["tags"] = ", ".join(detail.tags)
                if detail.about_text or detail.rating_percent or detail.original_title or detail.original_publication:
                    updates["comment"] = cme.format_enriched_comment(candidate.url, detail)
                if detail.cover_url:
                    updates["selected_cover_url"] = detail.cover_url
                if updates:
                    enriched = replace(enriched, **updates)
            self.current_preview = enriched
            # Nazev/autor bereme z enriched (uz vyresil fallback na base_preview),
            # aby nezustaly stare hodnoty z drive vybraneho kandidata.
            self.title_edit.setText(enriched.title)
            self.authors_edit.setText(enriched.authors)
            self.refresh_preview_labels()
            self.update_import_enabled()

        def update_import_enabled(self) -> None:
            self.import_button.setEnabled(bool(self.title_edit.text().strip() and self.authors_edit.text().strip()))

        def preview(self) -> cme.ImportPreview:
            # Uzivatel edituje nazev, autora a odkaz; zbytek bere z current_preview
            # (pocatecni fallback nebo aplikovany kandidat).
            return replace(
                self.current_preview,
                title=self.title_edit.text(),
                authors=self.authors_edit.text(),
                url=self.current_url(),
                allow_strong_duplicate=self.allow_duplicate_check.isChecked(),
            )


    class PreferencesDialog(QDialog):
        """Dialog pro knihovnu a rizikove servisni akce."""

        def __init__(self, parent: "CalibreMetaQtWindow") -> None:
            super().__init__(parent)
            self.parent_window = parent
            self.setWindowTitle("Preferences")
            self.setMinimumWidth(720)
            self._build_ui()

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)
            form = QGridLayout()
            form.addWidget(QLabel("Knihovna"), 0, 0)
            self.library_edit = QLineEdit(self.parent_window.library_path)
            form.addWidget(self.library_edit, 0, 1)
            browse = QPushButton("Zmenit")
            browse.setObjectName("neutralButton")
            browse.clicked.connect(self.choose_library)
            form.addWidget(browse, 0, 2)
            use_calibre = QPushButton("Pouzit z Calibre")
            use_calibre.setObjectName("neutralButton")
            use_calibre.clicked.connect(self.use_calibre_library)
            form.addWidget(use_calibre, 0, 3)
            form.addWidget(QLabel("Vzhled"), 1, 0)
            self.theme_combo = QComboBox()
            self.theme_combo.addItems(THEME_VALUES)
            self.theme_combo.setCurrentText(self.parent_window.theme)
            form.addWidget(self.theme_combo, 1, 1)
            auto_settings = normalize_auto_settings(read_app_settings())
            self.startup_preview_check = QCheckBox("Po startu nacist nove knihy")
            self.startup_preview_check.setChecked(auto_settings["startup_preview"])
            self.auto_link_audit_check = QCheckBox("Po nacteni spustit audit odkazu")
            self.auto_link_audit_check.setChecked(auto_settings["auto_link_audit"])
            self.auto_cover_audit_check = QCheckBox("Po auditu pripravit obalky")
            self.auto_cover_audit_check.setChecked(auto_settings["auto_cover_audit"])
            form.addWidget(self.startup_preview_check, 2, 1, 1, 3)
            form.addWidget(self.auto_link_audit_check, 3, 1, 1, 3)
            form.addWidget(self.auto_cover_audit_check, 4, 1, 1, 3)

            ai_settings = normalize_ai_settings(read_app_settings())
            form.addWidget(QLabel("AI provider importu"), 5, 0)
            self.ai_provider_combo = QComboBox()
            self.ai_provider_combo.addItems(AI_PROVIDER_VALUES)
            self.ai_provider_combo.setCurrentText(str(ai_settings["provider"]))
            form.addWidget(self.ai_provider_combo, 5, 1, 1, 3)
            form.addWidget(QLabel("Model"), 6, 0)
            self.ai_model_edit = QLineEdit(str(ai_settings["model"]))
            form.addWidget(self.ai_model_edit, 6, 1, 1, 3)
            form.addWidget(QLabel("EPUB text limit"), 7, 0)
            self.ai_text_limit_edit = QLineEdit(str(ai_settings["text_limit"]))
            form.addWidget(self.ai_text_limit_edit, 7, 1, 1, 3)
            form.addWidget(QLabel("AI timeout (s)"), 8, 0)
            self.ai_timeout_edit = QLineEdit(str(ai_settings["timeout"]))
            form.addWidget(self.ai_timeout_edit, 8, 1, 1, 3)
            form.addWidget(QLabel("Knih naráz (multiimport)"), 9, 0)
            self.ai_workers_spin = QSpinBox()
            self.ai_workers_spin.setRange(MULTIIMPORT_WORKERS_MIN, MULTIIMPORT_WORKERS_MAX)
            self.ai_workers_spin.setValue(int(ai_settings["workers"]))
            self.ai_workers_spin.setToolTip(
                "Kolik knih se při hromadném importu analyzuje současně.\n"
                "5 je změřené optimum pro cloud i pro Ollamu.\n"
                "Snižte při slabším počítači nebo pomalém připojení."
            )
            form.addWidget(self.ai_workers_spin, 9, 1)
            workers_hint = QLabel("doporučeno 5")
            workers_hint.setEnabled(False)
            form.addWidget(workers_hint, 9, 2, 1, 2)
            # Status klice pro cloud providery: rekne jestli appka nasla API klic.
            self.ai_key_status_label = QLabel()
            form.addWidget(QLabel("API klic"), 10, 0)
            form.addWidget(self.ai_key_status_label, 10, 1, 1, 3)
            # Signal az po nastaveni hodnot, jinak by init prepsal ulozeny model defaultem.
            self.ai_provider_combo.currentTextChanged.connect(self._on_ai_provider_changed)
            self._update_ai_key_status()
            layout.addLayout(form)

            buttons = QHBoxLayout()
            rebuild = QPushButton("Rebuild data")
            rebuild.setObjectName("dangerButton")
            rebuild.clicked.connect(self.run_rebuild)
            rollback = QPushButton("Rollback")
            rollback.setObjectName("dangerButton")
            rollback.clicked.connect(self.run_rollback)
            save = QPushButton("Ulozit")
            save.setObjectName("neutralButton")
            save.clicked.connect(self.save_library)
            close = QPushButton("Zavrit")
            close.setObjectName("neutralButton")
            close.clicked.connect(self.accept)
            buttons.addWidget(rebuild)
            buttons.addWidget(rollback)
            buttons.addStretch(1)
            buttons.addWidget(save)
            buttons.addWidget(close)
            layout.addLayout(buttons)

        def _on_ai_provider_changed(self, provider: str) -> None:
            """Pri zmene providera prepne model na jeho default a obnovi status klice."""
            self.ai_model_edit.setText(AI_PROVIDER_DEFAULT_MODELS.get(provider, ""))
            self._update_ai_key_status()

        def _update_ai_key_status(self) -> None:
            """Ukaze, jestli appka nasla API klic pro vybraneho cloud providera."""
            provider = self.ai_provider_combo.currentText()
            if provider in ("anthropic", "openai"):
                found = bool(cme.read_api_key(provider))
                self.ai_key_status_label.setText("nalezen" if found else "CHYBI (nastav v .env)")
            else:
                self.ai_key_status_label.setText("nepouziva se")

        def choose_library(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Vyber Calibre knihovnu", self.library_edit.text())
            if selected:
                self.library_edit.setText(selected)

        def use_calibre_library(self) -> None:
            library = shared.read_calibre_library_path()
            if not library:
                QMessageBox.information(self, "Calibre", "Calibre knihovna nenalezena.")
                return
            self.library_edit.setText(library)

        def save_library(self) -> None:
            library = self.library_edit.text().strip()
            if not library:
                QMessageBox.warning(self, "Knihovna", "Zadej cestu ke knihovne.")
                return
            save_app_settings(library, self.theme_combo.currentText())
            settings = read_app_settings()
            settings["startup_preview"] = self.startup_preview_check.isChecked()
            settings["auto_link_audit"] = self.auto_link_audit_check.isChecked()
            settings["auto_cover_audit"] = self.auto_cover_audit_check.isChecked()
            ai_raw = {
                "provider": self.ai_provider_combo.currentText(),
                "model": self.ai_model_edit.text(),
                "text_limit": self.ai_text_limit_edit.text(),
                "timeout": self.ai_timeout_edit.text(),
                "workers": self.ai_workers_spin.value(),
            }
            settings["ai"] = normalize_ai_settings({"ai": ai_raw})
            shared.SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            self.parent_window.library_path = library
            self.parent_window.theme = normalize_theme(self.theme_combo.currentText())
            self.parent_window.auto_settings = normalize_auto_settings(settings)
            self.parent_window.apply_theme()
            self.parent_window.set_status("Knihovna ulozena")

        def run_rebuild(self) -> None:
            self.save_library()
            self.parent_window.run_rebuild()

        def run_rollback(self) -> None:
            self.save_library()
            self.parent_window.run_rollback()

    class CalibreMetaQtWindow(QMainWindow):
        """Hlavni Qt okno. Drzi tabulku, filtry, detail a statusbar."""

        def __init__(self) -> None:
            super().__init__()
            self.matches_path = cme.MATCHES_PATH
            self.library_path = shared.initial_library_path()
            settings = read_app_settings()
            theme_setting = settings.get("theme", "system")
            self.theme = normalize_theme(theme_setting if isinstance(theme_setting, str) else "system")
            self.auto_settings = normalize_auto_settings(settings)
            self.rows: list[cme.MatchRow] = []
            self.filtered_rows: list[cme.MatchRow] = []
            self.auto_skip_filter_allowed = True
            self.worker_running = False
            self.csv_loaded = False
            self.calibre_running = False
            # Posledni zname pripojeni. Neoveruje se na timeru: sonda ma 1s
            # timeout a offline by tak UI kazdych par vterin zamrzavalo.
            # Obnovuje se, kdyz na tom zalezi (start, analyza, import).
            self.online = True
            # Zaloha pripravena pro aktualni davku multiimportu (viz
            # prepare_multiimport_backup); None = zalohovat nechce uzivatel.
            self._multiimport_backup_ready = False
            self._multiimport_backup_path: Path | None = None
            self.bridge = WorkerBridge()
            self.bridge.finished.connect(self.finish_background)
            self.bridge.cover_ready.connect(self.finish_cover_preview)
            self.bridge.review_ready.connect(self.finish_review_metadata_preview)
            self.bridge.import_ready.connect(self.finish_import_analysis)
            self.bridge.apply_ready.connect(self.finish_import_apply)
            self.cover_preview_request_id = 0
            self.review_preview_request_id = 0
            self.review_preview_book_id: int | None = None
            self.review_preview_written_url = ""
            self.review_preview_detail: cme.BookDetailMetadata | None = None
            self.cover_preview_cache: dict[str, tuple[str, bytes]] = {}
            self.cover_option_buttons: dict[str, QToolButton] = {}
            self.setWindowTitle(app_title())
            if ICON_PATH.exists():
                self.setWindowIcon(QIcon(str(ICON_PATH)))
            self.resize(1320, 780)
            self._build_ui()
            self.calibre_timer = QTimer(self)
            self.calibre_timer.timeout.connect(self.refresh_calibre_indicator)
            # V testech (CALIBRE_META_EDIT_TEST=1) casovac nespoustime: jinak by
            # kazde nahromadene testovaci okno kazdych 5 s poustelo `tasklist`
            # (subprocess) a sada by kvadraticky zpomalovala.
            if os.environ.get("CALIBRE_META_EDIT_TEST") != "1":
                self.calibre_timer.start(5000)
            self.load_csv(show_message=False)
            if os.environ.get("CALIBRE_META_EDIT_TEST") != "1":
                self.is_online_now()
            if (
                self.auto_settings["startup_preview"]
                and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
                and os.environ.get("CALIBRE_META_EDIT_TEST") != "1"
            ):
                schedule_qt_startup_preview(self.run_preview)

        def _build_ui(self) -> None:
            root = QWidget()
            layout = QVBoxLayout(root)
            layout.setContentsMargins(10, 10, 10, 6)
            layout.setSpacing(8)
            layout.addLayout(self._build_toolbar())
            layout.addLayout(self._build_filter_row())
            layout.addWidget(self._build_main_area(), stretch=1)
            self.setCentralWidget(root)
            self.setStatusBar(QStatusBar())
            self.online_indicator = QLabel()
            self.statusBar().addPermanentWidget(self.online_indicator)
            self.calibre_indicator = QLabel()
            self.statusBar().addPermanentWidget(self.calibre_indicator)
            self.update_online_indicator()
            self.set_status("Ready")
            self.apply_theme()

        def _build_multiimport_menu(self) -> None:
            menu = self.menuBar().addMenu("Multiimport")
            self.multiimport_files_action = menu.addAction("Vybrat vice knih...")
            self.multiimport_files_action.triggered.connect(lambda _checked=False: self.choose_multiimport_files())
            self.multiimport_folder_action = menu.addAction("Vybrat slozku...")
            self.multiimport_folder_action.triggered.connect(lambda _checked=False: self.choose_multiimport_folder())

        def _build_toolbar(self) -> QHBoxLayout:
            toolbar = QHBoxLayout()
            toolbar.setSpacing(6)
            self.buttons: list[QToolButton] = []

            # Leva skupina: nacist, ulozit - maly odstup - preferences.
            self._add_button(toolbar, "Nacist data", self.load_csv, "neutralButton", "load", show_text=False)
            self._add_button(toolbar, "Ulozit data", self.save_csv, "neutralButton", "save", show_text=False)
            toolbar.addSpacing(10)
            self._add_button(toolbar, "Preferences", self.open_preferences, "neutralButton", "preferences", show_text=False)
            # Velky odstup deli levou skupinu (u leveho okraje) od prave (u praveho okraje).
            toolbar.addStretch(1)
            # Prava skupina: import, obalky, odkaz, Calibre - odstup - smazat - odstup - zapsat.
            self.unified_import_button = self._add_button(
                toolbar,
                "Unified import",
                self.on_unified_import_clicked,
                "neutralButton",
                "import-epub",
                show_text=False,
            )
            self.import_button = self._add_button(
                toolbar, "Import knihy", lambda: self.start_epub_import(), "neutralButton", "import-epub", show_text=False
            )
            self.import_button.hide()
            self.update_import_button_enabled(True)
            self._add_button(toolbar, "Obalky", self.run_covers, "neutralButton", "covers", show_text=False)
            self._add_button(toolbar, "Najit / overit odkaz", self.run_audit, "neutralButton", "link", show_text=False)
            self._add_button(toolbar, "Nacist z Calibre", self.run_update_selected, "updateButton", "load-calibre", show_text=False)
            toolbar.addSpacing(10)
            self._add_button(toolbar, "Smazat z Calibre", self.delete_selected_rows, "dangerButton", "delete", show_text=False)
            toolbar.addSpacing(10)
            self._add_button(toolbar, "Zapsat", self.run_apply, "applyButton", "write-calibre", show_text=False)
            return toolbar

        def _build_filter_row(self) -> QHBoxLayout:
            # Filtry maji vlastni radek primo nad tabulkou (drive byly v toolbaru s tlacitky).
            bar = QHBoxLayout()
            bar.setSpacing(6)
            self._build_filterbar(bar)
            bar.addStretch(1)
            return bar

        def _add_button(
            self,
            layout: QHBoxLayout,
            text: str,
            callback: Callable[[], None],
            object_name: str = "",
            icon: str = "",
            show_text: bool = True,
        ) -> QToolButton:
            button = QToolButton()
            button.setText(text if show_text else "")
            button.setToolTip(text)
            button.setIconSize(QSize(32, 32))
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon if show_text else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            if not show_text:
                button.setProperty("iconOnly", True)
                button.setFixedSize(42, 42)
            if icon:
                button.setIcon(self.icon_for(icon))
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(lambda _checked=False, callback=callback: callback())
            layout.addWidget(button)
            self.buttons.append(button)
            return button

        def icon_for(self, name: str) -> QIcon:
            """Vrati vlastni SVG ikonu (assets/icons, pak icons/), nebo Qt fallback."""
            asset_path = asset_icon_path(name)
            if asset_path is not None:
                return QIcon(str(asset_path))
            path = ICON_DIR / f"{name}.svg"
            if path.exists():
                return QIcon(str(path))
            # "epub" a "cover" nemaji vlastni SVG; bez tohoto rozliseni by oba
            # spadly na SP_FileIcon a vypadaly stejne. Import EPUB = sipka dolu (import).
            fallback = {
                "open": QStyle.StandardPixmap.SP_DialogOpenButton,
                "save": QStyle.StandardPixmap.SP_DialogSaveButton,
                "apply": QStyle.StandardPixmap.SP_DialogApplyButton,
                "epub": QStyle.StandardPixmap.SP_ArrowDown,
            }.get(name, QStyle.StandardPixmap.SP_FileIcon)
            return self.style().standardIcon(fallback)

        def _build_filterbar(self, bar: QHBoxLayout) -> None:
            self.title_filter = self._filter_edit("Kniha", bar)
            self.author_filter = self._filter_edit("Autor", bar)
            self.status_checks = self._filter_checks(STATUS_FILTER_VALUES, bar)
            self.source_checks = self._filter_checks(SOURCE_FILTER_VALUES, bar)
            self.type_checks = self._filter_checks(TYPE_FILTER_VALUES, bar)

        def _filter_edit(self, label: str, layout: QHBoxLayout) -> QLineEdit:
            layout.addWidget(QLabel(label))
            field = QLineEdit()
            field.setClearButtonEnabled(True)
            field.setMinimumWidth(130)
            field.textChanged.connect(self.refresh_table)
            layout.addWidget(field, stretch=2)
            return field

        def _filter_checks(self, values: Sequence[str], layout: QHBoxLayout) -> dict[str, QCheckBox]:
            frame = QFrame()
            row = QHBoxLayout(frame)
            row.setContentsMargins(20, 0, 0, 0)
            row.setSpacing(8)
            checks: dict[str, QCheckBox] = {}
            for value in values:
                check = QCheckBox(filter_label(value))
                check.setChecked(default_filter_checked(values, value))
                check.pressed.connect(self.disable_auto_skip_filter)
                check.stateChanged.connect(self.refresh_table)
                row.addWidget(check)
                checks[value] = check
            layout.addWidget(frame)
            return checks

        def disable_auto_skip_filter(self) -> None:
            """Po rucnim kliknuti uzivatele uz neskace skip filtr zpatky sam."""
            self.auto_skip_filter_allowed = False

        def _build_main_area(self) -> QSplitter:
            splitter = QSplitter(Qt.Orientation.Horizontal)
            self.table = QTableWidget(0, len(TABLE_COLUMNS))
            self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            self.table.setSortingEnabled(True)
            self.table.setAlternatingRowColors(True)
            self.table.verticalHeader().setVisible(False)
            self.table.verticalHeader().setDefaultSectionSize(22)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.table.horizontalHeader().setStretchLastSection(False)
            self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table.horizontalHeader().customContextMenuRequested.connect(self.show_column_menu)
            self.table.itemSelectionChanged.connect(self.on_selection_changed)
            self.apply_column_settings()
            splitter.addWidget(self.table)
            splitter.addWidget(self._build_detail_panel())
            splitter.setSizes([900, 360])
            return splitter

        def apply_column_settings(self) -> None:
            """Pri startu obnovi sirky a viditelnost sloupcu ze settings.json."""
            settings = normalize_column_settings(read_app_settings().get("columns"))
            for index, column in enumerate(TABLE_COLUMNS):
                column_settings = settings.get(column, {})
                width = column_settings.get("width")
                if isinstance(width, int):
                    self.table.setColumnWidth(index, width)
                visible = column_settings.get("visible")
                if index in REQUIRED_COLUMN_INDEXES:
                    self.table.setColumnHidden(index, False)
                elif isinstance(visible, bool):
                    self.table.setColumnHidden(index, not visible)

        def save_column_settings(self, width_overrides: dict[int, int] | None = None) -> None:
            """Ulozi aktualni sirky a viditelnost sloupcu do settings.json."""
            width_overrides = width_overrides or {}
            settings = read_app_settings()
            previous_columns = normalize_column_settings(settings.get("columns"))
            columns: dict[str, dict[str, bool | int]] = {}
            for index, column in enumerate(TABLE_COLUMNS):
                previous_width = previous_columns.get(column, {}).get("width")
                if index in width_overrides:
                    width = width_overrides[index]
                elif self.table.isColumnHidden(index) and isinstance(previous_width, int):
                    width = previous_width
                else:
                    width = self.table.columnWidth(index)
                columns[column] = {
                    "visible": False if index in REQUIRED_COLUMN_INDEXES else not self.table.isColumnHidden(index),
                    "width": max(MIN_COLUMN_WIDTH, width),
                }
            settings["columns"] = {
                column: values for column, values in columns.items()
            }
            for index in REQUIRED_COLUMN_INDEXES:
                settings["columns"][TABLE_COLUMNS[index]]["visible"] = True
            shared.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            shared.SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        def show_column_menu(self, pos: QPoint) -> None:
            """Prave kliknuti na hlavicku sloupcu ukaze volbu viditelnosti."""
            menu = QMenu(self)
            header = self.table.horizontalHeader()
            for index, column in enumerate(TABLE_COLUMNS):
                action = QAction(column, menu)
                action.setCheckable(True)
                action.setChecked(not self.table.isColumnHidden(index))
                if index < 3:
                    action.setEnabled(False)
                else:
                    action.toggled.connect(lambda checked, col=index: self.set_column_visible(col, checked))
                menu.addAction(action)
            menu.exec(header.mapToGlobal(pos))

        def set_column_visible(self, column: int, visible: bool) -> None:
            """Zmeni viditelnost sloupce a hned ji ulozi."""
            if column in REQUIRED_COLUMN_INDEXES:
                return
            column_settings = normalize_column_settings(read_app_settings().get("columns")).get(TABLE_COLUMNS[column], {})
            previous_width = column_settings.get("width")
            if visible:
                self.table.setColumnHidden(column, False)
                if isinstance(previous_width, int):
                    self.table.setColumnWidth(column, previous_width)
                self.save_column_settings()
                return
            width = self.table.columnWidth(column)
            self.table.setColumnHidden(column, True)
            self.save_column_settings({column: width})

        def closeEvent(self, event: Any) -> None:
            """Pred zavrenim ulozi rozlozeni sloupcu."""
            self.save_column_settings()
            super().closeEvent(event)

        def _build_detail_panel(self) -> QWidget:
            panel = QWidget()
            panel.setMinimumWidth(320)
            panel.setMaximumWidth(460)
            layout = QVBoxLayout(panel)
            self.detail_tabs = QTabWidget()
            layout.addWidget(self.detail_tabs)

            current_tab = QWidget()
            current_layout = QVBoxLayout(current_tab)
            self.current_data_grid = QGridLayout()
            self.current_data_labels: dict[str, QLabel] = {}
            for row_index, field in enumerate(
                ("ID", "Kniha", "Autor", "Status", "Zdroj", "Typ", "Rok vydani", "Vydavatel", "Tagy", "Obalka")
            ):
                name = QLabel(field)
                name.setObjectName("fieldName")
                value = QLabel("")
                value.setWordWrap(True)
                self.current_data_grid.addWidget(name, row_index, 0)
                self.current_data_grid.addWidget(value, row_index, 1)
                self.current_data_labels[field] = value
            current_layout.addLayout(self.current_data_grid)
            self.current_cover_image = QLabel("")
            self.current_cover_image.setObjectName("coverImage")
            self.current_cover_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.current_cover_image.setFixedSize(150, 220)
            current_layout.addWidget(self.current_cover_image, alignment=Qt.AlignmentFlag.AlignHCenter)
            current_layout.addWidget(QLabel("Komentar"))
            self.current_comment_preview = QTextEdit()
            self.current_comment_preview.setReadOnly(True)
            self.current_comment_preview.setMinimumHeight(160)
            current_layout.addWidget(self.current_comment_preview, stretch=1)
            current_layout.addStretch(1)
            self.detail_tabs.addTab(current_tab, "Aktualni data")

            review_tab = QWidget()
            review_layout = QVBoxLayout(review_tab)
            status_buttons = QHBoxLayout()
            self.approve_button = self._add_button(
                status_buttons, "Approve", lambda: self.set_selected_status("approve"), "approveButton"
            )
            self.review_button = self._add_button(
                status_buttons, "Review", lambda: self.set_selected_status("review"), "reviewButton"
            )
            self.skip_button = self._add_button(status_buttons, "Skip", lambda: self.set_selected_status("skip"), "skipButton")
            self.story_button = self._add_button(status_buttons, "Povidka", self.mark_selected_story, "storyButton")
            for index, button in enumerate((self.approve_button, self.review_button, self.skip_button, self.story_button)):
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                status_buttons.setStretch(index, 1)
            review_layout.addLayout(status_buttons)

            link_row = QHBoxLayout()
            link_row.addWidget(QLabel("Odkaz"))
            self.url_edit = QLineEdit()
            self.url_edit.setClearButtonEnabled(True)
            self.url_edit.textChanged.connect(self.update_link_buttons)
            link_row.addWidget(self.url_edit, stretch=1)
            self.use_link_button = self._add_button(link_row, "Pouzit odkaz", self.apply_selected_url, "neutralButton", "apply", show_text=False)
            self.open_link_button = self._add_button(link_row, "Otevrit odkaz", self.open_selected_url, "neutralButton", "chrome", show_text=False)
            self.use_link_button.setFixedSize(28, 28)
            self.open_link_button.setFixedSize(28, 28)
            self.use_link_button.setIconSize(QSize(18, 18))
            self.open_link_button.setIconSize(QSize(18, 18))
            review_layout.addLayout(link_row)

            self.cover_status = QLabel("Bez obalky")
            self.cover_status.setObjectName("coverStatus")
            self.cover_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cover_image = QLabel("")
            self.cover_image.setObjectName("coverImage")
            self.cover_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cover_image.setFixedSize(150, 220)
            self.cover_image.setScaledContents(False)
            self.cover_image.setVisible(False)
            self.cover_source = QLabel("")
            self.cover_source.setWordWrap(True)
            self.cover_options_widget = QWidget()
            self.cover_options_layout = QGridLayout(self.cover_options_widget)
            self.cover_options_layout.setContentsMargins(0, 0, 0, 0)
            self.cover_options_layout.setHorizontalSpacing(6)
            self.cover_options_layout.setVerticalSpacing(6)
            # Vyber obalky jinak nejde vzit zpet - klik na miniaturu se hned uklada.
            # Tohle tlacitko zahodi nabidku i vyber a vrati stav pred auditem.
            self.clear_cover_button = QPushButton("Zrusit vyber obalky")
            self.clear_cover_button.setToolTip(
                "Zahodi nabidnute obalky a vrati knihu do stavu pred auditem obalek."
            )
            self.clear_cover_button.clicked.connect(self.clear_selected_cover)
            self.clear_cover_button.setVisible(False)
            review_layout.addWidget(self.cover_status)
            review_layout.addWidget(self.cover_image, alignment=Qt.AlignmentFlag.AlignHCenter)
            review_layout.addWidget(self.cover_source)
            review_layout.addWidget(self.cover_options_widget)
            review_layout.addWidget(self.clear_cover_button)
            review_layout.addWidget(QLabel("Metadata k zapisu"))
            self.review_data_grid = QGridLayout()
            self.review_data_labels: dict[str, QLabel] = {}
            self.review_data_edits: dict[str, QLineEdit] = {}
            for row_index, field in enumerate(
                ("Status", "Zdroj", "Typ", "Rok vydani", "Vydavatel", "Serie", "Cislo serie", "Tagy", "Hodnoceni", "Originalni nazev", "Originalne vyslo")
            ):
                name = QLabel(field)
                name.setObjectName("fieldName")
                if field in REVIEW_EDITABLE_FIELDS:
                    value = QLineEdit()
                    value.setClearButtonEnabled(True)
                    value.textEdited.connect(lambda text, field=field: self.review_field_edited(field, text))
                    self.review_data_edits[field] = value
                else:
                    value = QLabel("")
                    value.setWordWrap(True)
                    self.review_data_labels[field] = value
                self.review_data_grid.addWidget(name, row_index, 0)
                self.review_data_grid.addWidget(value, row_index, 1)
            review_layout.addLayout(self.review_data_grid)
            review_layout.addWidget(QLabel("Komentar po zapisu"))
            self.review_comment_preview = QTextEdit()
            self.review_comment_preview.setReadOnly(True)
            self.review_comment_preview.setMinimumHeight(140)
            review_layout.addWidget(self.review_comment_preview, stretch=1)
            self.detail_tabs.addTab(review_tab, "Review")

            self.log_tab = QWidget()
            log_layout = QVBoxLayout(self.log_tab)
            self.output = QTextEdit()
            self.output.setReadOnly(True)
            self.output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            log_layout.addWidget(self.output, stretch=1)
            self.detail_tabs.addTab(self.log_tab, "Log")
            return panel

        def load_csv(self, show_message: bool = True) -> None:
            self.auto_skip_filter_allowed = True
            if not cme.matches_storage_exists(self.matches_path):
                self.rows = []
                self.csv_loaded = False
                self.refresh_table()
                self.set_status(f"Soubor nenalezen: {self.matches_path}")
                return
            try:
                self.rows = cme.read_matches_csv(self.matches_path)
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"Pracovni data nejde nacist:\n{exc}")
                return
            self.csv_loaded = True
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))
            if show_message:
                self.write_output(f"Nacteno: {self.matches_path}\n{shared.status_summary(self.rows)}")

        def save_csv(self, show_message: bool = True) -> bool:
            try:
                cme.write_matches_csv(self.matches_path, self.rows, overwrite=True)
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"Pracovni data nejde ulozit:\n{exc}")
                return False
            self.csv_loaded = True
            self.set_status(f"Ulozeno. {shared.status_summary(self.rows)}")
            if show_message:
                self.write_output(f"Ulozeno: {self.matches_path}")
            return True

        def refresh_table(self) -> None:
            selected_ids = self.selected_book_ids()
            statuses = self.checked_values(self.status_checks)
            sources = self.checked_values(self.source_checks)
            work_types = self.checked_values(self.type_checks)
            self.filtered_rows = filter_rows(
                self.rows,
                title=self.title_filter.text(),
                author=self.author_filter.text(),
                statuses=statuses,
                sources=sources,
                work_types=work_types,
            )
            if should_enable_skip_filter(
                self.rows,
                self.filtered_rows,
                self.title_filter.text(),
                self.author_filter.text(),
                statuses,
                sources,
                work_types,
            ) and self.auto_skip_filter_allowed:
                self.auto_skip_filter_allowed = False
                self.status_checks["skip"].blockSignals(True)
                self.status_checks["skip"].setChecked(True)
                self.status_checks["skip"].blockSignals(False)
                self.set_status("Nic k reseni, zobrazuju i skip")
                self.filtered_rows = filter_rows(
                    self.rows,
                    title=self.title_filter.text(),
                    author=self.author_filter.text(),
                    statuses=self.checked_values(self.status_checks),
                    sources=sources,
                    work_types=work_types,
                )
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(self.filtered_rows))
            for row_index, row in enumerate(self.filtered_rows):
                values = (
                    str(row.book_id),
                    row.title,
                    row.authors,
                    row.status,
                    row.source,
                    row.work_type,
                    row.chosen_url,
                    row.reason,
                )
                for col_index, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, row.book_id)
                    if col_index == 0:
                        item.setData(Qt.ItemDataRole.DisplayRole, row.book_id)
                    item.setBackground(status_color(row.status))
                    item.setForeground(QColor("#111111"))
                    self.table.setItem(row_index, col_index, item)
            self.table.setSortingEnabled(True)
            self.restore_selection(selected_ids)
            if not self.selected_book_ids() and self.table.rowCount():
                self.table.selectRow(0)
                self.on_selection_changed()

        def checked_values(self, checks: dict[str, QCheckBox]) -> set[str] | None:
            """Vrati vybrane hodnoty; vse vybrane znamena bez filtru."""
            selected = {value for value, check in checks.items() if check.isChecked()}
            if len(selected) == len(checks):
                return None
            return selected

        def restore_selection(self, book_ids: set[int]) -> None:
            if not book_ids:
                self.on_selection_changed()
                return
            self.table.clearSelection()
            for row_index in range(self.table.rowCount()):
                item = self.table.item(row_index, 0)
                book_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
                if book_id in book_ids:
                    self.table.selectRow(row_index)
            self.on_selection_changed()

        def selected_book_ids(self) -> set[int]:
            selected: set[int] = set()
            for item in self.table.selectedItems():
                book_id = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(book_id, int):
                    selected.add(book_id)
            return selected

        def selected_row(self) -> cme.MatchRow | None:
            selected = sorted(self.selected_book_ids())
            if not selected:
                return None
            index = shared.find_row_index(self.rows, selected[0])
            return self.rows[index] if index is not None else None

        def selected_rows(self) -> list[cme.MatchRow]:
            """Vrati vsechny vybrane radky v poradi podle ID."""
            rows: list[cme.MatchRow] = []
            for book_id in sorted(self.selected_book_ids()):
                index = shared.find_row_index(self.rows, book_id)
                if index is not None:
                    rows.append(self.rows[index])
            return rows

        def on_selection_changed(self) -> None:
            rows = self.selected_rows()
            self.update_current_data(rows)
            link_text = selection_link_text(rows)
            if self.url_edit.text() != link_text:
                self.url_edit.setText(link_text)
            self.update_link_buttons()
            self.update_cover_preview(rows)
            self.update_review_metadata_preview(rows)

        def update_current_data(self, rows: Sequence[cme.MatchRow]) -> None:
            """Prekresli zalozku Aktualni data."""
            metadata: cme.CurrentBookMetadata | None = None
            if len(rows) == 1:
                try:
                    metadata = cme.get_current_book_metadata(self.library_path, rows[0].book_id)
                except Exception:
                    metadata = cme.CurrentBookMetadata(tags=[])
            values = dict(current_data_fields(rows, metadata))
            for field, label in self.current_data_labels.items():
                label.setText(values.get(field, ""))
            if metadata is not None and metadata.comment:
                self.current_comment_preview.setHtml(metadata.comment)
            else:
                self.current_comment_preview.setHtml("<p>Bez komentare</p>")
            self.update_current_cover(rows)

        def update_current_cover(self, rows: Sequence[cme.MatchRow]) -> None:
            """Ukaze obalku, ktera uz realne je v Calibre."""
            self.current_cover_image.clear()
            if len(rows) != 1:
                self.current_cover_image.setText("Bez nahledu")
                return
            row = rows[0]
            try:
                local_cover = cme.get_local_cover_path(self.library_path, row.book_id)
            except Exception:
                self.current_data_labels["Obalka"].setText("nejde nacist")
                self.current_cover_image.setText("Bez nahledu")
                return
            if local_cover is None:
                self.current_data_labels["Obalka"].setText("neni v Calibre")
                self.current_cover_image.setText("Bez nahledu")
                return
            self.current_data_labels["Obalka"].setText("v Calibre")
            try:
                if not self.set_label_pixmap(self.current_cover_image, local_cover.read_bytes()):
                    self.current_cover_image.setText("Bez nahledu")
            except OSError:
                self.current_cover_image.setText("Bez nahledu")

        def set_cover_placeholder(self, status: str, source: str = "") -> None:
            """Nastavi textovy stav nahledu obalky."""
            self.cover_status.setText(status)
            self.cover_source.setText(source)
            self.cover_image.clear()
            self.cover_image.setText("Bez nahledu")
            self.cover_image.setVisible(False)
            self.clear_cover_options()

        def set_label_pixmap(self, label: QLabel, image_bytes: bytes) -> bool:
            """Zobrazi obrazek do daneho QLabelu."""
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                return False
            scaled = pixmap.scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setText("")
            label.setPixmap(scaled)
            return True

        def set_cover_pixmap(self, status: str, image_bytes: bytes, source: str = "") -> None:
            """Zobrazi obrazek obalky v detailu."""
            self.cover_image.setVisible(True)
            if not self.set_label_pixmap(self.cover_image, image_bytes):
                self.set_cover_placeholder("Obalku nejde zobrazit", source)
                return
            self.cover_status.setText(status)
            self.cover_source.setText(source)

        def clear_cover_options(self) -> None:
            """Smaze mala tlacitka kandidatnich obalek."""
            # Bez nabidky neni co rusit, tak tlacitko schovame; show_cover_options
            # ho zase ukaze, az nejake obalky vykresli.
            self.clear_cover_button.setVisible(False)
            self.cover_option_buttons = {}
            while self.cover_options_layout.count():
                item = self.cover_options_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        def cover_button_style(self, selected: bool) -> str:
            """Vrati jednoduchy ramecek pro vybranou obalku."""
            if selected:
                return "QToolButton { border: 2px solid #1565c0; background: #e3f2fd; }"
            return "QToolButton { border: 1px solid #bdbdbd; background: #eeeeee; }"

        def set_cover_button_image(self, button: QToolButton, image_bytes: bytes) -> bool:
            """Nastavi nahled do maleho tlacitka obalky."""
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                return False
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(58, 82))
            button.setText("")
            return True

        def select_cover_candidate(self, book_id: int, cover_url: str) -> None:
            """Ulozi vybranou kandidatni obalku do CSV radku."""
            try:
                self.rows = shared.update_rows_selected_cover(self.rows, book_id, cover_url)
            except ValueError as exc:
                QMessageBox.warning(self, "Obalka", str(exc))
                return
            self.save_csv(show_message=False)
            self.refresh_table()
            self.update_cover_preview(self.selected_rows())

        def clear_selected_cover(self) -> None:
            """Zahodi nabidku obalek u vybrane knihy a vrati jeji stav pred auditem."""
            rows = self.selected_rows()
            if len(rows) != 1:
                return
            self.rows = shared.clear_rows_cover_selection(self.rows, rows[0].book_id)
            self.save_csv(show_message=False)
            self.refresh_table()
            self.update_cover_preview(self.selected_rows())

        def show_cover_options(self, row: cme.MatchRow, cover_urls: Sequence[str]) -> None:
            """Zobrazi grid kandidatnich obalek z pracovnich dat."""
            self.clear_cover_options()
            selected_url = row.selected_cover_url.strip()
            for index, cover_url in enumerate(cover_urls):
                button = QToolButton()
                button.setToolTip(cover_url)
                button.setText(str(index + 1))
                button.setFixedSize(70, 96)
                button.setStyleSheet(self.cover_button_style(cover_url == selected_url))
                button.clicked.connect(lambda _checked=False, url=cover_url, book_id=row.book_id: self.select_cover_candidate(book_id, url))
                self.cover_option_buttons[cover_url] = button
                self.cover_options_layout.addWidget(button, index // 3, index % 3)
                cached = self.cover_preview_cache.get(cover_url)
                if cached:
                    self.set_cover_button_image(button, cached[1])
                else:
                    self.load_cover_url(cover_url)
            self.clear_cover_button.setVisible(bool(cover_urls))

        def load_cover_url(self, cover_url: str) -> None:
            """Stahne obrazek kandidata na pozadi."""
            request_id = self.cover_preview_request_id

            def worker() -> None:
                try:
                    image_bytes = cme.fetch_binary(cover_url)
                    self.bridge.cover_ready.emit(request_id, "Kandidat obalky", cover_url, cover_url, image_bytes)
                except Exception as exc:
                    self.bridge.cover_ready.emit(request_id, "Obalku nejde nacist", cover_url, str(exc), b"")

            threading.Thread(target=worker, daemon=True).start()

        def update_cover_preview(self, rows: Sequence[cme.MatchRow]) -> None:
            """Ukaze lokalni obalku, nebo kandidatni obalky z pracovnich dat."""
            self.cover_preview_request_id += 1
            self.clear_cover_options()
            if not rows:
                self.set_cover_placeholder("Bez vyberu")
                return
            if len(rows) > 1:
                self.set_cover_placeholder(f"Vybrano {len(rows)} knih")
                return
            row = rows[0]
            try:
                local_cover = cme.get_local_cover_path(self.library_path, row.book_id)
            except Exception as exc:
                self.set_cover_placeholder("Obalku nejde nacist", str(exc))
                return
            if row.status == "skip":
                self.set_cover_placeholder(
                    "Obalka uz je v Calibre" if local_cover is not None else "Bez obalky"
                )
                return
            cover_urls = shared.cover_urls_from_row(row)
            if not cover_urls:
                self.set_cover_placeholder(
                    "Obalka uz je v Calibre" if local_cover is not None else "Bez obalky"
                )
                return
            selected_url = row.selected_cover_url.strip()
            preview_url = selected_url or cover_urls[0]
            if row.cover_reason == "cover-overwrite-declined":
                status = "Kandidatni obalky - prepsani odmitnuto"
            elif row.cover_reason == "cover-partial-error":
                status = "Nektery zdroj obalek selhal - nabidka muze byt neuplna"
            elif selected_url:
                status = "Vybrana kandidatni obalka"
            elif row.status == "skip":
                status = "Kandidatni obalky - historie"
            else:
                status = "Kandidatni obalky - vyber jednu"
            if local_cover is not None:
                status += " - Obalka uz je v Calibre"
            cached = self.cover_preview_cache.get(preview_url)
            if cached:
                self.set_cover_pixmap(status, cached[1], preview_url)
            else:
                self.cover_status.setText(status + " - nacitam")
                self.cover_source.setText(preview_url)
                self.cover_image.clear()
                self.cover_image.setVisible(True)
                self.cover_image.setText("Nacitam")
                self.load_cover_url(preview_url)
            self.show_cover_options(row, cover_urls)

        def set_review_fields(self, rows: Sequence[cme.MatchRow], written_url: str = "", detail: cme.BookDetailMetadata | None = None, error: str = "") -> None:
            """Prekresli metadata, ktera se budou zapisovat."""
            values = dict(review_data_fields(rows, written_url, detail, error))
            for field, label in self.review_data_labels.items():
                label.setText(values.get(field, ""))
            for field, edit in self.review_data_edits.items():
                edit.blockSignals(True)
                edit.setText(values.get(field, ""))
                edit.setEnabled(detail is not None and len(rows) == 1)
                edit.blockSignals(False)

        def review_field_edited(self, field: str, value: str) -> None:
            """Ulozi rucne upravenou hodnotu Review pole do CSV radku."""
            rows = self.selected_rows()
            if len(rows) != 1:
                return
            book_id = rows[0].book_id
            self.rows = shared.update_rows_review_override(self.rows, book_id, field, value)
            self.save_csv(show_message=False)
            updated = self.selected_rows()
            if len(updated) != 1:
                return
            self.render_review_comment_from_current_fields(updated[0])

        def render_review_comment_from_current_fields(self, row: cme.MatchRow) -> None:
            """Prekresli komentar po rucni zmene Review pole."""
            if self.review_preview_book_id != row.book_id or self.review_preview_detail is None:
                return
            detail = cme.apply_review_overrides(row, self.review_preview_detail)
            self.review_comment_preview.setHtml(cme.format_enriched_comment(self.review_preview_written_url, detail))

        def update_review_metadata_preview(self, rows: Sequence[cme.MatchRow]) -> None:
            """Na pozadi nacte web metadata pro vybranou knihu."""
            self.review_preview_request_id += 1
            request_id = self.review_preview_request_id
            self.review_preview_book_id = None
            self.review_preview_written_url = ""
            self.review_preview_detail = None
            self.review_comment_preview.setHtml("<p>Bez nahledu</p>")
            if not rows:
                self.set_review_fields(rows)
                return
            if len(rows) > 1:
                self.set_review_fields(rows)
                self.review_comment_preview.setHtml(f"<p>Vybrano {len(rows)} knih</p>")
                return
            row = rows[0]
            self.set_review_fields(rows)
            url = row.chosen_url.strip()
            if not url:
                self.review_comment_preview.setHtml("<p>Bez odkazu</p>")
                return
            if cme.is_valid_databaze_story_url(url) or (
                not cme.is_valid_apply_url(url)
                and not cme.is_valid_legie_story_url(url)
                and not cme.is_valid_google_books_url(url)
                and not cme.is_valid_openlibrary_url(url)
            ):
                self.review_comment_preview.setHtml(cme.format_link_html(url))
                return
            self.review_comment_preview.setHtml("<p>Nacitam metadata...</p>")

            def worker() -> None:
                try:
                    if row.source == "legie" or cme.is_valid_legie_story_url(url):
                        detail = cme.parse_legie_story_detail(cme.fetch_text(url), url)
                        comment = cme.format_legie_comment(url, detail)
                        self.bridge.review_ready.emit(request_id, row.book_id, url, None, comment)
                        return
                    if row.source == "googlebooks" or cme.is_valid_google_books_url(url):
                        written_url, detail = cme.fetch_google_books_detail_metadata(url)
                        comment = cme.format_enriched_comment(written_url, detail)
                        self.bridge.review_ready.emit(request_id, row.book_id, written_url, detail, comment)
                        return
                    if row.source == "openlibrary" or cme.is_valid_openlibrary_url(url):
                        written_url, detail = cme.fetch_openlibrary_detail_metadata(url)
                        comment = cme.format_enriched_comment(written_url, detail)
                        self.bridge.review_ready.emit(request_id, row.book_id, written_url, detail, comment)
                        return
                    if cme.is_valid_apply_url(url):
                        written_url, detail = cme.fetch_databaze_book_detail_metadata(url)
                        canonical_url = cme.canonical_detail_output_url(url, written_url)
                        comment = cme.format_enriched_comment(canonical_url, detail)
                        self.bridge.review_ready.emit(request_id, row.book_id, canonical_url, detail, comment)
                        return
                    self.bridge.review_ready.emit(request_id, row.book_id, url, None, cme.format_link_html(url))
                except Exception as exc:
                    self.bridge.review_ready.emit(request_id, row.book_id, url, None, "CHYBA: " + str(exc))

            threading.Thread(target=worker, daemon=True).start()

        def finish_review_metadata_preview(self, request_id: int, book_id: int, written_url: str, detail: object, comment_html: str) -> None:
            """Prevezme metadata pro Review tab z background threadu."""
            if request_id != self.review_preview_request_id:
                return
            rows = self.selected_rows()
            if len(rows) != 1 or rows[0].book_id != book_id:
                return
            if comment_html.startswith("CHYBA: "):
                self.set_review_fields(rows, written_url, None, comment_html)
                self.review_comment_preview.setPlainText(comment_html)
                return
            metadata = detail if isinstance(detail, cme.BookDetailMetadata) else None
            self.review_preview_book_id = book_id
            self.review_preview_written_url = written_url
            self.review_preview_detail = metadata
            self.set_review_fields(rows, written_url, metadata)
            if metadata is not None:
                rendered_detail = cme.apply_review_overrides(rows[0], metadata)
                self.review_comment_preview.setHtml(cme.format_enriched_comment(written_url, rendered_detail))
            else:
                self.review_comment_preview.setHtml(comment_html)

        def finish_cover_preview(self, request_id: int, label: str, cache_key: str, source: str, image_bytes: bytes) -> None:
            """Prevezme nahled obalky z background threadu."""
            if request_id != self.cover_preview_request_id:
                return
            if not image_bytes:
                button = self.cover_option_buttons.get(cache_key)
                if button is not None:
                    button.setText("!")
                    button.setToolTip(source)
                    return
                self.set_cover_placeholder("Bez obalky", source)
                return
            self.cover_preview_cache[cache_key] = (source, image_bytes)
            button = self.cover_option_buttons.get(cache_key)
            if button is not None:
                self.set_cover_button_image(button, image_bytes)
            rows = self.selected_rows()
            if len(rows) == 1:
                cover_urls = shared.cover_urls_from_row(rows[0])
                selected_url = rows[0].selected_cover_url.strip() or (cover_urls[0] if cover_urls else "")
                if selected_url == cache_key:
                    self.set_cover_pixmap(label, image_bytes, source)

        def update_link_buttons(self) -> None:
            """Zapne link tlacitka podle vyberu a textu v poli Odkaz."""
            rows = self.selected_rows()
            link_text = self.url_edit.text()
            self.use_link_button.setEnabled(use_link_enabled(rows, link_text))
            self.open_link_button.setEnabled(open_link_enabled(rows, link_text))

        def set_selected_status(self, status: str) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            missing_cover = shared.rows_missing_cover_choice(self.rows, selected) if status == "approve" else []
            if missing_cover:
                titles = "\n".join(f"- {row.book_id} {row.title}" for row in missing_cover[:8])
                QMessageBox.information(self, "Vyber obalku", "Nejdriv vyber jednu obalku:\n" + titles)
                return
            self.rows = shared.update_rows_status(self.rows, selected, status)
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))

        def mark_selected_story(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            self.rows = shared.mark_rows_as_story(self.rows, selected)
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))

        def delete_selected_rows(self) -> None:
            """TRVALE smaze vybrane knihy z Calibre (vcetne souboru) a z pracovnich dat."""
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Smazat z Calibre", "Nejdriv vyber radek v tabulce.")
                return
            answer = QMessageBox.question(
                self,
                "Smazat z Calibre",
                f"TRVALE smazat {len(selected)} knih z Calibre vcetne souboru?\n"
                "Nelze vratit pres rollback metadata.db.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            calibredb_path = cme.find_calibredb()
            if not calibredb_path:
                QMessageBox.warning(self, "Smazat z Calibre", "Nepodarilo se najit calibredb. Mazani zruseno.")
                return
            library = self.library_path
            matches_path = self.matches_path
            ids = set(selected)
            self.run_background(
                "Smazat z Calibre",
                lambda: cme.delete_books_from_calibre(library, ids, calibredb_path, matches_path=matches_path),
                reload_after=True,
            )

        def apply_selected_url(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            if self.url_edit.text().strip() == "Ruzne adresy":
                QMessageBox.information(self, "Odkaz", "Smaz text Ruzne adresy, nebo zadej konkretni odkaz.")
                return
            self.rows = shared.update_rows_url(self.rows, selected, self.url_edit.text())
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))

        def open_selected_url(self) -> None:
            row = self.selected_row()
            if row is None:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            url = self.url_edit.text().strip() or row.chosen_url.strip()
            if not url:
                QMessageBox.information(self, "Bez odkazu", "Vybrany radek nema odkaz.")
                return
            webbrowser.open_new(url)

        def run_preview(self) -> None:
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            action = self.make_preview_action(args)
            self.run_background(auto_workflow_title(self.auto_settings), action, reload_after=True)

        def run_update_selected(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            args.book_ids = sorted(selected)
            action = self.make_preview_action(args)
            self.run_background("Nacist z Calibre + " + auto_workflow_title(self.auto_settings), action, reload_after=True)

        def make_preview_action(self, args: Any) -> Callable[[], int]:
            """Sestavi preview workflow podle nastaveni automatickych auditu."""
            if self.auto_settings["auto_link_audit"] and self.auto_settings["auto_cover_audit"]:
                return shared.make_preview_with_audits_action(args, matches_path=self.matches_path)
            if self.auto_settings["auto_link_audit"]:
                return shared.make_preview_with_legie_audit_action(args, matches_path=self.matches_path)
            preview_action = lambda: cme.run_preview(args)
            if not self.auto_settings["auto_cover_audit"]:
                return preview_action
            cover_action = shared.make_cover_audit_action(args, matches_path=self.matches_path)
            return lambda: shared.run_preview_audit_then_cover_audit(
                preview_func=preview_action,
                link_audit_func=lambda: 0,
                cover_audit_func=cover_action,
            )

        def run_audit(self) -> None:
            selected = self.selected_book_ids()
            self.rows = shared.sync_single_selected_url(self.rows, selected, self.url_edit.text())
            self.refresh_table()
            if not self.save_csv(show_message=False):
                return
            args = shared.make_legie_audit_args(self.library_path, selected if selected else None)
            link_action = shared.make_legie_audit_action(args)
            if self.auto_settings["auto_cover_audit"]:
                cover_args = shared.make_cover_args(self.library_path, selected if selected else None)
                cover_action = shared.make_cover_audit_action(cover_args, matches_path=self.matches_path)
                action = lambda: shared.run_preview_audit_then_cover_audit(
                    preview_func=lambda: 0,
                    link_audit_func=link_action,
                    cover_audit_func=cover_action,
                )
            else:
                action = link_action
            self.run_background("Najit / overit odkaz", action, reload_after=True)

        def run_apply(self) -> None:
            confirmed, allow_force = self.ask_apply_confirmation()
            if not confirmed:
                return
            overwrite_ids = shared.cover_overwrite_book_ids(self.rows, self.library_path)
            skip_cover_book_ids: list[int] = []
            if overwrite_ids and not self.ask_cover_overwrite_confirmation(len(overwrite_ids)):
                skip_cover_book_ids = sorted(overwrite_ids)
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            args.skip_cover_book_ids = skip_cover_book_ids
            action = shared.make_apply_action(args=args, allow_force=allow_force, matches_path=self.matches_path)
            self.run_background("Zapis do Calibre", action, reload_after=True)

        def on_unified_import_clicked(self) -> None:
            dialog = UnifiedImportDialog(
                unified_import_start_folder(),
                self,
                dialog_state=unified_import_dialog_state(),
            )
            result = dialog.exec()
            try:
                save_unified_import_dialog_state(dialog.export_ui_state())
            except OSError as exc:
                if result == QDialog.DialogCode.Accepted:
                    QMessageBox.warning(
                        self,
                        "Unified import",
                        f"Nastavení okna se nepodařilo uložit:\n{exc}",
                    )
            if result != QDialog.DialogCode.Accepted:
                self.write_output("Unified import: zruseno.")
                return
            try:
                save_unified_import_last_folder(dialog.current_folder)
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    "Unified import",
                    f"Poslední složku se nepodařilo uložit:\n{exc}",
                )
            self._route_unified_import_files(dialog.selected_files)

        def _route_unified_import_files(self, paths: Sequence[Path]) -> None:
            files = normalize_unified_import_files(paths)
            if not files:
                return
            if len(files) == 1:
                self.write_output(f"Unified import: 1 soubor -> single import.\n{files[0]}")
                if not self.save_csv(show_message=False):
                    return
                self.start_epub_import(str(files[0]))
                return
            self.write_output(f"Unified import: {len(files)} soubory -> multiimport.")
            self.run_multiimport_analysis(files)

        def run_covers(self) -> None:
            selected = self.selected_book_ids()
            self.rows = shared.sync_single_selected_url(self.rows, selected, self.url_edit.text())
            self.refresh_table()
            include_existing_covers = bool(selected)
            if not selected:
                answer = QMessageBox.question(
                    self,
                    "Audit obalek",
                    "Zahrnout i knihy, ktere uz maji obalku?\n\n"
                    "Audit obalky pouze pripravi. Do Calibre se zapisi az pres Zapsat do Calibre.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                include_existing_covers = answer == QMessageBox.StandardButton.Yes
            if not self.save_csv(show_message=False):
                return
            args = shared.make_cover_args(
                self.library_path,
                selected if selected else None,
                include_existing_covers=include_existing_covers,
            )
            action = shared.make_cover_audit_action(args=args, matches_path=self.matches_path)
            self.run_background("Audit obalek", action, reload_after=True)

        def start_epub_import(
            self,
            path: str | None = None,
            *,
            analyze: Callable[[str], cme.ImportAnalysis] | None = None,
            runner: Callable[[Callable[[], None]], None] | None = None,
        ) -> None:
            """Spusti analyzu EPUB importu a po dokonceni otevre ImportDialog.

            `analyze` a `runner` jsou injektovatelne pro testy.
            Bez nich appka pouzije realnou backend analyzu (vcetne AI nastaveni)
            na samostatnem vlakne pres `WorkerBridge.import_ready`.
            Pred otevrenim dialogu na vyber souboru ulozi pracovni data.
            """
            interactive = path is None
            if interactive:
                if not self.save_csv(show_message=False):
                    return
                path = self._choose_epub_file()
            epub_path = path
            if not epub_path:
                return
            if self.worker_running:
                QMessageBox.information(self, "Bezi akce", "Pockej, az skonci aktualni akce.")
                return
            if analyze is None:
                analyze = self._build_import_analyze_callable()
            if runner is None:
                runner = lambda target: threading.Thread(target=target, daemon=True).start()
            self.worker_running = True
            self.set_ui_enabled(False)
            self.detail_tabs.setCurrentWidget(self.log_tab)
            self.write_output(f"Import knihy: analyza {epub_path}...")
            self.set_status("Import knihy: analyza")

            def worker() -> None:
                # Posbira logy AI extrakce/hledani z teto analyzy a ulozi je,
                # aby je finish_import_analysis ukazal v Log tabu.
                captured = io.StringIO()
                handler = logging.StreamHandler(captured)
                handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
                ai_logger = logging.getLogger("calibre_meta")
                previous_level = ai_logger.level
                ai_logger.addHandler(handler)
                ai_logger.setLevel(logging.INFO)
                try:
                    analysis = analyze(epub_path)
                    self._last_import_log = captured.getvalue().strip()
                    self.bridge.import_ready.emit(analysis, "")
                except Exception as exc:
                    self._last_import_log = captured.getvalue().strip()
                    self.bridge.import_ready.emit(None, str(exc))
                finally:
                    ai_logger.removeHandler(handler)
                    ai_logger.setLevel(previous_level)

            runner(worker)

        def _build_import_analyze_callable(self) -> Callable[[str], cme.ImportAnalysis]:
            """Slozi default analyze funkci podle aktualnich AI nastaveni."""
            library = self.library_path
            ai_settings = normalize_ai_settings(read_app_settings())
            provider = str(ai_settings.get("provider", "off"))
            resolver: object = cme.build_ai_resolver(
                provider,
                str(ai_settings.get("model", "")),
                timeout=int(ai_settings.get("timeout", 120)),
            )
            settings = {
                "epub_text_limit": ai_settings.get("text_limit", 5000),
                "ebook_meta_path": cme.find_ebook_tool("ebook-meta") or "ebook-meta",
                "ebook_convert_path": cme.find_ebook_tool("ebook-convert") or "ebook-convert",
            }
            # Resolver drzime, abychom po davce poznali, jestli AI selhavala.
            # Sam o sobe ustupuje tise a uzivatel by se to jinak nedozvedel.
            self._last_ai_resolver = resolver
            return lambda epub: run_import_analysis(epub, library, settings, ai_resolver=resolver)

        def ai_failure_reason(self) -> str:
            """Duvod, proc AI vrstva pri posledni analyze selhavala (jinak prazdny)."""
            resolver = getattr(self, "_last_ai_resolver", None)
            return str(getattr(resolver, "last_error", "") or "")

        def warn_about_ai_failure(self) -> bool:
            """Rekne uzivateli, ze AI vrstva neběžela a proč. Vraci True kdyz varovala.

            Bez tohohle se na mrtvou AI (dosly kredit, vypnuta Ollama) prijde jen
            tak, ze je detekce zahadne horsi.
            """
            reason = self.ai_failure_reason()
            if not reason:
                return False
            QMessageBox.warning(
                self,
                "AI vrstva selhala",
                "Analýza proběhla, ale AI se nepodařilo použít, takže detekce "
                "názvu a autora je méně přesná.\n\n"
                f"Důvod: {reason}\n\n"
                "Zkontrolujte poskytovatele a klíč v Preferences (u cloudu bývá "
                "na vině vyčerpaný kredit, u Ollamy vypnutý server nebo "
                "nestažený model).",
            )
            return True

        def _choose_epub_file(self) -> str:
            path, _filter = QFileDialog.getOpenFileName(
                self,
                "Vyber knihu k importu",
                "",
                book_import_file_filter(),
            )
            return path

        def choose_multiimport_files(self) -> None:
            paths, _filter = QFileDialog.getOpenFileNames(
                self,
                "Vyber knihy",
                "",
                book_import_file_filter(),
            )
            if not paths:
                return
            files = cme.collect_import_files_from_paths([Path(path) for path in paths])
            self.run_multiimport_analysis(files)

        def choose_multiimport_folder(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Vyber slozku s knihami", "")
            if not folder:
                return
            files = cme.collect_import_files_from_folder(Path(folder))
            self.run_multiimport_analysis(files)

        def _find_import_duplicates(
            self,
            preview: cme.ImportPreview,
        ) -> list[cme.DuplicateCandidate]:
            """Duplicity k nahledu v aktualni knihovne (lokalni ctení z DB)."""
            return cme.find_calibre_import_duplicates(self.library_path, preview)

        def prepare_multiimport_backup(self, enabled: bool) -> Path | None:
            """Vytvori jednu zalohu metadata.db pred celou davkou multiimportu.

            Volat pred zapisem davky. Nasledne `_write_multiimport_item` uz
            zadnou dalsi zalohu nedela - jinak by se DB kopirovala u kazde knihy.
            Kdyz je `enabled` False, nezalohuje se vubec.
            """
            self._multiimport_backup_ready = True
            self._multiimport_backup_path = (
                cme.create_backup(self.library_path, Path("backups")) if enabled else None
            )
            return self._multiimport_backup_path

        def _write_multiimport_item(
            self,
            preview: cme.ImportPreview,
            source_path: Path,
        ) -> cme.ImportApplyResult:
            calibredb_path = cme.find_calibredb()
            if not calibredb_path:
                return cme.ImportApplyResult(
                    book_id=0,
                    status="failed",
                    error="Nepodařilo se najít calibredb.",
                )
            # Kdyz uz je zaloha davky pripravena, podstrcime ji misto dalsiho
            # kopirovani. Bez pripravy zustava puvodni chovani (zaloha na knihu).
            backup_func = None
            if getattr(self, "_multiimport_backup_ready", False):
                batch_backup = self._multiimport_backup_path
                backup_func = lambda _library, _backups_dir: batch_backup or Path("")
            return cme.apply_import_preview(
                preview,
                source_path,
                library=self.library_path,
                calibredb_path=calibredb_path,
                quit_func=lambda force: shared.quit_calibre(allow_force=force),
                allow_force=True,
                matches_path=self.matches_path,
                backup_func=backup_func,
            )

        def _refresh_after_multiimport_write(
            self,
            summary: cme.MultiImportWriteSummary,
        ) -> None:
            if summary.succeeded <= 0:
                return
            self.show_import_review_filter()
            self.load_csv(show_message=False)

        def run_multiimport_analysis(
            self,
            files: Sequence[Path],
            *,
            analyze: Callable[[str], cme.ImportAnalysis] | None = None,
            connectivity_check: Callable[[], bool] | None = None,
        ) -> list[cme.MultiImportBatchItem]:
            items = cme.build_multiimport_batch_items(files)
            if items:
                online = self.is_online_now(connectivity_check)
                if not online:
                    answer = QMessageBox.question(
                        self,
                        "Bez připojení k internetu",
                        "Zdá se, že počítač není online. Online vyhledávání metadat může "
                        "selhat nebo vrátit neúplné výsledky.\n\n"
                        "Chcete v analýze pokračovat?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return items

            analyze_book = analyze or self._build_import_analyze_callable()
            progress = MultiImportProgressDialog(
                len(items),
                self,
                title="Průběh načítání",
                initial_text="Připravuji analýzu…",
                progress_prefix="Analyzuji",
            )

            def update_progress(
                current: int,
                total: int,
                item: cme.MultiImportBatchItem,
            ) -> None:
                progress.update_progress(current, total, item.display_name)
                QApplication.processEvents()

            analyzed: list[list[cme.MultiImportBatchItem]] = []
            errors: list[BaseException] = []

            def run_analysis() -> None:
                try:
                    analyzed.append(
                        cme.run_multiimport_batch_analysis(
                            items,
                            lambda path: analyze_book(str(path)),
                            precheck_safe_matches=False,
                            progress_callback=update_progress,
                            max_workers=int(
                                normalize_ai_settings(read_app_settings())["workers"]
                            ),
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    progress.accept()

            progress.run_after_first_paint(run_analysis)
            progress.show_prepared()
            progress.exec()
            if errors:
                raise errors[0]
            analyzed_items = analyzed[0] if analyzed else items
            self.warn_about_ai_failure()
            MultiImportResultsDialog(analyzed_items, parent=self).exec()
            return analyzed_items

        def finish_import_analysis(self, analysis: object, error: str) -> None:
            """Zpracuje vysledek analyzy z workeru: dialog, nebo varovani."""
            self.worker_running = False
            self.set_ui_enabled(True)
            import_log = getattr(self, "_last_import_log", "")
            log_suffix = f"\n\n{import_log}" if import_log else ""
            if analysis is None or error:
                message = error or "Analyzu se nepodarilo dokoncit."
                self.write_output(f"Import knihy: CHYBA\n{message}{log_suffix}")
                self.set_status("Import knihy: CHYBA")
                QMessageBox.warning(self, "Import knihy", message)
                return
            self.write_output(f"Import knihy: nahled pripraven{log_suffix}")
            self.set_status("Import knihy: nahled pripraven")
            if should_auto_import(analysis):
                self.write_output(f"Import knihy: 100% shoda bez duplicit, importuji automaticky{log_suffix}")
                self.set_status("Import knihy: automaticky import")
                self.run_import_apply(analysis.preview, Path(analysis.epub_path))
                return
            library = self.library_path
            dialog = ImportDialog(
                analysis,
                parent=self,
                duplicate_func=lambda preview: cme.find_calibre_import_duplicates(library, preview),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.run_import_apply(dialog.preview(), Path(analysis.epub_path))

        def run_import_apply(
            self,
            preview: cme.ImportPreview,
            epub_path: Path,
            *,
            apply_func: Callable[[cme.ImportPreview, Path], cme.ImportApplyResult] | None = None,
            runner: Callable[[Callable[[], None]], None] | None = None,
            allow_force: bool = True,
        ) -> None:
            """Spusti realny zapis EPUB importu pres backend apply_import_preview.

            Provadi se na samostatnem vlakne; vysledek se vraci pres
            `WorkerBridge.apply_ready` na UI thread. `apply_func` a `runner`
            jsou injektovatelne pro testy, aby se nesahalo na Calibre.
            """
            if not cme.is_valid_import_preview(preview):
                QMessageBox.warning(
                    self,
                    "Import knihy",
                    "Chybi nazev nebo autor; import zruseny.",
                )
                return
            if self.worker_running:
                QMessageBox.information(self, "Bezi akce", "Pockej, az skonci aktualni akce.")
                return
            if apply_func is None:
                calibredb_path = cme.find_calibredb()
                if not calibredb_path:
                    QMessageBox.warning(
                        self,
                        "Import knihy",
                        "Nepodarilo se najit calibredb. Zapis zruseny.",
                    )
                    return
                library = self.library_path
                matches_path = self.matches_path
                apply_func = lambda prev, ep: cme.apply_import_preview(
                    prev,
                    ep,
                    library=library,
                    calibredb_path=calibredb_path,
                    quit_func=lambda force: shared.quit_calibre(allow_force=force),
                    allow_force=allow_force,
                    matches_path=matches_path,
                )
            if runner is None:
                runner = lambda target: threading.Thread(target=target, daemon=True).start()

            self.worker_running = True
            self.set_ui_enabled(False)
            self.detail_tabs.setCurrentWidget(self.log_tab)
            self.write_output(f"Import knihy: zapis {epub_path}...")
            self.set_status("Import knihy: zapis")

            def worker() -> None:
                try:
                    result = apply_func(preview, epub_path)
                    self.bridge.apply_ready.emit(result, "")
                except Exception as exc:
                    self.bridge.apply_ready.emit(None, str(exc))

            runner(worker)

        def finish_import_apply(self, result: object, error: str) -> None:
            """Zpracuje vysledek apply workeru: dialog, refresh tabulky."""
            self.worker_running = False
            self.set_ui_enabled(True)
            if error or result is None:
                message = error or "Zapis se nepodaril."
                self.write_output(f"Import knihy: CHYBA\n{message}")
                self.set_status("Import knihy: CHYBA")
                QMessageBox.warning(self, "Import knihy", message)
                return
            status = getattr(result, "status", "")
            backup = getattr(result, "backup_path", "") or "bez zalohy"
            if status != "updated":
                reason = getattr(result, "error", "") or "neznama chyba"
                if reason.startswith("strong-duplicate"):
                    message = (
                        "Kniha uz v Calibre je (silna duplicita).\n"
                        "Pokud ji presto chces importovat, zaskrtni v dialogu "
                        "'Importovat i pres duplicitu' a dej Importovat znovu."
                    )
                else:
                    message = f"Zapis selhal: {reason}\nZaloha: {backup}"
                self.write_output(f"Import knihy: CHYBA\n{message}")
                self.set_status("Import knihy: CHYBA")
                QMessageBox.warning(self, "Import knihy", message)
                return
            book_id = getattr(result, "book_id", 0)
            message = f"Kniha {book_id} byla naimportovana.\nZaloha: {backup}"
            # Uspech uz je videt v logu a status baru; modalni potvrzeni je navic.
            self.write_output(f"Import knihy: OK\n{message}")
            self.set_status("Import knihy: OK")
            self.show_import_review_filter()
            self.load_csv(show_message=False)
            self._auto_fetch_cover_after_import(book_id)

        def _auto_fetch_cover_after_import(self, book_id: int) -> None:
            """Po importu automaticky stahne obalku pro novou knihu (cover audit).

            Stejny mechanismus jako tlacitko Obalky, jen cileny na nove book_id.
            Pri vice obalkach zustane kniha v review (rucni vyber), pri chybe se
            jen zaloguje a import zustane platny.
            """
            if book_id <= 0:
                return
            args = shared.make_cover_args(self.library_path, {book_id})
            action = shared.make_cover_audit_action(args=args, matches_path=self.matches_path)
            self.run_background("Import: stahuji obalku", action, reload_after=True)

        def show_import_review_filter(self) -> None:
            """Po importu ukaze nove review radky a schova skip. Approve nemeni."""
            self.auto_skip_filter_allowed = False
            for key, checked in {"review": True, "skip": False}.items():
                check = self.status_checks.get(key)
                if check is None:
                    continue
                check.blockSignals(True)
                check.setChecked(checked)
                check.blockSignals(False)

        def run_rebuild(self) -> None:
            message = (
                "Rebuild prepise pracovni data.\n"
                "Stara pracovni data ulozim do backups\\matches.\n"
                "Knihy s existujicim odkazem nebudu hledat znovu.\n"
                "Pokracovat?"
            )
            choice = QMessageBox.question(
                self,
                "Rebuild data",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            args = shared.make_script_args(self.library_path, overwrite=True)
            action = shared.make_rebuild_action(args, self.matches_path)
            self.run_background("Rebuild data", action, reload_after=True)

        def run_rollback(self) -> None:
            backup_path, _filter = QFileDialog.getOpenFileName(
                self,
                "Vyber zalohu metadata.db",
                str(shared.BACKUPS_DIR),
                "Calibre metadata zalohy (metadata*.db);;SQLite DB (*.db);;Vsechny soubory (*.*)",
            )
            if not backup_path:
                return
            confirmed, allow_force = self.ask_rollback_confirmation(Path(backup_path))
            if not confirmed:
                return
            action = shared.make_rollback_action(self.library_path, Path(backup_path), allow_force=allow_force)
            self.run_background("Rollback zalohy", action, reload_after=False)

        def ask_apply_confirmation(self) -> tuple[bool, bool]:
            box = QMessageBox(self)
            box.setWindowTitle("Zapsat do Calibre")
            box.setText(shared.apply_confirmation_message())
            force = QCheckBox("Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F")
            force.setChecked(True)
            box.setCheckBox(force)
            box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Ok)
            result = box.exec() == QMessageBox.StandardButton.Ok
            return result, force.isChecked()

        def ask_cover_overwrite_confirmation(self, count: int) -> bool:
            box = QMessageBox(self)
            box.setWindowTitle("Prepsat existujici obalky?")
            box.setText(f"Nektere vybrane knihy uz maji v Calibre obalku. Pocet: {count}")
            box.setInformativeText(
                "Pokud zvolite Ne, puvodni obalky zustanou zachovane. "
                "Ostatni zmeny se zapisi beze zmeny, pokud je to mozne."
            )
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            return box.exec() == QMessageBox.StandardButton.Yes

        def ask_cover_confirmation(self, candidates: Sequence[cme.CoverCandidate], selected_only: bool) -> tuple[bool, bool]:
            if not candidates:
                QMessageBox.information(
                    self,
                    "Obalky",
                    "Neni co doplnovat.\nBeru jen knihy bez obalky, s odkazem na Databazi knih nebo Legii a mimo status review.",
                )
                return False, False
            shown = "\n".join(f"- {candidate.book_id} {candidate.title}" for candidate in candidates[:25])
            more = "" if len(candidates) <= 25 else f"\n... a dalsich {len(candidates) - 25}"
            scope = "vybranych knih" if selected_only else "celeho seznamu"
            box = QMessageBox(self)
            box.setWindowTitle("Doplnit obalky")
            box.setText(
                f"Appka doplni obalky pro {len(candidates)} knih z {scope}.\n"
                "Pouze tam, kde Calibre hlasi, ze obalka chybi.\n"
                "Pred zapisem vytvori zalohu metadata.db.\n\n"
                f"{shown}{more}"
            )
            force = QCheckBox("Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F")
            force.setChecked(True)
            box.setCheckBox(force)
            box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Ok)
            result = box.exec() == QMessageBox.StandardButton.Ok
            return result, force.isChecked()

        def ask_rollback_confirmation(self, backup_path: Path) -> tuple[bool, bool]:
            box = QMessageBox(self)
            box.setWindowTitle("Rollback zalohy")
            box.setText(
                "Appka udela:\n"
                "1. pokusi se zavrit Calibre\n"
                "2. ulozi aktualni metadata.db jako nouzovou zalohu\n"
                "3. obnovi vybranou zalohu:\n"
                f"{backup_path}"
            )
            force = QCheckBox("Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F")
            force.setChecked(True)
            box.setCheckBox(force)
            box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            result = box.exec() == QMessageBox.StandardButton.Ok
            return result, force.isChecked()

        def run_background(self, title: str, action: Callable[[], int], reload_after: bool) -> None:
            if self.worker_running:
                QMessageBox.information(self, "Bezi akce", "Pockej, az skonci aktualni akce.")
                return
            self.worker_running = True
            self.set_ui_enabled(False)
            self.detail_tabs.setCurrentWidget(self.log_tab)
            self.write_output(f"{title}...")
            self.set_status(title)

            def worker() -> None:
                buffer = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                        result = action()
                    text = buffer.getvalue().strip()
                except Exception as exc:
                    result = 1
                    text = f"Chyba: {exc}"
                self.bridge.finished.emit(title, result, text, reload_after)

            threading.Thread(target=worker, daemon=True).start()

        def finish_background(self, title: str, result: int, text: str, reload_after: bool) -> None:
            self.worker_running = False
            self.set_ui_enabled(True)
            if reload_after and result == 0:
                self.load_csv(show_message=False)
            self.update_import_button_enabled(True)
            suffix = "OK" if result == 0 else "CHYBA"
            self.write_output(f"{title}: {suffix}\n\n{text or '(bez vystupu)'}")
            self.set_status(f"{title}: {suffix}. {shared.status_summary(self.rows)}")

        def apply_theme(self) -> None:
            """Pouzije zvoleny vzhled bez restartu appky."""
            app = QApplication.instance()
            if app is not None:
                app.setStyle(QStyleFactory.create("Fusion"))
            base = """
                * { font-family: "Segoe UI"; }
                QPushButton, QToolButton { min-height: 30px; padding: 4px 8px; border-radius: 3px; }
                /* Border-radius vyse prepne tlacitka na stylesheet vykreslovani, cimz zmizi
                   nativni ramecek. Bez vlastniho pozadi a ramu by tlacitko zdedilo pozadi
                   okna a splynulo s pozadim jako obycejny text. Barvy pro dark/light se
                   dopisuji nize; tady je varianta pro systemovy vzhled. */
                QPushButton { background: palette(button); border: 1px solid palette(mid); }
                QPushButton:hover { background: palette(light); }
                QPushButton:pressed { background: palette(dark); }
                QToolButton { font-size: 8pt; }
                QToolButton[iconOnly="true"] {
                    min-width: 42px;
                    max-width: 42px;
                    min-height: 42px;
                    max-height: 42px;
                    padding: 0;
                }
                QPushButton#approveButton, QToolButton#approveButton { background: #2e7d32; color: white; }
                QPushButton#reviewButton, QToolButton#reviewButton { background: #ef6c00; color: white; }
                QPushButton#skipButton, QPushButton#neutralButton, QToolButton#skipButton, QToolButton#neutralButton { background: #757575; color: white; }
                QPushButton#storyButton, QPushButton#updateButton, QToolButton#storyButton, QToolButton#updateButton { background: #1565c0; color: white; }
                QPushButton#applyButton, QPushButton#dangerButton, QToolButton#applyButton, QToolButton#dangerButton { background: #c62828; color: white; }
                /* Barevna tlacitka maji ID selektor, ktery prebiji obecne
                   QPushButton:hover/:pressed, takze bez techto radku by na najeti
                   mysi nereagovala (na rozdil od ostatnich tlacitek). Hover = svetlejsi
                   odstin, pressed = tmavsi (stejne jako activebackground v app.py). */
                QPushButton#approveButton:hover, QToolButton#approveButton:hover { background: #388e3c; }
                QPushButton#approveButton:pressed, QToolButton#approveButton:pressed { background: #1b5e20; }
                QPushButton#reviewButton:hover, QToolButton#reviewButton:hover { background: #f57c00; }
                QPushButton#reviewButton:pressed, QToolButton#reviewButton:pressed { background: #bf5b00; }
                QPushButton#skipButton:hover, QPushButton#neutralButton:hover, QToolButton#skipButton:hover, QToolButton#neutralButton:hover { background: #8d8d8d; }
                QPushButton#skipButton:pressed, QPushButton#neutralButton:pressed, QToolButton#skipButton:pressed, QToolButton#neutralButton:pressed { background: #616161; }
                QPushButton#storyButton:hover, QPushButton#updateButton:hover, QToolButton#storyButton:hover, QToolButton#updateButton:hover { background: #1976d2; }
                QPushButton#storyButton:pressed, QPushButton#updateButton:pressed, QToolButton#storyButton:pressed, QToolButton#updateButton:pressed { background: #0d47a1; }
                QPushButton#applyButton:hover, QPushButton#dangerButton:hover, QToolButton#applyButton:hover, QToolButton#dangerButton:hover { background: #d32f2f; }
                QPushButton#applyButton:pressed, QPushButton#dangerButton:pressed, QToolButton#applyButton:pressed, QToolButton#dangerButton:pressed { background: #8e0000; }
                QPushButton:disabled, QToolButton:disabled { background: #bdbdbd; color: #eeeeee; }
                QLineEdit, QComboBox { min-height: 28px; }
                QLineEdit::clear-button { width: 22px; height: 22px; subcontrol-position: center right; }
                QLineEdit QToolButton {
                    color: #111111;
                    font-size: 15pt;
                    font-weight: 700;
                    min-width: 22px;
                    min-height: 22px;
                    padding: 0;
                    margin: 0 3px 0 0;
                }
                QLabel#coverStatus { font-weight: 700; padding: 4px; border-radius: 3px; background: #eeeeee; color: #111111; }
                QLabel#coverImage { border: 1px solid #b8b8b8; background: #fafafa; color: #777777; }
                QTableWidget { gridline-color: palette(mid); }
                QTableWidget::item:selected, QTableWidget::item:selected:!active {
                    background: #0d6efd;
                    color: #ffffff;
                }
                QTextEdit { font-family: Consolas; font-size: 10pt; }
            """
            # Pravidla tlacitek musi v obou tematech prijit AZ za pravidlem pro QWidget.
            # Oba selektory maji stejnou vahu, takze rozhoduje poradi - kdyby QWidget
            # prislo pozdeji, prebilo by pozadi tlacitka pozadim okna.
            if self.theme == "dark":
                self.setStyleSheet(
                    base
                    + """
                    QMainWindow, QWidget { background: #202124; color: #f2f2f2; }
                    QLineEdit, QComboBox, QTextEdit { background: #2d2f33; color: #f2f2f2; border: 1px solid #4b4d52; }
                    QHeaderView::section { background: #3a3a3a; color: #ffffff; padding: 4px; }
                    QPushButton { background: #3a3d42; color: #f2f2f2; border: 1px solid #5a5d63; }
                    QPushButton:hover { background: #45484e; }
                    QPushButton:pressed { background: #2d2f33; }
                    QPushButton:disabled { background: #2a2c30; color: #6b6e73; border: 1px solid #3a3d42; }
                    """
                )
            elif self.theme == "light":
                self.setStyleSheet(
                    base
                    + """
                    QMainWindow, QWidget { background: #f5f5f5; color: #111111; }
                    QLineEdit, QComboBox, QTextEdit { background: #ffffff; color: #111111; border: 1px solid #c7c7c7; }
                    QHeaderView::section { background: #e8e8e8; color: #111111; padding: 4px; }
                    QPushButton { background: #e9e9e9; color: #111111; border: 1px solid #b8b8b8; }
                    QPushButton:hover { background: #dcdcdc; }
                    QPushButton:pressed { background: #cfcfcf; }
                    QPushButton:disabled { background: #f0f0f0; color: #909090; border: 1px solid #d5d5d5; }
                    """
                )
            else:
                # System tema jinak spadne na svetle base disabled #bdbdbd/#eeeeee,
                # kde skoro bily text splyva se svetlym pozadim (kontrast 1.62:1).
                # Dame mu stejne vypnute tlacitko jako tmave tema: tmave pozadi,
                # nevyrazny sedy text. Enabled tlacitka si dal berou barvu z palety
                # (base), takze na tmave Windows palete disabled i enabled ladi.
                self.setStyleSheet(
                    base
                    + """
                    QPushButton:disabled { background: #2a2c30; color: #6b6e73; border: 1px solid #3a3d42; }
                    """
                )

        def open_preferences(self) -> None:
            PreferencesDialog(self).exec()

        def set_ui_enabled(self, enabled: bool) -> None:
            """Pri background akci vypne ovladani, log zustava citelny."""
            self.table.setEnabled(enabled)
            self.title_filter.setEnabled(enabled)
            self.author_filter.setEnabled(enabled)
            for check in list(self.status_checks.values()) + list(self.source_checks.values()) + list(self.type_checks.values()):
                check.setEnabled(enabled)
            self.url_edit.setEnabled(enabled)
            self.detail_tabs.setTabEnabled(0, enabled)
            self.detail_tabs.setTabEnabled(1, enabled)
            self.detail_tabs.setTabEnabled(2, True)
            for button in self.buttons:
                button.setEnabled(enabled)
            for button in (self.approve_button, self.review_button, self.skip_button, self.story_button, self.use_link_button, self.open_link_button):
                button.setEnabled(enabled)
            if enabled:
                self.on_selection_changed()
            self.update_import_button_enabled(enabled)

        def update_import_button_enabled(self, ui_enabled: bool = True) -> None:
            """Import EPUB je dostupny vzdy, kdyz nebezi background akce."""
            if hasattr(self, "import_button"):
                self.import_button.setEnabled(ui_enabled and not self.worker_running)

        def write_output(self, text: str) -> None:
            self.output.setPlainText(text)

        def set_status(self, text: str) -> None:
            self.calibre_running = is_calibre_running()
            self.statusBar().showMessage(statusbar_text(text, self.calibre_running, self.csv_loaded))
            self.update_calibre_indicator()

        def refresh_calibre_indicator(self) -> None:
            """Timerem hlida, jestli se mezitim Calibre zapnulo nebo vypnulo."""
            self.calibre_running = is_calibre_running()
            self.update_calibre_indicator()

        def update_calibre_indicator(self) -> None:
            """Prekresli puntik Calibre ve statusbaru."""
            color = "#2e7d32" if self.calibre_running else "#c62828"
            label = "Calibre zapnuto" if self.calibre_running else "Calibre vypnuto"
            self.calibre_indicator.setText(f"<span style='color:{color}; font-size:16px;'>●</span> {label}")

        def update_online_indicator(self) -> None:
            """Prekresli puntik pripojeni ve statusbaru podle posledniho zjisteni."""
            color = "#2e7d32" if self.online else "#c62828"
            label = "Online" if self.online else "Offline"
            self.online_indicator.setText(
                f"<span style='color:{color}; font-size:16px;'>●</span> {label}"
            )

        def is_online_now(
            self,
            connectivity_check: Callable[[], bool] | None = None,
        ) -> bool:
            """Zjisti pripojeni, ulozi vysledek a prekresli indikator.

            Vola se jen v okamzicich, kdy na pripojeni zalezi (start, analyza,
            import), aby sonda s 1s timeoutem nezasekavala UI na timeru.
            """
            check = connectivity_check or is_probably_online
            try:
                self.online = bool(check())
            except Exception:
                self.online = False
            self.update_online_indicator()
            return self.online

    def status_color(status: str) -> QColor:
        """Vrati jemnou barvu radku podle statusu."""
        if status == "approve":
            return QColor("#e8f5e9")
        if status == "review":
            return QColor("#fff3e0")
        if status == "skip":
            return QColor("#f5f5f5")
        return QColor("#ffffff")

else:

    class CalibreMetaQtWindow:  # type: ignore[no-redef]
        """Placeholder, kdyz PySide6 jeste neni nainstalovane."""

        def __init__(self) -> None:
            raise RuntimeError("PySide6 neni nainstalovane")


def main() -> int:
    """Spusti Qt appku."""
    if not PYSIDE6_AVAILABLE:
        raise RuntimeError("PySide6 neni nainstalovane. Spust: python -m pip install PySide6")
    # Diagnostika do konzole (hlavne AI import). Spust z konzole pro videni logu.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.chdir(APP_DIR)
    app = QApplication([])
    app.setFont(QFont("Segoe UI", 9))
    window = CalibreMetaQtWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
