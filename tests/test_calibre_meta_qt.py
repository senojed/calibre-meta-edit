# Testy hlidaji Qt app helpery bez otevirani grafickeho okna.

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import calibre_meta_edit as cme


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None


class QtHelperTests(unittest.TestCase):
    def test_qt_app_title_includes_version(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.APP_VERSION, "0.2.15")
        self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.2.15")

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

        self.assertEqual(text, "Ready | matches.csv nacteno | 0.2.15")

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


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class QtImportTests(unittest.TestCase):
    def test_qt_imports_when_pyside6_available(self):
        import calibre_meta_qt as qt

        self.assertIsNotNone(qt.CalibreMetaQtWindow)

    def test_qt_startup_preview_uses_single_shot_timer(self):
        import calibre_meta_qt as qt

        callback = object()
        with patch.object(qt.QTimer, "singleShot") as single_shot:
            qt.schedule_qt_startup_preview(callback)

        single_shot.assert_called_once_with(250, callback)
