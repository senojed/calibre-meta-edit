# Testy hlidaji Qt app helpery bez otevirani grafickeho okna.

import csv
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

import calibre_meta_edit as cme


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ["CALIBRE_META_EDIT_TEST"] = "1"
# Bez realneho okna: rychlejsi a stabilnejsi. Musi byt drive nez se importuje Qt
# (importuje se az uvnitr testovych metod, takze tady je to vcas).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class QtHelperTests(unittest.TestCase):
    def test_qt_app_title_includes_version(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.APP_VERSION, "0.4.11")
        self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.4.11")

    def test_ai_test_result_text_variants(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.ai_test_result_text(True, "", 0.0), "AI je vypnutá")
        self.assertEqual(qt.ai_test_result_text(False, "Ollama neběží", 1.2), "Nefunguje: Ollama neběží")
        self.assertEqual(qt.ai_test_result_text(False, "", 2.34), "Funguje (~2.3 s)")

    def test_shared_writable_paths_use_app_data_dir(self):
        import calibre_meta_qt as qt
        self.assertEqual(qt.shared.SETTINGS_PATH, cme.app_data_dir() / "settings.json")
        self.assertEqual(qt.shared.BACKUPS_DIR, cme.app_data_dir() / "backups")

    def test_icon_paths_use_app_base_dir(self):
        import calibre_meta_qt as qt
        base = cme.app_base_dir()
        self.assertEqual(qt.ICON_PATH, base / "app_icon.svg")
        self.assertEqual(qt.ICON_DIR, base / "icons")
        self.assertEqual(qt.ASSETS_ICON_DIR, base / "assets" / "icons")

    def test_startup_readiness_all_ok_ollama(self):
        import calibre_meta_qt as qt
        problems = qt.startup_readiness_problems(
            calibre_ok=True, provider="ollama", ollama_reachable=True,
            model_present=True, model="llama3.1:8b", key_present=False,
        )
        self.assertEqual(problems, [])

    def test_startup_readiness_reports_missing_calibre_and_ollama(self):
        import calibre_meta_qt as qt
        problems = qt.startup_readiness_problems(
            calibre_ok=False, provider="ollama", ollama_reachable=False,
            model_present=False, model="llama3.1:8b", key_present=False,
        )
        self.assertIn("Calibre nenalezeno", problems)
        self.assertTrue(any("Ollama" in p for p in problems))

    def test_startup_readiness_reports_missing_model(self):
        import calibre_meta_qt as qt
        problems = qt.startup_readiness_problems(
            calibre_ok=True, provider="ollama", ollama_reachable=True,
            model_present=False, model="llama3.1:8b", key_present=False,
        )
        self.assertEqual(problems, ["Model llama3.1:8b není stažený (ollama pull llama3.1:8b)"])

    def test_startup_readiness_cloud_missing_key(self):
        import calibre_meta_qt as qt
        problems = qt.startup_readiness_problems(
            calibre_ok=True, provider="anthropic", ollama_reachable=False,
            model_present=False, model="", key_present=False,
        )
        self.assertEqual(problems, ["Chybí API klíč pro anthropic"])

    def test_startup_readiness_off_ignores_ai(self):
        import calibre_meta_qt as qt
        problems = qt.startup_readiness_problems(
            calibre_ok=True, provider="off", ollama_reachable=False,
            model_present=False, model="", key_present=False,
        )
        self.assertEqual(problems, [])

    def test_normalize_auto_settings_has_hide_startup_check_default_false(self):
        import calibre_meta_qt as qt
        self.assertFalse(qt.normalize_auto_settings({})["hide_startup_check"])
        self.assertTrue(qt.normalize_auto_settings({"hide_startup_check": True})["hide_startup_check"])

    def test_ollama_indicator_states(self):
        import calibre_meta_qt as qt
        self.assertEqual(qt.ollama_indicator_state("ollama", True, True)[0], "#2e7d32")
        self.assertEqual(qt.ollama_indicator_state("ollama", False, False)[0], "#c62828")
        self.assertEqual(qt.ollama_indicator_state("ollama", True, False)[0], "#c62828")
        self.assertEqual(qt.ollama_indicator_state("anthropic", True, True)[0], "#9e9e9e")

    def test_api_indicator_states(self):
        import calibre_meta_qt as qt
        self.assertEqual(qt.api_indicator_state("anthropic", True)[0], "#2e7d32")
        self.assertEqual(qt.api_indicator_state("openai", False)[0], "#c62828")
        self.assertEqual(qt.api_indicator_state("ollama", True)[0], "#9e9e9e")
        self.assertEqual(qt.api_indicator_state("off", False)[0], "#9e9e9e")

    def test_book_import_filter_lists_all_supported_formats(self):
        import calibre_meta_qt as qt

        filter_text = qt.book_import_file_filter()
        for extension, _label in cme.BOOK_IMPORT_FORMATS:
            pattern = "*" + extension
            self.assertIn(pattern, filter_text)
        self.assertIn("EPUB (*.epub)", filter_text)
        self.assertIn("Vsechny soubory (*.*)", filter_text)

    def test_unified_import_start_folder_uses_saved_existing_folder(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = qt.unified_import_start_folder(
                {qt.UNIFIED_IMPORT_LAST_FOLDER_KEY: str(folder)},
                fallback=Path.cwd(),
            )

            self.assertEqual(result, folder.absolute())

    def test_unified_import_start_folder_falls_back_when_saved_folder_is_missing(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            fallback = Path(tmp)
            result = qt.unified_import_start_folder(
                {qt.UNIFIED_IMPORT_LAST_FOLDER_KEY: str(fallback / "missing")},
                fallback=fallback,
            )

            self.assertEqual(result, fallback.absolute())

    def test_save_unified_import_last_folder_preserves_other_settings(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = root / "settings.json"
            folder = root / "books"
            folder.mkdir()
            settings_path.write_text('{"theme": "dark"}', encoding="utf-8")

            qt.save_unified_import_last_folder(folder, settings_path)

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["theme"], "dark")
            self.assertEqual(saved[qt.UNIFIED_IMPORT_LAST_FOLDER_KEY], str(folder.absolute()))

    def test_save_unified_import_dialog_state_preserves_other_settings(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text('{"theme": "dark"}', encoding="utf-8")

            qt.save_unified_import_dialog_state(
                {
                    "size": [1000, 700],
                    "splitter_sizes": [250, 750],
                    "file_column_widths": [300, 90, 120],
                    "sort_column": 2,
                    "sort_order": "desc",
                },
                settings_path,
            )

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["theme"], "dark")
            self.assertEqual(
                saved[qt.UNIFIED_IMPORT_DIALOG_STATE_KEY],
                {
                    "size": [1000, 700],
                    "splitter_sizes": [250, 750],
                    "file_column_widths": [300, 90, 120],
                    "sort_column": 2,
                    "sort_order": "desc",
                },
            )

    def test_unified_import_dialog_state_ignores_invalid_values(self):
        import calibre_meta_qt as qt

        state = qt.unified_import_dialog_state(
            {
                qt.UNIFIED_IMPORT_DIALOG_STATE_KEY: {
                    "size": [200, "bad"],
                    "splitter_sizes": [100, 200],
                    "file_column_widths": [250, 80, 110],
                    "sort_column": 9,
                    "sort_order": "sideways",
                }
            }
        )

        self.assertEqual(
            state,
            {
                "splitter_sizes": [100, 200],
                "file_column_widths": [250, 80, 110],
            },
        )

    def test_normalize_unified_import_files_filters_dedupes_and_sorts_absolute_paths(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "z.epub"
            mobi = root / "A.mobi"
            text = root / "notes.txt"
            epub.write_text("x", encoding="utf-8")
            mobi.write_text("x", encoding="utf-8")
            text.write_text("x", encoding="utf-8")

            result = qt.normalize_unified_import_files([epub, text, mobi, epub])

            self.assertEqual(result, [mobi.absolute(), epub.absolute()])

    def test_is_probably_online_uses_short_generic_socket_probe(self):
        import calibre_meta_qt as qt

        with patch.object(qt.socket, "create_connection") as create_connection:
            result = qt.is_probably_online()

        self.assertTrue(result)
        create_connection.assert_called_once_with(("1.1.1.1", 443), timeout=1.0)

    def test_is_probably_online_returns_false_for_socket_error(self):
        import calibre_meta_qt as qt

        with patch.object(qt.socket, "create_connection", side_effect=OSError("offline")):
            result = qt.is_probably_online()

        self.assertFalse(result)

    def test_multiimport_analysis_summary_counts_final_statuses(self):
        import calibre_meta_qt as qt

        items = [
            cme.MultiImportBatchItem(Path("ready.epub"), "ready.epub", status="ready"),
            cme.MultiImportBatchItem(Path("review.epub"), "review.epub", status="needs_review"),
            cme.MultiImportBatchItem(Path("duplicate.epub"), "duplicate.epub", status="duplicate_warning"),
            cme.MultiImportBatchItem(Path("error.epub"), "error.epub", status="analysis_error"),
        ]

        summary = qt.multiimport_analysis_summary(items)

        self.assertIn("Podporovane soubory: 4", summary)
        self.assertIn("Analyzovano uspesne: 3", summary)
        self.assertIn("Pripraveno: 1", summary)
        self.assertIn("Vyzaduje kontrolu: 1", summary)
        self.assertIn("Varovani na duplicitu: 1", summary)
        self.assertIn("Chyby: 1", summary)
        self.assertIn("Nic nebylo importovano.", summary)

    def test_multiimport_status_label_maps_known_statuses_and_falls_back_safely(self):
        import calibre_meta_qt as qt

        expected = {
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

        self.assertEqual({status: qt.multiimport_status_label(status) for status in expected}, expected)
        self.assertEqual(qt.multiimport_status_label("future_status"), "Neznámý stav: future_status")

    def test_multiimport_validation_reason_label_maps_known_reasons_and_falls_back(self):
        import calibre_meta_qt as qt

        expected = {
            "no_checked_items": "Není vybraná žádná položka.",
            "status_not_ready": "Položka není ve stavu Připraveno.",
            "missing_analysis": "Chybí analýza.",
            "missing_preview": "Chybí náhled importu.",
            "missing_candidate": "Chybí vybraný kandidát.",
            "duplicate_warning": "Položka má varování na duplicitu.",
            "analysis_error": "Položka má chybu analýzy.",
            "invalid_preview": "Náhled importu není validní: chybí název nebo autor.",
        }

        self.assertEqual({reason: qt.multiimport_validation_reason_label(reason) for reason in expected}, expected)
        self.assertEqual(qt.multiimport_validation_reason_label("future_reason"), "Neznámý důvod: future_reason")

    def test_multiimport_validation_summary_reports_valid_selection_without_import(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(Path("book.epub"), "book.epub")
        result = cme.MultiImportValidationResult([item], [])

        text = qt.multiimport_validation_summary_text(result)

        self.assertIn("Výběr je validní", text)
        self.assertIn("Položek připravených k budoucímu importu: 1", text)
        self.assertIn("Nic nebylo importováno.", text)

    def test_multiimport_validation_summary_reports_no_checked_items(self):
        import calibre_meta_qt as qt

        result = cme.MultiImportValidationResult(
            [],
            [cme.MultiImportValidationIssue(None, "no_checked_items")],
        )

        text = qt.multiimport_validation_summary_text(result)

        self.assertIn("Není vybraná žádná položka.", text)
        self.assertIn("Nic nebylo importováno.", text)

    def test_multiimport_validation_summary_identifies_blocked_item(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(Path("book.epub"), "book.epub")
        result = cme.MultiImportValidationResult(
            [],
            [cme.MultiImportValidationIssue(item, "status_not_ready")],
        )

        text = qt.multiimport_validation_summary_text(result)

        self.assertIn("Blokující problémy: 1", text)
        self.assertIn("book.epub: Položka není ve stavu Připraveno.", text)

    def test_multiimport_item_row_text_includes_state_duplicates_and_error(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(
            Path("book.epub"),
            "book.epub",
            checked_for_import=True,
            status="analysis_error",
            error_message="network failed",
            duplicates=[cme.DuplicateCandidate(7, "Kniha", "Autor")],
        )

        text = qt.multiimport_item_row_text(item)

        self.assertIn("book.epub", text)
        self.assertIn("Chyba analýzy", text)
        self.assertNotIn("analysis_error", text)
        self.assertIn("Predvybrano: ano", text)
        self.assertIn("Duplicity: 1", text)
        self.assertIn("network failed", text)

    def test_multiimport_item_detail_text_includes_preview_candidate_and_duplicates(self):
        import calibre_meta_qt as qt

        candidate = cme.ImportCandidate("databazeknih", "Kandidat", "Autor K.", "https://dk/1", score=95)
        duplicate = cme.DuplicateCandidate(7, "Existujici", "Autor E.", score=90)
        item = cme.MultiImportBatchItem(
            Path("book.epub"),
            "book.epub",
            status="duplicate_warning",
            current_preview=cme.ImportPreview(
                title="Nahled",
                authors="Autor N.",
                source="databazeknih",
                url="https://dk/1",
            ),
            selected_candidate=candidate,
            duplicates=[duplicate],
        )

        text = qt.multiimport_item_detail_text(item)

        self.assertNotIn("Soubor:", text)
        self.assertIn("Nazev: Nahled", text)
        self.assertIn("Autori: Autor N.", text)
        self.assertIn("Zdroj: databazeknih", text)
        self.assertIn("Odkaz: https://dk/1", text)
        self.assertIn("Stav: Možná duplicita", text)
        self.assertNotIn("duplicate_warning", text)
        self.assertIn("Kandidat / Autor K. / 95%", text)
        self.assertIn("Existujici / Autor E.", text)

    def test_multiimport_item_detail_text_explains_multiple_100_percent_candidates(self):
        import calibre_meta_qt as qt

        first = cme.ImportCandidate("databazeknih", "Kniha", "Autor", "https://dk/1", score=100)
        second = cme.ImportCandidate("databazeknih", "Kniha", "Autor", "https://dk/2", score=100)
        preview = cme.ImportPreview(title="Kniha", authors="Autor", url=first.url)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[first, second],
            recommended=first,
            duplicates=[],
            preview=preview,
            messages=[],
        )
        item = cme.MultiImportBatchItem(
            Path("book.epub"),
            "book.epub",
            checked_for_import=True,
            status="needs_review",
            analysis=analysis,
            current_preview=preview,
            selected_candidate=first,
        )

        text = qt.multiimport_item_detail_text(item)

        self.assertIn("Důvod kontroly:", text)
        self.assertIn("více různých kandidátů se 100% shodou", text)
        self.assertIn("https://dk/1", text)
        self.assertIn("https://dk/2", text)
        self.assertIn("Automatický import je zablokován", text)
        self.assertIn("jednopoložkový ruční postup", text)
        validation = cme.validate_multiimport_checked_items([item])
        self.assertEqual(validation.issues[0].reason, "multiple_100_candidate_urls")

    def test_multiimport_compact_status_labels_are_visually_distinct(self):
        import calibre_meta_qt as qt

        self.assertEqual(
            {
                status: qt.multiimport_compact_status_label(status)
                for status in (
                    "ready",
                    "needs_review",
                    "duplicate_warning",
                    "analysis_error",
                    "writing",
                    "written",
                    "write_error",
                )
            },
            {
                "ready": "✓",
                "needs_review": "👁",
                "duplicate_warning": "⧉",
                "analysis_error": "✕",
                "writing": "↻",
                "written": "✓",
                "write_error": "✕",
            },
        )

    def test_multiimport_row_status_symbol_marks_manual_confirm(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(Path("a.epub"), "a.epub", status="needs_review")
        self.assertEqual(qt.multiimport_row_status_symbol(item), "👁")
        item.manually_confirmed = True
        self.assertEqual(qt.multiimport_row_status_symbol(item), "W")
        self.assertEqual(qt.multiimport_row_status_tooltip(item), "Ručně potvrzeno k importu")
        item.status = "written"
        self.assertEqual(qt.multiimport_row_status_symbol(item), "✓")

    def test_multiimport_item_matches_filter_by_name(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(Path("Verne.epub"), "Verne, Jules.epub", status="ready")
        self.assertTrue(qt.multiimport_item_matches_filter(item, name_query="verne"))
        self.assertFalse(qt.multiimport_item_matches_filter(item, name_query="hugo"))

    def test_multiimport_item_matches_filter_by_status_and_checked(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(
            Path("a.epub"), "a.epub", status="needs_review", checked_for_import=True
        )
        self.assertTrue(qt.multiimport_item_matches_filter(item, statuses={"needs_review"}))
        self.assertTrue(
            qt.multiimport_item_matches_filter(item, statuses={"needs_review", "ready"})
        )
        self.assertFalse(qt.multiimport_item_matches_filter(item, statuses={"ready"}))
        self.assertTrue(qt.multiimport_item_matches_filter(item, checked=True))
        self.assertFalse(qt.multiimport_item_matches_filter(item, checked=False))

    def test_detail_text_hides_stale_precheck_after_manual_confirm(self):
        import calibre_meta_qt as qt

        analysis = cme.ImportAnalysis(
            epub_path="book.pdb",
            signals=[],
            candidates=[],
            recommended=None,  # automat kandidata nenasel
            duplicates=[],
            preview=cme.ImportPreview(title="Kniha", authors=""),
            messages=[],
        )
        item = cme.MultiImportBatchItem(
            Path("book.pdb"),
            "book.pdb",
            status="needs_review",
            analysis=analysis,
            current_preview=cme.ImportPreview(title="Kniha", authors="Autor"),
        )

        self.assertIn("Chybí vybraný kandidát", qt.multiimport_item_detail_text(item))

        # Uzivatel si kandidata vybral rucne -> puvodni duvod uz neplati.
        item.manually_confirmed = True

        text = qt.multiimport_item_detail_text(item)
        self.assertNotIn("Chybí vybraný kandidát", text)
        self.assertNotIn("Důvod kontroly", text)

    def test_multiimport_write_error_label_translates_known_codes(self):
        import calibre_meta_qt as qt

        self.assertIn("už v Calibre je", qt.multiimport_write_error_label("strong-duplicate"))
        # Neznamy kod projde beze zmeny, at se neztrati informace.
        self.assertEqual(qt.multiimport_write_error_label("calibredb crashed"), "calibredb crashed")

    def test_multiimport_write_failures_text_lists_failed_books_with_reason(self):
        import calibre_meta_qt as qt

        failed = cme.MultiImportBatchItem(
            Path("bad.epub"),
            "bad.epub",
            status="write_error",
            write_result=cme.ImportApplyResult(0, "failed", "strong-duplicate"),
        )
        written = cme.MultiImportBatchItem(
            Path("good.epub"),
            "good.epub",
            status="written",
            write_result=cme.ImportApplyResult(7, "updated"),
        )

        text = qt.multiimport_write_failures_text([written, failed])

        self.assertIn("bad.epub", text)
        self.assertIn("už v Calibre je", text)
        self.assertNotIn("good.epub", text)

    def test_multiimport_write_failures_text_empty_when_all_written(self):
        import calibre_meta_qt as qt

        written = cme.MultiImportBatchItem(
            Path("good.epub"),
            "good.epub",
            status="written",
            write_result=cme.ImportApplyResult(7, "updated"),
        )

        self.assertEqual(qt.multiimport_write_failures_text([written]), "")

    def test_multiimport_item_detail_text_shows_write_failure_reason(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(
            Path("bad.epub"),
            "bad.epub",
            status="write_error",
            current_preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            write_result=cme.ImportApplyResult(0, "failed", "strong-duplicate"),
        )

        text = qt.multiimport_item_detail_text(item)

        self.assertIn("Import selhal:", text)
        self.assertIn("už v Calibre je", text)

    def test_multiimport_status_tooltips_preserve_semantic_labels(self):
        import calibre_meta_qt as qt

        self.assertEqual(
            {
                status: qt.multiimport_status_tooltip(status)
                for status in (
                    "ready",
                    "needs_review",
                    "duplicate_warning",
                    "analysis_error",
                    "writing",
                    "written",
                    "write_error",
                )
            },
            {
                "ready": "OK",
                "needs_review": "Kontrola",
                "duplicate_warning": "Duplicita",
                "analysis_error": "Chyba",
                "writing": "Zápis",
                "written": "Hotovo",
                "write_error": "Chyba zápisu",
            },
        )

    def test_multiimport_export_rows_preserve_order_and_include_analysis_data(self):
        import calibre_meta_qt as qt

        candidate = cme.ImportCandidate("databazeknih", "Kandidat", "Autor K.", "https://dk/1", score=95)
        items = [
            cme.MultiImportBatchItem(
                Path("first.epub"),
                "first.epub",
                checked_for_import=True,
                status="ready",
                current_preview=cme.ImportPreview(
                    title="Příběh",
                    authors="Autor",
                    source="databazeknih",
                    url="https://dk/1",
                ),
                selected_candidate=candidate,
                duplicates=[cme.DuplicateCandidate(7, "Duplicitni", "Autor D.")],
            ),
            cme.MultiImportBatchItem(
                Path("second.mobi"),
                "second.mobi",
                status="analysis_error",
                error_message="network failed",
            ),
        ]

        rows = qt.multiimport_export_rows(items)

        self.assertEqual([row["file"] for row in rows], ["first.epub", "second.mobi"])
        self.assertEqual(rows[0]["checked_for_import"], "true")
        self.assertEqual(rows[0]["status"], "ready")
        self.assertEqual(rows[0]["status_label"], "Připraveno")
        self.assertEqual(rows[0]["preview_title"], "Příběh")
        self.assertEqual(rows[0]["recommended_title"], "Kandidat")
        self.assertEqual(rows[0]["recommended_score"], "95")
        self.assertEqual(rows[0]["duplicate_count"], "1")
        self.assertEqual(rows[1]["error_message"], "network failed")

    def test_write_multiimport_csv_report_writes_utf8_header_and_rows(self):
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(
            Path("book.epub"),
            "book.epub",
            status="ready",
            current_preview=cme.ImportPreview(title="Příběh", authors="Autor"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.csv"

            qt.write_multiimport_csv_report(path, [item])

            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(reader.fieldnames, list(qt.MULTIIMPORT_EXPORT_COLUMNS))
        self.assertEqual(rows[0]["preview_title"], "Příběh")

    def test_filter_rows_supports_title_author_status_source_type_sets(self):
        import calibre_meta_qt as qt

        rows = [
            cme.MatchRow(1, "Kat", "Martin Moudry", "approve", "https://x", "a", "b", "c", "databazeknih", ""),
            cme.MatchRow(2, "Samuela", "Anatolij Dneprov", "skip", "https://y", "a", "b", "c", "legie", "povidka"),
            cme.MatchRow(3, "Vinen", "Jim Butcher", "review", "https://z", "a", "b", "c", "databazeknih", ""),
        ]

        result = qt.filter_rows(
            rows,
            title="",
            author="",
            statuses={"approve", "review"},
            sources={"databazeknih"},
            work_types={""},
        )

        self.assertEqual([row.book_id for row in result], [1, 3])

    def test_filter_rows_can_show_only_empty_work_type(self):
        import calibre_meta_qt as qt

        rows = [
            cme.MatchRow(1, "Kat", "Martin Moudry", "approve", "https://x", "a", "b", "c", "databazeknih", ""),
            cme.MatchRow(2, "Samuela", "Anatolij Dneprov", "skip", "https://y", "a", "b", "c", "legie", "povidka"),
        ]

        result = qt.filter_rows(rows, work_types={""})

        self.assertEqual([row.book_id for row in result], [1])

    def test_statusbar_text_contains_ready_calibre_csv_and_version(self):
        import calibre_meta_qt as qt

        text = qt.statusbar_text("Ready", calibre_running=False, csv_loaded=True)

        self.assertEqual(text, "Ready | pracovni data nactena | 0.4.11")

    def test_default_filter_checked_hides_skip_after_start(self):
        import calibre_meta_qt as qt

        self.assertTrue(qt.default_filter_checked(qt.STATUS_FILTER_VALUES, "approve"))
        self.assertTrue(qt.default_filter_checked(qt.STATUS_FILTER_VALUES, "review"))
        self.assertFalse(qt.default_filter_checked(qt.STATUS_FILTER_VALUES, "skip"))
        self.assertTrue(qt.default_filter_checked(qt.SOURCE_FILTER_VALUES, "databazeknih"))

    def test_should_enable_skip_filter_only_for_empty_pending_view(self):
        import calibre_meta_qt as qt

        rows = [cme.MatchRow(1, "Hotovo", "Autor", "skip", "", "", "none", "x")]

        self.assertTrue(
            qt.should_enable_skip_filter(rows, [], "", "", {"approve", "review"}, None, None)
        )
        self.assertFalse(
            qt.should_enable_skip_filter(rows, rows, "", "", {"approve", "review"}, None, None)
        )
        self.assertFalse(
            qt.should_enable_skip_filter(rows, [], "kat", "", {"approve", "review"}, None, None)
        )
        self.assertFalse(qt.should_enable_skip_filter(rows, [], "", "", None, None, None))

    def test_normalize_auto_settings_defaults_to_enabled(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_auto_settings({})

        self.assertEqual(
            settings,
            {
                "startup_preview": True,
                "auto_link_audit": True,
                "auto_cover_audit": True,
                "hide_startup_check": False,
            },
        )

    def test_normalize_auto_settings_reads_saved_booleans(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_auto_settings(
            {
                "startup_preview": False,
                "auto_link_audit": True,
                "auto_cover_audit": False,
            }
        )

        self.assertEqual(settings["startup_preview"], False)
        self.assertEqual(settings["auto_link_audit"], True)
        self.assertEqual(settings["auto_cover_audit"], False)

    def test_normalize_ai_settings_defaults_workers_to_five(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.normalize_ai_settings({})["workers"], 5)

    def test_normalize_ai_settings_clamps_workers_to_range(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.normalize_ai_settings({"ai": {"workers": 3}})["workers"], 3)
        # Mimo rozsah srovnat: chranime databazeknih i slaby stroj.
        self.assertEqual(qt.normalize_ai_settings({"ai": {"workers": 99}})["workers"], 8)
        self.assertEqual(qt.normalize_ai_settings({"ai": {"workers": 0}})["workers"], 1)
        self.assertEqual(qt.normalize_ai_settings({"ai": {"workers": "blbost"}})["workers"], 5)

    def test_normalize_ai_settings_defaults_to_off(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({})

        self.assertEqual(
            settings,
            {
                "provider": "off",
                "model": "llama3.1:8b",
                "text_limit": 5000,
                "timeout": 120,
                "workers": 5,
            },
        )

    def test_normalize_ai_settings_reads_saved_values(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({"ai": {"provider": "ollama", "model": "mistral", "text_limit": 2000}})

        self.assertEqual(settings["provider"], "ollama")
        self.assertEqual(settings["model"], "mistral")
        self.assertEqual(settings["text_limit"], 2000)

    def test_normalize_ai_settings_accepts_cloud_providers(self):
        import calibre_meta_qt as qt

        self.assertIn("anthropic", qt.AI_PROVIDER_VALUES)
        self.assertIn("openai", qt.AI_PROVIDER_VALUES)

    def test_normalize_ai_settings_anthropic_default_model(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({"ai": {"provider": "anthropic", "model": ""}})
        self.assertEqual(settings["provider"], "anthropic")
        self.assertEqual(settings["model"], "claude-sonnet-4-6")

    def test_normalize_ai_settings_openai_default_model(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({"ai": {"provider": "openai", "model": ""}})
        self.assertEqual(settings["model"], "gpt-4o")

    def test_normalize_ai_settings_keeps_custom_cloud_model(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({"ai": {"provider": "anthropic", "model": "claude-opus-4-8"}})
        self.assertEqual(settings["model"], "claude-opus-4-8")

    def test_auto_workflow_title_reflects_enabled_steps(self):
        import calibre_meta_qt as qt

        self.assertEqual(
            qt.auto_workflow_title({"auto_link_audit": True, "auto_cover_audit": True}),
            "Nacitani novych knih + Audit odkazu + Audit obalek",
        )
        self.assertEqual(
            qt.auto_workflow_title({"auto_link_audit": False, "auto_cover_audit": True}),
            "Nacitani novych knih + Audit obalek",
        )
        self.assertEqual(
            qt.auto_workflow_title({"auto_link_audit": False, "auto_cover_audit": False}),
            "Nacitani novych knih",
        )

    def test_normalize_theme_accepts_only_known_values(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.normalize_theme("dark"), "dark")
        self.assertEqual(qt.normalize_theme("LIGHT"), "light")
        self.assertEqual(qt.normalize_theme("bad"), "system")

    def test_save_app_settings_preserves_column_settings(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"columns": {"Status": {"visible": False, "width": 88}}}),
                encoding="utf-8",
            )

            qt.save_app_settings("B:\\", "dark", settings_path)

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(data["library_path"], "B:\\")
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["columns"]["Status"], {"visible": False, "width": 88})

    def test_normalize_column_settings_ignores_unknown_and_broken_values(self):
        import calibre_meta_qt as qt

        result = qt.normalize_column_settings(
            {
                "Status": {"visible": False, "width": 92},
                "Odkaz": {"visible": "yes", "width": 4},
                "Nesmysl": {"visible": True, "width": 100},
            }
        )

        self.assertEqual(result, {"Status": {"visible": False, "width": 92}})

    def test_selection_summary_handles_multiple_rows(self):
        import calibre_meta_qt as qt

        rows = [
            cme.MatchRow(1, "Kat", "Martin Moudry", "approve", "https://x", "a", "b", "c", "databazeknih", ""),
            cme.MatchRow(2, "Samuela", "Anatolij Dneprov", "skip", "https://y", "a", "b", "c", "legie", "povidka"),
        ]

        self.assertEqual(qt.selection_title(rows), "Vybrano 2 polozek")
        self.assertEqual(qt.selection_link_text(rows), "Ruzne adresy")
        self.assertFalse(qt.selection_link_actions_enabled(rows))
        self.assertFalse(qt.use_link_enabled(rows, "Ruzne adresy"))
        self.assertTrue(qt.use_link_enabled(rows, ""))

    def test_selection_link_actions_enabled_for_same_url(self):
        import calibre_meta_qt as qt

        rows = [
            cme.MatchRow(1, "Kat", "Martin Moudry", "approve", "https://x", "a", "b", "c", "databazeknih", ""),
            cme.MatchRow(2, "Kat 2", "Martin Moudry", "review", "https://x", "a", "b", "c", "databazeknih", ""),
        ]

        self.assertEqual(qt.selection_link_text(rows), "https://x")
        self.assertTrue(qt.selection_link_actions_enabled(rows))
        self.assertTrue(qt.open_link_enabled(rows, "https://x"))

    def test_current_data_fields_reads_calibre_metadata_slots(self):
        import calibre_meta_qt as qt

        row = cme.MatchRow(
            1,
            "Straze! Straze!",
            "Terry Pratchett",
            "review",
            "https://www.databazeknih.cz/knihy/straze-straze-459",
            "",
            "title-only",
            "title-only",
            "databazeknih",
            "",
            cover_urls="https://img/1.jpg|https://img/2.jpg",
        )

        metadata = cme.CurrentBookMetadata("1987", "Ikar", ["Fantasy", "Humor"], "<p>Komentar</p>")
        fields = dict(qt.current_data_fields([row], metadata))

        self.assertEqual(fields["Kniha"], "Straze! Straze!")
        self.assertNotIn("Odkaz", fields)
        self.assertEqual(fields["Rok vydani"], "1987")
        self.assertNotIn("Hodnoceni", fields)
        self.assertNotIn("Vydani", fields)
        self.assertEqual(fields["Vydavatel"], "Ikar")
        self.assertEqual(fields["Tagy"], "Fantasy, Humor")
        self.assertEqual(fields["Obalka"], "nenacteno")

    def test_review_data_fields_show_planned_web_metadata(self):
        import calibre_meta_qt as qt

        row = cme.MatchRow(
            1,
            "Pohyblive obrazky",
            "Terry Pratchett",
            "review",
            "https://www.databazeknih.cz/knihy/pohyblive-obrazky-461",
            "",
            "exact-title-author",
            "exact-title-author",
            "databazeknih",
            "",
        )
        detail = cme.BookDetailMetadata(
            published_year="1996",
            publisher="Talpress",
            series="Úžasná Zeměplocha",
            series_index="21",
            tags=["Fantasy", "Humor"],
            rating_percent="87 %",
            original_title="Moving Pictures",
            original_publication="1990",
            original_publisher="Gollancz",
        )

        fields = dict(qt.review_data_fields([row], "https://www.databazeknih.cz/prehled-knihy/pohyblive-obrazky-461", detail))

        self.assertNotIn("Zapisovany odkaz", fields)
        self.assertNotIn("Chyba", fields)
        self.assertEqual(fields["Rok vydani"], "1996")
        self.assertEqual(fields["Vydavatel"], "Talpress")
        self.assertEqual(fields["Serie"], "Úžasná Zeměplocha")
        self.assertEqual(fields["Cislo serie"], "21")
        self.assertEqual(fields["Tagy"], "Fantasy, Humor")
        self.assertEqual(fields["Hodnoceni"], "87 %")
        self.assertEqual(fields["Originalni nazev"], "Moving Pictures")
        self.assertEqual(fields["Originalne vyslo"], "1990")
        self.assertNotIn("Originalni vydavatel", fields)
        self.assertNotIn("Serie", qt.REVIEW_EDITABLE_FIELDS)
        self.assertNotIn("Cislo serie", qt.REVIEW_EDITABLE_FIELDS)

    def test_review_data_fields_apply_row_overrides(self):
        import calibre_meta_qt as qt

        row = cme.MatchRow(
            1,
            "Pohyblive obrazky",
            "Terry Pratchett",
            "review",
            "https://www.databazeknih.cz/knihy/pohyblive-obrazky-461",
            "",
            "exact-title-author",
            "exact-title-author",
            "databazeknih",
            "",
            review_published_year="1999",
            review_publisher="Rucne",
        )
        detail = cme.BookDetailMetadata(published_year="1996", publisher="Talpress")

        fields = dict(qt.review_data_fields([row], "", detail))

        self.assertEqual(fields["Rok vydani"], "1999")
        self.assertEqual(fields["Vydavatel"], "Rucne")
        self.assertEqual(fields["Serie"], "nenacteno")
        self.assertEqual(fields["Cislo serie"], "nenacteno")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class QtImportTests(unittest.TestCase):

    def test_multiimport_progress_dialog_has_visible_content_and_updates(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        progress = qt.MultiImportProgressDialog(3)

        self.assertEqual(progress.progress_label.text(), "Připravuji import…")
        self.assertEqual((progress.progress_bar.minimum(), progress.progress_bar.maximum()), (0, 3))
        self.assertEqual(progress.progress_bar.value(), 0)
        progress.show_prepared()
        self.assertTrue(progress.isVisible())
        self.assertTrue(progress.progress_label.isVisible())
        self.assertTrue(progress.progress_bar.isVisible())

        progress.update_progress(2, 3, "book.epub")

        self.assertIn("2/3", progress.progress_label.text())
        self.assertIn("book.epub", progress.progress_label.text())
        self.assertEqual(progress.progress_bar.value(), 2)
        progress.close()
        app.processEvents()

    def _valid_multiimport_item(
        self,
        name: str = "book.epub",
        *,
        checked: bool = False,
    ) -> cme.MultiImportBatchItem:
        candidate = cme.ImportCandidate(
            "databazeknih", "Kniha", "Autor", f"https://example.test/{name}", score=100
        )
        preview = cme.ImportPreview(
            title="Kniha",
            authors="Autor",
            url=candidate.url,
        )
        analysis = cme.ImportAnalysis(
            epub_path=name,
            signals=[],
            candidates=[candidate],
            recommended=candidate,
            duplicates=[],
            preview=preview,
            messages=[],
        )
        return cme.MultiImportBatchItem(
            Path(name),
            name,
            checked_for_import=checked,
            status="ready",
            analysis=analysis,
            current_preview=preview,
            selected_candidate=candidate,
        )

    def _needs_review_multiimport_item(
        self,
        name: str = "review.epub",
    ) -> cme.MultiImportBatchItem:
        recommended = cme.ImportCandidate(
            "databazeknih", "Kniha", "Autor", f"https://dk/{name}/rec", score=60
        )
        alternate = cme.ImportCandidate(
            "databazeknih", "Kniha jina", "Autor", f"https://dk/{name}/alt", score=55
        )
        preview = cme.ImportPreview(title="Kniha", authors="Autor", url=recommended.url)
        analysis = cme.ImportAnalysis(
            epub_path=name,
            signals=[],
            candidates=[recommended, alternate],
            recommended=recommended,
            duplicates=[],
            preview=preview,
            messages=[],
        )
        return cme.MultiImportBatchItem(
            Path(name),
            name,
            checked_for_import=False,
            status="needs_review",
            analysis=analysis,
            current_preview=preview,
            selected_candidate=recommended,
        )

    def _run_import_click(self, dialog, qt):
        from PySide6.QtWidgets import QMessageBox

        with (
            patch.object(
                qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ),
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt.QMessageBox, "warning") as warning,
            patch.object(qt, "MultiImportProgressDialog") as progress_class,
            patch.object(qt.QApplication, "processEvents"),
        ):
            progress_class.return_value.run_after_first_paint.side_effect = (
                lambda callback: callback()
            )
            dialog.import_button.click()
        return warning

    def _offline_dialog(self, qt, events, *, online: bool):
        # Dve polozky = davkovy rezim, takze import_button jde na import_checked_items
        # (kde je offline kontrola), ne na single-accept.
        items = [
            self._valid_multiimport_item("a.epub", checked=True),
            self._valid_multiimport_item("b.epub", checked=True),
        ]
        return qt.ImportReviewDialog(
            items,
            write_one=lambda _preview, _path: (
                events.append("write") or cme.ImportApplyResult(1, "updated")
            ),
            connectivity_check=lambda: online,
        )

    def test_multiimport_offline_warning_cancel_blocks_write(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        events = []
        dialog = self._offline_dialog(qt, events, online=False)

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                side_effect=[
                    QMessageBox.StandardButton.Yes,  # potvrzeni importu
                    QMessageBox.StandardButton.No,  # offline varovani -> zrusit
                ],
            ) as question,
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt, "MultiImportProgressDialog"),
            patch.object(qt.QApplication, "processEvents"),
        ):
            dialog.import_button.click()

        self.assertEqual(events, [])
        self.assertEqual(question.call_count, 2)
        self.assertIn("není online", question.call_args.args[2])
        app.processEvents()

    def test_multiimport_offline_warning_confirm_proceeds_with_write(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        events = []
        dialog = self._offline_dialog(qt, events, online=False)

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                side_effect=[
                    QMessageBox.StandardButton.Yes,
                    QMessageBox.StandardButton.Yes,
                ],
            ),
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt, "MultiImportProgressDialog") as progress_class,
            patch.object(qt.QApplication, "processEvents"),
        ):
            progress_class.return_value.run_after_first_paint.side_effect = (
                lambda callback: callback()
            )
            dialog.import_button.click()

        self.assertIn("write", events)
        app.processEvents()

    def test_multiimport_online_skips_offline_warning(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        events = []
        dialog = self._offline_dialog(qt, events, online=True)

        with (
            patch.object(
                qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ) as question,
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt, "MultiImportProgressDialog") as progress_class,
            patch.object(qt.QApplication, "processEvents"),
        ):
            progress_class.return_value.run_after_first_paint.side_effect = (
                lambda callback: callback()
            )
            dialog.import_button.click()

        # Jen potvrzeni importu, zadne offline varovani navic.
        self.assertEqual(question.call_count, 1)
        self.assertIn("write", events)
        app.processEvents()

    def test_ollama_indicator_green_when_ollama_ready(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "ollama", "model": "llama3.1:8b"}}):
            with patch.object(qt.cme, "ollama_status", return_value=cme.OllamaStatus(True, True)) as probe:
                window = qt.CalibreMetaQtWindow()
                window.refresh_ai_indicators()
        probe.assert_called()
        self.assertIn("#2e7d32", window.ollama_indicator.text())
        app.processEvents()

    def test_ollama_indicator_not_probed_for_cloud(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "anthropic", "model": ""}}):
            with patch.object(qt.cme, "ollama_status") as probe:
                window = qt.CalibreMetaQtWindow()
                window.refresh_ai_indicators()
        probe.assert_not_called()
        self.assertIn("#9e9e9e", window.ollama_indicator.text())
        app.processEvents()

    def test_api_indicator_reflects_key_presence(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "anthropic", "model": ""}}):
            with patch.object(qt.cme, "read_api_key", return_value="k"):
                window = qt.CalibreMetaQtWindow()
                window.refresh_ai_indicators()
        self.assertIn("#2e7d32", window.api_indicator.text())
        self.assertIn("API", window.api_indicator.text())
        app.processEvents()

    def test_run_startup_check_shows_dialog_when_problems(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        shown = {}

        class FakeDialog:
            def __init__(self, problems, parent=None):
                shown["problems"] = problems

            def exec(self):
                shown["exec"] = True
                return 0

            def dont_show_again(self):
                return False

        with (
            patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "ollama", "model": "llama3.1:8b"}}),
            patch.object(qt.cme, "find_calibredb", return_value=""),
            patch.object(qt.cme, "ollama_status", return_value=cme.OllamaStatus(False, False)),
            patch.object(qt, "StartupCheckDialog", FakeDialog),
        ):
            window = qt.CalibreMetaQtWindow()
            window.run_startup_check()
        self.assertTrue(shown.get("exec"))
        self.assertTrue(any("Calibre" in p for p in shown["problems"]))
        app.processEvents()

    def test_run_startup_check_silent_when_ok(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with (
            patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "off", "model": ""}}),
            patch.object(qt.cme, "find_calibredb", return_value="C:/calibredb.exe"),
            patch.object(qt, "StartupCheckDialog") as dialog_class,
        ):
            window = qt.CalibreMetaQtWindow()
            window.run_startup_check()
        dialog_class.assert_not_called()
        app.processEvents()

    def test_run_startup_check_respects_hidden_flag(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with (
            patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "off", "model": ""}, "hide_startup_check": True}),
            patch.object(qt.cme, "find_calibredb", return_value=""),
            patch.object(qt, "StartupCheckDialog") as dialog_class,
        ):
            window = qt.CalibreMetaQtWindow()
            window.run_startup_check()
        dialog_class.assert_not_called()
        app.processEvents()

    def test_qt_imports_when_pyside6_available(self):
        import calibre_meta_qt as qt

        self.assertIsNotNone(qt.CalibreMetaQtWindow)

    def test_table_item_style_does_not_override_explicit_main_table_foreground(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.theme = "dark"
        window.apply_theme()

        style = window.styleSheet()
        self.assertNotIn("QTableWidget::item { color:", style)
        self.assertNotIn("color: palette(text)", style)
        self.assertNotIn("QTableWidget::item { color: #111111; }", style)
        app.processEvents()

    def test_disabled_button_background_per_theme(self):
        """Vypnuta tlacitka drive spadla na svetle base disabled (#bdbdbd/#eeeeee),
        kde skoro bily text splyval s pozadim (1.62:1). System i light maji mit
        vlastni citelny disabled: system tmavy jako dark tema, light svetlejsi nez
        zapnute (ustupuje do svetleho okna)."""
        from PySide6.QtWidgets import QApplication, QPushButton
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        cases = {
            "system": (42, 44, 48),    # #2a2c30, jako tmave tema
            "light": (240, 240, 240),  # #f0f0f0, svetlejsi nez enabled #e9e9e9
            "dark": (42, 44, 48),      # #2a2c30
        }
        for theme, expected in cases.items():
            window.theme = theme
            window.apply_theme()
            button = QPushButton("x")
            button.setEnabled(False)
            button.setStyleSheet(window.styleSheet())
            button.resize(120, 30)
            pixel = button.grab().toImage().pixelColor(60, 4)
            self.assertEqual(
                (pixel.red(), pixel.green(), pixel.blue()),
                expected,
                f"tema {theme}: nespravne pozadi vypnuteho tlacitka",
            )
        app.processEvents()

    def test_preferences_neutral_buttons_follow_theme_not_grey(self):
        """Zmenit/Ulozit/Zavrit/Pouzit z Calibre drive mely natvrdo sedou
        neutralButton, ktera v light teme vypadala jako tmave tlacitko z jineho
        tematu. Maji brat obecny styl (svetla v light). Cervena danger zustava."""
        from PySide6.QtWidgets import QApplication, QPushButton
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.theme = "light"
        window.apply_theme()
        dialog = qt.PreferencesDialog(window)

        by_text = {b.text(): b for b in dialog.findChildren(QPushButton)}
        for label in ("Zmenit", "Pouzit z Calibre", "Ulozit", "Zavrit"):
            button = by_text[label]
            self.assertEqual(button.objectName(), "")
            pixel = button.grab().toImage().pixelColor(button.width() // 2, 4)
            # svetle #e9e9e9 = (233, 233, 233), ne seda #757575 = (117, 117, 117)
            self.assertEqual((pixel.red(), pixel.green(), pixel.blue()), (233, 233, 233), label)
        # Cervena destruktivni tlacitka zustavaji vyrazna.
        self.assertEqual(by_text["Rebuild data"].objectName(), "dangerButton")
        self.assertEqual(by_text["Rollback"].objectName(), "dangerButton")
        app.processEvents()

    def test_light_theme_uses_soft_gridline(self):
        """Base gridline palette(mid) je v light teme #b8b8b8 a na bilych bunkach
        vystupuje. Light ma mit jemnejsi #e0e0e0."""
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.theme = "light"
        window.apply_theme()

        self.assertIn("gridline-color: #e0e0e0", window.styleSheet())
        app.processEvents()

    def test_colored_buttons_have_hover_and_pressed_states(self):
        """Barevna ID tlacitka drive nemela :hover/:pressed, takze na rozdil od
        ostatnich tlacitek nereagovala na mys. ID selektor prebiji obecny hover."""
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.theme = "system"
        window.apply_theme()

        style = window.styleSheet()
        for object_name in ("neutralButton", "dangerButton", "approveButton",
                            "reviewButton", "storyButton"):
            self.assertIn(f"#{object_name}:hover", style)
            self.assertIn(f"#{object_name}:pressed", style)
        app.processEvents()

    def test_multiimport_production_writer_adapter_reuses_single_item_apply_contract(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        expected = cme.ImportApplyResult(book_id=51, status="updated")

        with (
            patch.object(cme, "find_calibredb", return_value="C:/Calibre/calibredb.exe"),
            patch.object(cme, "apply_import_preview", return_value=expected) as apply_preview,
        ):
            result = window._write_multiimport_item(preview, Path("book.epub"))

        self.assertIs(result, expected)
        self.assertEqual(apply_preview.call_args.args[:2], (preview, Path("book.epub")))
        self.assertEqual(apply_preview.call_args.kwargs["library"], window.library_path)
        self.assertEqual(
            apply_preview.call_args.kwargs["calibredb_path"],
            "C:/Calibre/calibredb.exe",
        )
        self.assertEqual(apply_preview.call_args.kwargs["matches_path"], window.matches_path)
        self.assertTrue(apply_preview.call_args.kwargs["allow_force"])
        app.processEvents()

    def test_multiimport_post_write_refresh_reuses_existing_review_reload_path(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        validation = cme.MultiImportValidationResult([], [])
        summary = cme.MultiImportWriteSummary(validation, 2, 1, 1)

        with (
            patch.object(window, "show_import_review_filter") as show_review,
            patch.object(window, "load_csv") as load_csv,
        ):
            window._refresh_after_multiimport_write(summary)

        show_review.assert_called_once_with()
        load_csv.assert_called_once_with(show_message=False)
        app.processEvents()

    def test_import_epub_icon_is_distinct_from_cover_icon(self):
        # Import EPUB a Obalky drive padaly na stejny SP_FileIcon; musi se lisit.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        epub_icon = window.icon_for("epub")
        cover_icon = window.icon_for("cover")

        self.assertFalse(epub_icon.isNull())
        epub_img = epub_icon.pixmap(32, 32).toImage()
        cover_img = cover_icon.pixmap(32, 32).toImage()
        self.assertFalse(epub_img.isNull())
        self.assertNotEqual(epub_img, cover_img)
        app.processEvents()

    def test_qt_startup_preview_uses_single_shot_timer(self):
        import calibre_meta_qt as qt

        callback = object()
        with patch.object(qt.QTimer, "singleShot") as single_shot:
            qt.schedule_qt_startup_preview(callback)

        single_shot.assert_called_once_with(250, callback)

    def test_qt_window_does_not_schedule_startup_preview_in_offscreen_tests(self):
        from PySide6.QtWidgets import QApplication
        import os
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        old_value = os.environ.get("QT_QPA_PLATFORM")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            with patch.object(qt, "schedule_qt_startup_preview") as schedule:
                qt.CalibreMetaQtWindow()
        finally:
            if old_value is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = old_value

        schedule.assert_not_called()
        app.processEvents()

    def test_restore_selection_uses_sorted_table_book_ids(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = [
            cme.MatchRow(1, "Beta", "Autor", "review", "", "", "none", "x"),
            cme.MatchRow(2, "Alfa", "Autor", "review", "", "", "none", "x"),
        ]
        window.refresh_table()
        window.table.sortItems(1, Qt.SortOrder.AscendingOrder)

        window.restore_selection({1})

        self.assertEqual(window.selected_book_ids(), {1})
        self.assertEqual(window.selected_row().title, "Beta")
        app.processEvents()

    def test_refresh_table_selects_first_row_when_nothing_selected(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = [cme.MatchRow(4, "Realna", "Autor", "review", "", "", "none", "x")]

        window.refresh_table()

        self.assertEqual(window.selected_book_ids(), {4})
        app.processEvents()

    def test_manual_skip_filter_toggle_is_not_reenabled_automatically(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = [cme.MatchRow(4, "Hotovo", "Autor", "skip", "", "", "none", "x")]
        window.status_checks["approve"].setChecked(True)
        window.status_checks["review"].setChecked(True)
        window.status_checks["skip"].setChecked(False)
        window.auto_skip_filter_allowed = True

        window.refresh_table()
        window.disable_auto_skip_filter()
        window.status_checks["skip"].setChecked(False)
        window.refresh_table()

        self.assertFalse(window.status_checks["skip"].isChecked())
        self.assertEqual(window.table.rowCount(), 0)
        app.processEvents()

    def test_delete_selected_rows_confirmed_runs_calibre_delete(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        bg = []
        with (
            patch.object(window, "selected_book_ids", return_value={1, 2}),
            patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(qt.cme, "find_calibredb", return_value="calibredb.exe"),
            patch.object(window, "run_background", side_effect=lambda title, action, reload_after: bg.append((title, action, reload_after))),
        ):
            window.delete_selected_rows()

        self.assertEqual(len(bg), 1)
        self.assertEqual(bg[0][0], "Smazat z Calibre")
        self.assertTrue(bg[0][2])
        app.processEvents()

    def test_delete_selected_rows_cancelled_does_nothing(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with (
            patch.object(window, "selected_book_ids", return_value={1}),
            patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.No),
            patch.object(window, "run_background") as bg,
        ):
            window.delete_selected_rows()

        bg.assert_not_called()
        app.processEvents()

    def test_delete_selected_rows_without_calibredb_warns(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with (
            patch.object(window, "selected_book_ids", return_value={1}),
            patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(qt.cme, "find_calibredb", return_value=""),
            patch.object(qt.QMessageBox, "warning") as warning,
            patch.object(window, "run_background") as bg,
        ):
            window.delete_selected_rows()

        warning.assert_called_once()
        bg.assert_not_called()
        app.processEvents()

    def test_run_covers_uses_cover_audit_without_direct_write(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = [cme.MatchRow(1, "Kniha", "Autor", "review", "https://www.databazeknih.cz/knihy/a-1", "", "manual", "manual")]
        calls = []

        with (
            patch.object(window, "selected_book_ids", return_value={1}),
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background", side_effect=lambda title, action, reload_after: calls.append((title, action, reload_after))),
            patch.object(qt.shared, "make_cover_audit_action", return_value=lambda: 0) as audit_action,
            patch.object(qt.shared, "make_cover_action") as write_action,
        ):
            window.run_covers()

        audit_action.assert_called_once()
        write_action.assert_not_called()
        self.assertEqual(calls[0][0], "Audit obalek")
        self.assertTrue(calls[0][2])
        app.processEvents()

    def test_run_apply_without_cover_overwrite_does_not_ask_cover_question(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        captured = []
        with (
            patch.object(window, "ask_apply_confirmation", return_value=(True, False)),
            patch.object(window, "ask_cover_overwrite_confirmation") as cover_question,
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background"),
            patch.object(qt.shared, "cover_overwrite_book_ids", return_value=set()),
            patch.object(qt.shared, "make_apply_action", side_effect=lambda args, **kwargs: captured.append(args) or (lambda: 0)),
        ):
            window.run_apply()

        cover_question.assert_not_called()
        self.assertEqual(captured[0].skip_cover_book_ids, [])
        window.close()
        app.processEvents()

    def test_run_apply_declined_cover_overwrite_skips_only_affected_covers(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        captured = []
        with (
            patch.object(window, "ask_apply_confirmation", return_value=(True, False)),
            patch.object(window, "ask_cover_overwrite_confirmation", return_value=False) as cover_question,
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background"),
            patch.object(qt.shared, "cover_overwrite_book_ids", return_value={7, 9}),
            patch.object(qt.shared, "make_apply_action", side_effect=lambda args, **kwargs: captured.append(args) or (lambda: 0)),
        ):
            window.run_apply()

        cover_question.assert_called_once_with(2)
        self.assertEqual(captured[0].skip_cover_book_ids, [7, 9])
        window.close()
        app.processEvents()

    def test_run_apply_accepted_cover_overwrite_keeps_existing_cover_write(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        captured = []
        with (
            patch.object(window, "ask_apply_confirmation", return_value=(True, False)),
            patch.object(window, "ask_cover_overwrite_confirmation", return_value=True),
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background"),
            patch.object(qt.shared, "cover_overwrite_book_ids", return_value={7}),
            patch.object(qt.shared, "make_apply_action", side_effect=lambda args, **kwargs: captured.append(args) or (lambda: 0)),
        ):
            window.run_apply()

        self.assertEqual(captured[0].skip_cover_book_ids, [])
        window.close()
        app.processEvents()

    def test_cover_overwrite_confirmation_defaults_to_preserving_cover(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with (
            patch.object(qt.QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel),
            patch.object(qt.QMessageBox, "setDefaultButton") as set_default,
        ):
            accepted = window.ask_cover_overwrite_confirmation(2)

        self.assertFalse(accepted)
        set_default.assert_called_once_with(QMessageBox.StandardButton.No)
        window.close()
        app.processEvents()

    def test_run_covers_selected_rows_include_existing_covers_without_prompt(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        captured = []

        with (
            patch.object(window, "selected_book_ids", return_value={7}),
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "question") as question,
            patch.object(
                qt.shared,
                "make_cover_audit_action",
                side_effect=lambda args, matches_path: captured.append(args) or (lambda: 0),
            ),
            patch.object(qt.shared, "make_cover_action") as write_action,
        ):
            window.run_covers()

        question.assert_not_called()
        self.assertEqual(captured[0].book_ids, [7])
        self.assertTrue(captured[0].include_existing_covers)
        write_action.assert_not_called()
        app.processEvents()

    def test_run_covers_all_rows_asks_and_defaults_to_excluding_existing_covers(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        captured = []

        with (
            patch.object(window, "selected_book_ids", return_value=set()),
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question,
            patch.object(
                qt.shared,
                "make_cover_audit_action",
                side_effect=lambda args, matches_path: captured.append(args) or (lambda: 0),
            ),
        ):
            window.run_covers()

        self.assertIn("Zahrnout i knihy", question.call_args.args[2])
        self.assertFalse(captured[0].include_existing_covers)
        app.processEvents()

    def test_run_covers_all_rows_can_include_existing_covers(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        captured = []

        with (
            patch.object(window, "selected_book_ids", return_value=set()),
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(
                qt.shared,
                "make_cover_audit_action",
                side_effect=lambda args, matches_path: captured.append(args) or (lambda: 0),
            ),
        ):
            window.run_covers()

        self.assertTrue(captured[0].include_existing_covers)
        app.processEvents()

    def test_cover_preview_shows_candidates_and_existing_cover_note_together(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            cover_urls="https://img.example/new.jpg",
            selected_cover_url="https://img.example/new.jpg",
            cover_reason="single-cover-candidate",
        )

        with (
            patch.object(qt.cme, "get_local_cover_path", return_value=Path("cover.jpg")),
            patch.object(window, "load_cover_url") as load_cover,
        ):
            window.update_cover_preview([row])

        self.assertIn("Obalka uz je v Calibre", window.cover_status.text())
        self.assertIn("https://img.example/new.jpg", window.cover_option_buttons)
        load_cover.assert_called()
        app.processEvents()

    def test_clear_cover_button_appears_only_with_candidate_offer(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        offered = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            cover_urls="https://img.example/a.jpg|https://img.example/b.jpg",
            cover_reason="multiple-cover-candidates",
            cover_pre_audit_status="skip",
        )

        with (
            patch.object(qt.cme, "get_local_cover_path", return_value=None),
            patch.object(window, "load_cover_url"),
        ):
            # isHidden(), ne isVisibleTo(): Review je zalozka v tabu, takze kdyz
            # neni aktivni, cela stranka je skryta a viditelnost by lhala.
            window.update_cover_preview([offered])
            self.assertFalse(window.clear_cover_button.isHidden())

            window.update_cover_preview([])
            self.assertTrue(window.clear_cover_button.isHidden())

        app.processEvents()

    def test_clear_selected_cover_restores_pre_audit_status_and_saves(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            cover_urls="https://img.example/a.jpg|https://img.example/b.jpg",
            selected_cover_url="https://img.example/a.jpg",
            cover_reason="multiple-cover-candidates",
            cover_pre_audit_status="skip",
        )
        window.rows = [row]

        with (
            patch.object(window, "selected_rows", return_value=[row]),
            patch.object(window, "save_csv") as save_csv,
            patch.object(window, "refresh_table"),
            patch.object(window, "update_cover_preview"),
        ):
            window.clear_selected_cover()

        self.assertEqual(window.rows[0].status, "skip")
        self.assertEqual(window.rows[0].cover_urls, "")
        self.assertEqual(window.rows[0].selected_cover_url, "")
        self.assertEqual(window.rows[0].cover_pre_audit_status, "")
        save_csv.assert_called_once()
        app.processEvents()

    def test_cover_preview_hides_written_candidates_for_finished_rows(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "skip",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            cover_urls="https://img.example/written.jpg",
        )

        with (
            patch.object(qt.cme, "get_local_cover_path", return_value=Path("cover.jpg")),
            patch.object(window, "load_cover_url") as load_cover,
        ):
            window.update_cover_preview([row])

        self.assertEqual(window.cover_status.text(), "Obalka uz je v Calibre")
        self.assertNotIn("Vybrana kandidatni obalka", window.cover_status.text())
        self.assertEqual(window.cover_option_buttons, {})
        load_cover.assert_not_called()
        app.processEvents()

    def test_cover_preview_hides_declined_overwrite_candidates_for_finished_rows(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "skip",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            cover_urls="https://img.example/declined.jpg",
            cover_reason="cover-overwrite-declined",
        )

        with (
            patch.object(qt.cme, "get_local_cover_path", return_value=Path("cover.jpg")),
            patch.object(window, "load_cover_url") as load_cover,
        ):
            window.update_cover_preview([row])

        self.assertEqual(window.cover_status.text(), "Obalka uz je v Calibre")
        self.assertNotIn("Vybrana kandidatni obalka", window.cover_status.text())
        self.assertEqual(window.cover_option_buttons, {})
        load_cover.assert_not_called()
        app.processEvents()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class PreferencesDialogAITests(unittest.TestCase):
    def _open_dialog(self, qt, window):
        return qt.PreferencesDialog(window)

    def _patch_settings_path(self, qt, tmp_path):
        return patch.multiple(
            qt.shared,
            SETTINGS_PATH=tmp_path,
        )

    def _open_dialog_with_ai_test(self, qt, window, resolver, runner=None):
        return qt.PreferencesDialog(
            window,
            resolver_factory=lambda provider, model, timeout: resolver,
            test_runner=runner or (lambda target: target()),
        )

    def test_ai_test_reports_success(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)

        class FakeResolver:
            last_error = ""
            def extract(self, text):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog_with_ai_test(qt, window, FakeResolver())
                dialog.start_ai_test()
        self.assertTrue(dialog.ai_test_result_label.text().startswith("Funguje"))
        app.processEvents()

    def test_ai_test_reports_failure_reason(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)

        class FakeResolver:
            last_error = "Ollama neběží"
            def extract(self, text):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog_with_ai_test(qt, window, FakeResolver())
                dialog.start_ai_test()
        self.assertEqual(dialog.ai_test_result_label.text(), "Nefunguje: Ollama neběží")
        app.processEvents()

    def test_ai_test_reports_disabled(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog_with_ai_test(qt, window, cme.DisabledAIResolver())
                dialog.start_ai_test()
        self.assertEqual(dialog.ai_test_result_label.text(), "AI je vypnutá")
        app.processEvents()

    def test_ai_test_uses_current_dialog_values(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        captured = {}

        class FakeResolver:
            last_error = ""
            def extract(self, text):
                return None

        def factory(provider, model, timeout):
            captured["provider"] = provider
            captured["model"] = model
            captured["timeout"] = timeout
            return FakeResolver()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(
                    window,
                    resolver_factory=factory,
                    test_runner=lambda target: target(),
                )
                dialog.ai_provider_combo.setCurrentText("ollama")
                dialog.ai_model_edit.setText("llama-test")
                dialog.ai_timeout_edit.setText("42")
                dialog.start_ai_test()

        self.assertEqual(captured, {"provider": "ollama", "model": "llama-test", "timeout": 42})
        app.processEvents()

    def test_startup_check_toggle_saves_hide_flag(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(window)
                # Zaskrtnuto = kontrola zapnuta = neschovano. Odskrtnu -> schovat.
                self.assertTrue(dialog.startup_check_check.isChecked())
                dialog.startup_check_check.setChecked(False)
                dialog.save_library()
                saved = json.loads(tmp_path.read_text(encoding="utf-8"))
        self.assertTrue(saved["hide_startup_check"])
        app.processEvents()

    def test_dialog_starts_clean_and_marks_dirty_on_change(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(window)
                self.assertFalse(dialog.is_dirty())
                dialog.ai_model_edit.setText("something-else")
                self.assertTrue(dialog.is_dirty())
        app.processEvents()

    def test_save_resets_dirty_state(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(window)
                dialog.ai_model_edit.setText("something-else")
                dialog.save_library()
                self.assertFalse(dialog.is_dirty())
        app.processEvents()

    def test_close_when_dirty_prompts_and_saves(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtGui import QCloseEvent
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(window)
                dialog.ai_model_edit.setText("something-else")
                event = QCloseEvent()
                with (
                    patch.object(dialog, "_confirm_unsaved", return_value="save") as confirm,
                    patch.object(dialog, "save_library", wraps=dialog.save_library) as save,
                ):
                    dialog.closeEvent(event)
                confirm.assert_called_once()
                save.assert_called_once()
                self.assertTrue(event.isAccepted())
        app.processEvents()

    def test_close_when_dirty_cancel_stays_open(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtGui import QCloseEvent
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(window)
                dialog.ai_model_edit.setText("something-else")
                event = QCloseEvent()
                with patch.object(dialog, "_confirm_unsaved", return_value="cancel"):
                    dialog.closeEvent(event)
                self.assertFalse(event.isAccepted())
        app.processEvents()

    def test_close_when_clean_does_not_prompt(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QCloseEvent
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = qt.PreferencesDialog(window)
                event = QCloseEvent()
                with patch.object(dialog, "_confirm_unsaved") as confirm:
                    dialog.closeEvent(event)
                confirm.assert_not_called()
                self.assertTrue(event.isAccepted())
        app.processEvents()

    def test_preferences_dialog_has_key_status_label(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)
                self.assertTrue(hasattr(dialog, "ai_key_status_label"))
        app.processEvents()

    def test_changing_provider_switches_model_to_default(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)
                dialog.ai_provider_combo.setCurrentText("anthropic")
                self.assertEqual(dialog.ai_model_edit.text(), "claude-sonnet-4-6")
                dialog.ai_provider_combo.setCurrentText("openai")
                self.assertEqual(dialog.ai_model_edit.text(), "gpt-4o")
        app.processEvents()

    def test_key_status_label_reflects_missing_key(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                with patch.object(qt.cme, "read_api_key", return_value=""):
                    window = qt.CalibreMetaQtWindow()
                    dialog = self._open_dialog(qt, window)
                    dialog.ai_provider_combo.setCurrentText("anthropic")
                    self.assertIn("CHYB", dialog.ai_key_status_label.text().upper())
        app.processEvents()

    def test_key_status_label_reflects_found_key(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                with patch.object(qt.cme, "read_api_key", return_value="sk-found"):
                    window = qt.CalibreMetaQtWindow()
                    dialog = self._open_dialog(qt, window)
                    dialog.ai_provider_combo.setCurrentText("openai")
                    self.assertIn("NALEZEN", dialog.ai_key_status_label.text().upper())
        app.processEvents()

    def test_preferences_dialog_exposes_ai_import_widgets(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)

                self.assertTrue(hasattr(dialog, "ai_provider_combo"))
                self.assertTrue(hasattr(dialog, "ai_model_edit"))
                self.assertTrue(hasattr(dialog, "ai_text_limit_edit"))
                self.assertEqual(
                    [dialog.ai_provider_combo.itemText(i) for i in range(dialog.ai_provider_combo.count())],
                    list(qt.AI_PROVIDER_VALUES),
                )
        app.processEvents()

    def test_preferences_dialog_defaults_match_normalize_ai_settings(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        defaults = qt.normalize_ai_settings({})
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)

                self.assertEqual(dialog.ai_provider_combo.currentText(), str(defaults["provider"]))
                self.assertEqual(dialog.ai_model_edit.text(), str(defaults["model"]))
                self.assertEqual(dialog.ai_text_limit_edit.text(), str(defaults["text_limit"]))
        app.processEvents()

    def test_save_library_persists_ollama_provider_model_and_text_limit(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)
                dialog.library_edit.setText("B:\\lib")
                dialog.ai_provider_combo.setCurrentText("ollama")
                dialog.ai_model_edit.setText("llama-prefs")
                dialog.ai_text_limit_edit.setText("12345")

                dialog.save_library()

                saved = json.loads(tmp_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["ai"]["provider"], "ollama")
                self.assertEqual(saved["ai"]["model"], "llama-prefs")
                self.assertEqual(saved["ai"]["text_limit"], 12345)
        app.processEvents()

    def test_save_library_persists_worker_count(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)
                dialog.library_edit.setText("B:\\lib")
                # Vychozi hodnota je zmerene optimum.
                self.assertEqual(dialog.ai_workers_spin.value(), 5)
                dialog.ai_workers_spin.setValue(2)

                dialog.save_library()

                saved = json.loads(tmp_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["ai"]["workers"], 2)
        app.processEvents()

    def test_save_library_persists_disabled_provider(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)
                dialog.library_edit.setText("B:\\lib")
                dialog.ai_provider_combo.setCurrentText("off")
                dialog.ai_model_edit.setText("llama-keep")
                dialog.ai_text_limit_edit.setText("7000")

                dialog.save_library()

                saved = json.loads(tmp_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["ai"]["provider"], "off")
                self.assertEqual(saved["ai"]["model"], "llama-keep")
                self.assertEqual(saved["ai"]["text_limit"], 7000)
        app.processEvents()

    def test_save_library_normalizes_empty_text_limit_to_default(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        defaults = qt.normalize_ai_settings({})
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "settings.json"
            with patch.object(qt.shared, "SETTINGS_PATH", tmp_path):
                window = qt.CalibreMetaQtWindow()
                dialog = self._open_dialog(qt, window)
                dialog.library_edit.setText("B:\\lib")
                dialog.ai_provider_combo.setCurrentText("ollama")
                dialog.ai_model_edit.setText("")
                dialog.ai_text_limit_edit.setText("not-a-number")

                dialog.save_library()

                saved = json.loads(tmp_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["ai"]["model"], str(defaults["model"]))
                self.assertEqual(saved["ai"]["text_limit"], int(defaults["text_limit"]))
        app.processEvents()


class RunImportAnalysisTests(unittest.TestCase):
    def _make_analysis(self, preview=None):
        return cme.ImportAnalysis(
            epub_path="b.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=preview or cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )

    def test_run_import_analysis_passes_library_and_collects_duplicates(self):
        import calibre_meta_qt as qt

        analysis = self._make_analysis()
        duplicate = cme.DuplicateCandidate(
            book_id=42, title="Kniha", authors="Autor", score=100, reason="title-author"
        )
        seen = {}

        def fake_analyze(path, library, settings, ai_resolver=None):
            seen["analyze"] = (path, library, settings, ai_resolver)
            return analysis

        def fake_find_duplicates(library, preview):
            seen["dups"] = (library, preview)
            return [duplicate]

        result = qt.run_import_analysis(
            "b.epub",
            library="L:\\",
            settings={"epub_text_limit": 1000},
            analyze=fake_analyze,
            find_duplicates=fake_find_duplicates,
        )

        self.assertEqual(seen["analyze"][0], "b.epub")
        self.assertEqual(seen["analyze"][1], "L:\\")
        self.assertEqual(seen["analyze"][2], {"epub_text_limit": 1000})
        self.assertEqual(seen["dups"][0], "L:\\")
        self.assertEqual(seen["dups"][1].title, "Kniha")
        self.assertEqual([d.book_id for d in result.duplicates], [42])
        self.assertEqual(result.preview.title, "Kniha")

    def test_run_import_analysis_swallows_duplicate_error(self):
        import calibre_meta_qt as qt

        analysis = self._make_analysis()

        def boom(library, preview):
            raise RuntimeError("calibre offline")

        result = qt.run_import_analysis(
            "b.epub",
            library="L:\\",
            settings={},
            analyze=lambda *a, **k: analysis,
            find_duplicates=boom,
        )

        self.assertEqual(result.duplicates, [])
        self.assertEqual(result.preview.title, "Kniha")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class UnifiedImportDialogTests(unittest.TestCase):
    def test_dialog_lists_only_supported_files_and_starts_with_recursion_off(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "book.epub").write_text("x", encoding="utf-8")
            (root / "notes.txt").write_text("x", encoding="utf-8")

            dialog = qt.UnifiedImportDialog(root)

            self.assertEqual(dialog.file_table.rowCount(), 1)
            self.assertEqual(dialog.file_table.item(0, 0).text(), "book.epub")
            self.assertFalse(dialog.include_subfolders_check.isChecked())
            self.assertFalse(dialog.import_selected_button.isEnabled())
            self.assertFalse(dialog.path_edit.isReadOnly())
            self.assertTrue(dialog.folder_tree.header().isHidden())
            self.assertFalse(dialog.file_table.verticalHeader().isVisible())
            self.assertTrue(dialog.file_table.isSortingEnabled())
            self.assertEqual(dialog.back_button.text(), "←")
            self.assertEqual(dialog.up_button.text(), "↑")
            self.assertEqual(
                Path(dialog.directory_model.filePath(dialog.folder_tree.rootIndex())),
                qt.unified_import_tree_root(root),
            )
        app.processEvents()

    def test_dialog_can_navigate_by_manual_path_entry(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            (child / "book.epub").write_text("x", encoding="utf-8")
            dialog = qt.UnifiedImportDialog(root)

            dialog.path_edit.setText(str(child))
            dialog._apply_path_edit()

            self.assertEqual(dialog.current_folder, child.absolute())
            self.assertEqual(dialog.file_table.rowCount(), 1)
            self.assertEqual(dialog.file_table.item(0, 0).text(), "book.epub")
        app.processEvents()

    def test_dialog_enter_in_path_field_applies_manual_path(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            (child / "book.epub").write_text("x", encoding="utf-8")
            dialog = qt.UnifiedImportDialog(root)

            dialog.path_edit.setFocus()
            dialog.path_edit.setText(str(child))
            QTest.keyClick(dialog.path_edit, Qt.Key.Key_Return)

            self.assertEqual(dialog.current_folder, child.absolute())
            self.assertEqual(dialog.file_table.item(0, 0).text(), "book.epub")
        app.processEvents()

    def test_dialog_can_navigate_by_go_button(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            (child / "book.epub").write_text("x", encoding="utf-8")
            dialog = qt.UnifiedImportDialog(root)

            dialog.path_edit.setText(str(child))
            dialog.go_path_button.click()

            self.assertEqual(dialog.current_folder, child.absolute())
            self.assertEqual(dialog.file_table.item(0, 0).text(), "book.epub")
        app.processEvents()

    def test_dialog_tree_is_rooted_at_drive_so_parent_folders_are_visible(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()

            dialog = qt.UnifiedImportDialog(child)

            self.assertEqual(
                Path(dialog.directory_model.filePath(dialog.folder_tree.rootIndex())),
                qt.unified_import_tree_root(child),
            )
            self.assertNotEqual(dialog.folder_tree.rootIndex(), dialog.folder_tree.currentIndex())
        app.processEvents()

    def test_dialog_sorts_file_size_numerically(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            small = root / "small.epub"
            large = root / "large.epub"
            small.write_bytes(b"xx")
            large.write_bytes(b"x" * 10)
            dialog = qt.UnifiedImportDialog(root)

            dialog.file_table.sortItems(2, Qt.SortOrder.AscendingOrder)

            self.assertEqual(dialog.file_table.item(0, 0).text(), "small.epub")
            self.assertEqual(dialog.file_table.item(1, 0).text(), "large.epub")
        app.processEvents()

    def test_dialog_restores_saved_size_columns_splitter_and_sorting(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.epub").write_text("x", encoding="utf-8")
            (root / "a.mobi").write_text("x", encoding="utf-8")
            state = {
                "size": [1000, 700],
                "splitter_sizes": [260, 740],
                "file_column_widths": [310, 95, 125],
                "sort_column": 0,
                "sort_order": "desc",
            }

            dialog = qt.UnifiedImportDialog(root, dialog_state=state)

            self.assertEqual(dialog.size().width(), 1000)
            self.assertEqual(dialog.size().height(), 700)
            self.assertEqual(dialog.file_table.columnWidth(0), 310)
            self.assertEqual(dialog.file_table.columnWidth(1), 95)
            self.assertEqual(dialog.file_table.columnWidth(2), 125)
            self.assertEqual(dialog.file_table.horizontalHeader().sortIndicatorSection(), 0)
            self.assertEqual(
                dialog.file_table.horizontalHeader().sortIndicatorOrder(),
                Qt.SortOrder.DescendingOrder,
            )
        app.processEvents()

    def test_dialog_exports_current_ui_state(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dialog = qt.UnifiedImportDialog(root)
            dialog.resize(980, 640)
            dialog.file_table.setColumnWidth(0, 305)
            dialog.file_table.setColumnWidth(1, 85)
            dialog.file_table.setColumnWidth(2, 115)
            dialog.file_table.sortItems(1, Qt.SortOrder.DescendingOrder)

            state = dialog.export_ui_state()

            self.assertEqual(state["size"], [980, 640])
            self.assertEqual(state["file_column_widths"], [305, 85, 115])
            self.assertEqual(state["sort_column"], 1)
            self.assertEqual(state["sort_order"], "desc")
        app.processEvents()

    def test_selecting_one_file_enables_selected_import_and_returns_it(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.epub"
            book.write_text("x", encoding="utf-8")
            dialog = qt.UnifiedImportDialog(root)

            dialog.file_table.selectRow(0)
            dialog._update_selected_button()
            dialog._accept_selected_files()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_files, (book.absolute(),))
        app.processEvents()

    def test_folder_import_passes_recursive_checkbox_to_scanner(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.epub"
            book.write_text("x", encoding="utf-8")
            calls = []

            def scan(folder, recursive):
                calls.append((folder, recursive))
                return cme.ImportFolderScanResult((book,), ())

            dialog = qt.UnifiedImportDialog(root, scan_folder=scan)
            dialog.include_subfolders_check.setChecked(True)
            dialog._accept_current_folder()

            self.assertEqual(calls[-1], (root.absolute(), True))
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_files, (book.absolute(),))
        app.processEvents()

    def test_folder_import_with_skipped_directories_requires_confirmation(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.epub"
            blocked = root / "blocked"
            book.write_text("x", encoding="utf-8")

            def scan(folder, recursive):
                return cme.ImportFolderScanResult((book,), (blocked,))

            dialog = qt.UnifiedImportDialog(root, scan_folder=scan)
            with patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                dialog._accept_current_folder()

            self.assertEqual(dialog.selected_files, ())
        app.processEvents()

    def test_unreadable_current_folder_shows_specific_warning(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def scan(folder, recursive):
                return cme.ImportFolderScanResult((), (root,))

            dialog = qt.UnifiedImportDialog(root, scan_folder=scan)
            with patch.object(qt.QMessageBox, "warning") as warning:
                dialog._accept_current_folder()

            warning.assert_called_once()
            self.assertIn("nelze přečíst", warning.call_args.args[2])
            self.assertEqual(dialog.selected_files, ())
        app.processEvents()

    def test_selected_file_removed_before_confirmation_shows_warning(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.epub"
            book.write_text("x", encoding="utf-8")
            dialog = qt.UnifiedImportDialog(root)
            dialog.file_table.selectRow(0)
            book.unlink()

            with patch.object(qt.QMessageBox, "warning") as warning:
                dialog._accept_selected_files()

            warning.assert_called_once()
            self.assertEqual(dialog.selected_files, ())
        app.processEvents()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class QtImportWiringTests(unittest.TestCase):
    def test_is_online_now_updates_state_and_indicator(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertTrue(window.is_online_now(lambda: True))
        self.assertTrue(window.online)
        self.assertTrue(window.online_indicator.text().endswith("Online"))

        self.assertFalse(window.is_online_now(lambda: False))
        self.assertFalse(window.online)
        self.assertTrue(window.online_indicator.text().endswith("Offline"))
        app.processEvents()

    def test_is_online_now_treats_probe_error_as_offline(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        def failing_probe():
            raise OSError("sit nedostupna")

        self.assertFalse(window.is_online_now(failing_probe))
        self.assertTrue(window.online_indicator.text().endswith("Offline"))
        app.processEvents()

    def test_multiimport_analysis_offline_updates_indicator(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with (
            patch.object(
                qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ),
            patch.object(qt, "ImportReviewDialog"),
        ):
            window.run_multiimport_analysis(
                [Path("C:/books/book.epub")],
                analyze=lambda _path: None,
                connectivity_check=lambda: False,
            )

        self.assertFalse(window.online)
        self.assertTrue(window.online_indicator.text().endswith("Offline"))
        app.processEvents()

    def test_warn_about_ai_failure_shows_reason(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window._last_ai_resolver = SimpleNamespace(
            last_error="HTTP 400: Your credit balance is too low"
        )

        with patch.object(qt.QMessageBox, "warning") as warning:
            warned = window.warn_about_ai_failure()

        self.assertTrue(warned)
        warning.assert_called_once()
        self.assertIn("credit balance is too low", warning.call_args.args[2])
        app.processEvents()

    def test_warn_about_ai_failure_silent_when_ai_worked(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window._last_ai_resolver = SimpleNamespace(last_error="")

        with patch.object(qt.QMessageBox, "warning") as warning:
            warned = window.warn_about_ai_failure()

        self.assertFalse(warned)
        warning.assert_not_called()
        app.processEvents()

    def test_warn_about_ai_failure_silent_without_resolver(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with patch.object(qt.QMessageBox, "warning") as warning:
            self.assertFalse(window.warn_about_ai_failure())

        warning.assert_not_called()
        app.processEvents()

    def test_multiimport_analysis_warns_when_ai_failed(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window._last_ai_resolver = SimpleNamespace(last_error="Ollama nebezi")

        with (
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt, "ImportReviewDialog"),
            patch.object(cme, "run_multiimport_batch_analysis", return_value=[]),
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            scheduled = []
            progress_dialog.return_value.run_after_first_paint.side_effect = scheduled.append
            progress_dialog.return_value.exec.side_effect = lambda: scheduled.pop(0)()
            window.run_multiimport_analysis(
                [Path("C:/books/a.epub")],
                analyze=lambda _path: None,
                connectivity_check=lambda: True,
            )

        warning.assert_called_once()
        self.assertIn("Ollama nebezi", warning.call_args.args[2])
        app.processEvents()

    def test_multiimport_analysis_uses_worker_count_from_settings(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with (
            patch.object(qt, "read_app_settings", return_value={"ai": {"workers": 3}}),
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt, "ImportReviewDialog"),
            patch.object(cme, "run_multiimport_batch_analysis", return_value=[]) as batch_analysis,
        ):
            scheduled = []
            progress_dialog.return_value.run_after_first_paint.side_effect = scheduled.append
            progress_dialog.return_value.exec.side_effect = lambda: scheduled.pop(0)()
            window.run_multiimport_analysis(
                [Path("C:/books/a.epub"), Path("C:/books/b.epub")],
                analyze=lambda _path: None,
                connectivity_check=lambda: True,
            )

        # Pocet workeru bere z nastaveni, ne z pevne konstanty.
        self.assertEqual(batch_analysis.call_args.kwargs["max_workers"], 3)
        app.processEvents()

    def test_multiimport_prechecks_safe_matches(self):
        # V davkovem okne jsou jiste shody (100 % bez duplicit) po analyze rovnou
        # zaskrtnute k importu - "Vybrat 100 %" jako vychozi stav.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        safe = cme.ImportCandidate("databazeknih", "Kniha", "Autor", "https://dk/1", score=100)
        analysis = cme.ImportAnalysis(
            epub_path="b.epub",
            signals=[],
            candidates=[safe],
            recommended=safe,
            duplicates=[],
            preview=cme.ImportPreview(title="Kniha", authors="Autor", url="https://dk/1"),
            messages=[],
        )
        scheduled = []

        with (
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt, "ImportReviewDialog"),
            patch.object(qt.QApplication, "processEvents"),
        ):
            progress_dialog.return_value.run_after_first_paint.side_effect = scheduled.append
            progress_dialog.return_value.exec.side_effect = lambda: scheduled.pop(0)()
            items = window.run_multiimport_analysis(
                [Path("C:/books/a.epub")],
                analyze=lambda _path: analysis,
                connectivity_check=lambda: True,
            )

        self.assertEqual(items[0].status, "ready")
        self.assertTrue(items[0].checked_for_import)
        app.processEvents()

    def test_prepare_multiimport_backup_creates_one_backup_when_enabled(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with patch.object(
            cme, "create_backup", return_value=Path("backups/metadata-x.db")
        ) as create_backup:
            path = window.prepare_multiimport_backup(True)

        create_backup.assert_called_once()
        self.assertEqual(path, Path("backups/metadata-x.db"))
        self.assertTrue(window._multiimport_backup_ready)
        app.processEvents()

    def test_prepare_multiimport_backup_skips_backup_when_disabled(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with patch.object(cme, "create_backup") as create_backup:
            path = window.prepare_multiimport_backup(False)

        create_backup.assert_not_called()
        self.assertIsNone(path)
        self.assertTrue(window._multiimport_backup_ready)
        app.processEvents()

    def test_write_multiimport_item_reuses_batch_backup_instead_of_copying(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window._multiimport_backup_ready = True
        window._multiimport_backup_path = Path("backups/metadata-x.db")

        with (
            patch.object(cme, "find_calibredb", return_value="calibredb"),
            patch.object(
                cme,
                "apply_import_preview",
                return_value=cme.ImportApplyResult(1, "updated"),
            ) as apply_preview,
            patch.object(cme, "create_backup") as create_backup,
        ):
            window._write_multiimport_item(
                cme.ImportPreview(title="Kniha", authors="Autor"), Path("b.epub")
            )

        backup_func = apply_preview.call_args.kwargs["backup_func"]
        # Vraci uz hotovou zalohu davky, misto aby delal dalsi kopii.
        self.assertEqual(backup_func("lib", Path("backups")), Path("backups/metadata-x.db"))
        create_backup.assert_not_called()
        app.processEvents()

    def test_write_multiimport_item_keeps_default_backup_without_preparation(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with (
            patch.object(cme, "find_calibredb", return_value="calibredb"),
            patch.object(
                cme,
                "apply_import_preview",
                return_value=cme.ImportApplyResult(1, "updated"),
            ) as apply_preview,
        ):
            window._write_multiimport_item(
                cme.ImportPreview(title="Kniha", authors="Autor"), Path("b.epub")
            )

        # Bez pripravy davky zustava puvodni chovani (backend si zalohuje sam).
        self.assertIsNone(apply_preview.call_args.kwargs["backup_func"])
        app.processEvents()

    def _make_analysis(self):
        return cme.ImportAnalysis(
            epub_path="b.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )

    def test_legacy_import_epub_button_is_hidden_but_handler_remains_available(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertTrue(hasattr(window, "import_button"))
        self.assertEqual(window.import_button.toolTip(), "Import knihy")
        self.assertTrue(window.import_button.isHidden())
        self.assertTrue(callable(window.start_epub_import))
        app.processEvents()

    def test_toolbar_has_unified_import_skeleton_button(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertTrue(hasattr(window, "unified_import_button"))
        self.assertEqual(window.unified_import_button.toolTip(), "Unified import")
        app.processEvents()

    def test_unified_import_handler_cancel_does_not_save_or_start_import(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with (
            patch.object(qt, "UnifiedImportDialog") as dialog_class,
            patch.object(qt, "save_unified_import_last_folder") as save_folder,
            patch.object(qt, "save_unified_import_dialog_state") as save_dialog_state,
            patch.object(window, "write_output") as write_output,
            patch.object(window, "start_epub_import") as start_import,
            patch.object(window, "run_multiimport_analysis") as run_multiimport,
        ):
            dialog = dialog_class.return_value
            dialog.exec.return_value = QDialog.DialogCode.Rejected
            dialog.export_ui_state.return_value = {"size": [900, 600]}
            window.on_unified_import_clicked()

        save_folder.assert_not_called()
        save_dialog_state.assert_called_once_with({"size": [900, 600]})
        write_output.assert_called_once_with("Unified import: zruseno.")
        start_import.assert_not_called()
        run_multiimport.assert_not_called()
        app.processEvents()

    def test_unified_import_handler_routes_one_file_to_existing_single_import(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.epub"
            book.write_text("x", encoding="utf-8")
            with (
                patch.object(qt, "UnifiedImportDialog") as dialog_class,
                patch.object(qt, "unified_import_start_folder", return_value=root),
                patch.object(qt, "save_unified_import_last_folder") as save_folder,
                patch.object(qt, "save_unified_import_dialog_state") as save_dialog_state,
                patch.object(window, "write_output") as write_output,
                patch.object(window, "save_csv", return_value=True) as save_csv,
                patch.object(window, "start_epub_import") as start_import,
                patch.object(window, "run_multiimport_analysis") as run_multiimport,
            ):
                dialog = dialog_class.return_value
                dialog.exec.return_value = QDialog.DialogCode.Accepted
                dialog.current_folder = root
                dialog.selected_files = (book,)
                dialog.export_ui_state.return_value = {"size": [900, 600]}
                window.on_unified_import_clicked()

            save_folder.assert_called_once_with(root)
            save_dialog_state.assert_called_once_with({"size": [900, 600]})
            write_output.assert_called_once_with(f"Unified import: 1 soubor -> single import.\n{book.absolute()}")
            save_csv.assert_called_once_with(show_message=False)
            start_import.assert_called_once_with(str(book.absolute()))
            run_multiimport.assert_not_called()
        app.processEvents()

    def test_unified_import_handler_routes_multiple_files_to_existing_multiimport(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.epub"
            second = root / "b.mobi"
            first.write_text("x", encoding="utf-8")
            second.write_text("x", encoding="utf-8")
            with (
                patch.object(qt, "UnifiedImportDialog") as dialog_class,
                patch.object(qt, "unified_import_start_folder", return_value=root),
                patch.object(qt, "save_unified_import_last_folder") as save_folder,
                patch.object(qt, "save_unified_import_dialog_state") as save_dialog_state,
                patch.object(window, "write_output") as write_output,
                patch.object(window, "save_csv") as save_csv,
                patch.object(window, "start_epub_import") as start_import,
                patch.object(window, "run_multiimport_analysis") as run_multiimport,
            ):
                dialog = dialog_class.return_value
                dialog.exec.return_value = QDialog.DialogCode.Accepted
                dialog.current_folder = root
                dialog.selected_files = (second, first)
                dialog.export_ui_state.return_value = {"size": [900, 600]}
                window.on_unified_import_clicked()

            save_folder.assert_called_once_with(root)
            save_dialog_state.assert_called_once_with({"size": [900, 600]})
            write_output.assert_called_once_with("Unified import: 2 soubory -> multiimport.")
            save_csv.assert_not_called()
            start_import.assert_not_called()
            run_multiimport.assert_called_once_with([first.absolute(), second.absolute()])
        app.processEvents()

    def test_unified_import_continues_when_last_folder_cannot_be_saved(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.epub"
            book.write_text("x", encoding="utf-8")
            with (
                patch.object(qt, "UnifiedImportDialog") as dialog_class,
                patch.object(qt, "unified_import_start_folder", return_value=root),
                patch.object(qt, "save_unified_import_last_folder", side_effect=OSError("read only")),
                patch.object(qt.QMessageBox, "warning") as warning,
                patch.object(window, "save_csv", return_value=True),
                patch.object(window, "start_epub_import") as start_import,
            ):
                dialog = dialog_class.return_value
                dialog.exec.return_value = QDialog.DialogCode.Accepted
                dialog.current_folder = root
                dialog.selected_files = (book,)
                window.on_unified_import_clicked()

            warning.assert_called_once()
            start_import.assert_called_once_with(str(book.absolute()))
        app.processEvents()

    def test_unified_single_route_aborts_when_working_data_save_fails(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book.epub"
            book.write_text("x", encoding="utf-8")
            with (
                patch.object(window, "save_csv", return_value=False),
                patch.object(window, "start_epub_import") as start_import,
            ):
                window._route_unified_import_files([book])

            start_import.assert_not_called()
        app.processEvents()

    def test_legacy_multiimport_menu_is_hidden_but_handlers_remain_available(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertNotIn(
            "Multiimport",
            [action.text() for action in window.menuBar().actions()],
        )
        self.assertFalse(hasattr(window, "multiimport_files_action"))
        self.assertFalse(hasattr(window, "multiimport_folder_action"))
        self.assertTrue(callable(window.choose_multiimport_files))
        self.assertTrue(callable(window.choose_multiimport_folder))
        app.processEvents()

    def test_multiimport_files_picker_collects_files_and_starts_batch_analysis(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        selected = ["C:/books/b.epub", "C:/books/a.mobi"]
        collected = [Path("C:/books/a.mobi"), Path("C:/books/b.epub")]

        with (
            patch.object(qt.QFileDialog, "getOpenFileNames", return_value=(selected, "")) as picker,
            patch.object(cme, "collect_import_files_from_paths", return_value=collected) as collect,
            patch.object(window, "run_multiimport_analysis") as analyze,
        ):
            window.choose_multiimport_files()

        picker.assert_called_once_with(window, "Vyber knihy", "", qt.book_import_file_filter())
        collect.assert_called_once_with([Path(path) for path in selected])
        analyze.assert_called_once_with(collected)
        app.processEvents()

    def test_multiimport_folder_picker_collects_files_and_starts_batch_analysis(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        folder = "C:/books"
        collected = [Path("C:/books/a.azw3")]

        with (
            patch.object(qt.QFileDialog, "getExistingDirectory", return_value=folder) as picker,
            patch.object(cme, "collect_import_files_from_folder", return_value=collected) as collect,
            patch.object(window, "run_multiimport_analysis") as analyze,
        ):
            window.choose_multiimport_folder()

        picker.assert_called_once_with(window, "Vyber slozku s knihami", "")
        collect.assert_called_once_with(Path(folder))
        analyze.assert_called_once_with(collected)
        app.processEvents()

    def test_multiimport_analysis_reuses_single_import_analyzer_without_writing(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analysis = self._make_analysis()
        calls = []

        def analyze(path):
            progress = progress_dialog.return_value
            self.assertTrue(progress.show_prepared.called)
            calls.append(path)
            return analysis

        scheduled = []

        with (
            patch.object(window, "_build_import_analyze_callable", return_value=analyze) as build_analyzer,
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt.QApplication, "processEvents") as process_events,
            patch.object(qt, "ImportReviewDialog") as results_dialog,
            patch.object(cme, "apply_import_preview") as apply_preview,
            patch.object(window, "run_import_apply") as run_apply,
        ):
            progress = progress_dialog.return_value
            progress.run_after_first_paint.side_effect = scheduled.append
            progress.exec.side_effect = lambda: scheduled.pop(0)()
            items = window.run_multiimport_analysis(
                [Path("C:/books/book.epub")],
                connectivity_check=lambda: True,
            )

        build_analyzer.assert_called_once_with()
        self.assertEqual(calls, [str(Path("C:/books/book.epub"))])
        self.assertEqual(items[0].status, "needs_review")
        self.assertFalse(items[0].checked_for_import)
        progress_dialog.assert_called_once_with(
            1,
            window,
            title="Průběh načítání",
            initial_text="Připravuji analýzu…",
            progress_prefix="Analyzuji",
        )
        progress = progress_dialog.return_value
        progress.run_after_first_paint.assert_called_once()
        progress.show_prepared.assert_called_once_with()
        progress.update_progress.assert_called_once_with(1, 1, "book.epub")
        progress.accept.assert_called_once_with()
        results_dialog.assert_called_once_with(items, parent=window)
        results_dialog.return_value.exec.assert_called_once_with()
        apply_preview.assert_not_called()
        run_apply.assert_not_called()
        app.processEvents()

    def test_multiimport_analysis_offline_continue_runs_progress_and_results(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analysis = self._make_analysis()
        calls = []

        def analyze(path):
            calls.append(path)
            return analysis

        scheduled = []

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as question,
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt.QApplication, "processEvents"),
            patch.object(qt, "ImportReviewDialog") as results_dialog,
            patch.object(cme, "apply_import_preview") as apply_preview,
            patch.object(window, "run_import_apply") as run_apply,
        ):
            progress_dialog.return_value.run_after_first_paint.side_effect = scheduled.append
            progress_dialog.return_value.exec.side_effect = lambda: scheduled.pop(0)()
            items = window.run_multiimport_analysis(
                [Path("C:/books/book.epub")],
                analyze=analyze,
                connectivity_check=lambda: False,
            )

        question.assert_called_once_with(
            window,
            "Bez připojení k internetu",
            "Zdá se, že počítač není online. Online vyhledávání metadat může selhat "
            "nebo vrátit neúplné výsledky.\n\nChcete v analýze pokračovat?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self.assertEqual(calls, [str(Path("C:/books/book.epub"))])
        progress_dialog.assert_called_once()
        results_dialog.assert_called_once_with(items, parent=window)
        results_dialog.return_value.exec.assert_called_once_with()
        apply_preview.assert_not_called()
        run_apply.assert_not_called()
        app.processEvents()

    def test_multiimport_analysis_offline_cancel_stops_before_progress_and_analysis(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        calls = []

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.No,
            ) as question,
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt, "ImportReviewDialog") as results_dialog,
        ):
            items = window.run_multiimport_analysis(
                [Path("C:/books/book.epub")],
                analyze=lambda path: calls.append(path),
                connectivity_check=lambda: False,
            )

        question.assert_called_once()
        self.assertEqual(calls, [])
        self.assertEqual([item.status for item in items], ["pending"])
        progress_dialog.assert_not_called()
        results_dialog.assert_not_called()
        app.processEvents()

    def test_multiimport_analysis_connectivity_error_uses_offline_warning(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        def fail_check():
            raise RuntimeError("probe failed")

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.No,
            ) as question,
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt, "ImportReviewDialog") as results_dialog,
        ):
            items = window.run_multiimport_analysis(
                [Path("C:/books/book.epub")],
                analyze=lambda _path: self._make_analysis(),
                connectivity_check=fail_check,
            )

        question.assert_called_once()
        self.assertEqual([item.status for item in items], ["pending"])
        progress_dialog.assert_not_called()
        results_dialog.assert_not_called()
        app.processEvents()

    def test_review_tab_does_not_expose_original_publisher_control(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertNotIn("Originalni vydavatel", window.review_data_edits)
        self.assertNotIn("Originalni vydavatel", qt.REVIEW_EDITABLE_FIELDS)
        app.processEvents()

    def test_review_tab_exposes_series_rows_as_read_only(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertIn("Serie", window.review_data_labels)
        self.assertIn("Cislo serie", window.review_data_labels)
        self.assertNotIn("Serie", window.review_data_edits)
        self.assertNotIn("Cislo serie", window.review_data_edits)
        app.processEvents()

    def test_toolbar_right_buttons_follow_requested_order(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        right_tooltips = {
            "Unified import",
            "Obalky",
            "Najit / overit odkaz",
            "Nacist z Calibre",
            "Smazat z Calibre",
            "Zapsat",
        }
        self.assertEqual(
            [button.toolTip() for button in window.buttons if button.toolTip() in right_tooltips],
            [
                "Unified import",
                "Obalky",
                "Najit / overit odkaz",
                "Nacist z Calibre",
                "Smazat z Calibre",
                "Zapsat",
            ],
        )
        app.processEvents()

    def test_import_epub_button_enabled_on_fresh_idle_window_without_rows(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = []
        window.refresh_table()

        self.assertFalse(window.worker_running)
        self.assertEqual(window.selected_book_ids(), set())
        self.assertTrue(window.import_button.isEnabled())
        app.processEvents()

    def test_import_epub_button_reenabled_after_ui_enable_cycle_without_selection(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = []
        window.refresh_table()

        window.set_ui_enabled(False)
        self.assertFalse(window.import_button.isEnabled())
        window.set_ui_enabled(True)

        self.assertEqual(window.selected_book_ids(), set())
        self.assertTrue(window.import_button.isEnabled())
        app.processEvents()

    def test_import_epub_button_reenabled_after_background_reload_cycle(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = []
        window.refresh_table()
        window.worker_running = True
        window.set_ui_enabled(False)

        with patch.object(window, "load_csv", side_effect=lambda show_message=False: window.refresh_table()):
            window.finish_background("Nacist z Calibre", 0, "", reload_after=True)

        self.assertFalse(window.worker_running)
        self.assertEqual(window.selected_book_ids(), set())
        self.assertTrue(window.import_button.isEnabled())
        app.processEvents()

    def test_legacy_import_epub_button_invokes_start_epub_import(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with patch.object(window, "start_epub_import") as start_import:
            window.import_button.click()

        start_import.assert_called_once_with()
        app.processEvents()

    def test_legacy_import_epub_button_uses_file_picker(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with (
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "_choose_epub_file", return_value="") as choose_file,
        ):
            window.import_button.click()

        choose_file.assert_called_once_with()
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_clicking_import_epub_cancel_without_rows_exits_cleanly(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = []
        window.refresh_table()

        with (
            patch.object(window, "save_csv", return_value=True),
            patch.object(window, "_choose_epub_file", return_value=""),
        ):
            window.import_button.click()

        self.assertEqual(window.selected_book_ids(), set())
        self.assertFalse(window.worker_running)
        self.assertTrue(window.import_button.isEnabled())
        app.processEvents()

    def test_import_epub_click_still_works_after_ui_enable_cycle(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.set_ui_enabled(False)
        self.assertFalse(window.import_button.isEnabled())
        window.set_ui_enabled(True)

        with patch.object(window, "start_epub_import") as start_import:
            window.import_button.click()

        start_import.assert_called_once_with()
        app.processEvents()

    def test_start_epub_import_skips_when_no_path_selected(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analyze_calls = []

        def fake_runner(target):
            analyze_calls.append("runner")
            target()

        with (
            patch.object(window, "save_csv", return_value=True),
            patch.object(qt.QFileDialog, "getOpenFileName", return_value=("", "")),
        ):
            window.start_epub_import(analyze=lambda p: analyze_calls.append("analyze"), runner=fake_runner)

        self.assertEqual(analyze_calls, [])
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_start_epub_import_opens_review_dialog_with_batch_of_one(self):
        # Single import jde pres sjednoceny dialog jako davka o jedne polozce.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.status_checks["review"].setChecked(False)
        window.status_checks["skip"].setChecked(True)
        analysis = self._make_analysis()
        captured = {}

        class FakeDialog:
            def __init__(self, passed_items, parent=None, **kwargs):
                captured["items"] = passed_items
                captured["parent"] = parent

            def exec(self):
                captured["exec"] = True
                return 0

        def fake_runner(target):
            target()

        with patch.object(qt, "ImportReviewDialog", FakeDialog):
            window.start_epub_import(
                "book.epub",
                analyze=lambda path: analysis,
                runner=fake_runner,
            )
            app.processEvents()

        items = captured.get("items")
        self.assertEqual(len(items), 1)
        self.assertIs(items[0].analysis, analysis)
        self.assertEqual(items[0].current_preview, analysis.preview)
        self.assertIs(captured.get("parent"), window)
        self.assertTrue(captured.get("exec"))
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_single_import_warns_when_ai_layer_failed(self):
        # Multi tuhle hlasku ukazuje davno; single ji dosud nemel a na mrtvou AI
        # se prislo jen tak, ze detekce byla zahadne horsi.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window._last_ai_resolver = SimpleNamespace(last_error="doslo kredit")
        analysis = self._make_analysis()

        class FakeDialog:
            def __init__(self, _items, parent=None, **kwargs):
                pass

            def exec(self):
                return 0

        def fake_runner(target):
            target()

        with (
            patch.object(qt, "ImportReviewDialog", FakeDialog),
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.start_epub_import(
                "book.epub",
                analyze=lambda path: analysis,
                runner=fake_runner,
            )
            app.processEvents()

        warning.assert_called_once()
        self.assertIn("doslo kredit", warning.call_args.args[2])
        app.processEvents()

    def test_start_epub_import_shows_warning_on_analysis_failure(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        def boom(path):
            raise RuntimeError("rozbity epub")

        def fake_runner(target):
            target()

        with (
            patch.object(qt, "ImportReviewDialog") as dialog_class,
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.start_epub_import("book.epub", analyze=boom, runner=fake_runner)
            app.processEvents()

        dialog_class.assert_not_called()
        warning.assert_called_once()
        self.assertIn("rozbity epub", warning.call_args.args[2])
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_default_import_analyze_uses_ollama_resolver_and_text_limit(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analysis = self._make_analysis()
        captured = {}

        def fake_run_import_analysis(epub, library, settings, ai_resolver=None):
            captured["epub"] = epub
            captured["library"] = library
            captured["settings"] = settings
            captured["resolver"] = ai_resolver
            return analysis

        def fake_runner(target):
            target()

        ai_payload = {"ai": {"provider": "ollama", "model": "llama-test", "text_limit": 2222}}
        with (
            patch.object(qt, "run_import_analysis", side_effect=fake_run_import_analysis),
            patch.object(qt, "read_app_settings", return_value=ai_payload),
            patch.object(qt, "ImportReviewDialog"),
        ):
            window.start_epub_import("kniha.epub", runner=fake_runner)
            app.processEvents()

        self.assertEqual(captured["epub"], "kniha.epub")
        self.assertEqual(captured["settings"]["epub_text_limit"], 2222)
        self.assertIn("ebook_meta_path", captured["settings"])
        self.assertIn("ebook_convert_path", captured["settings"])
        self.assertIsInstance(captured["resolver"], cme.OllamaAIResolver)
        self.assertEqual(captured["resolver"].model, "llama-test")
        app.processEvents()

    def test_default_import_analyze_uses_disabled_resolver_when_ai_off(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analysis = self._make_analysis()
        captured = {}

        def fake_run_import_analysis(epub, library, settings, ai_resolver=None):
            captured["resolver"] = ai_resolver
            captured["settings"] = settings
            return analysis

        def fake_runner(target):
            target()

        with (
            patch.object(qt, "run_import_analysis", side_effect=fake_run_import_analysis),
            patch.object(qt, "read_app_settings", return_value={"ai": {"provider": "off"}}),
            patch.object(qt, "ImportReviewDialog"),
        ):
            window.start_epub_import("kniha.epub", runner=fake_runner)
            app.processEvents()

        self.assertIsInstance(captured["resolver"], cme.DisabledAIResolver)
        self.assertEqual(captured["settings"]["epub_text_limit"], 5000)
        self.assertIn("ebook_meta_path", captured["settings"])
        self.assertIn("ebook_convert_path", captured["settings"])
        app.processEvents()

    def test_interactive_import_saves_csv_before_choosing_file(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        order = []

        def fake_save_csv(show_message=False):
            order.append("save_csv")
            return True

        def fake_open(*args, **kwargs):
            order.append("open_file")
            return ("", "")

        with (
            patch.object(window, "save_csv", side_effect=fake_save_csv),
            patch.object(qt.QFileDialog, "getOpenFileName", side_effect=fake_open),
        ):
            window.start_epub_import()

        self.assertEqual(order, ["save_csv", "open_file"])
        app.processEvents()

    def test_interactive_import_aborts_when_save_csv_fails(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with (
            patch.object(window, "save_csv", return_value=False) as save_csv,
            patch.object(qt.QFileDialog, "getOpenFileName") as open_file,
        ):
            window.start_epub_import()

        save_csv.assert_called_once()
        open_file.assert_not_called()
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_should_auto_import_only_at_full_match_without_duplicates(self):
        import calibre_meta_qt as qt

        full = cme.ImportCandidate("databazeknih", "Kniha", "", "https://dk/x", score=100)
        partial = cme.ImportCandidate("databazeknih", "Kniha", "", "https://dk/y", score=70)
        dup = cme.DuplicateCandidate(book_id=1, title="Kniha", authors="Autor", score=100)

        self.assertTrue(qt.should_auto_import(self._make_analysis_with(candidates=[full], duplicates=[])))
        self.assertFalse(qt.should_auto_import(self._make_analysis_with(candidates=[partial], duplicates=[])))
        self.assertFalse(qt.should_auto_import(self._make_analysis_with(candidates=[full], duplicates=[dup])))
        self.assertFalse(qt.should_auto_import(self._make_analysis_with(candidates=[], duplicates=[])))

    def _make_analysis_with(self, candidates, duplicates):
        return cme.ImportAnalysis(
            epub_path="b.epub",
            signals=[],
            candidates=candidates,
            recommended=None,
            duplicates=duplicates,
            preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )

    def test_auto_import_at_full_match_skips_dialog_and_applies(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        full = cme.ImportCandidate("databazeknih", "Kniha", "", "https://dk/x", score=100)
        preview = cme.ImportPreview(title="Kniha", authors="Autor", url="https://dk/x")
        analysis = cme.ImportAnalysis(
            epub_path="b.epub",
            signals=[],
            candidates=[full],
            recommended=full,
            duplicates=[],
            preview=preview,
            messages=[],
        )
        dialog_created = {"n": 0}

        class FakeDialog:
            def __init__(self, _analysis, parent=None, **kwargs):
                dialog_created["n"] += 1

            def exec(self):
                return 0

        def fake_runner(target):
            target()

        with (
            patch.object(qt, "ImportReviewDialog", FakeDialog),
            patch.object(window, "run_import_apply") as apply_stub,
        ):
            window.start_epub_import("kniha.epub", analyze=lambda path: analysis, runner=fake_runner)
            app.processEvents()

        self.assertEqual(dialog_created["n"], 0)
        apply_stub.assert_called_once()
        called_preview, _called_path = apply_stub.call_args.args
        self.assertIs(called_preview, preview)
        app.processEvents()

    def test_accepted_import_dialog_calls_no_write_apply_stub(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analysis = self._make_analysis()
        edited_preview = cme.ImportPreview(title="Upraveno", authors="Editor")

        class FakeDialog:
            def __init__(self, _analysis, parent=None, **kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def preview(self):
                return edited_preview

        def fake_runner(target):
            target()

        with (
            patch.object(qt, "ImportReviewDialog", FakeDialog),
            patch.object(window, "run_import_apply") as apply_stub,
        ):
            window.start_epub_import(
                "kniha.epub",
                analyze=lambda path: analysis,
                runner=fake_runner,
            )
            app.processEvents()

        apply_stub.assert_called_once()
        called_preview, called_path = apply_stub.call_args.args
        self.assertIs(called_preview, edited_preview)
        self.assertEqual(Path(str(called_path)), Path("b.epub"))
        app.processEvents()

    def test_run_import_apply_blocks_invalid_preview(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        apply_calls = []

        def fake_runner(target):
            apply_calls.append("runner")
            target()

        def fake_apply(prev, ep):
            apply_calls.append("apply")
            return cme.ImportApplyResult(0, "updated")

        with patch.object(qt.QMessageBox, "warning") as warning:
            window.run_import_apply(
                cme.ImportPreview(title="", authors=""),
                Path("kniha.epub"),
                apply_func=fake_apply,
                runner=fake_runner,
            )

        warning.assert_called_once()
        self.assertEqual(apply_calls, [])
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_run_import_apply_success_reloads_csv_and_restores_ui(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.status_checks["review"].setChecked(False)
        window.status_checks["skip"].setChecked(True)
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=99, status="updated", error="", backup_path="C:/back.db")
        captured = {}

        def fake_apply(prev, ep):
            captured["preview"] = prev
            captured["path"] = ep
            return result

        def fake_runner(target):
            target()

        with (
            patch.object(window, "load_csv") as load_csv,
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "information") as info,
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=fake_apply,
                runner=fake_runner,
            )
            app.processEvents()

        self.assertIs(captured["preview"], preview)
        self.assertEqual(captured["path"], Path("kniha.epub"))
        load_csv.assert_called_once_with(show_message=False)
        info.assert_not_called()
        warning.assert_not_called()
        self.assertTrue(window.status_checks["review"].isChecked())
        self.assertFalse(window.status_checks["skip"].isChecked())
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_run_import_apply_success_triggers_cover_audit_for_book(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=99, status="updated", error="", backup_path="C:/back.db")

        def fake_apply(prev, ep):
            return result

        def fake_runner(target):
            target()

        with (
            patch.object(window, "load_csv"),
            patch.object(window, "run_background") as run_bg,
            patch.object(qt.shared, "make_cover_args") as mk_args,
            patch.object(qt.shared, "make_cover_audit_action"),
            patch.object(qt.QMessageBox, "information"),
        ):
            window.run_import_apply(preview, Path("kniha.epub"), apply_func=fake_apply, runner=fake_runner)
            app.processEvents()

        mk_args.assert_called_once()
        self.assertIn(99, mk_args.call_args.args[1])
        run_bg.assert_called_once()
        app.processEvents()

    def test_run_import_apply_failed_does_not_trigger_cover_audit(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=0, status="failed", error="boom", backup_path="")

        def fake_apply(prev, ep):
            return result

        def fake_runner(target):
            target()

        with (
            patch.object(window, "run_background") as run_bg,
            patch.object(qt.QMessageBox, "warning"),
        ):
            window.run_import_apply(preview, Path("kniha.epub"), apply_func=fake_apply, runner=fake_runner)
            app.processEvents()

        run_bg.assert_not_called()
        app.processEvents()

    def test_run_import_apply_success_reload_shows_imported_review_row(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.auto_skip_filter_allowed = False
        window.status_checks["approve"].setChecked(True)
        window.status_checks["review"].setChecked(False)
        window.status_checks["skip"].setChecked(True)
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=99, status="updated", error="", backup_path="C:/back.db")
        imported = cme.MatchRow(99, "Kniha", "Autor", "review", "", "", "imported", "imported")

        def fake_apply(prev, ep):
            return result

        def fake_runner(target):
            target()

        def fake_load_csv(show_message=False):
            window.rows = [imported]
            window.refresh_table()

        with (
            patch.object(window, "load_csv", side_effect=fake_load_csv),
            patch.object(qt.QMessageBox, "information"),
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=fake_apply,
                runner=fake_runner,
            )
            app.processEvents()

        self.assertTrue(window.status_checks["review"].isChecked())
        self.assertFalse(window.status_checks["skip"].isChecked())
        self.assertTrue(window.status_checks["approve"].isChecked())
        self.assertEqual(window.table.rowCount(), 1)
        self.assertEqual(window.table.item(0, 3).text(), "review")
        app.processEvents()

    def test_run_import_apply_success_leaves_approve_unchanged(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.status_checks["approve"].setChecked(False)
        window.status_checks["review"].setChecked(False)
        window.status_checks["skip"].setChecked(True)
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=99, status="updated", error="", backup_path="C:/back.db")

        def fake_apply(prev, ep):
            return result

        def fake_runner(target):
            target()

        with (
            patch.object(window, "load_csv"),
            patch.object(qt.QMessageBox, "information"),
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=fake_apply,
                runner=fake_runner,
            )
            app.processEvents()

        self.assertTrue(window.status_checks["review"].isChecked())
        self.assertFalse(window.status_checks["skip"].isChecked())
        self.assertFalse(window.status_checks["approve"].isChecked())
        app.processEvents()

    def test_run_import_apply_success_shows_no_success_messagebox(self):
        # Po uspesnem importu uz nechceme modalni potvrzeni; staci log + status.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=99, status="updated", error="", backup_path="C:/back.db")

        def fake_apply(prev, ep):
            return result

        def fake_runner(target):
            target()

        with (
            patch.object(window, "load_csv") as load_csv,
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "information") as info,
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=fake_apply,
                runner=fake_runner,
            )
            app.processEvents()

        info.assert_not_called()
        warning.assert_not_called()
        load_csv.assert_called_once_with(show_message=False)
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_run_import_apply_failed_status_shows_warning_and_no_reload(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.status_checks["review"].setChecked(False)
        window.status_checks["skip"].setChecked(True)
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(
            book_id=0, status="failed", error="add-failed", backup_path="C:/back.db"
        )

        def fake_apply(prev, ep):
            return result

        def fake_runner(target):
            target()

        with (
            patch.object(window, "load_csv") as load_csv,
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "information") as info,
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=fake_apply,
                runner=fake_runner,
            )
            app.processEvents()

        load_csv.assert_not_called()
        info.assert_not_called()
        warning.assert_called_once()
        self.assertIn("add-failed", warning.call_args.args[2])
        self.assertFalse(window.status_checks["review"].isChecked())
        self.assertTrue(window.status_checks["skip"].isChecked())
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_run_import_apply_strong_duplicate_shows_actionable_hint(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        result = cme.ImportApplyResult(book_id=0, status="failed", error="strong-duplicate", backup_path="")

        with (
            patch.object(window, "load_csv"),
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=lambda prev, ep: result,
                runner=lambda target: target(),
            )
            app.processEvents()

        warning.assert_called_once()
        self.assertIn("Importovat i pres duplicitu", warning.call_args.args[2])
        app.processEvents()

    def test_run_import_apply_exception_shows_warning_and_restores_ui(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")

        def boom(prev, ep):
            raise RuntimeError("calibredb chybi")

        def fake_runner(target):
            target()

        with (
            patch.object(window, "load_csv") as load_csv,
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                apply_func=boom,
                runner=fake_runner,
            )
            app.processEvents()

        load_csv.assert_not_called()
        warning.assert_called_once()
        self.assertIn("calibredb chybi", warning.call_args.args[2])
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_run_import_apply_default_path_uses_apply_import_preview_and_quit_calibre(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")
        captured = {}

        def fake_apply_import_preview(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return cme.ImportApplyResult(book_id=11, status="updated", backup_path="b.db")

        def fake_runner(target):
            target()

        with (
            patch.object(cme, "apply_import_preview", side_effect=fake_apply_import_preview),
            patch.object(cme, "find_calibredb", return_value="C:/Calibre2/calibredb.exe"),
            patch.object(window, "load_csv"),
            patch.object(window, "run_background"),
            patch.object(qt.QMessageBox, "information"),
        ):
            window.run_import_apply(
                preview,
                Path("kniha.epub"),
                runner=fake_runner,
                allow_force=False,
            )
            app.processEvents()

        kwargs = captured["kwargs"]
        self.assertEqual(captured["args"][0], preview)
        self.assertEqual(captured["args"][1], Path("kniha.epub"))
        self.assertEqual(kwargs["calibredb_path"], "C:/Calibre2/calibredb.exe")
        self.assertEqual(kwargs["allow_force"], False)
        self.assertTrue(callable(kwargs["quit_func"]))
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_run_import_apply_warns_when_calibredb_missing(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        preview = cme.ImportPreview(title="Kniha", authors="Autor")

        with (
            patch.object(cme, "find_calibredb", return_value=None),
            patch.object(cme, "apply_import_preview") as apply_call,
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            window.run_import_apply(preview, Path("kniha.epub"))

        apply_call.assert_not_called()
        warning.assert_called_once()
        self.assertFalse(window.worker_running)
        app.processEvents()

    def test_rejected_import_dialog_does_not_call_apply_stub(self):
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        analysis = self._make_analysis()

        class FakeDialog:
            def __init__(self, _analysis, parent=None, **kwargs):
                pass

            def exec(self):
                window.status_checks["review"].setChecked(False)
                window.status_checks["skip"].setChecked(True)
                return QDialog.DialogCode.Rejected

            def preview(self):
                raise AssertionError("preview should not be read on rejection")

        def fake_runner(target):
            target()

        with (
            patch.object(qt, "ImportReviewDialog", FakeDialog),
            patch.object(window, "run_import_apply") as apply_stub,
        ):
            window.start_epub_import(
                "kniha.epub",
                analyze=lambda path: analysis,
                runner=fake_runner,
            )
            app.processEvents()

        apply_stub.assert_not_called()
        self.assertFalse(window.status_checks["review"].isChecked())
        self.assertTrue(window.status_checks["skip"].isChecked())
        app.processEvents()


class ImportReviewDialogTests(unittest.TestCase):
    """Faze 1 sjednoceneho import dialogu: postaveny vedle starych, nezapojeny."""

    def _app(self):
        from PySide6.QtWidgets import QApplication
        import sys

        return QApplication.instance() or QApplication(sys.argv)

    def _analysis(
        self,
        *,
        title="Kniha",
        authors="Autor",
        url="https://dk/1",
        candidates=None,
        signals=None,
        duplicates=None,
    ):
        if candidates is None:
            candidates = [cme.ImportCandidate("databazeknih", title, authors, url, score=100)]
        return cme.ImportAnalysis(
            epub_path="book.epub",
            signals=signals or [],
            candidates=candidates,
            recommended=candidates[0] if candidates else None,
            duplicates=duplicates or [],
            preview=cme.ImportPreview(title=title, authors=authors, url=url),
            messages=[],
        )

    def _item(self, name="book.epub", **analysis_kwargs):
        return cme.build_single_import_batch_item(self._analysis(**analysis_kwargs), name)

    def test_single_item_hides_list_selection_and_filter(self):
        app = self._app()
        import calibre_meta_qt as qt

        dialog = qt.ImportReviewDialog([self._item()])

        self.assertTrue(dialog.single)
        # Cely levy sloupec (seznam, vyber, filtr, prehled) je pryc.
        self.assertTrue(dialog.left_panel.isHidden())
        # Pravy detail zustava.
        self.assertFalse(dialog.title_edit.isHidden())
        self.assertFalse(dialog.authors_edit.isHidden())
        app.processEvents()

    def test_multiple_items_show_list_selection_and_filter(self):
        app = self._app()
        import calibre_meta_qt as qt

        dialog = qt.ImportReviewDialog([self._item("a.epub"), self._item("b.epub")])

        self.assertFalse(dialog.single)
        self.assertFalse(dialog.left_panel.isHidden())
        self.assertFalse(dialog.items_table.isHidden())
        self.assertFalse(dialog.selection_buttons_widget.isHidden())
        self.assertFalse(dialog.filter_widget.isHidden())
        self.assertEqual(dialog.items_table.rowCount(), 2)
        app.processEvents()

    def test_rows_hold_item_identity_and_checkbox_follows_after_sort(self):
        from PySide6.QtCore import Qt

        app = self._app()
        import calibre_meta_qt as qt

        first = self._item("first.epub")
        second = self._item("second.epub")
        dialog = qt.ImportReviewDialog([first, second])

        self.assertIs(dialog._item_for_row(0), first)
        # Serazeni prehazi radky; identita se drzi v UserRole, ne v indexu.
        dialog.items_table.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.assertIs(dialog._item_for_row(0), second)

        # Zaskrtnuti radku 0 musi menit druhou knihu, ne prvni.
        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(second.checked_for_import)
        self.assertFalse(first.checked_for_import)
        app.processEvents()

    def test_empty_sections_start_collapsed_filled_expanded(self):
        app = self._app()
        import calibre_meta_qt as qt

        signal = cme.ImportSourceSignal(source="epub", title="Kniha", authors="Autor")
        item = self._item(signals=[signal])  # signaly a kandidati jsou, duplicity ne

        dialog = qt.ImportReviewDialog([item])

        self.assertTrue(dialog.signals_section.is_expanded())
        self.assertTrue(dialog.candidates_section.is_expanded())
        self.assertFalse(dialog.duplicates_section.is_expanded())
        app.processEvents()

    def test_editing_title_author_flushes_into_item_preview(self):
        app = self._app()
        import calibre_meta_qt as qt

        item = self._item()
        dialog = qt.ImportReviewDialog([item])

        dialog.title_edit.setText("Novy nazev")
        dialog.authors_edit.setText("Novy autor")
        preview = dialog.preview()

        self.assertEqual(preview.title, "Novy nazev")
        self.assertEqual(preview.authors, "Novy autor")
        self.assertEqual(item.current_preview.title, "Novy nazev")
        self.assertEqual(item.current_preview.authors, "Novy autor")
        app.processEvents()

    def test_switching_rows_saves_previous_edits_and_loads_next(self):
        app = self._app()
        import calibre_meta_qt as qt

        a = self._item("a.epub")
        b = self._item("b.epub", title="Kniha B")
        dialog = qt.ImportReviewDialog([a, b])

        dialog.title_edit.setText("Upraveno A")
        dialog.items_table.setCurrentCell(1, 0)

        self.assertEqual(a.current_preview.title, "Upraveno A")
        self.assertEqual(dialog.title_edit.text(), "Kniha B")
        app.processEvents()

    def test_selecting_candidate_previews_fields_without_committing(self):
        # Klik na kandidata je jen zivy nahled: pole se prepisou, ale polozka se
        # nepotvrdi ani nezaskrtne (to udela az "Pouzit kandidata").
        app = self._app()
        import calibre_meta_qt as qt

        cand = cme.ImportCandidate(
            "databazeknih", "Nahled nazev", "Nahled autor", "https://dk/nahled", score=40
        )
        item = self._item(candidates=[cand])
        dialog = qt.ImportReviewDialog([item])

        dialog.candidates_list.setCurrentRow(0)

        self.assertEqual(dialog.title_edit.text(), "Nahled nazev")
        self.assertEqual(dialog.authors_edit.text(), "Nahled autor")
        self.assertEqual(dialog.url_edit.text(), "https://dk/nahled")
        self.assertFalse(item.manually_confirmed)
        self.assertFalse(item.checked_for_import)
        app.processEvents()

    def test_using_candidate_updates_preview_and_checks_item(self):
        app = self._app()
        import calibre_meta_qt as qt

        cand = cme.ImportCandidate("databazeknih", "Vybrana", "Autor X", "https://dk/9", score=40)
        item = self._item(candidates=[cand])
        dialog = qt.ImportReviewDialog([item])

        dialog.candidates_list.setCurrentRow(0)
        dialog.use_selected_candidate()

        self.assertIs(item.selected_candidate, cand)
        self.assertTrue(item.manually_confirmed)
        self.assertTrue(item.checked_for_import)
        self.assertEqual(dialog.title_edit.text(), "Vybrana")
        self.assertEqual(item.current_preview.url, "https://dk/9")
        app.processEvents()

    def test_status_filter_hides_nonmatching_rows(self):
        app = self._app()
        import calibre_meta_qt as qt

        ready = self._item("ready.epub")  # status "ready"
        review = self._item("review.epub", candidates=[
            cme.ImportCandidate("databazeknih", "X", "Y", "https://dk/2", score=40)
        ])  # low score -> "needs_review"
        dialog = qt.ImportReviewDialog([ready, review])

        self.assertIn("ready", dialog.status_checks)
        # Odznaci "needs_review" -> radek review.epub se skryje.
        dialog.status_checks["needs_review"].setChecked(False)

        self.assertFalse(dialog.items_table.isRowHidden(dialog._row_for_item(ready)))
        self.assertTrue(dialog.items_table.isRowHidden(dialog._row_for_item(review)))
        app.processEvents()

    def test_section_titles_show_counts(self):
        app = self._app()
        import calibre_meta_qt as qt

        signal = cme.ImportSourceSignal(source="epub", title="Kniha", authors="Autor")
        dup = cme.DuplicateCandidate(1, "Kniha", "Autor", strong=True)
        item = self._item(signals=[signal], duplicates=[dup])
        dialog = qt.ImportReviewDialog([item])

        self.assertEqual(dialog.signals_section.toggle_button.text(), "Signály (1)")
        self.assertEqual(dialog.candidates_section.toggle_button.text(), "Kandidáti (1)")
        self.assertEqual(dialog.duplicates_section.toggle_button.text(), "Duplicity (1)")
        app.processEvents()

    def test_batch_import_button_shows_checked_count(self):
        from PySide6.QtCore import Qt

        app = self._app()
        import calibre_meta_qt as qt

        a = self._item("a.epub")
        b = self._item("b.epub")
        dialog = qt.ImportReviewDialog([a, b], write_one=lambda preview, path: None)

        self.assertEqual(dialog.import_button.text(), "Importovat (0)")
        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(dialog.import_button.text(), "Importovat (1)")
        self.assertTrue(dialog.import_button.isEnabled())
        app.processEvents()

    def test_candidate_label_is_single_line_with_url_in_tooltip(self):
        # URL na druhem radku zdvojnasobovala vysku kazdeho kandidata. Kompaktni
        # jeden radek; URL do tooltipu a porad dostupna pres "Otevrit odkaz".
        app = self._app()
        import calibre_meta_qt as qt

        cand = cme.ImportCandidate(
            "databazeknih", "Na vlnach Orinoka", "Jules Verne", "https://dk/933", score=100
        )
        dialog = qt.ImportReviewDialog([self._item(candidates=[cand])])

        list_item = dialog.candidates_list.item(0)
        self.assertNotIn("\n", list_item.text())
        self.assertIn("100%", list_item.text())
        self.assertIn("Na vlnach Orinoka", list_item.text())
        self.assertEqual(list_item.toolTip(), "https://dk/933")
        app.processEvents()

    def test_using_candidate_enriches_preview_from_candidate_detail(self):
        # Parita se starym single dialogem: kandidat nese detail (rok, vydavatel,
        # serie, tagy, obalku) a ten se musi propsat do nahledu, ne jen nazev/autor.
        app = self._app()
        import calibre_meta_qt as qt

        detail = cme.BookDetailMetadata(
            published_year="2001",
            publisher="Argo",
            series="Serie",
            series_index="2",
            tags=["fantasy", "epos"],
            cover_url="https://dk/cover.jpg",
        )
        cand = cme.ImportCandidate(
            "databazeknih", "Vybrana", "Autor X", "https://dk/9", score=40, detail=detail
        )
        item = self._item(candidates=[cand])
        dialog = qt.ImportReviewDialog([item])

        dialog.candidates_list.setCurrentRow(0)
        dialog.use_selected_candidate()

        self.assertEqual(item.current_preview.published_year, "2001")
        self.assertEqual(item.current_preview.publisher, "Argo")
        self.assertEqual(item.current_preview.series, "Serie")
        self.assertEqual(item.current_preview.series_index, "2")
        self.assertEqual(item.current_preview.tags, "fantasy, epos")
        self.assertEqual(item.current_preview.selected_cover_url, "https://dk/cover.jpg")
        app.processEvents()

    def test_dialog_exposes_bottom_action_buttons(self):
        app = self._app()
        import calibre_meta_qt as qt

        dialog = qt.ImportReviewDialog([self._item()])

        for attr in ("backup_check", "validate_button", "export_button", "import_button", "close_button"):
            self.assertTrue(hasattr(dialog, attr), f"chybi {attr}")
        self.assertEqual(dialog.import_button.text(), "Importovat")
        app.processEvents()

    def test_analysis_error_item_disables_detail_editing(self):
        app = self._app()
        import calibre_meta_qt as qt

        item = cme.MultiImportBatchItem(Path("bad.epub"), "bad.epub")
        item.status = "analysis_error"
        item.error_message = "rozbite"

        dialog = qt.ImportReviewDialog([item])

        self.assertFalse(dialog.title_edit.isEnabled())
        self.assertFalse(dialog.candidates_list.isEnabled())
        app.processEvents()

    # --- pokryti prenesene z byvalych ImportDialog/MultiImportResultsDialog testu ---

    def test_bulk_selection_safe_all_clear(self):
        app = self._app()
        import calibre_meta_qt as qt

        safe = self._item("safe.epub")  # 100% bez duplicit -> "ready"
        review = self._item("review.epub", candidates=[
            cme.ImportCandidate("databazeknih", "X", "Y", "https://dk/2", score=40)
        ])  # nizke skore -> "needs_review"
        dialog = qt.ImportReviewDialog([safe, review])

        dialog.select_all_items()
        self.assertTrue(safe.checked_for_import)
        self.assertTrue(review.checked_for_import)

        dialog.clear_selected_items()
        self.assertFalse(safe.checked_for_import)
        self.assertFalse(review.checked_for_import)

        dialog.select_safe_items()
        self.assertTrue(safe.checked_for_import)
        self.assertFalse(review.checked_for_import)
        app.processEvents()

    def test_validate_selection_shows_summary(self):
        app = self._app()
        import calibre_meta_qt as qt

        dialog = qt.ImportReviewDialog([self._item()])
        with patch.object(qt.QMessageBox, "information") as info:
            dialog.validate_selection()
        info.assert_called_once()
        app.processEvents()

    def test_export_csv_writes_report(self):
        app = self._app()
        import calibre_meta_qt as qt

        dialog = qt.ImportReviewDialog([self._item()])
        with (
            patch.object(qt.QFileDialog, "getSaveFileName", return_value=("out.csv", "")),
            patch.object(qt, "write_multiimport_csv_report") as writer,
            patch.object(qt.QMessageBox, "information"),
        ):
            dialog.export_csv()
        writer.assert_called_once()
        app.processEvents()

    def test_import_checked_items_runs_batch_write(self):
        from PySide6.QtWidgets import QMessageBox

        app = self._app()
        import calibre_meta_qt as qt

        item = self._item()
        item.checked_for_import = True
        writes = []

        def write_one(preview, path):
            writes.append(path)
            return cme.ImportApplyResult(book_id=1, status="updated")

        dialog = qt.ImportReviewDialog(
            [item],
            write_one=write_one,
            connectivity_check=lambda: True,
            prepare_backup=lambda enabled: None,
        )
        scheduled = []
        with (
            patch.object(qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt.QApplication, "processEvents"),
        ):
            progress_dialog.return_value.run_after_first_paint.side_effect = scheduled.append
            progress_dialog.return_value.exec.side_effect = lambda: scheduled.pop(0)()
            dialog.import_checked_items()

        self.assertEqual(len(writes), 1)
        app.processEvents()

    def test_manual_url_builds_candidate_and_checks_item(self):
        app = self._app()
        import calibre_meta_qt as qt

        item = self._item()
        detail = cme.BookDetailMetadata()

        def fake_link(url):
            return ("Titul z odkazu", "Autor z odkazu", "https://dk/manual", detail)

        dialog = qt.ImportReviewDialog(
            [item],
            link_data_func=fake_link,
            runner=lambda target: target(),
            duplicate_finder=lambda preview: [],
        )
        dialog.manual_url_edit.setText("https://dk/manual")
        dialog.start_use_link()

        self.assertTrue(item.manually_confirmed)
        self.assertTrue(item.checked_for_import)
        self.assertEqual(item.current_preview.url, "https://dk/manual")
        app.processEvents()

    def test_research_replaces_candidates(self):
        app = self._app()
        import calibre_meta_qt as qt

        item = self._item()
        new_cands = [cme.ImportCandidate("databazeknih", "Novy", "Autor", "https://dk/new", score=80)]
        dialog = qt.ImportReviewDialog(
            [item],
            search_func=lambda title, authors: new_cands,
            runner=lambda target: target(),
            duplicate_finder=lambda preview: [],
        )
        dialog.start_research()

        self.assertEqual(item.analysis.candidates, new_cands)
        self.assertEqual(dialog.candidates_list.count(), 1)
        app.processEvents()

    def test_allow_duplicate_flushes_into_preview(self):
        app = self._app()
        import calibre_meta_qt as qt

        item = self._item(duplicates=[cme.DuplicateCandidate(1, "K", "A", strong=True)])
        dialog = qt.ImportReviewDialog([item])

        self.assertTrue(dialog.allow_duplicate_check.isEnabled())
        dialog.allow_duplicate_check.setChecked(True)
        self.assertTrue(dialog.preview().allow_strong_duplicate)
        app.processEvents()
