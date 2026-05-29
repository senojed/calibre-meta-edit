# Testy hlidaji logiku desktop appky bez otevirani grafickeho okna.

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import calibre_meta_app as app
import calibre_meta_edit as cme


class AppModelTests(unittest.TestCase):
    def test_app_title_includes_version(self):
        self.assertEqual(app.APP_VERSION, "0.0.6")
        self.assertEqual(app.app_title(), "Calibre Meta Edit 0.0.6")

    def test_open_url_in_new_window_uses_new_window_opener(self):
        calls = []

        result = app.open_url_in_new_window(
            "https://www.databazeknih.cz/knihy/foo-123",
            opener=lambda url: calls.append(url) or True,
        )

        self.assertTrue(result)
        self.assertEqual(calls, ["https://www.databazeknih.cz/knihy/foo-123"])

    def test_initial_library_path_prefers_saved_settings_then_calibre_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            calibre_config_path = Path(tmp) / "global.py.json"
            settings_path.write_text(json.dumps({"library_path": "D:\\Knihy"}), encoding="utf-8")
            calibre_config_path.write_text(json.dumps({"library_path": "E:\\Calibre"}), encoding="utf-8")

            selected = app.initial_library_path(settings_path, calibre_config_path)

        self.assertEqual(selected, "D:\\Knihy")

    def test_initial_library_path_uses_calibre_config_when_settings_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            calibre_config_path = Path(tmp) / "global.py.json"
            calibre_config_path.write_text(json.dumps({"library_path": "E:\\Calibre"}), encoding="utf-8")

            selected = app.initial_library_path(Path(tmp) / "missing.json", calibre_config_path)

        self.assertEqual(selected, "E:\\Calibre")

    def test_save_library_path_writes_settings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"

            app.save_library_path("D:\\Knihy", settings_path)

            data = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"library_path": "D:\\Knihy"})

    def test_make_script_args_uses_selected_library(self):
        args = app.make_script_args("D:\\Knihy")

        self.assertEqual(args.library, "D:\\Knihy")
        self.assertIsNone(args.book_id)
        self.assertIsNone(args.limit)
        self.assertEqual(args.sleep, 1.0)
        self.assertFalse(args.overwrite)

    def test_make_script_args_can_request_overwrite(self):
        args = app.make_script_args("D:\\Knihy", overwrite=True)

        self.assertTrue(args.overwrite)

    def test_button_colors_define_requested_status_and_apply_colors(self):
        self.assertEqual(app.button_colors("approve")["bg"], "#2e7d32")
        self.assertEqual(app.button_colors("review")["bg"], "#ef6c00")
        self.assertEqual(app.button_colors("skip")["bg"], "#757575")
        self.assertEqual(app.button_colors("apply")["bg"], "#c62828")
        self.assertEqual(app.button_colors("rebuild")["bg"], "#c62828")

    def test_toolbar_spacing_adds_large_gap_before_approve(self):
        spacing = app.toolbar_spacing()

        self.assertGreaterEqual(spacing["before_approve"], 54)
        self.assertEqual(spacing["between_status"], 6)
        self.assertGreaterEqual(spacing["after_skip"], 18)

    def test_primary_toolbar_order_saves_before_rebuild(self):
        self.assertEqual(
            app.primary_toolbar_order(),
            ("Nacist CSV", "Nacist nove knihy", "Ulozit CSV", "Rebuild CSV"),
        )

    def test_url_bar_button_order_opens_after_use_link(self):
        self.assertEqual(app.url_bar_button_order(), ("Pouzit odkaz", "Otevrit odkaz"))

    def test_bind_default_dialog_actions_focuses_default_and_binds_enter_escape(self):
        calls = []

        class FakeDialog:
            def __init__(self):
                self.bindings = {}

            def bind(self, key, callback):
                self.bindings[key] = callback

        class FakeButton:
            def __init__(self):
                self.focused = False

            def focus_set(self):
                self.focused = True

        dialog = FakeDialog()
        button = FakeButton()

        app.bind_default_dialog_actions(
            dialog,
            confirm=lambda: calls.append("confirm"),
            cancel=lambda: calls.append("cancel"),
            default_button=button,
        )
        dialog.bindings["<Return>"](None)
        dialog.bindings["<Escape>"](None)

        self.assertTrue(button.focused)
        self.assertEqual(calls, ["confirm", "cancel"])

    def test_center_dialog_places_dialog_in_parent_center(self):
        class FakeParent:
            def winfo_rootx(self):
                return 100

            def winfo_rooty(self):
                return 50

            def winfo_width(self):
                return 800

            def winfo_height(self):
                return 600

        class FakeDialog:
            def __init__(self):
                self.geometry_value = ""
                self.updated = False

            def update_idletasks(self):
                self.updated = True

            def winfo_width(self):
                return 300

            def winfo_height(self):
                return 200

            def geometry(self, value):
                self.geometry_value = value

        dialog = FakeDialog()

        app.center_dialog(dialog, FakeParent())

        self.assertTrue(dialog.updated)
        self.assertEqual(dialog.geometry_value, "+350+250")

    def test_update_row_keeps_other_fields_and_changes_status_and_url(self):
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://www.databazeknih.cz/knihy/stara-1",
            "https://www.databazeknih.cz/knihy/stara-1",
            "title-only",
            "title-only",
        )

        updated = app.update_row(row, "approve", " https://www.databazeknih.cz/knihy/nova-2 ")

        self.assertEqual(updated.book_id, 1)
        self.assertEqual(updated.title, "Kniha")
        self.assertEqual(updated.status, "approve")
        self.assertEqual(updated.chosen_url, "https://www.databazeknih.cz/knihy/nova-2")
        self.assertEqual(updated.reason, "title-only")

    def test_update_row_rejects_unknown_status(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "review", "", "", "none", "no-candidates")

        with self.assertRaises(ValueError):
            app.update_row(row, "bad", "")

    def test_status_summary_counts_rows_by_status(self):
        rows = [
            cme.MatchRow(1, "A", "Autor", "approve", "", "", "none", "x"),
            cme.MatchRow(2, "B", "Autor", "review", "", "", "none", "x"),
            cme.MatchRow(3, "C", "Autor", "review", "", "", "none", "x"),
        ]

        self.assertEqual(app.status_summary(rows), "Celkem 3 | approve 1 | review 2 | skip 0")

    def test_update_rows_status_changes_multiple_selected_rows(self):
        rows = [
            cme.MatchRow(1, "A", "Autor", "review", "url-a", "", "none", "x"),
            cme.MatchRow(2, "B", "Autor", "review", "url-b", "", "none", "x"),
            cme.MatchRow(3, "C", "Autor", "review", "url-c", "", "none", "x"),
        ]

        updated = app.update_rows_status(rows, {1, 3}, "approve")

        self.assertEqual([row.status for row in updated], ["approve", "review", "approve"])
        self.assertEqual([row.chosen_url for row in updated], ["url-a", "url-b", "url-c"])

    def test_sort_rows_orders_by_text_column_case_insensitive(self):
        rows = [
            cme.MatchRow(1, "beta", "Autor", "review", "", "", "none", "x"),
            cme.MatchRow(2, "Alfa", "Autor", "review", "", "", "none", "x"),
        ]

        sorted_rows = app.sort_rows(rows, "title", descending=False)

        self.assertEqual([row.title for row in sorted_rows], ["Alfa", "beta"])

    def test_sort_rows_orders_book_id_as_number(self):
        rows = [
            cme.MatchRow(10, "B", "Autor", "review", "", "", "none", "x"),
            cme.MatchRow(2, "A", "Autor", "review", "", "", "none", "x"),
        ]

        sorted_rows = app.sort_rows(rows, "book_id", descending=True)

        self.assertEqual([row.book_id for row in sorted_rows], [10, 2])

    def test_quit_calibre_skips_taskkill_when_calibre_is_not_running(self):
        calls = []

        def runner(args):
            calls.append(args)
            return cme.CommandResult(0, "INFO: No tasks are running", "")

        with contextlib.redirect_stdout(io.StringIO()):
            result = app.quit_calibre(runner)

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "tasklist")

    def test_quit_calibre_uses_taskkill_without_force_when_calibre_is_running(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args[0] == "tasklist":
                return cme.CommandResult(0, "calibre.exe 1234 Console", "")
            return cme.CommandResult(0, "SUCCESS", "")

        with contextlib.redirect_stdout(io.StringIO()):
            result = app.quit_calibre(runner)

        self.assertEqual(result, 0)
        self.assertEqual(calls[1], ["taskkill", "/IM", "calibre.exe", "/T"])

    def test_quit_calibre_can_force_kill_when_soft_taskkill_requires_force(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args[0] == "tasklist":
                return cme.CommandResult(0, "calibre.exe 1234 Console", "")
            if "/F" in args:
                return cme.CommandResult(0, "SUCCESS", "")
            return cme.CommandResult(
                1,
                "",
                "This process can only be terminated forcefully (with /F option).",
            )

        with contextlib.redirect_stdout(io.StringIO()):
            result = app.quit_calibre(runner, allow_force=True)

        self.assertEqual(result, 0)
        self.assertEqual(calls[1], ["taskkill", "/IM", "calibre.exe", "/T"])
        self.assertEqual(calls[2], ["taskkill", "/IM", "calibre.exe", "/T", "/F"])

    def test_quit_calibre_hides_soft_taskkill_error_when_force_succeeds(self):
        def runner(args):
            if args[0] == "tasklist":
                return cme.CommandResult(0, "calibre.exe 1234 Console", "")
            if "/F" in args:
                return cme.CommandResult(0, "SUCCESS", "")
            return cme.CommandResult(
                1,
                "",
                "This process can only be terminated forcefully (with /F option).",
            )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = app.quit_calibre(runner, allow_force=True)

        self.assertEqual(result, 0)
        self.assertNotIn("only be terminated forcefully", output.getvalue())
        self.assertIn("SUCCESS", output.getvalue())

    def test_find_row_index_returns_non_first_row(self):
        rows = [
            cme.MatchRow(1, "A", "Autor", "review", "", "", "none", "x"),
            cme.MatchRow(2, "B", "Autor", "review", "", "", "none", "x"),
        ]

        self.assertEqual(app.find_row_index(rows, 2), 1)

    def test_format_failed_apply_results_lists_failed_rows_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apply-results-20260529-120000.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=cme.APPLY_RESULTS_FIELDS)
                writer.writeheader()
                writer.writerow({
                    "book_id": "1",
                    "title": "Dobry zapis",
                    "status": "updated",
                    "chosen_url": "https://www.databazeknih.cz/knihy/a-1",
                    "error": "",
                })
                writer.writerow({
                    "book_id": "2",
                    "title": "Spatny zapis",
                    "status": "failed",
                    "chosen_url": "https://www.databazeknih.cz/knihy/b-2",
                    "error": "calibredb chyba",
                })

            summary = app.format_failed_apply_results(path)

        self.assertIn("Failed zapisy:", summary)
        self.assertIn("2 Spatny zapis: calibredb chyba", summary)
        self.assertNotIn("Dobry zapis", summary)

    def test_format_new_failed_apply_results_uses_only_newest_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            results_dir = base_dir / "apply-results"
            results_dir.mkdir()
            old_path = results_dir / "apply-results-20260529-100000.csv"
            new_path = results_dir / "apply-results-20260529-110000.csv"
            for path, title in ((old_path, "Stary fail"), (new_path, "Novy fail")):
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=cme.APPLY_RESULTS_FIELDS)
                    writer.writeheader()
                    writer.writerow({
                        "book_id": "1",
                        "title": title,
                        "status": "failed",
                        "chosen_url": "",
                        "error": "chyba",
                    })

            summary = app.format_new_failed_apply_results(base_dir, {old_path})

        self.assertIn("Novy fail", summary)
        self.assertNotIn("Stary fail", summary)

    def test_run_apply_then_preview_quits_applies_then_previews(self):
        calls = []

        result = app.run_apply_then_preview(
            quit_func=lambda: calls.append("quit") or 0,
            apply_func=lambda: calls.append("apply") or 0,
            preview_func=lambda: calls.append("preview") or 0,
        )

        self.assertEqual(result, 0)
        self.assertEqual(calls, ["quit", "apply", "preview"])

    def test_run_apply_then_preview_skips_preview_when_apply_fails(self):
        calls = []

        result = app.run_apply_then_preview(
            quit_func=lambda: calls.append("quit") or 0,
            apply_func=lambda: calls.append("apply") or 1,
            preview_func=lambda: calls.append("preview") or 0,
        )

        self.assertEqual(result, 1)
        self.assertEqual(calls, ["quit", "apply"])

    def test_run_apply_then_preview_prints_failed_summary_when_apply_fails(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = app.run_apply_then_preview(
                quit_func=lambda: 0,
                apply_func=lambda: 1,
                preview_func=lambda: self.fail("preview should not run after failed apply"),
                failed_summary_func=lambda: "Failed zapisy:\n- 2 Spatny zapis: chyba",
            )

        self.assertEqual(result, 1)
        self.assertIn("Spatny zapis", output.getvalue())

    def test_make_apply_action_tracks_new_apply_results_without_name_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            args = object()
            calls = []

            def quit_runner(allow_force):
                calls.append(("quit", allow_force))
                return 0

            def apply_runner(received_args):
                calls.append(("apply", received_args))
                path = base_dir / "apply-results" / "apply-results-20260529-120000.csv"
                path.parent.mkdir()
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=cme.APPLY_RESULTS_FIELDS)
                    writer.writeheader()
                    writer.writerow({
                        "book_id": "2",
                        "title": "Spatny zapis",
                        "status": "failed",
                        "chosen_url": "",
                        "error": "calibredb chyba",
                    })
                return 1

            def preview_runner(received_args):
                self.fail("preview should not run after failed apply")

            action = app.make_apply_action(
                args=args,
                allow_force=True,
                base_dir=base_dir,
                quit_runner=quit_runner,
                apply_runner=apply_runner,
                preview_runner=preview_runner,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = action()

        self.assertEqual(result, 1)
        self.assertEqual(calls, [("quit", True), ("apply", args)])
        self.assertIn("Failed zapisy:", output.getvalue())
        self.assertIn("Spatny zapis", output.getvalue())

    def test_make_rebuild_action_backs_up_matches_then_runs_overwrite_preview(self):
        args = app.make_script_args("D:\\Knihy", overwrite=True)
        calls = []

        def backup_func(matches_path, backups_dir):
            calls.append(("backup", matches_path, backups_dir))
            return backups_dir / "matches-20260529-120000.csv"

        def preview_runner(received_args):
            calls.append(("preview", received_args))
            return 0

        action = app.make_rebuild_action(
            args=args,
            matches_path=Path("matches.csv"),
            backups_dir=Path("backups") / "matches",
            backup_func=backup_func,
            preview_runner=preview_runner,
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = action()

        self.assertEqual(result, 0)
        self.assertEqual(calls[0], ("backup", Path("matches.csv"), Path("backups") / "matches"))
        self.assertEqual(calls[1], ("preview", args))
        self.assertTrue(args.overwrite)
        self.assertIn("Zaloha matches.csv:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
