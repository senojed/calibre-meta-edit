# Testy hlidaji Qt app helpery bez otevirani grafickeho okna.

import importlib.util
import unittest

import calibre_meta_edit as cme


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None


class QtHelperTests(unittest.TestCase):
    def test_qt_app_title_includes_version(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.APP_VERSION, "0.1.6")
        self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.1.6")

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

        self.assertEqual(text, "Ready | matches.csv nacteno | 0.1.6")

    def test_normalize_theme_accepts_only_known_values(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.normalize_theme("dark"), "dark")
        self.assertEqual(qt.normalize_theme("LIGHT"), "light")
        self.assertEqual(qt.normalize_theme("bad"), "system")

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


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class QtImportTests(unittest.TestCase):
    def test_qt_imports_when_pyside6_available(self):
        import calibre_meta_qt as qt

        self.assertIsNotNone(qt.CalibreMetaQtWindow)
