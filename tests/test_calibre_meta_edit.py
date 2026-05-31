# Testy hlidaji chovani skriptu pro nahled, parovani a bezpecny zapis Calibre komentaru.

import contextlib
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import calibre_meta_edit as cme


class TextAndUrlTests(unittest.TestCase):
    def test_normalize_text_removes_diacritics_series_number_and_extra_spaces(self):
        self.assertEqual(cme.normalize_text("  Bouřková   fronta (1)  "), "bourkova fronta")

    def test_overview_url_converts_to_book_url(self):
        self.assertEqual(
            cme.overview_to_book_url("/prehled-knihy/foo-123"),
            "https://www.databazeknih.cz/knihy/foo-123",
        )

    def test_book_url_converts_to_overview_url_for_detail_fetch(self):
        self.assertEqual(
            cme.book_url_to_overview_url("https://www.databazeknih.cz/knihy/foo-123"),
            "https://www.databazeknih.cz/prehled-knihy/foo-123",
        )

    def test_build_search_url_uses_quote_plus_for_all_authors(self):
        url = cme.build_search_url("Loď osudu", ["Robin Hobb", "Megan Lindholm"])
        self.assertEqual(
            url,
            "https://www.databazeknih.cz/vyhledavani/knihy?q=Lo%C4%8F+osudu+Robin+Hobb+Megan+Lindholm",
        )

    def test_unc_library_path_builds_windows_sqlite_readonly_uri(self):
        self.assertEqual(
            cme.build_sqlite_readonly_uri(r"\\server\share\path"),
            "file:////server/share/path/metadata.db?mode=ro",
        )

    def test_subprocess_window_options_can_hide_windows_console(self):
        self.assertEqual(cme.subprocess_window_options(create_no_window=123), {"creationflags": 123})
        self.assertEqual(cme.subprocess_window_options(create_no_window=None), {})


class CommentTests(unittest.TestCase):
    def test_format_link_html_matches_calibre_comment_style(self):
        url = "https://www.databazeknih.cz/knihy/foo-123"
        self.assertEqual(
            cme.format_link_html(url),
            '<div>\n<p><a href="https://www.databazeknih.cz/knihy/foo-123" target="_blank"><span style="color: #6cb4ee">https://www.databazeknih.cz/knihy/foo-123</span></a></p></div>',
        )

    def test_build_new_comment_returns_only_link_for_empty_comment(self):
        url = "https://www.databazeknih.cz/knihy/foo-123"
        self.assertEqual(cme.build_new_comment(url, ""), cme.format_link_html(url))

    def test_build_new_comment_prepends_link_to_current_comment(self):
        url = "https://www.databazeknih.cz/knihy/foo-123"
        self.assertEqual(
            cme.build_new_comment(url, "  <p>Původní popis</p>"),
            cme.format_link_html(url) + "\n<p>Původní popis</p>",
        )

    def test_format_enriched_comment_overwrites_with_link_rating_and_about_text(self):
        url = "https://www.databazeknih.cz/knihy/foo-123"
        detail = cme.BookDetailMetadata(
            published_year="2013",
            publisher="Fantom Print",
            tags=["Literatura svetova", "Romany"],
            rating_percent="89 %",
            about_text="Popis knihy & dalsi text.",
        )

        comment = cme.format_enriched_comment(url, detail)

        self.assertIn('<a href="https://www.databazeknih.cz/knihy/foo-123" target="_blank">', comment)
        self.assertIn("<p><strong>89 %</strong></p>", comment)
        self.assertIn("<p>Popis knihy &amp; dalsi text.</p>", comment)
        self.assertNotIn("Puvodni", comment)

    def test_add_target_blank_repairs_only_databaze_links(self):
        comment = (
            '<p><a href="https://www.databazeknih.cz/knihy/foo-123">db</a></p>'
            '<p><a href="https://example.com/knihy/foo-123">web</a></p>'
            '<p><a href="https://www.databazeknih.cz/knihy/bar-456" target="_blank">hotovo</a></p>'
        )

        repaired = cme.add_target_blank_to_databaze_links(comment)

        self.assertIn('href="https://www.databazeknih.cz/knihy/foo-123" target="_blank"', repaired)
        self.assertIn('<a href="https://example.com/knihy/foo-123">web</a>', repaired)
        self.assertEqual(repaired.count('target="_blank"'), 2)

    def test_comment_has_databaze_link_detects_existing_link(self):
        self.assertTrue(cme.comment_has_databaze_link('<a href="https://www.databazeknih.cz/knihy/foo-123">x</a>'))
        self.assertFalse(cme.comment_has_databaze_link("<p>Bez odkazu</p>"))

    def test_extract_first_databaze_link_returns_first_url(self):
        comment = '<a href="https://www.databazeknih.cz/knihy/foo-123">x</a>'
        self.assertEqual(cme.extract_first_databaze_link(comment), "https://www.databazeknih.cz/knihy/foo-123")


class ParserAndMatchingTests(unittest.TestCase):
    def test_parse_search_results_uses_html_parser_and_converts_urls(self):
        fixture = Path(__file__).parent / "fixtures" / "databazeknih_search.html"
        candidates = cme.parse_search_results(fixture.read_text(encoding="utf-8"))
        self.assertEqual(candidates[0].title, "Loď osudu")
        self.assertEqual(candidates[0].url, "https://www.databazeknih.cz/knihy/zive-lode-lod-osudu-152421")
        self.assertIn("Robin Hobb", candidates[0].text)

    def test_parse_book_detail_metadata_reads_json_ld_about_rating_and_user_tags(self):
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Book",
          "datePublished": "2013-01-01",
          "publisher": [{"@type": "Organization", "name": "Fantom Print"}],
          "genre": ["Literatura svetova", "Romany", "Fantasy"],
          "aggregateRating": {"ratingValue": "4.6", "bestRating": "5"}
        }
        </script>
        <div class="rating_container">
          <div class='ratValue'>89 <em>%</em></div>
        </div>
        <div class="gridMain">
          <h2>O knize <em>Lod osudu</em></h2>
          <p class='new2 odtop'>Prvni cast.
          <span class='end_text'>Druha cast.</span><a class='show_hide_more'>... cely text</a></p>
        </div>
        <div class="whiteBoxLight">
          <h3 class="lora"><a href='/seznam-stitku'>Stitky</a> knihy</h3>
          <a class="tag" href="/stitky/draci-16">draci</a>
          <a class="tag" href="/stitky/fantasy-18630">fantasy</a>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.published_year, "2013")
        self.assertEqual(detail.publisher, "Fantom Print")
        self.assertEqual(detail.rating_percent, "89 %")
        self.assertEqual(detail.about_text, "Prvni cast. Druha cast.")
        self.assertEqual(detail.tags, ["Literatura svetova", "Romany", "Fantasy", "draci"])

    def test_match_book_approves_exact_title_and_author(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], "")
        candidates = [cme.Candidate("Loď osudu", "Robin Hobb", "https://www.databazeknih.cz/knihy/zive-lode-lod-osudu-152421")]
        match = cme.match_book(book, candidates)
        self.assertEqual(match.status, "approve")
        self.assertEqual(match.confidence, "exact-title-author")
        self.assertEqual(match.reason, "exact-title-author")

    def test_match_book_marks_title_only_as_review(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], "")
        candidates = [cme.Candidate("Loď osudu", "Neznámý autor", "https://www.databazeknih.cz/knihy/foo-123")]
        match = cme.match_book(book, candidates)
        self.assertEqual(match.status, "review")
        self.assertEqual(match.reason, "title-only")

    def test_match_book_marks_multiple_exact_title_matches_as_review(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], "")
        candidates = [
            cme.Candidate("Loď osudu", "Robin Hobb", "https://www.databazeknih.cz/knihy/foo-123"),
            cme.Candidate("Loď osudu", "Robin Hobb", "https://www.databazeknih.cz/knihy/bar-456"),
        ]
        match = cme.match_book(book, candidates)
        self.assertEqual(match.status, "review")
        self.assertEqual(match.reason, "multiple-title-matches")
        self.assertEqual(match.candidate_urls, "https://www.databazeknih.cz/knihy/foo-123|https://www.databazeknih.cz/knihy/bar-456")

    def test_match_book_skips_existing_link(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], '<a href="https://www.databazeknih.cz/knihy/foo-123">x</a>')
        match = cme.match_book(book, [])
        self.assertEqual(match.status, "skip")
        self.assertEqual(match.reason, "already-linked")
        self.assertEqual(match.chosen_url, "https://www.databazeknih.cz/knihy/foo-123")

    def test_preview_books_does_not_check_robots_when_all_books_are_already_linked(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], '<a href="https://www.databazeknih.cz/knihy/foo-123">x</a>')
        rows = cme.preview_books(
            [book],
            fetcher=lambda url: self.fail("fetcher should not be called"),
            robots_checker=lambda: self.fail("robots_checker should not be called"),
            sleeper=lambda seconds: self.fail("sleeper should not be called"),
            sleep_seconds=1.0,
        )
        self.assertEqual(rows[0].status, "skip")
        self.assertEqual(rows[0].reason, "already-linked")

    def test_preview_books_sleeps_after_robots_before_first_search(self):
        fixture = Path(__file__).parent / "fixtures" / "databazeknih_search.html"
        calls = []
        rows = cme.preview_books(
            [cme.Book(309, "Loď osudu", ["Robin Hobb"], "")],
            fetcher=lambda url: calls.append("fetch") or fixture.read_text(encoding="utf-8"),
            robots_checker=lambda: calls.append("robots") or True,
            sleeper=lambda seconds: calls.append(f"sleep:{seconds}"),
            sleep_seconds=1.0,
        )
        self.assertEqual(calls[:3], ["robots", "sleep:1.0", "fetch"])
        self.assertEqual(rows[0].status, "approve")


class CsvAndFilesystemTests(unittest.TestCase):
    def test_write_matches_csv_uses_utf8_bom_and_refuses_existing_file(self):
        row = cme.MatchRow(1, "Loď osudu", "Robin Hobb", "approve", "https://www.databazeknih.cz/knihy/foo-123", "", "exact-title-author", "exact-title-author")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            cme.write_matches_csv(path, [row], overwrite=False)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with self.assertRaises(FileExistsError):
                cme.write_matches_csv(path, [row], overwrite=False)

    def test_read_matches_csv_reads_utf8_bom_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=cme.MATCHES_FIELDS)
                writer.writeheader()
                writer.writerow({
                    "book_id": "309",
                    "title": "Loď osudu",
                    "authors": "Robin Hobb",
                    "status": "approve",
                    "chosen_url": "https://www.databazeknih.cz/knihy/foo-123",
                    "candidate_urls": "",
                    "confidence": "exact-title-author",
                    "reason": "exact-title-author",
                })
            rows = cme.read_matches_csv(path)
            self.assertEqual(rows[0].book_id, 309)
            self.assertEqual(rows[0].title, "Loď osudu")

    def test_filter_new_books_skips_books_already_in_matches_csv(self):
        books = [
            cme.Book(1, "Stara kniha", ["Autor"], ""),
            cme.Book(2, "Nova kniha", ["Autor"], ""),
        ]
        existing_rows = [
            cme.MatchRow(1, "Stara kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/a-1", "", "manual", "manual")
        ]

        new_books = cme.filter_new_books(books, existing_rows)

        self.assertEqual([book.id for book in new_books], [2])

    def test_run_preview_existing_matches_processes_only_new_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            old_row = cme.MatchRow(1, "Stara kniha", "Autor", "review", "https://www.databazeknih.cz/knihy/a-1", "", "manual", "manual")
            cme.write_matches_csv(path, [old_row], overwrite=False)

            original_matches_path = cme.MATCHES_PATH
            original_read_books = cme.read_books
            original_preview_books = cme.preview_books
            seen_book_ids = []
            try:
                cme.MATCHES_PATH = path
                cme.read_books = lambda library, book_id=None, limit=None: [
                    cme.Book(1, "Stara kniha", ["Autor"], ""),
                    cme.Book(2, "Nova kniha", ["Autor"], ""),
                ]

                def fake_preview_books(books, sleep_seconds):
                    seen_book_ids.extend(book.id for book in books)
                    return [
                        cme.MatchRow(2, "Nova kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/b-2", "", "exact-title-author", "exact-title-author")
                    ]

                cme.preview_books = fake_preview_books

                with contextlib.redirect_stdout(io.StringIO()):
                    result = cme.run_preview(SimpleNamespace(library="library", book_id=None, limit=None, sleep=0, overwrite=False))
            finally:
                cme.MATCHES_PATH = original_matches_path
                cme.read_books = original_read_books
                cme.preview_books = original_preview_books

            rows = cme.read_matches_csv(path)
            self.assertEqual(result, 0)
            self.assertEqual(seen_book_ids, [2])
            self.assertEqual([row.book_id for row in rows], [1, 2])
            self.assertEqual(rows[0].status, "review")

    def test_create_backup_makes_directory_and_copies_metadata_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir()
            (library / "metadata.db").write_bytes(b"db")
            backups = Path(tmp) / "backups"
            backup_path = cme.create_backup(library, backups, timestamp="20260526-161500")
            self.assertEqual(backup_path.read_bytes(), b"db")
            self.assertEqual(backup_path.name, "metadata-20260526-161500.db")

    def test_restore_metadata_backup_makes_safety_backup_then_replaces_metadata_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir()
            (library / "metadata.db").write_bytes(b"current db")
            backups = Path(tmp) / "backups"
            backups.mkdir()
            selected_backup = backups / "metadata-20260529-120000.db"
            selected_backup.write_bytes(b"old db")

            safety_backup = cme.restore_metadata_backup(
                library,
                selected_backup,
                backups,
                timestamp="20260529-130000",
            )

            self.assertEqual(safety_backup, backups / "metadata-before-restore-20260529-130000.db")
            self.assertEqual(safety_backup.read_bytes(), b"current db")
            self.assertEqual((library / "metadata.db").read_bytes(), b"old db")

    def test_run_restore_backup_refuses_when_sqlite_sidecar_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir()
            (library / "metadata.db").write_bytes(b"current db")
            (library / "metadata.db-wal").write_bytes(b"wal")
            selected_backup = Path(tmp) / "metadata-20260529-120000.db"
            selected_backup.write_bytes(b"old db")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = cme.run_restore_backup(SimpleNamespace(library=library, backup=selected_backup))

            self.assertEqual(result, 1)
            self.assertEqual((library / "metadata.db").read_bytes(), b"current db")
            self.assertIn("Databaze ma vedlejsi SQLite soubory", output.getvalue())

    def test_backup_matches_csv_copies_old_matches_to_matches_backup_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            matches_path = Path(tmp) / "matches.csv"
            matches_path.write_text("old csv", encoding="utf-8")
            backups = Path(tmp) / "backups" / "matches"

            backup_path = cme.backup_matches_csv(matches_path, backups, timestamp="20260529-120000")

            self.assertEqual(backup_path, backups / "matches-20260529-120000.csv")
            self.assertEqual(backup_path.read_text(encoding="utf-8"), "old csv")

    def test_backup_matches_csv_returns_none_when_matches_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_path = cme.backup_matches_csv(
                Path(tmp) / "missing.csv",
                Path(tmp) / "backups" / "matches",
                timestamp="20260529-120000",
            )

            self.assertIsNone(backup_path)

    def test_sqlite_sidecar_detection_finds_wal_shm_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            (library / "metadata.db-wal").write_text("", encoding="utf-8")
            self.assertEqual(cme.find_sqlite_sidecars(library), [library / "metadata.db-wal"])

    def test_apply_results_path_uses_apply_results_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = cme.apply_results_path("20260529-120000", base_dir=Path(tmp))

            self.assertEqual(path, Path(tmp) / "apply-results" / "apply-results-20260529-120000.csv")
            self.assertTrue(path.parent.exists())


class CalibreDbAndApplyTests(unittest.TestCase):
    def test_find_calibredb_prefers_path_then_fallback(self):
        self.assertEqual(
            cme.find_calibredb(
                which_func=lambda name: r"C:\tools\calibredb.exe",
                exists_func=lambda path: False,
            ),
            r"C:\tools\calibredb.exe",
        )
        self.assertEqual(
            cme.find_calibredb(
                which_func=lambda name: None,
                exists_func=lambda path: str(path) == cme.CALIBREDB_FALLBACK,
            ),
            cme.CALIBREDB_FALLBACK,
        )

    def test_select_books_prefers_book_id_over_limit(self):
        books = [cme.Book(1, "A", [], ""), cme.Book(2, "B", [], "")]
        self.assertEqual([book.id for book in cme.select_books(books, book_id=2, limit=1)], [2])

    def test_select_match_rows_supports_limit_and_book_id_precedence(self):
        rows = [
            cme.MatchRow(1, "A", "Autor", "approve", "https://www.databazeknih.cz/knihy/a-1", "", "exact-title-author", "exact-title-author"),
            cme.MatchRow(2, "B", "Autor", "approve", "https://www.databazeknih.cz/knihy/b-2", "", "exact-title-author", "exact-title-author"),
        ]
        self.assertEqual([row.book_id for row in cme.select_match_rows(rows, book_id=None, limit=1)], [1])
        self.assertEqual([row.book_id for row in cme.select_match_rows(rows, book_id=2, limit=1)], [2])

    def test_is_valid_apply_url_accepts_only_databaze_knih_book_urls(self):
        self.assertTrue(cme.is_valid_apply_url("https://www.databazeknih.cz/knihy/foo-123"))
        self.assertFalse(cme.is_valid_apply_url("https://www.databazeknih.cz/prehled-knihy/foo-123"))

    def test_apply_match_row_overwrites_comment_and_metadata_from_databaze_detail(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/new-2", "", "exact-title-author", "exact-title-author")
        calls = []
        fetched_urls = []
        detail_html = """
        <script type="application/ld+json">
        {"@type": "Book", "datePublished": "2013-01-01", "publisher": [{"name": "Fantom Print"}], "genre": ["Fantasy"]}
        </script>
        <div class='ratValue'>89 <em>%</em></div>
        <h2>O knize <em>Kniha</em></h2><p class='new2 odtop'>Novy popis.</p>
        <h3><a>Stitky</a> knihy</h3><a class="tag">draci</a>
        """

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: fetched_urls.append(url) or detail_html,
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(fetched_urls, ["https://www.databazeknih.cz/prehled-knihy/new-2"])
        self.assertEqual(calls[0][0], r"C:\calibredb.exe")
        self.assertIn("--field", calls[0])
        self.assertIn("pubdate:2013", calls[0])
        self.assertIn("publisher:Fantom Print", calls[0])
        self.assertIn("tags:Fantasy,draci", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("<strong>89 %</strong>", comments_field)
        self.assertIn("Novy popis.", comments_field)

    def test_apply_match_row_calls_calibredb_with_argument_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            connection = sqlite3.connect(db_path)
            connection.execute("create table comments (book integer primary key, text text)")
            connection.execute("insert into comments(book, text) values(?, ?)", (1, "<p>Popis</p>"))
            connection.commit()
            connection.close()

            row = cme.MatchRow(1, "Kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/new-2", "", "exact-title-author", "exact-title-author")
            calls = []
            result = cme.apply_match_row(
                row,
                Path(tmp),
                r"C:\calibredb.exe",
                runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
                fetcher=lambda url: "<script type='application/ld+json'>{\"@type\":\"Book\"}</script>",
            )

            self.assertEqual(result.status, "updated")
            self.assertEqual(calls[0][0], r"C:\calibredb.exe")
            self.assertIn("--field", calls[0])
            self.assertIn("comments:", next(arg for arg in calls[0] if arg.startswith("comments:")))

    def test_apply_match_row_fails_without_writing_when_detail_fetch_fails(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/new-2", "", "exact-title-author", "exact-title-author")
        calls = []

        def fetcher(url):
            raise RuntimeError("http 500")

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=fetcher,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("detail-fetch-error", result.error)
        self.assertEqual(calls, [])

    def test_run_apply_marks_finished_approved_rows_as_skip_in_matches_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            matches_path = Path(tmp) / "matches.csv"
            rows = [
                cme.MatchRow(1, "Zapsana", "Autor", "approve", "https://www.databazeknih.cz/knihy/a-1", "", "manual", "manual"),
                cme.MatchRow(2, "Chybna", "Autor", "approve", "https://www.databazeknih.cz/knihy/b-2", "", "manual", "manual"),
                cme.MatchRow(3, "Uz mela odkaz", "Autor", "approve", "https://www.databazeknih.cz/knihy/c-3", "", "manual", "manual"),
                cme.MatchRow(4, "Jen review", "Autor", "review", "https://www.databazeknih.cz/knihy/d-4", "", "manual", "manual"),
                cme.MatchRow(5, "Spatny odkaz", "Autor", "approve", "https://example.com/spatne", "", "manual", "manual"),
            ]
            cme.write_matches_csv(matches_path, rows, overwrite=False)

            original_matches_path = cme.MATCHES_PATH
            original_find_sidecars = cme.find_sqlite_sidecars
            original_find_calibredb = cme.find_calibredb
            original_smoke = cme.run_calibredb_smoke
            original_create_backup = cme.create_backup
            original_apply_results_path = cme.apply_results_path
            original_apply_match_row = cme.apply_match_row
            try:
                cme.MATCHES_PATH = matches_path
                cme.find_sqlite_sidecars = lambda library: []
                cme.find_calibredb = lambda: r"C:\calibredb.exe"
                cme.run_calibredb_smoke = lambda calibredb_path, library: cme.CommandResult(0, "ok", "")
                cme.create_backup = lambda library, backups_dir: Path(tmp) / "metadata-backup.db"
                cme.apply_results_path = lambda timestamp: Path(tmp) / "apply-results.csv"

                def fake_apply_match_row(row, library, calibredb_path):
                    if row.book_id == 1:
                        return cme.ApplyResult(row.book_id, row.title, "updated", row.chosen_url, "")
                    if row.book_id == 2:
                        return cme.ApplyResult(row.book_id, row.title, "failed", row.chosen_url, "docasna chyba")
                    if row.book_id == 3:
                        return cme.ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")
                    return cme.ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "invalid-url")

                cme.apply_match_row = fake_apply_match_row

                with contextlib.redirect_stdout(io.StringIO()):
                    result = cme.run_apply(SimpleNamespace(library="library", book_id=None, limit=None))
            finally:
                cme.MATCHES_PATH = original_matches_path
                cme.find_sqlite_sidecars = original_find_sidecars
                cme.find_calibredb = original_find_calibredb
                cme.run_calibredb_smoke = original_smoke
                cme.create_backup = original_create_backup
                cme.apply_results_path = original_apply_results_path
                cme.apply_match_row = original_apply_match_row

            updated_rows = cme.read_matches_csv(matches_path)

        self.assertEqual(result, 1)
        self.assertEqual([row.status for row in updated_rows], ["skip", "approve", "skip", "review", "approve"])

    def test_repair_book_comment_target_updates_old_databaze_link(self):
        book = cme.Book(
            1,
            "Kniha",
            ["Autor"],
            '<p><a href="https://www.databazeknih.cz/knihy/foo-123">db</a></p>',
        )
        calls = []

        result = cme.repair_book_comment_target(
            book,
            Path("library"),
            r"C:\calibredb.exe",
            lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(calls[0][0], r"C:\calibredb.exe")
        field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn('target="_blank"', field)

    def test_repair_book_comment_target_skips_when_no_change_needed(self):
        book = cme.Book(
            1,
            "Kniha",
            ["Autor"],
            '<p><a href="https://www.databazeknih.cz/knihy/foo-123" target="_blank">db</a></p>',
        )
        calls = []

        result = cme.repair_book_comment_target(
            book,
            Path("library"),
            r"C:\calibredb.exe",
            lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
