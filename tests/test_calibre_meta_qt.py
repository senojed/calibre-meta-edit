# Testy hlidaji Qt app helpery bez otevirani grafickeho okna.

import csv
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
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

        self.assertEqual(qt.APP_VERSION, "0.4.7")
        self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.4.7")

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
            "invalid_preview": "Náhled importu není validní.",
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

        self.assertEqual(text, "Ready | pracovni data nactena | 0.4.7")

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

    def test_normalize_ai_settings_defaults_to_off(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({})

        self.assertEqual(settings, {"provider": "off", "model": "llama3", "text_limit": 5000, "timeout": 120})

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

    def test_multiimport_write_starts_after_prepared_progress_dialog_enters_event_loop(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._valid_multiimport_item(checked=True)
        events = []
        scheduled = []
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda _preview, _path: (
                events.append("write") or cme.ImportApplyResult(1, "updated")
            ),
        )

        def register(callback):
            events.append("registered")
            scheduled.append(callback)

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt, "MultiImportProgressDialog") as progress_class,
            patch.object(qt.QApplication, "processEvents"),
        ):
            progress = progress_class.return_value
            progress.run_after_first_paint.side_effect = register
            progress.show_prepared.side_effect = lambda: events.append("painted")
            progress.exec.side_effect = lambda: (events.append("event-loop"), scheduled.pop(0)())
            dialog.import_button.click()

        # Prace se registruje, pak se okno ukaze, a teprve po vstupu do event
        # loopu (kde probehne prvni paint) se spusti zapis. Zadna bila plocha.
        self.assertEqual(events[:4], ["registered", "painted", "event-loop", "write"])
        progress.run_after_first_paint.assert_called_once()
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

    def test_multiimport_results_manual_candidate_unlocks_import(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._needs_review_multiimport_item()
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda _preview, _path: cme.ImportApplyResult(1, "updated"),
        )

        self.assertEqual(dialog.candidates_list.count(), 2)
        dialog.candidates_list.setCurrentRow(1)
        dialog.use_selected_candidate()

        self.assertTrue(item.manually_confirmed)
        self.assertTrue(item.checked_for_import)
        self.assertEqual(item.current_preview.url, item.analysis.candidates[1].url)
        self.assertTrue(cme.validate_multiimport_checked_items([item]).ok)
        self.assertEqual(dialog.items_table.item(0, 1).text(), "W")
        app.processEvents()

    def test_multiimport_results_manual_url_confirms_item(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._needs_review_multiimport_item()
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda _preview, _path: cme.ImportApplyResult(1, "updated"),
        )

        dialog.manual_url_edit.setText("https://dk/custom")
        dialog.use_manual_url()

        self.assertTrue(item.manually_confirmed)
        self.assertTrue(item.checked_for_import)
        self.assertEqual(item.current_preview.url, "https://dk/custom")
        self.assertEqual(item.current_preview.title, "Kniha")
        self.assertTrue(cme.validate_multiimport_checked_items([item]).ok)
        app.processEvents()

    def test_multiimport_results_open_candidate_link_uses_desktop_services(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._needs_review_multiimport_item()
        dialog = qt.MultiImportResultsDialog([item])
        dialog.candidates_list.setCurrentRow(0)

        with patch.object(qt.QDesktopServices, "openUrl") as open_url:
            dialog.open_selected_candidate_link()

        open_url.assert_called_once()
        self.assertEqual(
            open_url.call_args.args[0].toString(),
            item.analysis.candidates[0].url,
        )
        app.processEvents()

    def test_multiimport_results_filters_hide_rows(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        ready = self._valid_multiimport_item("alfa.epub", checked=True)
        review = self._needs_review_multiimport_item("beta.epub")
        dialog = qt.MultiImportResultsDialog([ready, review])

        dialog.name_filter.setText("beta")
        self.assertTrue(dialog.items_table.isRowHidden(0))
        self.assertFalse(dialog.items_table.isRowHidden(1))

        dialog.name_filter.setText("")
        self.assertFalse(dialog.items_table.isRowHidden(0))
        self.assertFalse(dialog.items_table.isRowHidden(1))

        # Stav jako zaskrtavatka: necham jen 'ready' -> review radek zmizi.
        for status, check in dialog.status_checks.items():
            check.setChecked(status == "ready")
        self.assertFalse(dialog.items_table.isRowHidden(0))
        self.assertTrue(dialog.items_table.isRowHidden(1))

        # Vic stavu naraz: ready + needs_review -> oba viditelne.
        for status, check in dialog.status_checks.items():
            check.setChecked(status in ("ready", "needs_review"))
        self.assertFalse(dialog.items_table.isRowHidden(0))
        self.assertFalse(dialog.items_table.isRowHidden(1))

        for check in dialog.status_checks.values():
            check.setChecked(True)
        dialog.checked_filter.setCurrentIndex(dialog.checked_filter.findData(True))
        self.assertFalse(dialog.items_table.isRowHidden(0))
        self.assertTrue(dialog.items_table.isRowHidden(1))
        app.processEvents()

    def test_multiimport_results_candidate_controls_disabled_for_analysis_error(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._valid_multiimport_item()
        item.status = "analysis_error"
        item.analysis = None
        dialog = qt.MultiImportResultsDialog([item])

        self.assertEqual(dialog.candidates_list.count(), 0)
        self.assertFalse(dialog.candidates_list.isEnabled())
        self.assertFalse(dialog.use_manual_url_button.isEnabled())
        self.assertFalse(dialog.use_candidate_button.isEnabled())
        app.processEvents()

    def test_qt_imports_when_pyside6_available(self):
        import calibre_meta_qt as qt

        self.assertIsNotNone(qt.CalibreMetaQtWindow)

    def test_import_dialog_validates_title_and_author(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        self.assertFalse(dialog.import_button.isEnabled())
        dialog.title_edit.setText("Kniha")
        dialog.authors_edit.setText("Autor")
        dialog.update_import_enabled()

        self.assertTrue(dialog.import_button.isEnabled())
        app.processEvents()

    def test_multiimport_results_dialog_is_read_only_and_updates_details(self):
        from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidget
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        items = [
            cme.MultiImportBatchItem(
                Path("ready.epub"),
                "ready.epub",
                status="ready",
                current_preview=cme.ImportPreview(title="Ready", authors="Autor"),
            ),
            cme.MultiImportBatchItem(Path("review.epub"), "review.epub", status="needs_review"),
            cme.MultiImportBatchItem(
                Path("duplicate.epub"),
                "duplicate.epub",
                status="duplicate_warning",
                duplicates=[cme.DuplicateCandidate(5, "Duplicita", "Autor D.")],
            ),
            cme.MultiImportBatchItem(
                Path("error.epub"),
                "error.epub",
                status="analysis_error",
                error_message="analysis failed",
            ),
        ]

        dialog = qt.MultiImportResultsDialog(items)

        self.assertIsInstance(dialog.items_table, QTableWidget)
        self.assertEqual(dialog.items_table.rowCount(), 4)
        self.assertEqual(dialog.items_table.columnCount(), 3)
        self.assertEqual(
            [dialog.items_table.horizontalHeaderItem(column).text() for column in range(3)],
            ["Import", "Stav", "Soubor"],
        )
        self.assertEqual(
            [dialog.items_table.item(row, 1).text() for row in range(4)],
            ["✓", "👁", "⧉", "✕"],
        )
        self.assertEqual(
            [dialog.items_table.item(row, 1).toolTip() for row in range(4)],
            ["OK", "Kontrola", "Duplicita", "Chyba"],
        )
        self.assertEqual(
            dialog.items_table.horizontalHeader().sectionResizeMode(1),
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.assertFalse(dialog.items_table.isSortingEnabled())
        displayed_rows = [
            " | ".join(dialog.items_table.item(row, column).text() for column in range(3))
            for row in range(4)
        ]
        self.assertTrue(all("Predvybrano" not in row for row in displayed_rows))
        self.assertTrue(all("Předvybráno" not in row for row in displayed_rows))
        self.assertTrue(all("Duplicity:" not in row for row in displayed_rows))
        self.assertTrue(dialog.detail_text.isReadOnly())
        self.assertEqual(dialog.import_button.text(), "Importovat zaškrtnuté")
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertIn("Ready", dialog.detail_text.toPlainText())
        dialog.items_table.setCurrentCell(2, 0)
        self.assertIn("Duplicita", dialog.detail_text.toPlainText())
        dialog.items_table.setCurrentCell(3, 0)
        self.assertIn("analysis failed", dialog.detail_text.toPlainText())
        app.processEvents()

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

    def test_multiimport_results_dialog_initializes_checks_and_disables_errors(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        ready = cme.MultiImportBatchItem(
            Path("ready.epub"),
            "ready.epub",
            checked_for_import=True,
            status="ready",
        )
        error = cme.MultiImportBatchItem(
            Path("error.epub"),
            "error.epub",
            checked_for_import=True,
            status="analysis_error",
            error_message="failed",
        )

        dialog = qt.MultiImportResultsDialog([ready, error])

        self.assertEqual(dialog.items_table.item(0, 0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(dialog.items_table.item(1, 0).checkState(), Qt.CheckState.Unchecked)
        self.assertFalse(error.checked_for_import)
        self.assertFalse(
            dialog.items_table.item(1, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
        )
        self.assertEqual(dialog.selected_summary_label.text(), "Vybráno k importu: 1")
        app.processEvents()

    def test_multiimport_results_dialog_toggle_updates_model_summary_and_detail(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = cme.MultiImportBatchItem(Path("review.epub"), "review.epub", status="needs_review")
        dialog = qt.MultiImportResultsDialog([item])

        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Checked)

        self.assertTrue(item.checked_for_import)
        self.assertEqual(dialog.selected_summary_label.text(), "Vybráno k importu: 1")
        self.assertIn("Predvybrano: ano", dialog.detail_text.toPlainText())

        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)

        self.assertFalse(item.checked_for_import)
        self.assertEqual(dialog.selected_summary_label.text(), "Vybráno k importu: 0")
        app.processEvents()

    def test_multiimport_import_button_tracks_eligible_checked_items(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._valid_multiimport_item()
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda _preview, _path: cme.ImportApplyResult(1, "updated"),
        )

        self.assertFalse(dialog.import_button.isEnabled())
        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dialog.import_button.isEnabled())
        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(dialog.import_button.isEnabled())
        app.processEvents()

    def test_multiimport_validation_failure_blocks_writer_and_confirmation(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        valid = self._valid_multiimport_item("valid.epub", checked=True)
        invalid = self._valid_multiimport_item("review.epub", checked=True)
        invalid.status = "needs_review"
        writer_calls = []
        dialog = qt.MultiImportResultsDialog(
            [valid, invalid],
            write_one=lambda preview, path: writer_calls.append((preview, path)),
            post_write_refresh=lambda summary: writer_calls.append(("refresh", summary)),
        )

        with (
            patch.object(qt.QMessageBox, "warning") as warning,
            patch.object(qt.QMessageBox, "question") as question,
            patch.object(cme, "run_multiimport_batch_write") as run_write,
            patch.object(dialog, "accept") as accept,
        ):
            dialog.import_button.click()

        self.assertTrue(dialog.import_button.isEnabled())
        self.assertEqual(writer_calls, [])
        run_write.assert_not_called()
        question.assert_not_called()
        accept.assert_not_called()
        self.assertIn("Nic nebylo importováno.", warning.call_args.args[2])
        self.assertEqual([valid.status, invalid.status], ["ready", "needs_review"])
        app.processEvents()

    def test_multiimport_confirmation_cancel_does_not_run_writer(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._valid_multiimport_item(checked=True)
        writer_calls = []
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda preview, path: writer_calls.append((preview, path)),
            post_write_refresh=lambda summary: writer_calls.append(("refresh", summary)),
        )

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.No,
            ),
            patch.object(cme, "run_multiimport_batch_write") as run_write,
            patch.object(dialog, "accept") as accept,
        ):
            dialog.import_button.click()

        self.assertEqual(writer_calls, [])
        run_write.assert_not_called()
        accept.assert_not_called()
        self.assertEqual(item.status, "ready")
        app.processEvents()

    def test_multiimport_confirmation_runs_guarded_writer_and_refreshes_rows(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        first = self._valid_multiimport_item("first.epub", checked=True)
        ignored = self._valid_multiimport_item("ignored.epub", checked=False)
        second = self._valid_multiimport_item("second.epub", checked=True)
        events = []
        refresh_summaries = []
        real_validate = cme.validate_multiimport_checked_items

        def validate(items):
            events.append("validate")
            return real_validate(items)

        def write_one(_preview, path):
            events.append(f"write:{path.name}")
            if path == first.source_path:
                return cme.ImportApplyResult(book_id=41, status="updated")
            return cme.ImportApplyResult(book_id=0, status="failed", error="failed")

        dialog = qt.MultiImportResultsDialog(
            [first, ignored, second],
            write_one=write_one,
            post_write_refresh=refresh_summaries.append,
        )

        with (
            patch.object(cme, "validate_multiimport_checked_items", side_effect=validate),
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as question,
            patch.object(qt.QMessageBox, "information") as information,
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt.QApplication, "processEvents"),
            patch.object(dialog, "accept") as accept,
            patch.object(
                cme,
                "should_auto_import",
                side_effect=AssertionError("must not be called"),
                create=True,
            ),
        ):
            # Simuluje odpaleni prace az po prvnim vykresleni (paint-hook).
            progress_dialog.return_value.run_after_first_paint.side_effect = (
                lambda callback: callback()
            )
            dialog.import_button.click()

        self.assertEqual(events[0], "validate")
        self.assertGreaterEqual(events.count("validate"), 2)
        self.assertEqual(
            [event for event in events if event.startswith("write:")],
            ["write:first.epub", "write:second.epub"],
        )
        question.assert_called_once()
        self.assertEqual([first.status, ignored.status, second.status], ["written", "ready", "write_error"])
        self.assertEqual([first.calibre_id, ignored.calibre_id, second.calibre_id], [41, None, None])
        self.assertEqual(
            [dialog.items_table.item(row, 1).text() for row in range(3)],
            ["✓", "✓", "✕"],
        )
        self.assertEqual(dialog.items_table.item(0, 1).toolTip(), "Hotovo")
        self.assertEqual(dialog.items_table.item(2, 1).toolTip(), "Chyba zápisu")
        self.assertFalse(first.checked_for_import)
        self.assertFalse(second.checked_for_import)
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertEqual(len(refresh_summaries), 1)
        self.assertEqual(refresh_summaries[0].succeeded, 1)
        accept.assert_not_called()
        summary_text = information.call_args.args[2]
        self.assertIn("Pokusů: 2", summary_text)
        self.assertIn("Úspěšně: 1", summary_text)
        self.assertIn("Selhalo: 1", summary_text)
        progress = progress_dialog.return_value
        progress_dialog.assert_called_once_with(2, dialog)
        self.assertGreater(
            progress.method_calls.index(call.show_prepared()),
            progress.method_calls.index(call.prepare(2)),
        )
        progress.update_progress.assert_has_calls(
            [call(1, 2, "first.epub"), call(2, 2, "second.epub")]
        )
        progress.close.assert_called_once_with()
        progress.deleteLater.assert_called_once_with()
        app.processEvents()

    def test_multiimport_all_success_refreshes_and_closes_dialog(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._valid_multiimport_item(checked=True)
        refresh_summaries = []
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda _preview, _path: cme.ImportApplyResult(61, "updated"),
            post_write_refresh=refresh_summaries.append,
        )

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(qt.QMessageBox, "information") as information,
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt.QApplication, "processEvents"),
            patch.object(dialog, "accept") as accept,
        ):
            progress_dialog.return_value.run_after_first_paint.side_effect = (
                lambda callback: callback()
            )
            dialog.import_button.click()

        self.assertEqual(len(refresh_summaries), 1)
        self.assertTrue(refresh_summaries[0].ok)
        information.assert_called_once()
        accept.assert_called_once_with()
        app.processEvents()

    def test_multiimport_all_failure_stays_open_without_refresh(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = self._valid_multiimport_item(checked=True)
        refresh_summaries = []
        dialog = qt.MultiImportResultsDialog(
            [item],
            write_one=lambda _preview, _path: cme.ImportApplyResult(
                0, "failed", "write failed"
            ),
            post_write_refresh=refresh_summaries.append,
        )

        with (
            patch.object(
                qt.QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(qt.QMessageBox, "information"),
            patch.object(qt, "MultiImportProgressDialog") as progress_dialog,
            patch.object(qt.QApplication, "processEvents"),
            patch.object(dialog, "accept") as accept,
        ):
            progress_dialog.return_value.run_after_first_paint.side_effect = (
                lambda callback: callback()
            )
            dialog.import_button.click()

        self.assertEqual(refresh_summaries, [])
        self.assertEqual(item.status, "write_error")
        accept.assert_not_called()
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

    def test_multiimport_import_button_allows_checked_blocked_item_to_show_warning(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        item = cme.MultiImportBatchItem(Path("ready.epub"), "ready.epub", status="ready")
        dialog = qt.MultiImportResultsDialog([item], parent=window)

        self.assertEqual(dialog.import_button.text(), "Importovat zaškrtnuté")
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertIn("Vyberte alespoň jednu položku", dialog.import_button.toolTip())
        self.assertEqual(dialog.validate_button.text(), "Ověřit výběr")
        self.assertEqual(dialog.export_button.text(), "Exportovat CSV")

        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Checked)

        self.assertTrue(item.checked_for_import)
        self.assertTrue(dialog.import_button.isEnabled())
        with (
            patch.object(qt.QMessageBox, "warning") as warning,
            patch.object(cme, "apply_import_preview") as apply_preview,
            patch.object(window, "run_import_apply") as run_apply,
        ):
            dialog.import_button.click()

        self.assertIn("ready.epub: Chybí analýza", warning.call_args.args[2])
        self.assertIn("Nic nebylo importováno", warning.call_args.args[2])
        apply_preview.assert_not_called()
        run_apply.assert_not_called()
        app.processEvents()

    def test_multiimport_blocked_warning_lists_duplicate_unrecognized_and_ambiguous_reasons(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        duplicate = cme.MultiImportBatchItem(
            Path("duplicate.epub"),
            "duplicate.epub",
            checked_for_import=True,
            status="duplicate_warning",
            duplicates=[cme.DuplicateCandidate(7, "Existující", "Autor")],
        )
        unrecognized_analysis = cme.ImportAnalysis(
            epub_path="unknown.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Unknown", authors="Autor"),
            messages=[],
        )
        unrecognized = cme.MultiImportBatchItem(
            Path("unknown.epub"),
            "unknown.epub",
            checked_for_import=True,
            status="needs_review",
            analysis=unrecognized_analysis,
            current_preview=unrecognized_analysis.preview,
        )
        first = cme.ImportCandidate("databazeknih", "Kniha A", "Autor", "https://dk/1", score=100)
        second = cme.ImportCandidate("databazeknih", "Kniha B", "Autor", "https://dk/2", score=100)
        ambiguous_analysis = cme.ImportAnalysis(
            epub_path="ambiguous.epub",
            signals=[],
            candidates=[first, second],
            recommended=first,
            duplicates=[],
            preview=cme.ImportPreview(title="Kniha A", authors="Autor", url=first.url),
            messages=[],
        )
        ambiguous = cme.MultiImportBatchItem(
            Path("ambiguous.epub"),
            "ambiguous.epub",
            checked_for_import=True,
            status="needs_review",
            analysis=ambiguous_analysis,
            current_preview=ambiguous_analysis.preview,
            selected_candidate=first,
        )
        writer_calls = []
        dialog = qt.MultiImportResultsDialog(
            [duplicate, unrecognized, ambiguous],
            write_one=lambda preview, path: writer_calls.append((preview, path)),
        )

        with patch.object(qt.QMessageBox, "warning") as warning:
            dialog.import_button.click()

        message = warning.call_args.args[2]
        self.assertIn("duplicate.epub", message)
        self.assertIn("varování na duplicitu", message)
        self.assertIn("unknown.epub", message)
        self.assertIn("Chybí vybraný kandidát", message)
        self.assertIn("ambiguous.epub", message)
        self.assertIn("více různých kandidátů se 100% shodou", message)
        self.assertIn("bezpečně vybrat jednu", message)
        self.assertEqual(writer_calls, [])
        app.processEvents()

    def test_multiimport_results_dialog_exposes_bulk_selection_buttons(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        dialog = qt.MultiImportResultsDialog([])

        self.assertEqual(dialog.select_safe_button.text(), "Vybrat 100 %")
        self.assertEqual(dialog.select_all_button.text(), "Vybrat vše")
        self.assertEqual(dialog.clear_selection_button.text(), "Vše odznačit")
        self.assertFalse(dialog.import_button.isEnabled())
        app.processEvents()

    def test_multiimport_results_dialog_select_safe_checks_only_valid_ready_items(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        candidate = cme.ImportCandidate(
            source="databazeknih",
            title="Safe",
            authors="Autor",
            url="https://example.test/safe",
            score=100,
        )
        preview = cme.ImportPreview(
            title="Safe",
            authors="Autor",
            url="https://example.test/safe",
        )
        analysis = cme.ImportAnalysis(
            epub_path="safe.epub",
            signals=[],
            candidates=[candidate],
            recommended=candidate,
            duplicates=[],
            preview=preview,
            messages=[],
        )
        items = [
            cme.MultiImportBatchItem(
                Path("safe.epub"),
                "safe.epub",
                status="ready",
                analysis=analysis,
                current_preview=preview,
                selected_candidate=candidate,
            ),
            cme.MultiImportBatchItem(
                Path("review.epub"),
                "review.epub",
                checked_for_import=True,
                status="needs_review",
            ),
            cme.MultiImportBatchItem(
                Path("duplicate.epub"),
                "duplicate.epub",
                checked_for_import=True,
                status="duplicate_warning",
            ),
            cme.MultiImportBatchItem(
                Path("error.epub"),
                "error.epub",
                checked_for_import=True,
                status="analysis_error",
            ),
            cme.MultiImportBatchItem(
                Path("invalid.epub"),
                "invalid.epub",
                checked_for_import=True,
                status="ready",
            ),
        ]
        dialog = qt.MultiImportResultsDialog(items, parent=window)

        with (
            patch.object(cme, "apply_import_preview") as apply_preview,
            patch.object(window, "run_import_apply") as run_apply,
        ):
            dialog.select_safe_items()

        self.assertEqual([item.checked_for_import for item in items], [True, False, False, False, False])
        self.assertEqual(
            [dialog.items_table.item(row, 0).checkState() for row in range(5)],
            [Qt.CheckState.Checked] + [Qt.CheckState.Unchecked] * 4,
        )
        self.assertFalse(
            dialog.items_table.item(3, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
        )
        self.assertEqual(dialog.selected_summary_label.text(), "Vybráno k importu: 1")
        self.assertTrue(dialog.import_button.isEnabled())
        apply_preview.assert_not_called()
        run_apply.assert_not_called()
        app.processEvents()

    def test_multiimport_results_dialog_select_all_and_clear_update_selection_only(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        items = [
            cme.MultiImportBatchItem(Path("ready.epub"), "ready.epub", status="ready"),
            cme.MultiImportBatchItem(Path("review.epub"), "review.epub", status="needs_review"),
            cme.MultiImportBatchItem(
                Path("duplicate.epub"), "duplicate.epub", status="duplicate_warning"
            ),
            cme.MultiImportBatchItem(Path("error.epub"), "error.epub", status="analysis_error"),
        ]
        dialog = qt.MultiImportResultsDialog(items, parent=window)

        with (
            patch.object(cme, "apply_import_preview") as apply_preview,
            patch.object(window, "run_import_apply") as run_apply,
        ):
            dialog.select_all_items()
            self.assertEqual([item.checked_for_import for item in items], [True, True, True, False])
            self.assertEqual(dialog.selected_summary_label.text(), "Vybráno k importu: 3")
            self.assertTrue(dialog.import_button.isEnabled())

            dialog.clear_selected_items()

        self.assertEqual([item.checked_for_import for item in items], [False, False, False, False])
        self.assertTrue(
            all(
                dialog.items_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
                for row in range(4)
            )
        )
        self.assertEqual(dialog.selected_summary_label.text(), "Vybráno k importu: 0")
        self.assertFalse(dialog.import_button.isEnabled())
        apply_preview.assert_not_called()
        run_apply.assert_not_called()
        app.processEvents()

    def test_multiimport_results_dialog_exports_current_items(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        item = cme.MultiImportBatchItem(Path("book.epub"), "book.epub", status="ready")
        dialog = qt.MultiImportResultsDialog([item])
        dialog.items_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        output_path = "C:/reports/multiimport.csv"

        with (
            patch.object(qt.QFileDialog, "getSaveFileName", return_value=(output_path, "")) as picker,
            patch.object(qt, "write_multiimport_csv_report") as writer,
            patch.object(qt.QMessageBox, "information") as information,
        ):
            dialog.export_csv()

        self.assertEqual(dialog.export_button.text(), "Exportovat CSV")
        picker.assert_called_once_with(
            dialog,
            "Exportovat multiimport CSV",
            "multiimport-report.csv",
            "CSV soubory (*.csv)",
        )
        writer.assert_called_once_with(Path(output_path), dialog.items)
        self.assertTrue(item.checked_for_import)
        information.assert_called_once()
        app.processEvents()

    def test_multiimport_results_dialog_cancelled_export_does_not_write(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        dialog = qt.MultiImportResultsDialog([])

        with (
            patch.object(qt.QFileDialog, "getSaveFileName", return_value=("", "")),
            patch.object(qt, "write_multiimport_csv_report") as writer,
        ):
            dialog.export_csv()

        writer.assert_not_called()
        app.processEvents()

    def test_multiimport_results_dialog_reports_export_error(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        dialog = qt.MultiImportResultsDialog([])

        with (
            patch.object(qt.QFileDialog, "getSaveFileName", return_value=("C:/reports/report.csv", "")),
            patch.object(qt, "write_multiimport_csv_report", side_effect=OSError("disk full")),
            patch.object(qt.QMessageBox, "warning") as warning,
        ):
            dialog.export_csv()

        self.assertIn("disk full", warning.call_args.args[2])
        app.processEvents()

    def test_multiimport_results_dialog_validates_current_selection_without_writing(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        item = cme.MultiImportBatchItem(
            Path("book.epub"),
            "book.epub",
            checked_for_import=True,
            status="needs_review",
        )
        dialog = qt.MultiImportResultsDialog([item], parent=window)
        result = cme.MultiImportValidationResult(
            [],
            [cme.MultiImportValidationIssue(item, "status_not_ready")],
        )

        with (
            patch.object(cme, "validate_multiimport_checked_items", return_value=result) as validate,
            patch.object(qt.QMessageBox, "information") as information,
            patch.object(cme, "apply_import_preview") as apply_preview,
            patch.object(window, "run_import_apply") as run_apply,
        ):
            dialog.validate_selection()

        self.assertEqual(dialog.validate_button.text(), "Ověřit výběr")
        self.assertTrue(dialog.import_button.isEnabled())
        validate.assert_called_once_with(dialog.items)
        self.assertTrue(item.checked_for_import)
        self.assertIn("Položka není ve stavu Připraveno.", information.call_args.args[2])
        apply_preview.assert_not_called()
        run_apply.assert_not_called()
        app.processEvents()

    def test_import_dialog_returns_preview_with_edited_title_author(self):
        # Dialog je zjednoduseny: uzivatel edituje jen nazev a autora.
        # Zbyle pole (publisher, comment, ...) se berou z puvodniho preview.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Stary", authors="Autor", publisher="Vydavatel", comment="Popis"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)
        dialog.title_edit.setText("Novy")

        preview = dialog.preview()

        self.assertEqual(preview.title, "Novy")
        self.assertEqual(preview.authors, "Autor")
        # Nezobrazena pole zustavaji zachovana z puvodniho preview.
        self.assertEqual(preview.publisher, "Vydavatel")
        self.assertEqual(preview.comment, "Popis")
        app.processEvents()

    def test_import_dialog_has_no_editable_metadata_fields(self):
        # Zjednoduseny dialog uz nesmi vystavovat siroky editor metadat.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        # url_edit je ZAMERNE editovatelne (rucni vlozeni odkazu) - neni v seznamu.
        for removed in ("series_edit", "series_index_edit", "year_edit", "publisher_edit", "tags_edit", "comment_edit"):
            self.assertFalse(hasattr(dialog, removed), f"{removed} ma byt odstraneno")
        app.processEvents()

    def test_import_dialog_candidate_score_display_includes_percent(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[cme.ImportCandidate("databazeknih", "Kniha", "Autor", "https://x", score=42)],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        self.assertTrue(dialog.candidates_list.item(0).text().startswith("42% databazeknih:"))
        app.processEvents()

    def test_import_dialog_low_score_candidate_can_be_manually_applied(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        detail = cme.BookDetailMetadata(published_year="1990", publisher="Talpress", tags=["Fantasy", "Humor"])
        candidate = cme.ImportCandidate("databazeknih", "Kandidat", "Autor", "https://x", score=12, detail=detail)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Puvodni", authors="Puvodni autor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)
        dialog.candidates_list.setCurrentRow(0)

        dialog.apply_selected_candidate()

        # Nazev/autor se promitnou do editovatelnych poli.
        self.assertEqual(dialog.title_edit.text(), "Kandidat")
        self.assertEqual(dialog.authors_edit.text(), "Autor")
        # URL se promitne do editovatelneho pole.
        self.assertEqual(dialog.url_edit.text(), "https://x")
        # Obohacena metadata (rok, vydavatel, tagy) jdou interne do preview().
        preview = dialog.preview()
        self.assertEqual(preview.url, "https://x")
        self.assertEqual(preview.published_year, "1990")
        self.assertEqual(preview.publisher, "Talpress")
        self.assertEqual(preview.tags, "Fantasy, Humor")
        app.processEvents()

    def test_import_dialog_double_clicking_candidate_populates_preview_fields(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        candidate = cme.ImportCandidate("openlibrary", "Manual", "Autor", "https://manual", score=5)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)
        item = dialog.candidates_list.item(0)
        dialog.candidates_list.setCurrentItem(item)

        dialog.candidates_list.itemDoubleClicked.emit(item)

        self.assertEqual(dialog.title_edit.text(), "Manual")
        self.assertEqual(dialog.authors_edit.text(), "Autor")
        self.assertEqual(dialog.url_edit.text(), "https://manual")
        self.assertEqual(dialog.preview().url, "https://manual")
        app.processEvents()

    def test_import_dialog_use_candidate_button_state_and_click(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        candidate = cme.ImportCandidate("openlibrary", "Manual", "Autor", "https://manual", score=5)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        self.assertFalse(dialog.use_candidate_button.isEnabled())
        dialog.candidates_list.setCurrentRow(0)
        self.assertTrue(dialog.use_candidate_button.isEnabled())
        dialog.use_candidate_button.click()

        self.assertEqual(dialog.title_edit.text(), "Manual")
        self.assertEqual(dialog.url_edit.text(), "https://manual")
        self.assertEqual(dialog.preview().url, "https://manual")
        app.processEvents()

    def test_import_dialog_open_link_button_state_tracks_url(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        candidate = cme.ImportCandidate("openlibrary", "Manual", "Autor", "https://example.test/book", score=5)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        # Bez URL je tlacitko vypnute; po aplikaci kandidata s URL se zapne.
        self.assertFalse(dialog.open_link_button.isEnabled())
        dialog.candidates_list.setCurrentRow(0)
        dialog.apply_selected_candidate()
        self.assertTrue(dialog.open_link_button.isEnabled())
        app.processEvents()

    def test_import_dialog_open_link_button_opens_current_url(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(url="https://example.test/book"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        with patch.object(qt.QDesktopServices, "openUrl", return_value=True) as open_url:
            dialog.open_link_button.click()

        opened = open_url.call_args.args[0]
        self.assertIsInstance(opened, QUrl)
        self.assertEqual(opened.toString(), "https://example.test/book")
        app.processEvents()

    def test_import_dialog_open_link_ignores_empty_url(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        with patch.object(qt.QDesktopServices, "openUrl") as open_url:
            dialog.open_current_url()

        open_url.assert_not_called()
        app.processEvents()

    def test_import_dialog_manual_url_flows_into_preview(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Hrr na ne", authors="Terry Pratchett"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        dialog.url_edit.setText("https://www.databazeknih.cz/knihy/x")
        self.assertEqual(dialog.preview().url, "https://www.databazeknih.cz/knihy/x")
        self.assertTrue(dialog.open_link_button.isEnabled())
        app.processEvents()

    def test_import_dialog_research_repopulates_candidates(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Hrr", authors="Terry Pratchett"),
            messages=[],
        )
        found = [cme.ImportCandidate("databazeknih", "Hrrr na ně!", "", "https://dk/x", score=100)]
        captured = {}

        def fake_search(title, authors):
            captured["title"] = title
            captured["authors"] = authors
            return found

        dialog = qt.ImportDialog(analysis, search_func=fake_search, runner=lambda target: target())
        dialog.title_edit.setText("Hrrr na ně!")
        dialog.start_research()

        self.assertEqual(captured["title"], "Hrrr na ně!")
        self.assertEqual(dialog.candidates_list.count(), 1)
        self.assertIn("Hrrr na ně!", dialog.candidates_list.item(0).text())
        app.processEvents()

    def test_import_dialog_use_link_enriches_preview(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Strata", authors="Terry Pratchett"),
            messages=[],
        )
        detail = cme.BookDetailMetadata(published_year="1981", publisher="Talpress", tags=["fantasy"], about_text="popis", cover_url="https://dk/cover.jpg")
        url = "https://www.databazeknih.cz/knihy/strata-17178"
        dialog = qt.ImportDialog(
            analysis,
            runner=lambda target: target(),
            link_data_func=lambda u: ("Strata", "Terry Pratchett", url, detail),
            search_func=lambda title, authors: [],
        )
        dialog.url_edit.setText(url)
        dialog.start_use_link()

        result = dialog.preview()
        self.assertEqual(result.title, "Strata")
        self.assertEqual(result.authors, "Terry Pratchett")
        self.assertEqual(result.published_year, "1981")
        self.assertEqual(result.publisher, "Talpress")
        self.assertEqual(result.url, url)
        self.assertIn("fantasy", result.tags)
        self.assertEqual(result.selected_cover_url, "https://dk/cover.jpg")
        app.processEvents()

    def test_import_dialog_use_link_fixes_title_and_author_from_catalog(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="HRR NA NE", authors=""),
            messages=[],
        )
        url = "https://www.databazeknih.cz/knihy/hrrr-na-ne-471"
        found = [cme.ImportCandidate("databazeknih", "Hrrr na ně!", "", "https://dk/hrrr", score=100)]
        dups = [cme.DuplicateCandidate(book_id=471, title="Hrrr na ně!", authors="Terry Pratchett", score=100)]
        dialog = qt.ImportDialog(
            analysis,
            runner=lambda target: target(),
            link_data_func=lambda u: ("Hrrr na ně!", "Terry Pratchett", url, cme.BookDetailMetadata()),
            search_func=lambda title, authors: found,
            duplicate_func=lambda preview: dups,
        )
        dialog.url_edit.setText(url)
        dialog.start_use_link()

        self.assertEqual(dialog.title_edit.text(), "Hrrr na ně!")
        self.assertEqual(dialog.authors_edit.text(), "Terry Pratchett")
        # Po opraveni se automaticky prehledalo: kandidati i duplicity.
        self.assertEqual(dialog.candidates_list.count(), 1)
        self.assertEqual(dialog.duplicates_list.count(), 1)
        app.processEvents()

    def test_import_dialog_use_link_skips_when_url_empty(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Strata", authors="Terry Pratchett"),
            messages=[],
        )
        called = {"n": 0}

        def fake_link_data(url):
            called["n"] += 1
            return ("", "", "u", cme.BookDetailMetadata())

        dialog = qt.ImportDialog(analysis, runner=lambda target: target(), link_data_func=fake_link_data)
        dialog.url_edit.setText("")
        dialog.start_use_link()

        self.assertEqual(called["n"], 0)
        app.processEvents()

    def test_import_dialog_allow_duplicate_checkbox_sets_preview_flag(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        dup = cme.DuplicateCandidate(book_id=1, title="Kniha", authors="Autor", score=100)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[dup],
            preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        # S duplicitou je zatrzitko aktivni; bez nej preview.allow_strong_duplicate False.
        self.assertTrue(dialog.allow_duplicate_check.isEnabled())
        self.assertFalse(dialog.preview().allow_strong_duplicate)
        dialog.allow_duplicate_check.setChecked(True)
        self.assertTrue(dialog.preview().allow_strong_duplicate)
        app.processEvents()

    def test_import_dialog_allow_duplicate_disabled_without_duplicates(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)
        self.assertFalse(dialog.allow_duplicate_check.isEnabled())
        app.processEvents()

    def test_import_dialog_allow_duplicate_keeps_user_choice_on_recompute(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        dup = cme.DuplicateCandidate(book_id=1, title="Kniha", authors="Autor", score=100)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[dup],
            preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)
        dialog.allow_duplicate_check.setChecked(True)
        # Prepocet duplicit (napr. po 'Hledat znovu') nesmi odskrtnout volbu uzivatele.
        dialog.populate_duplicates([])
        self.assertTrue(dialog.allow_duplicate_check.isChecked())
        app.processEvents()

    def test_import_dialog_research_skips_when_title_empty(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="", authors=""),
            messages=[],
        )
        called = {"n": 0}

        def fake_search(title, authors):
            called["n"] += 1
            return []

        dialog = qt.ImportDialog(analysis, search_func=fake_search, runner=lambda target: target())
        dialog.title_edit.setText("   ")
        dialog.start_research()

        self.assertEqual(called["n"], 0)
        app.processEvents()

    def test_import_dialog_using_candidate_does_not_accept_or_apply(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        candidate = cme.ImportCandidate("openlibrary", "Manual", "Autor", "https://manual", score=5)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)
        dialog.candidates_list.setCurrentRow(0)

        with patch.object(dialog, "accept") as accept:
            dialog.use_candidate_button.click()

        accept.assert_not_called()
        self.assertEqual(dialog.title_edit.text(), "Manual")
        app.processEvents()

    def test_import_dialog_accept_uses_final_preview(self):
        # Dialog lze potvrdit; preview() vraci aktualni rozhodnuti.
        from PySide6.QtWidgets import QApplication, QDialog
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Kniha", authors="Autor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        self.assertTrue(dialog.import_button.isEnabled())
        dialog.import_button.click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        preview = dialog.preview()
        self.assertEqual(preview.title, "Kniha")
        self.assertEqual(preview.authors, "Autor")
        app.processEvents()

    def test_import_dialog_using_candidate_updates_import_choice(self):
        # Vyber a pouziti kandidata zmeni preview pouzity pro import (URL, zdroj).
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        candidate = cme.ImportCandidate("databazeknih", "Spravny", "Autor", "https://spravny", score=88)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Fallback", authors="Fallback autor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        # Pred pouzitim kandidata drzi preview fallback.
        self.assertEqual(dialog.preview().title, "Fallback")
        dialog.candidates_list.setCurrentRow(0)
        dialog.apply_selected_candidate()

        preview = dialog.preview()
        self.assertEqual(preview.title, "Spravny")
        self.assertEqual(preview.authors, "Autor")
        self.assertEqual(preview.url, "https://spravny")
        self.assertEqual(preview.source, "databazeknih")
        self.assertEqual(dialog.source_label.text(), "databazeknih")
        app.processEvents()

    def test_import_dialog_preserves_candidate_series_metadata_without_controls(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        detail = cme.BookDetailMetadata(series="Nadace", series_index="2")
        candidate = cme.ImportCandidate("databazeknih", "Nadace", "Isaac Asimov", "https://x", detail=detail)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate],
            recommended=candidate,
            duplicates=[],
            preview=cme.ImportPreview(title="Nadace", authors="Isaac Asimov"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis, runner=lambda target: target())

        dialog.candidates_list.setCurrentRow(0)
        dialog.apply_selected_candidate()

        self.assertEqual(dialog.current_preview.series, "Nadace")
        self.assertEqual(dialog.current_preview.series_index, "2")
        self.assertFalse(hasattr(dialog, "series_edit"))
        self.assertFalse(hasattr(dialog, "series_index_edit"))
        app.processEvents()

    def test_import_dialog_switching_candidate_does_not_leak_hidden_metadata(self):
        # Kandidat A ma detail metadata; kandidat B ne. Po prepnuti z A na B
        # nesmi B podedit skryta metadata z A; ma padnout jen na base_preview.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        detail = cme.BookDetailMetadata(published_year="1990", publisher="Talpress", tags=["Fantasy", "Humor"], about_text="popis A")
        candidate_a = cme.ImportCandidate("databazeknih", "Kniha A", "Autor A", "https://a", score=80, detail=detail)
        candidate_b = cme.ImportCandidate("openlibrary", "Kniha B", "Autor B", "https://b", score=70)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate_a, candidate_b],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="Fallback", authors="Fallback autor", publisher="BaseVydavatel"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        # Aplikuj A -> preview ma detail metadata z A.
        dialog.candidates_list.setCurrentRow(0)
        dialog.apply_selected_candidate()
        preview_a = dialog.preview()
        self.assertEqual(preview_a.publisher, "Talpress")
        self.assertEqual(preview_a.tags, "Fantasy, Humor")
        self.assertEqual(preview_a.published_year, "1990")
        self.assertTrue(preview_a.comment)

        # Aplikuj B -> preview pouziva B, ale neprosaknou metadata z A.
        dialog.candidates_list.setCurrentRow(1)
        dialog.apply_selected_candidate()
        preview_b = dialog.preview()
        self.assertEqual(preview_b.title, "Kniha B")
        self.assertEqual(preview_b.authors, "Autor B")
        self.assertEqual(preview_b.url, "https://b")
        self.assertEqual(preview_b.source, "openlibrary")
        # Zadne A metadata.
        self.assertNotEqual(preview_b.publisher, "Talpress")
        self.assertEqual(preview_b.tags, "")
        self.assertEqual(preview_b.published_year, "")
        self.assertEqual(preview_b.comment, "")
        # Fallback jen na base_preview metadata.
        self.assertEqual(preview_b.publisher, "BaseVydavatel")
        app.processEvents()

    def test_import_dialog_candidate_without_title_uses_base_fallback(self):
        # Kandidat bez title/authors nesmi nechat stare viditelne hodnoty;
        # ma ukazat enriched/base fallback.
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        candidate_a = cme.ImportCandidate("databazeknih", "Kniha A", "Autor A", "https://a", score=80)
        candidate_empty = cme.ImportCandidate("openlibrary", "", "", "https://b", score=70)
        analysis = cme.ImportAnalysis(
            epub_path="book.epub",
            signals=[],
            candidates=[candidate_a, candidate_empty],
            recommended=None,
            duplicates=[],
            preview=cme.ImportPreview(title="BaseTitul", authors="BaseAutor"),
            messages=[],
        )
        dialog = qt.ImportDialog(analysis)

        dialog.candidates_list.setCurrentRow(0)
        dialog.apply_selected_candidate()
        self.assertEqual(dialog.title_edit.text(), "Kniha A")

        # Kandidat bez title/authors -> fallback na base, ne stale "Kniha A".
        dialog.candidates_list.setCurrentRow(1)
        dialog.apply_selected_candidate()
        self.assertEqual(dialog.title_edit.text(), "BaseTitul")
        self.assertEqual(dialog.authors_edit.text(), "BaseAutor")
        self.assertEqual(dialog.preview().url, "https://b")
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
            patch.object(qt, "MultiImportResultsDialog") as results_dialog,
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
            patch.object(qt, "MultiImportResultsDialog") as results_dialog,
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
            patch.object(qt, "MultiImportResultsDialog") as results_dialog,
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
            patch.object(qt, "MultiImportResultsDialog") as results_dialog,
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

    def test_start_epub_import_opens_dialog_with_analysis_on_success(self):
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
            def __init__(self, passed_analysis, parent=None, **kwargs):
                captured["analysis"] = passed_analysis
                captured["parent"] = parent

            def exec(self):
                captured["exec"] = True
                return 0

        def fake_runner(target):
            target()

        with patch.object(qt, "ImportDialog", FakeDialog):
            window.start_epub_import(
                "book.epub",
                analyze=lambda path: analysis,
                runner=fake_runner,
            )
            app.processEvents()

        self.assertIs(captured.get("analysis"), analysis)
        self.assertIs(captured.get("parent"), window)
        self.assertTrue(captured.get("exec"))
        self.assertFalse(window.worker_running)
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
            patch.object(qt, "ImportDialog") as dialog_class,
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
            patch.object(qt, "ImportDialog"),
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
            patch.object(qt, "ImportDialog"),
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
            patch.object(qt, "ImportDialog", FakeDialog),
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
            patch.object(qt, "ImportDialog", FakeDialog),
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
            patch.object(qt, "ImportDialog", FakeDialog),
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
