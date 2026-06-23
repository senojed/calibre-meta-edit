# Testy hlidaji Qt app helpery bez otevirani grafickeho okna.

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import calibre_meta_edit as cme


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ["CALIBRE_META_EDIT_TEST"] = "1"


class QtHelperTests(unittest.TestCase):
    def test_qt_app_title_includes_version(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.APP_VERSION, "0.4.4")
        self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.4.4")

    def test_book_import_filter_lists_all_supported_formats(self):
        import calibre_meta_qt as qt

        filter_text = qt.book_import_file_filter()
        for extension, _label in cme.BOOK_IMPORT_FORMATS:
            pattern = "*" + extension
            self.assertIn(pattern, filter_text)
        self.assertIn("EPUB (*.epub)", filter_text)
        self.assertIn("Vsechny soubory (*.*)", filter_text)

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

        self.assertEqual(text, "Ready | pracovni data nactena | 0.4.4")

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
        self.assertEqual(fields["Tagy"], "Fantasy, Humor")
        self.assertEqual(fields["Hodnoceni"], "87 %")
        self.assertEqual(fields["Originalni nazev"], "Moving Pictures")
        self.assertEqual(fields["Originalne vyslo"], "1990")
        self.assertNotIn("Originalni vydavatel", fields)

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


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class QtImportTests(unittest.TestCase):
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

    def test_toolbar_has_import_epub_button(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        self.assertTrue(hasattr(window, "import_button"))
        self.assertEqual(window.import_button.toolTip(), "Import knihy")
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

    def test_toolbar_right_buttons_follow_requested_order(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        right_tooltips = {
            "Import knihy",
            "Obalky",
            "Najit / overit odkaz",
            "Nacist z Calibre",
            "Smazat z Calibre",
            "Zapsat",
        }
        self.assertEqual(
            [button.toolTip() for button in window.buttons if button.toolTip() in right_tooltips],
            [
                "Import knihy",
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

    def test_clicking_visible_import_epub_button_invokes_start_epub_import(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        with patch.object(window, "start_epub_import") as start_import:
            window.import_button.click()

        start_import.assert_called_once_with()
        app.processEvents()

    def test_clicking_visible_import_epub_button_uses_file_picker(self):
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
