# Testy hlidaji chovani skriptu pro nahled, parovani a bezpecny zapis Calibre komentaru.

import contextlib
import csv
import io
import inspect
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

import calibre_meta_edit as cme


def write_test_epub(
    path: Path,
    title: str = "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b",
    creator: str = "John Irving",
    creators: list[str] | None = None,
    language: str = "cs",
    body: str = "John Irving\nImagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b\nCopyright 1996",
    opf_path: str = "OEBPS/content.opf",
    item_href: str = "title.xhtml",
    item_path: str = "OEBPS/title.xhtml",
) -> None:
    container_xml = f"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    creator_tags = "\n".join(f"    <dc:creator>{value}</dc:creator>" for value in (creators or [creator]))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
{creator_tags}
    <dc:language>{language}</dc:language>
    <dc:publisher>Odeon</dc:publisher>
    <dc:date>1996</dc:date>
  </metadata>
  <manifest>
    <item id="title" href="{item_href}" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="title"/>
  </spine>
</package>"""
    xhtml = f"""<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{body}</p></body></html>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container_xml)
        archive.writestr(opf_path, opf)
        archive.writestr(item_path, xhtml)


class TextAndUrlTests(unittest.TestCase):
    def test_normalize_text_removes_punctuation_from_title_words(self):
        self.assertEqual(cme.normalize_text("Stráže! Stráže!"), "straze straze")

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

    def test_legie_url_normalizes_double_slash_story_path(self):
        self.assertEqual(
            cme.legie_absolute_url("https://www.legie.info//povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie"),
            "https://www.legie.info/povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie",
        )
        self.assertTrue(
            cme.is_valid_legie_story_url(
                "https://www.legie.info//povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie"
            )
        )

    def test_build_search_url_uses_quote_plus_for_all_authors(self):
        url = cme.build_search_url("Loď osudu", ["Robin Hobb", "Megan Lindholm"])
        self.assertEqual(
            url,
            "https://www.databazeknih.cz/vyhledavani/knihy?q=Lo%C4%8F+osudu+Robin+Hobb+Megan+Lindholm",
        )

    def test_search_variants_add_plain_ascii_fallback(self):
        variants = cme.search_variants("Stráže! Stráže!", ["Terry Pratchett"])

        self.assertEqual(variants, [("Stráže! Stráže!", ["Terry Pratchett"]), ("straze straze", ["terry pratchett"])])

    def test_build_legie_search_url_uses_quote_plus_for_title_and_authors(self):
        url = cme.build_legie_search_url("A opice si myslely", ["Orson Scott Card"])
        self.assertEqual(
            url,
            "https://www.legie.info/index.php?search_text=A+opice+si+myslely+Orson+Scott+Card",
        )

    def test_google_books_url_helpers_read_volume_id(self):
        url = "https://books.google.cz/books/about/Turn_Coat.html?id=cf1Tl4WhhHUC&redir_esc=y"

        self.assertEqual(cme.google_books_volume_id_from_url(url), "cf1Tl4WhhHUC")
        self.assertTrue(cme.is_valid_google_books_url(url))
        self.assertEqual(cme.google_books_url("cf1Tl4WhhHUC"), "https://books.google.com/books?id=cf1Tl4WhhHUC")

    def test_openlibrary_url_helpers_read_edition_key(self):
        url = "https://openlibrary.org/books/OL26247313M/Homo_Deus_A_Brief_History_of_Tomorrow"

        self.assertEqual(cme.openlibrary_edition_key_from_url(url), "OL26247313M")
        self.assertTrue(cme.is_valid_openlibrary_url(url))
        self.assertEqual(cme.openlibrary_url("OL26247313M"), "https://openlibrary.org/books/OL26247313M")

    def test_build_google_books_search_url_uses_title_and_author(self):
        url = cme.build_google_books_search_url("Turn Coat", ["Jim Butcher"])

        self.assertIn("q=intitle%3ATurn+Coat+inauthor%3AJim+Butcher", url)
        self.assertIn("printType=books", url)

    def test_build_openlibrary_search_url_uses_title_and_author(self):
        url = cme.build_openlibrary_search_url("Homo Deus: A Brief History of Tomorrow", ["Yuval Noah Harari"])

        self.assertIn("title=Homo+Deus%3A+A+Brief+History+of+Tomorrow", url)
        self.assertIn("author=Yuval+Noah+Harari", url)

    def test_parse_search_results_reads_databaze_story_candidates(self):
        html = """
        <a href="https://www.databazeknih.cz/povidky/samuela-2229">
            <img title="Samuela" />
            Samuela
        </a>
        <p>Povídka od: Anatolij Petrovič Dněprov</p>
        """

        candidates = cme.parse_search_results(html)

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].title, "Samuela")
        self.assertEqual(candidates[0].url, "https://www.databazeknih.cz/povidky/samuela-2229")
        self.assertIn("Anatolij Petrovič Dněprov", candidates[0].text)

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
            original_title="Twenty Pence with Envelope and Seasonal Greeting",
            original_publication="12/1987",
            original_publisher="Gollancz",
            about_text="Popis knihy & dalsi text.",
        )

        comment = cme.format_enriched_comment(url, detail)

        self.assertIn('<a href="https://www.databazeknih.cz/knihy/foo-123" target="_blank">', comment)
        self.assertIn("<p><strong>89 %</strong></p>", comment)
        self.assertIn("Originalni nazev: Twenty Pence with Envelope and Seasonal Greeting", comment)
        self.assertIn("Originalne vyslo: 12/1987", comment)
        self.assertIn("Originalni vydavatel: Gollancz", comment)
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


class ImportModelTests(unittest.TestCase):
    def test_import_preview_requires_title_and_author(self):
        valid = cme.ImportPreview(title="Kniha", authors="Autor")
        missing_title = cme.ImportPreview(title="", authors="Autor")
        missing_author = cme.ImportPreview(title="Kniha", authors="")

        self.assertTrue(cme.is_valid_import_preview(valid))
        self.assertFalse(cme.is_valid_import_preview(missing_title))
        self.assertFalse(cme.is_valid_import_preview(missing_author))

    def test_import_candidate_defaults_are_safe(self):
        candidate = cme.ImportCandidate(source="databazeknih", title="Kniha", authors="Autor", url="https://x")

        self.assertEqual(candidate.score, 0)
        self.assertEqual(candidate.reason, "")
        self.assertEqual(candidate.work_type, "")
        self.assertEqual(candidate.evidence_text, "")
        self.assertIsNone(candidate.detail)


class AuthorDisplayNameTests(unittest.TestCase):
    def test_normalizes_simple_sort_name_to_display_order(self):
        self.assertEqual(cme.normalize_author_display_name("Verne, Jules"), "Jules Verne")
        self.assertEqual(cme.normalize_author_display_name("Asimov, Isaac"), "Isaac Asimov")

    def test_normalizes_sort_name_with_diacritics(self):
        self.assertEqual(cme.normalize_author_display_name("\u010capek, Karel"), "Karel \u010capek")

    def test_normalizes_sort_name_with_initials(self):
        self.assertEqual(cme.normalize_author_display_name("Tolkien, J. R. R."), "J. R. R. Tolkien")

    def test_keeps_already_display_name_unchanged(self):
        self.assertEqual(cme.normalize_author_display_name("Jules Verne"), "Jules Verne")

    def test_keeps_empty_author_safe(self):
        self.assertEqual(cme.normalize_author_display_name(""), "")
        self.assertEqual(cme.normalize_author_display_names(""), "")
        self.assertEqual(cme.normalize_author_display_names("   "), "   ")

    def test_does_not_mangle_ambiguous_multi_comma(self):
        self.assertEqual(
            cme.normalize_author_display_name("King, Jr., Martin Luther"),
            "King, Jr., Martin Luther",
        )

    def test_does_not_mangle_suffix_sort_name(self):
        self.assertEqual(cme.normalize_author_display_name("Tolkien, Jr."), "Tolkien, Jr.")

    def test_does_not_rewrite_organization_name(self):
        self.assertEqual(
            cme.normalize_author_display_name("Penguin Books, Ltd"),
            "Penguin Books, Ltd",
        )

    def test_normalizes_each_author_in_multi_author_string(self):
        self.assertEqual(
            cme.normalize_author_display_names("Verne, Jules & Asimov, Isaac"),
            "Jules Verne & Isaac Asimov",
        )

    def test_does_not_split_bare_ampersand_inside_name(self):
        self.assertEqual(cme.normalize_author_display_names("AT&T Press"), "AT&T Press")
        self.assertEqual(cme.normalize_author_display_names("R&D Team"), "R&D Team")

    def test_does_not_normalize_organization_with_comma(self):
        self.assertEqual(
            cme.normalize_author_display_name("R&D Team, Editorial"),
            "R&D Team, Editorial",
        )

    def test_initial_epub_preview_uses_normalized_display_author(self):
        signal = cme.import_signal_from_epub_metadata(
            cme.EpubMetadata(title="Tajupln\u00fd ostrov", authors="Verne, Jules")
        )

        preview = cme.choose_initial_import_preview([signal])

        self.assertEqual(preview.authors, "Jules Verne")

    def test_candidate_preview_normalizes_sort_style_author(self):
        fallback = cme.ImportPreview(title="Nadace", authors="Isaac Asimov")
        candidate = cme.ImportCandidate(
            source="databazeknih", title="Nadace", authors="Asimov, Isaac", url="https://x"
        )

        preview = cme.import_preview_from_candidate(candidate, fallback)

        self.assertEqual(preview.authors, "Isaac Asimov")


class BookImportFormatTests(unittest.TestCase):
    def test_ebook_tool_formats_are_lowercase_with_dot(self):
        self.assertEqual(cme.EBOOK_TOOL_FORMATS, {".mobi", ".azw3", ".pdb"})

    def test_find_ebook_tool_prefers_which(self):
        found = cme.find_ebook_tool("ebook-meta", which_func=lambda name: "/usr/bin/" + name)
        self.assertEqual(found, "/usr/bin/ebook-meta")

    def test_find_ebook_tool_falls_back_to_calibre_dir(self):
        found = cme.find_ebook_tool(
            "ebook-convert",
            which_func=lambda name: None,
            exists_func=lambda path: path.endswith("ebook-convert.exe"),
        )
        self.assertTrue(found.endswith("ebook-convert.exe"))
        self.assertIn("Calibre2", found)

    def test_find_ebook_tool_missing_returns_none(self):
        found = cme.find_ebook_tool(
            "ebook-meta", which_func=lambda name: None, exists_func=lambda path: False
        )
        self.assertIsNone(found)


class ImportDuplicateTests(unittest.TestCase):
    def test_find_import_duplicates_strong_match_title_and_author(self):
        books = [
            cme.Book(1, "Str\u00e1\u017ee! Str\u00e1\u017ee!", ["Terry Pratchett"]),
            cme.Book(2, "Mort", ["Terry Pratchett"]),
        ]
        preview = cme.ImportPreview(title="Str\u00e1\u017ee str\u00e1\u017ee", authors="Terry Pratchett")

        duplicates = cme.find_import_duplicates(preview, books)

        self.assertEqual([item.book_id for item in duplicates], [1])
        self.assertTrue(duplicates[0].strong)

    def test_find_import_duplicates_ignores_same_author_different_title(self):
        books = [cme.Book(2, "Mort", ["Terry Pratchett"])]
        preview = cme.ImportPreview(title="Str\u00e1\u017ee str\u00e1\u017ee", authors="Terry Pratchett")

        duplicates = cme.find_import_duplicates(preview, books)

        self.assertEqual(duplicates, [])

    def test_find_calibre_import_duplicates_uses_books_reader(self):
        preview = cme.ImportPreview(title="Mort", authors="Terry Pratchett")

        duplicates = cme.find_calibre_import_duplicates(
            "B:\\",
            preview,
            books_reader=lambda library: [cme.Book(2, "Mort", ["Terry Pratchett"])],
        )

        self.assertEqual(duplicates[0].book_id, 2)


class ImportApplyTests(unittest.TestCase):
    def test_parse_calibredb_add_book_ids_reads_single_id(self):
        self.assertEqual(cme.parse_calibredb_add_book_ids("Added book ids: 123"), [123])

    def test_parse_calibredb_add_book_ids_reads_multiple_ids(self):
        self.assertEqual(cme.parse_calibredb_add_book_ids("Added book ids: 10, 11"), [10, 11])

    def test_apply_import_preview_adds_book_sets_metadata_and_writes_match_row(self):
        calls = []
        rows_written = []
        preview = cme.ImportPreview(
            title="Kniha",
            authors="Autor",
            url="https://example.test/book",
            source="openlibrary",
            comment="Komentar",
        )

        def runner(args):
            calls.append(args)
            if args[1] == "add":
                return cme.CommandResult(0, "Added book ids: 42", "")
            return cme.CommandResult(0, "ok", "")

        result = cme.apply_import_preview(
            preview,
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=runner,
            existing_ids_reader=lambda library: {1},
            duplicate_reader=lambda library, preview: [],
            backup_func=lambda library, backups_dir: Path("backups/metadata-test.db"),
            rows_reader=lambda path: [],
            rows_writer=lambda path, rows, overwrite: rows_written.extend(rows),
            quit_func=lambda allow_force: 0,
        )

        self.assertEqual(result.book_id, 42)
        self.assertEqual(result.status, "updated")
        self.assertEqual(rows_written[0].book_id, 42)
        self.assertEqual(rows_written[0].status, "review")
        self.assertTrue(any(call[1] == "add" for call in calls))
        self.assertTrue(any(call[1] == "set_metadata" for call in calls))

    def test_apply_import_preview_rejects_invalid_preview_before_side_effects(self):
        calls = []

        result = cme.apply_import_preview(
            cme.ImportPreview(title="", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            duplicate_reader=lambda library, preview: [],
            backup_func=lambda library, backups_dir: Path("backup.db"),
            quit_func=lambda allow_force: calls.append(["quit"]) or 0,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "missing-title-or-author")
        self.assertEqual(calls, [])

    def test_apply_import_preview_stops_when_quit_calibre_fails(self):
        calls = []

        result = cme.apply_import_preview(
            cme.ImportPreview(title="Kniha", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            duplicate_reader=lambda library, preview: [],
            backup_func=lambda library, backups_dir: calls.append(["backup"]) or Path("backup.db"),
            quit_func=lambda allow_force: 1,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "quit-calibre-failed")
        self.assertEqual(calls, [])

    def test_apply_import_preview_blocks_strong_duplicate_before_quit(self):
        calls = []
        duplicate = cme.DuplicateCandidate(1, "Kniha", "Autor", strong=True)

        result = cme.apply_import_preview(
            cme.ImportPreview(title="Kniha", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            duplicate_reader=lambda library, preview: [duplicate],
            quit_func=lambda allow_force: calls.append(["quit"]) or 0,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "strong-duplicate")
        self.assertEqual(calls, [])

    def test_apply_import_preview_blocks_strong_duplicate_after_backup(self):
        calls = []
        duplicate = cme.DuplicateCandidate(1, "Kniha", "Autor", strong=True)
        duplicate_calls = []

        def duplicate_reader(library, preview):
            duplicate_calls.append(1)
            return [] if len(duplicate_calls) == 1 else [duplicate]

        result = cme.apply_import_preview(
            cme.ImportPreview(title="Kniha", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            existing_ids_reader=lambda library: {1},
            duplicate_reader=duplicate_reader,
            backup_func=lambda library, backups_dir: Path("backups/metadata-test.db"),
            quit_func=lambda allow_force: 0,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "strong-duplicate-after-close")
        self.assertEqual(result.backup_path, "backups\\metadata-test.db")
        self.assertEqual(calls, [])

    def test_apply_import_preview_reports_add_failure(self):
        calls = []

        result = cme.apply_import_preview(
            cme.ImportPreview(title="Kniha", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=lambda args: calls.append(args) or cme.CommandResult(1, "", "add failed"),
            existing_ids_reader=lambda library: {1},
            duplicate_reader=lambda library, preview: [],
            backup_func=lambda library, backups_dir: Path("backup.db"),
            quit_func=lambda allow_force: 0,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "add failed")
        self.assertTrue(any(call[1] == "add" for call in calls))
        self.assertFalse(any(len(call) > 1 and call[1] == "set_metadata" for call in calls))

    def test_apply_import_preview_uses_existing_ids_diff_when_add_output_has_no_id(self):
        calls = []
        id_reads = []

        def existing_ids_reader(library):
            id_reads.append(1)
            return {1} if len(id_reads) == 1 else {1, 42}

        def runner(args):
            calls.append(args)
            if args[1] == "add":
                return cme.CommandResult(0, "ok", "")
            return cme.CommandResult(0, "metadata ok", "")

        result = cme.apply_import_preview(
            cme.ImportPreview(title="Kniha", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=runner,
            existing_ids_reader=existing_ids_reader,
            duplicate_reader=lambda library, preview: [],
            backup_func=lambda library, backups_dir: Path("backup.db"),
            rows_reader=lambda path: [],
            rows_writer=lambda path, rows, overwrite: None,
            quit_func=lambda allow_force: 0,
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.book_id, 42)

    def test_apply_import_preview_reports_metadata_failure_without_writing_rows(self):
        rows_written = []

        def runner(args):
            if args[1] == "add":
                return cme.CommandResult(0, "Added book ids: 42", "")
            return cme.CommandResult(1, "", "metadata failed")

        result = cme.apply_import_preview(
            cme.ImportPreview(title="Kniha", authors="Autor"),
            epub_path=Path("book.epub"),
            library="B:\\",
            calibredb_path="calibredb",
            runner=runner,
            existing_ids_reader=lambda library: {1},
            duplicate_reader=lambda library, preview: [],
            backup_func=lambda library, backups_dir: Path("backup.db"),
            rows_reader=lambda path: [],
            rows_writer=lambda path, rows, overwrite: rows_written.extend(rows),
            quit_func=lambda allow_force: 0,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.book_id, 42)
        self.assertEqual(result.error, "metadata failed")
        self.assertEqual(rows_written, [])

    def test_apply_import_preview_appends_match_row_to_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            matches_path = Path(tmp) / "matches.db"
            matches_path.write_text("", encoding="utf-8")
            old_row = cme.MatchRow(1, "Stara", "Autor", "skip", "", "", "manual", "manual")
            rows_written = []

            def runner(args):
                if args[1] == "add":
                    return cme.CommandResult(0, "Added book ids: 42", "")
                return cme.CommandResult(0, "ok", "")

            result = cme.apply_import_preview(
                cme.ImportPreview(title="Nova", authors="Autor"),
                epub_path=Path("book.epub"),
                library="B:\\",
                calibredb_path="calibredb",
                runner=runner,
                existing_ids_reader=lambda library: {1},
                duplicate_reader=lambda library, preview: [],
                backup_func=lambda library, backups_dir: Path("backup.db"),
                rows_reader=lambda path: [old_row],
                rows_writer=lambda path, rows, overwrite: rows_written.extend(rows),
                quit_func=lambda allow_force: 0,
                matches_path=matches_path,
            )

        self.assertEqual(result.status, "updated")
        self.assertEqual([row.book_id for row in rows_written], [1, 42])


class ImportCandidateScoringTests(unittest.TestCase):
    def test_score_import_candidates_prefers_title_and_author_match(self):
        signals = [
            cme.ImportSourceSignal("epub-metadata", "Str\u00e1\u017ee! Str\u00e1\u017ee!", "Terry Pratchett", language="cs"),
            cme.ImportSourceSignal("filename", "Str\u00e1\u017ee str\u00e1\u017ee", "Terry Pratchett"),
        ]
        candidates = [
            cme.ImportCandidate(
                "databazeknih",
                "Str\u00e1\u017ee! Str\u00e1\u017ee!",
                "Terry Pratchett",
                "https://dk/good",
                evidence_text="Str\u00e1\u017ee! Str\u00e1\u017ee! Terry Pratchett",
            ),
            cme.ImportCandidate("databazeknih", "Str\u00e1\u017ee stromy", "Jin\u00fd Autor", "https://dk/bad"),
        ]

        scored = cme.score_import_candidates(signals, candidates)

        self.assertEqual(scored[0].url, "https://dk/good")
        self.assertGreater(scored[0].score, scored[1].score)

    def test_score_import_candidates_requires_databaze_author_evidence_text(self):
        signals = [cme.ImportSourceSignal("epub-metadata", "Kniha", "Autor")]
        candidate = cme.ImportCandidate("databazeknih", "Kniha", "Autor", "https://dk/no-author", evidence_text="Kniha Jiny")

        scored = cme.score_import_candidates(signals, [candidate])

        self.assertEqual(scored[0].reason, "title=70;author=0")
        self.assertEqual(scored[0].score, 70)

    def test_score_import_candidates_prefers_clean_filename_signal_over_broken_epub_metadata(self):
        signals = [
            cme.ImportSourceSignal("epub-metadata", "Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a", "Irving John\u256a", language="cs", confidence=60),
            cme.ImportSourceSignal("filename", "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b", "John Irving", confidence=30),
        ]
        candidates = [
            cme.ImportCandidate(
                "databazeknih",
                "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b",
                "",
                "https://dk/good",
                evidence_text="Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b John Irving",
            ),
            cme.ImportCandidate("databazeknih", "Imagin\u00e1rn\u00ed planeta", "", "https://dk/bad", evidence_text="Imagin\u00e1rn\u00ed planeta Jiny"),
        ]

        scored = cme.score_import_candidates(signals, candidates)

        self.assertEqual(scored[0].url, "https://dk/good")
        self.assertGreaterEqual(scored[0].score, 90)
        self.assertGreater(scored[0].score, scored[1].score)

    def test_score_import_candidates_gives_one_word_title_match_low_score(self):
        signals = [cme.ImportSourceSignal("filename", "Purpurov\u00e1 mumie", "Anatolij Dn\u011bprov")]
        candidates = [cme.ImportCandidate("databazeknih", "Purpurov\u00e1 planeta", "Jin\u00fd Autor", "https://dk/bad")]

        scored = cme.score_import_candidates(signals, candidates)

        self.assertLess(scored[0].score, 50)

    def test_score_import_candidates_uses_evidence_text_for_databaze_author(self):
        signals = [cme.ImportSourceSignal("epub-metadata", "Kniha", "Autor")]
        candidates = [
            cme.ImportCandidate("databazeknih", "Kniha", "", "https://dk/good", evidence_text="Kniha Autor"),
            cme.ImportCandidate("databazeknih", "Kniha", "", "https://dk/bad", evidence_text="Kniha Jiny"),
        ]

        scored = cme.score_import_candidates(signals, candidates)

        self.assertEqual(scored[0].url, "https://dk/good")
        self.assertGreater(scored[0].score, scored[1].score)

    def test_import_source_names_for_czech_english_and_unknown(self):
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="cs")]), ["databazeknih", "legie", "googlebooks", "openlibrary"])
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="en")]), ["databazeknih", "legie", "googlebooks", "openlibrary"])
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="cs"), cme.ImportSourceSignal("text", language="cs")]), ["databazeknih", "legie"])
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="en"), cme.ImportSourceSignal("text", language="en")]), ["googlebooks", "openlibrary"])
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="")]), ["databazeknih", "legie", "googlebooks", "openlibrary"])


class ImportOnlineLookupTests(unittest.TestCase):
    def test_lookup_import_candidates_uses_existing_parsers(self):
        signals = [cme.ImportSourceSignal("epub-metadata", "Turn Coat", "Jim Butcher", language="en")]
        google_json = json.dumps(
            {
                "items": [
                    {
                        "id": "abc",
                        "volumeInfo": {
                            "title": "Turn Coat",
                            "authors": ["Jim Butcher"],
                        },
                    }
                ]
            }
        )
        open_json = json.dumps({"docs": []})

        def fetcher(url):
            if "googleapis" in url:
                return google_json
            if "openlibrary" in url:
                return open_json
            return ""

        candidates = cme.lookup_import_candidates(signals, fetcher=fetcher)

        self.assertEqual(candidates[0].source, "googlebooks")
        self.assertEqual(candidates[0].title, "Turn Coat")
        self.assertEqual(candidates[0].authors, "Jim Butcher")

    def test_import_candidate_from_databaze_keeps_author_empty_and_uses_evidence(self):
        signals = [cme.ImportSourceSignal("epub-metadata", "Kniha", "Autor")]
        raw = cme.Candidate("Kniha", "volny text bez strukturovaneho autora", "https://dk/kniha")

        candidate = cme.import_candidate_from_search_candidate("databazeknih", raw, signals)

        self.assertEqual(candidate.authors, "")
        self.assertEqual(candidate.evidence_text, "volny text bez strukturovaneho autora")

    def test_lookup_import_candidates_single_english_language_calls_all_sources(self):
        signals = [cme.ImportSourceSignal("epub-metadata", "Turn Coat", "Jim Butcher", language="en")]
        calls = []

        def fetcher(url):
            calls.append(url)
            if "googleapis" in url:
                return json.dumps({"items": []})
            if "openlibrary" in url:
                return json.dumps({"docs": []})
            return ""

        cme.lookup_import_candidates(signals, fetcher=fetcher)

        self.assertTrue(any("databazeknih.cz" in url for url in calls))
        self.assertTrue(any("legie.info" in url for url in calls))
        self.assertTrue(any("googleapis" in url for url in calls))
        self.assertTrue(any("openlibrary" in url for url in calls))

    def test_lookup_import_candidates_continues_after_source_error(self):
        signals = [cme.ImportSourceSignal("epub-metadata", "Turn Coat", "Jim Butcher", language="en")]
        google_json = json.dumps(
            {
                "items": [
                    {
                        "id": "abc",
                        "volumeInfo": {"title": "Turn Coat", "authors": ["Jim Butcher"]},
                    }
                ]
            }
        )

        def fetcher(url):
            if "databazeknih.cz" in url:
                raise OSError("down")
            if "googleapis" in url:
                return google_json
            if "openlibrary" in url:
                return json.dumps({"docs": []})
            return ""

        candidates = cme.lookup_import_candidates(signals, fetcher=fetcher)

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].source, "googlebooks")

    def test_analyze_epub_for_import_keeps_fallback_preview_when_lookup_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "Jim Butcher - Turn Coat.epub"
            write_test_epub(epub, title="Turn Coat", creator="Jim Butcher", language="en")

            analysis = cme.analyze_epub_for_import(
                epub,
                library="B:\\",
                settings={},
                online_lookup=lambda _signals: (_ for _ in ()).throw(OSError("down")),
            )

        self.assertIsNone(analysis.recommended)
        self.assertEqual(analysis.candidates, [])
        self.assertEqual(analysis.preview.title, "Turn Coat")
        self.assertEqual(analysis.preview.authors, "Jim Butcher")


class ImportEpubParsingTests(unittest.TestCase):
    def test_filename_signal_cleans_broken_diacritics_and_reversed_author(self):
        signal = cme.import_signal_from_path(Path("C:/inbox/Irving John - Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a.epub"))

        self.assertEqual(signal.title, "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b")
        self.assertEqual(signal.authors, "John Irving")
        self.assertEqual(signal.source, "filename")

    def test_analyze_epub_for_import_combines_epub_and_filename_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "Irving John - Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a.epub"
            write_test_epub(epub)

            analysis = cme.analyze_epub_for_import(epub, library="B:\\", settings={}, online_lookup=lambda _signals: [])

        self.assertEqual(analysis.preview.title, "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b")
        self.assertEqual(analysis.preview.authors, "John Irving")
        self.assertGreaterEqual(len(analysis.signals), 2)

    def test_analyze_epub_for_import_prefers_clean_filename_over_broken_epub_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "Irving John - Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a.epub"
            write_test_epub(epub, title="Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a", creator="Irving John\u256a")

            analysis = cme.analyze_epub_for_import(epub, library="B:\\", settings={}, online_lookup=lambda _signals: [])

        self.assertEqual(analysis.preview.title, "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b")
        self.assertEqual(analysis.preview.authors, "John Irving")

    def test_analyze_epub_for_import_keeps_complete_metadata_over_title_only_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "Imaginarni pritelkyne.epub"
            write_test_epub(epub, title="Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a", creator="John Irving\u256a")

            analysis = cme.analyze_epub_for_import(epub, library="B:\\", settings={}, online_lookup=lambda _signals: [])

        self.assertTrue(cme.is_valid_import_preview(analysis.preview))
        self.assertEqual(analysis.preview.title, "Imagin\u00e1rn\u00ed p\u00b2\u00edtelkyn\u256a")
        self.assertEqual(analysis.preview.authors, "John Irving\u256a")

    def test_analyze_epub_for_import_ignores_weak_online_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "Jim Butcher - Turn Coat.epub"
            write_test_epub(epub, title="Turn Coat", creator="Jim Butcher", language="en")
            candidates = [cme.ImportCandidate("openlibrary", "Storm Front", "Jim Butcher", "https://weak")]

            analysis = cme.analyze_epub_for_import(
                epub,
                library="B:\\",
                settings={},
                online_lookup=lambda _signals: candidates,
            )

        self.assertIsNone(analysis.recommended)
        self.assertEqual(analysis.preview.title, "Turn Coat")
        self.assertEqual(analysis.preview.authors, "Jim Butcher")
        self.assertEqual(analysis.preview.url, "")

    def test_analyze_epub_for_import_reorders_candidates_before_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "Jim Butcher - Turn Coat.epub"
            write_test_epub(epub, title="Turn Coat", creator="Jim Butcher", language="en")
            candidates = [
                cme.ImportCandidate("openlibrary", "Storm Front", "Jim Butcher", "https://bad"),
                cme.ImportCandidate("googlebooks", "Turn Coat", "Jim Butcher", "https://good"),
            ]

            analysis = cme.analyze_epub_for_import(
                epub,
                library="B:\\",
                settings={},
                online_lookup=lambda _signals: candidates,
            )

        self.assertIsNotNone(analysis.recommended)
        self.assertEqual(analysis.recommended.url, "https://good")
        self.assertEqual(analysis.candidates[0].url, "https://good")
        self.assertEqual(analysis.preview.source, "googlebooks")

    def test_disabled_ai_resolver_returns_none(self):
        resolver = cme.DisabledAIResolver()

        choice = resolver.resolve([], [])

        self.assertIsNone(choice)

    def test_ollama_ai_resolver_returns_none_when_unavailable(self):
        def failing_requester(_url, _payload, _headers):
            raise OSError("offline")

        resolver = cme.OllamaAIResolver(requester=failing_requester)

        choice = resolver.resolve([], [cme.ImportCandidate("openlibrary", "Good", "Autor", "https://good")])

        self.assertIsNone(choice)

    def test_ai_choice_can_promote_matching_candidate(self):
        class FixedResolver:
            def resolve(self, _signals, _candidates):
                return cme.AIImportChoice("https://good", 90, "match")

        candidates = [
            cme.ImportCandidate("openlibrary", "Bad", "Autor", "https://bad", score=70),
            cme.ImportCandidate("openlibrary", "Good", "Autor", "https://good", score=60),
        ]

        selected = cme.resolve_import_candidate_with_ai([], candidates, FixedResolver())

        self.assertEqual(selected.url, "https://good")
        self.assertIn("ai=90", selected.reason)

    def test_ai_resolver_failure_falls_back_to_scored_candidate(self):
        class FailingResolver:
            def resolve(self, _signals, _candidates):
                raise OSError("offline")

        candidates = [cme.ImportCandidate("openlibrary", "Good", "Autor", "https://good", score=80)]

        selected = cme.resolve_import_candidate_with_ai([], candidates, FailingResolver())

        self.assertEqual(selected.url, "https://good")

    def test_low_score_candidate_is_not_recommended_without_ai_confidence(self):
        candidates = [cme.ImportCandidate("openlibrary", "Bad", "Autor", "https://bad", score=10)]

        selected = cme.resolve_import_candidate_with_ai([], candidates, cme.DisabledAIResolver())

        self.assertIsNone(selected)

    def test_ollama_ai_resolver_returns_none_on_malformed_response(self):
        # Ollama vrati nevalidni JSON nebo vnitrni "response" neni platny JSON.
        # resolve() musi chybu spolknout a vratit None bez vyjimky.
        candidates = [cme.ImportCandidate("openlibrary", "Good", "Autor", "https://good")]

        def invalid_outer_json(_url, _payload, _headers):
            return "this is not json"

        def malformed_inner_response(_url, _payload, _headers):
            return json.dumps({"response": "{not valid json"})

        for requester in (invalid_outer_json, malformed_inner_response):
            resolver = cme.OllamaAIResolver(requester=requester)
            choice = resolver.resolve([], candidates)
            self.assertIsNone(choice)

    def test_ai_choice_below_confidence_threshold_falls_back_to_scored(self):
        # AI vrati platnou URL, ale s confidence pod prahem 80.
        # Nesmi vybrat AI URL; ma padnout zpet na normalni skore (candidates[0]).
        class LowConfidenceResolver:
            def resolve(self, _signals, _candidates):
                return cme.AIImportChoice("https://good", 50, "match")

        candidates = [
            cme.ImportCandidate("openlibrary", "Top", "Autor", "https://top", score=85),
            cme.ImportCandidate("openlibrary", "Good", "Autor", "https://good", score=60),
        ]

        selected = cme.resolve_import_candidate_with_ai([], candidates, LowConfidenceResolver())

        self.assertEqual(selected.url, "https://top")
        self.assertNotEqual(selected.url, "https://good")

    def test_extract_year_reads_reasonable_publication_year(self):
        self.assertEqual(cme.extract_year("Published 1996-01-01"), "1996")
        self.assertEqual(cme.extract_year("bez roku"), "")

    def test_read_epub_metadata_extracts_basic_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_test_epub(epub)

            metadata = cme.read_epub_metadata(epub)

        self.assertEqual(metadata.title, "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b")
        self.assertEqual(metadata.authors, "John Irving")
        self.assertEqual(metadata.language, "cs")
        self.assertEqual(metadata.publisher, "Odeon")
        self.assertEqual(metadata.published_year, "1996")

    def test_read_epub_metadata_joins_multiple_creators(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_test_epub(epub, creators=["John One", "Jane Two"])

            metadata = cme.read_epub_metadata(epub)

        self.assertEqual(metadata.authors, "John One & Jane Two")

    def test_extract_epub_start_text_reads_spine_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_test_epub(epub, body="Tituln\u00ed strana\nSpr\u00e1vn\u00fd n\u00e1zev\nAutor")

            text = cme.extract_epub_start_text(epub, limit=80)

        self.assertIn("Tituln\u00ed strana", text)
        self.assertIn("Spr\u00e1vn\u00fd n\u00e1zev", text)

    def test_extract_epub_start_text_resolves_uri_spine_href(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_test_epub(
                epub,
                opf_path="OPS/package/content.opf",
                item_href="../Text/chapter%201.xhtml#start",
                item_path="OPS/Text/chapter 1.xhtml",
                body="Text pres relativni URI",
            )

            text = cme.extract_epub_start_text(epub, limit=80)

        self.assertIn("Text pres relativni URI", text)

    def test_extract_epub_start_text_reads_start_of_oversized_spine_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_test_epub(epub, body="Oversized zacatek " + ("A" * 6_000_000))

            text = cme.extract_epub_start_text(epub, limit=80)

        self.assertIn("Oversized zacatek", text)


class ParserAndMatchingTests(unittest.TestCase):
    def test_parse_search_results_uses_html_parser_and_converts_urls(self):
        fixture = Path(__file__).parent / "fixtures" / "databazeknih_search.html"
        candidates = cme.parse_search_results(fixture.read_text(encoding="utf-8"))
        self.assertEqual(candidates[0].title, "Loď osudu")
        self.assertEqual(candidates[0].url, "https://www.databazeknih.cz/knihy/zive-lode-lod-osudu-152421")
        self.assertIn("Robin Hobb", candidates[0].text)

    def test_parse_search_results_uses_anchor_text_when_image_title_missing(self):
        html = "<a href='/prehled-knihy/purpurova-planeta-60769'>Purpurova planeta</a>"

        candidates = cme.parse_search_results(html)

        self.assertEqual(candidates[0].title, "Purpurova planeta")

    def test_parse_legie_story_detail_reads_story_metadata(self):
        fixture = Path(__file__).parent / "fixtures" / "legie_story_7347.html"

        detail = cme.parse_legie_story_detail(
            fixture.read_text(encoding="utf-8"),
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
        )

        self.assertEqual(detail.legie_id, "7347")
        self.assertEqual(detail.title, "A opice si myslely, že to všechno je z legrace")
        self.assertEqual(detail.author, "Orson Scott Card")
        self.assertEqual(detail.category, "sci-fi")
        self.assertEqual(detail.rating_percent, "80 %")
        self.assertEqual(detail.rating_count, "11")
        self.assertEqual(detail.original_title, "The Monkeys Thought 'Twas All in Fun")
        self.assertEqual(detail.original_publication, "05/1979")
        self.assertEqual(detail.czech_publication, "Ikarie 1995/05")
        self.assertIn("Petr Kotrle", detail.about_text)

    def test_parse_legie_story_detail_extracts_cover_url(self):
        detail = cme.parse_legie_story_detail(
            """
            <div id="pro_obal">
              <img src="images/kniha-small/1/138-2213.jpg" class="obal_kniha" title="prebal knihy" />
            </div>
            """,
            "https://www.legie.info/povidka/40",
        )

        self.assertEqual(detail.cover_url, "https://www.legie.info/images/kniha-small/1/138-2213.jpg")

    def test_parse_legie_story_detail_handles_missing_publication_and_void_tags(self):
        html = """
        <h2 id="nazev_povidky">Povidka</h2>
        <p id="jine_nazvy">originální název: Original Story</p>
        <div id="anotace">Prvni veta.<br />Druha veta.<hr />Petr Kotrle</div>
        """

        detail = cme.parse_legie_story_detail(html, "https://www.legie.info/povidka/1-povidka")

        self.assertEqual(detail.original_title, "Original Story")
        self.assertEqual(detail.original_publication, "")
        self.assertIn("Druha veta.", detail.about_text)
        self.assertIn("Petr Kotrle", detail.about_text)

    def test_parse_legie_search_results_reads_story_candidates(self):
        fixture = Path(__file__).parent / "fixtures" / "legie_search_story.html"

        candidates = cme.parse_legie_search_results(fixture.read_text(encoding="utf-8"))

        self.assertEqual(candidates[0].title, "A opice si myslely, že to všechno je z legrace")
        self.assertEqual(
            candidates[0].url,
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
        )
        self.assertIn("Orson Scott Card", candidates[0].text)

    def test_parse_legie_search_results_reads_direct_story_detail_page(self):
        html = """
        <h3><a href="autor/806-anatolij-petrovic-dneprov">Anatolij Petrovič Dněprov</a></h3>
        <h2 id="nazev_povidky">Purpurová mumie</h2>
        <ul id="zalozky">
          <li><a href="povidka/31031/zakladni-info#zalozky">základní informace</a></li>
          <li><a href="povidka/31031/diskuze#zalozky">diskuze</a></li>
        </ul>
        """

        candidates = cme.parse_legie_search_results(html)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Purpurová mumie")
        self.assertIn("Anatolij Petrovič Dněprov", candidates[0].text)
        self.assertEqual(candidates[0].url, "https://www.legie.info/povidka/31031")

    def test_match_legie_story_candidate_returns_review_never_approve(self):
        book = cme.Book(429, "A opice si myslely, že je to všechno jen legrace", ["Orson Scott Card"], "")
        candidates = [
            cme.Candidate(
                "A opice si myslely, že to všechno je z legrace",
                "A opice si myslely, že to všechno je z legrace Orson Scott Card",
                "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            )
        ]

        row = cme.match_legie_story(book, candidates)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.status, "review")
        self.assertEqual(row.source, "legie")
        self.assertEqual(row.work_type, "povidka")
        self.assertEqual(row.reason, "legie-story-candidate")

    def test_match_legie_story_accepts_inverted_author_name_order(self):
        book = cme.Book(554, "Samuela", ["Anatolij Petrovic Dneprov"], "")
        candidates = [
            cme.Candidate(
                "Samuela",
                "Samuela Dneprov, Anatolij Petrovic",
                "https://www.legie.info/povidka/393-anatolij-petrovic-dneprov-samuela",
            )
        ]

        row = cme.match_legie_story(book, candidates)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.chosen_url, "https://www.legie.info/povidka/393-anatolij-petrovic-dneprov-samuela")

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

    def test_parse_book_detail_metadata_reads_original_title_and_publication(self):
        html = """
        <div>
          <span>Originální název:</span>
          <span>Twenty Pence with Envelope and Seasonal Greeting (12/1987)</span>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.original_title, "Twenty Pence with Envelope and Seasonal Greeting")
        self.assertEqual(detail.original_publication, "12/1987")

    def test_parse_book_detail_metadata_reads_original_publication_without_title(self):
        html = """
        <div class='book-details__row'>
          <dt>OriginÃ¡l vyÅ¡el</dt>
          <dd>1987</dd>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.original_title, "")
        self.assertEqual(detail.original_publication, "1987")

    def test_parse_book_detail_metadata_reads_first_publication_year_as_original_publication(self):
        html = """
        <div class='book-details__row'>
          <dt>Rok 1. vydání</dt>
          <dd>1987</dd>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.original_title, "")
        self.assertEqual(detail.original_publication, "1987")

    def test_parse_book_detail_metadata_reads_original_title_and_separate_publication(self):
        html = """
        <div class='book-details__row'>
          <dt>OriginÃ¡lnÃ­ nÃ¡zev</dt>
          <dd>Sourcery</dd>
        </div>
        <div class='book-details__row'>
          <dt>OriginÃ¡l vyÅ¡el</dt>
          <dd>1988</dd>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.original_title, "Sourcery")
        self.assertEqual(detail.original_publication, "1988")

    def test_parse_book_detail_metadata_reads_original_publisher(self):
        html = """
        <div class='book-details__row'>
          <dt>OriginÃ¡lnÃ­ vydavatel</dt>
          <dd>Gollancz</dd>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.original_publisher, "Gollancz")

    def test_parse_google_books_search_results_and_metadata(self):
        search_json = """
        {
          "items": [
            {
              "id": "cf1Tl4WhhHUC",
              "volumeInfo": {
                "title": "Turn Coat",
                "authors": ["Jim Butcher"]
              }
            }
          ]
        }
        """
        detail_json = """
        {
          "id": "cf1Tl4WhhHUC",
          "volumeInfo": {
            "title": "Turn Coat",
            "authors": ["Jim Butcher"],
            "publisher": "Penguin",
            "publishedDate": "2009-04-07",
            "description": "<p>Wizard Harry Dresden faces a traitor.</p>",
            "categories": ["Fiction / Fantasy"],
            "averageRating": 4.5,
            "ratingsCount": 12,
            "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"}
          }
        }
        """

        candidates = cme.parse_google_books_search_results(search_json)
        written_url, detail = cme.parse_google_books_volume_metadata(detail_json)

        self.assertEqual(candidates[0].title, "Turn Coat")
        self.assertEqual(candidates[0].url, "https://books.google.com/books?id=cf1Tl4WhhHUC")
        self.assertEqual(written_url, "https://books.google.com/books?id=cf1Tl4WhhHUC")
        self.assertEqual(detail.published_year, "2009")
        self.assertEqual(detail.publisher, "Penguin")
        self.assertEqual(detail.tags, ["Fiction / Fantasy"])
        self.assertEqual(detail.rating_percent, "4,5 / 5 (12 hodnoceni)")
        self.assertEqual(detail.about_text, "Wizard Harry Dresden faces a traitor.")
        self.assertEqual(detail.cover_url, "https://books.google.com/cover.jpg")

    def test_parse_openlibrary_search_results_and_metadata(self):
        search_json = """
        {
          "docs": [
            {
              "title": "Homo Deus: A Brief History of Tomorrow",
              "author_name": ["Yuval Noah Harari"],
              "edition_key": ["OL26247313M"]
            }
          ]
        }
        """
        detail_json = """
        {
          "key": "/books/OL26247313M",
          "publish_date": "2015",
          "publishers": ["Harvill Secker"],
          "subjects": ["Civilization, modern, 21st century", "Technology and civilization"],
          "description": {"value": "<p>Future of humanity.</p>"},
          "covers": [123456]
        }
        """

        candidates = cme.parse_openlibrary_search_results(search_json)
        written_url, detail = cme.parse_openlibrary_edition_metadata(detail_json)

        self.assertEqual(candidates[0].title, "Homo Deus: A Brief History of Tomorrow")
        self.assertEqual(candidates[0].url, "https://openlibrary.org/books/OL26247313M")
        self.assertEqual(written_url, "https://openlibrary.org/books/OL26247313M")
        self.assertEqual(detail.published_year, "2015")
        self.assertEqual(detail.publisher, "Harvill Secker")
        self.assertEqual(detail.tags, ["Civilization, modern, 21st century", "Technology and civilization"])
        self.assertEqual(detail.about_text, "Future of humanity.")
        self.assertEqual(detail.cover_url, "https://covers.openlibrary.org/b/id/123456-L.jpg")

    def test_parse_book_detail_metadata_prefers_visible_publication_year_over_bad_json_ld_year(self):
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Book",
          "datePublished": "0101-01-01",
          "publisher": [{"@type": "Organization", "name": "AF 167"}],
          "genre": ["Fantasy"]
        }
        </script>
        <div class="lora lineHeightMid">
          <a href='/zanry/fantasy-21'>Fantasy</a><br />
          1992
          <span class='pozn'>,</span>
          <a href='/nakladatelstvi/af-304'>AF 167</a>
          <dl class='book-details'></dl>
        </div>
        """

        detail = cme.parse_book_detail_metadata(html)

        self.assertEqual(detail.published_year, "1992")

    def test_parse_oldest_edition_metadata_reads_oldest_year_publisher_and_url(self):
        html = """
        <a href='/prehled-knihy/wrong-navigation-link'>Dalsi dil</a>
        <div class="lora lineHeightMid">
          <a href='/zanry/sci-fi-19'>Sci-fi</a><br />
          1997
          <span class='pozn'>,</span>
          <a href='/nakladatelstvi/baronet-206'>Baronet</a>
          ,
          <a href='/nakladatelstvi/knizni-klub-96'>Knizni klub</a>
        </div>
        <a class='bigger' href='/prehled-knihy/current-2016'>2001: Vesmirna odysea</a>
        <p class='new odtopm'>
          2016<span class="pozn_light">,</span>
          <a href="/nakladatelstvi/argo-50">Argo</a>
          ,
          <a href="/nakladatelstvi/triton-51">Triton</a>
        </p>
        <a class='bigger' href='/prehled-knihy/oldest-1971'>2001: Vesmirna odysea</a>
        <p class='new odtopm'>
          1971<span class="pozn_light">,</span>
          <a href="/nakladatelstvi/svoboda-5744">Svoboda</a>
        <div class='dropdown_black'></div>
        """

        edition = cme.parse_oldest_edition_metadata(html)

        self.assertEqual(edition.published_year, "1971")
        self.assertEqual(edition.publisher, "Svoboda")
        self.assertEqual(edition.url, "https://www.databazeknih.cz/prehled-knihy/oldest-1971")

    def test_parse_oldest_edition_metadata_handles_unclosed_format_icons(self):
        html = """
        <div class='lora lineHeightMid'>
          <img title="pevna vazba" src="/img/icons/formats/book.svg">
          2016<span>,</span>
          <a href="/nakladatelstvi/argo-50">Argo</a>
        </div>
        <a href="/prehled-knihy/abaddonova-brana-386979">
          <picture><img title="Abaddonova brana (2014)" /></picture>
        </a>
        <h6>Abaddonova brana</h6>
        <p class='new odtopm'>
          <img title="ekniha" src="/img/icons/formats/ebook.svg">
          2014<span class="pozn_light">,</span>
          <a href="/nakladatelstvi/triton-158">Triton</a>
          <div class='dropdown_black'></div>
          <span class="pozn odtopm fright">ISBN: 978-80-7387-799-6</span>
        </p>
        """

        edition = cme.parse_oldest_edition_metadata(html)

        self.assertEqual(edition.published_year, "2014")
        self.assertEqual(edition.publisher, "Triton")
        self.assertEqual(edition.url, "https://www.databazeknih.cz/prehled-knihy/abaddonova-brana-386979")

    def test_parse_oldest_edition_metadata_reads_year_without_publisher(self):
        html = """
        <a href='/prehled-knihy/cesta-krve-cynik-1064'>Cynik</a>
        <div class='lora lineHeightMid'>
          <a href='/zanry/romany-12'>Romany</a><span class='pozn'>,</span>
          <a href='/zanry/sci-fi-19'>Sci-fi</a><br />
          <img title="ekniha" src="/img/icons/formats/ebook.svg">
          2004
          <span class='pozn'>,</span>
          <dl class='book-details'>
            <span id='moreBookDetails' bookId='60133'>Vice info...</span>
          </dl>
        </div>
        """

        edition = cme.parse_oldest_edition_metadata(html)

        self.assertEqual(edition.published_year, "2004")
        self.assertEqual(edition.publisher, "")
        self.assertEqual(edition.url, "")

    def test_match_book_approves_exact_title_and_author(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], "")
        candidates = [cme.Candidate("Loď osudu", "Robin Hobb", "https://www.databazeknih.cz/knihy/zive-lode-lod-osudu-152421")]
        match = cme.match_book(book, candidates)
        self.assertEqual(match.status, "approve")
        self.assertEqual(match.confidence, "exact-title-author")
        self.assertEqual(match.reason, "exact-title-author")

    def test_match_book_marks_databaze_story_url_as_povidka(self):
        book = cme.Book(554, "Samuela", ["Anatolij Petrovic Dneprov"], "")
        candidates = [
            cme.Candidate(
                "Samuela",
                "Povidka od: Anatolij Petrovic Dneprov",
                "https://www.databazeknih.cz/povidky/samuela-2229",
            )
        ]

        match = cme.match_book(book, candidates)

        self.assertEqual(match.status, "approve")
        self.assertEqual(match.source, "databazeknih")
        self.assertEqual(match.work_type, "povidka")

    def test_match_book_marks_title_only_as_review(self):
        book = cme.Book(309, "Loď osudu", ["Robin Hobb"], "")
        candidates = [cme.Candidate("Loď osudu", "Neznámý autor", "https://www.databazeknih.cz/knihy/foo-123")]
        match = cme.match_book(book, candidates)
        self.assertEqual(match.status, "review")
        self.assertEqual(match.reason, "title-only")

    def test_match_book_reviews_title_prefix_with_exact_author(self):
        book = cme.Book(12, "Sapiens", ["Yuval Noah Harari"], "")
        candidates = [
            cme.Candidate(
                "3x Harari v darkovem boxu",
                "3x Harari v darkovem boxu Yuval Noah Harari",
                "https://www.databazeknih.cz/knihy/3x-harari-486050",
            ),
            cme.Candidate(
                "Sapiens: Od zvirete k bozskemu jedinci",
                "Sapiens: Od zvirete k bozskemu jedinci Yuval Noah Harari",
                "https://www.databazeknih.cz/knihy/sapiens-od-zvirete-k-bozskemu-jedinci-183405",
            ),
            cme.Candidate(
                "Homo sapiens stupidus",
                "Homo sapiens stupidus Frantisek Koukolik",
                "https://www.databazeknih.cz/knihy/homo-sapiens-stupidus-25440",
            ),
        ]

        match = cme.match_book(book, candidates)

        self.assertEqual(match.status, "review")
        self.assertEqual(match.reason, "title-prefix-author")
        self.assertEqual(match.chosen_url, "https://www.databazeknih.cz/knihy/sapiens-od-zvirete-k-bozskemu-jedinci-183405")

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

    def test_find_databaze_book_skips_audiobook_candidate(self):
        book = cme.Book(99, "Devet princu Amberu", ["Roger Zelazny"], "")
        search_html = """
        <a href="https://www.databazeknih.cz/prehled-knihy/devet-princu-amberu-543357">
          <img title="Devet princu Amberu" />
          Devet princu Amberu
        </a>
        <p>Roger Zelazny</p>
        <a href="https://www.databazeknih.cz/prehled-knihy/tajemny-amber-kroniky-amberu-devet-princu-amberu-12111">
          <img title="Devet princu Amberu" />
          Devet princu Amberu
        </a>
        <p>Roger Zelazny</p>
        """
        audiobook_more = """
        <div class='book-details__row'><dt>Forma</dt><dd>audiokniha</dd></div>
        """
        book_more = """
        <div class='book-details__row'><dt>Forma</dt><dd>klasicka kniha</dd></div>
        """

        def fetcher(url: str) -> str:
            if "book-detail-more-info/543357" in url:
                return audiobook_more
            if "book-detail-more-info/12111" in url:
                return book_more
            return search_html

        row = cme.find_databaze_book(
            book,
            fetcher=fetcher,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(row.status, "approve")
        self.assertEqual(
            row.chosen_url,
            "https://www.databazeknih.cz/knihy/tajemny-amber-kroniky-amberu-devet-princu-amberu-12111",
        )

    def test_match_book_skips_empty_candidate_title_instead_of_partial_match(self):
        book = cme.Book(31031, "Purpurova mumie", ["Anatolij Petrovic Dneprov"], "")
        candidates = [
            cme.Candidate(
                "",
                "Purpurova planeta jiny autor",
                "https://www.databazeknih.cz/knihy/purpurova-planeta-60769",
            )
        ]

        match = cme.match_book(book, candidates)

        self.assertEqual(match.status, "skip")
        self.assertEqual(match.chosen_url, "")
        self.assertEqual(match.reason, "no-candidates")

    def test_match_book_skips_one_shared_word_instead_of_partial_match(self):
        book = cme.Book(31031, "Purpurova mumie", ["Anatolij Petrovic Dneprov"], "")
        candidates = [
            cme.Candidate(
                "Purpurova planeta",
                "Purpurova planeta jiny autor",
                "https://www.databazeknih.cz/knihy/purpurova-planeta-60769",
            )
        ]

        match = cme.match_book(book, candidates)

        self.assertEqual(match.status, "skip")
        self.assertEqual(match.chosen_url, "")
        self.assertEqual(match.reason, "no-candidates")

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

    def test_preview_books_uses_legie_for_uncertain_databaze_match(self):
        db_html = "<a href='/prehled-knihy/plast-z-opici-kuze-265268'>Plast z opici kuze</a>"
        legie_html = (Path(__file__).parent / "fixtures" / "legie_search_story.html").read_text(encoding="utf-8")

        def fetcher(url: str) -> str:
            return legie_html if "legie.info" in url else db_html

        rows = cme.preview_books(
            [cme.Book(429, "A opice si myslely, že je to všechno jen legrace", ["Orson Scott Card"], "")],
            fetcher=fetcher,
            robots_checker=lambda: True,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(rows[0].source, "legie")
        self.assertEqual(rows[0].work_type, "povidka")
        self.assertEqual(rows[0].status, "review")

    def test_preview_books_skips_weak_databaze_match_when_legie_finds_nothing(self):
        db_html = "<a href='/prehled-knihy/purpurova-planeta-60769'>Purpurova planeta</a>"

        def fetcher(url: str) -> str:
            return "" if "legie.info" in url else db_html

        rows = cme.preview_books(
            [cme.Book(31031, "Purpurova mumie", ["Anatolij Petrovic Dneprov"], "")],
            fetcher=fetcher,
            robots_checker=lambda: True,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(rows[0].status, "skip")
        self.assertEqual(rows[0].chosen_url, "")

    def test_preview_books_uses_legie_for_purpurova_mumie_story(self):
        db_html = "<a href='/prehled-knihy/purpurova-planeta-60769'>Purpurova planeta</a>"
        legie_html = """
        <a href="https://www.legie.info//povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie">
          Purpurova mumie
        </a>
        <span>Anatolij Petrovic Dneprov</span>
        """

        def fetcher(url: str) -> str:
            return legie_html if "legie.info" in url else db_html

        rows = cme.preview_books(
            [cme.Book(31031, "Purpurova mumie", ["Anatolij Petrovic Dneprov"], "")],
            fetcher=fetcher,
            robots_checker=lambda: True,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(rows[0].status, "review")
        self.assertEqual(rows[0].source, "legie")
        self.assertEqual(rows[0].chosen_url, "https://www.legie.info/povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie")

    def test_audit_legie_rows_turns_suspicious_skip_into_review(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, že je to všechno jen legrace",
            "Orson Scott Card",
            "skip",
            "https://www.databazeknih.cz/knihy/plast-z-opici-kuze-265268",
            "",
            "title-only",
            "title-only",
            "databazeknih",
            "",
        )
        legie_html = (Path(__file__).parent / "fixtures" / "legie_search_story.html").read_text(encoding="utf-8")

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: legie_html,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "legie")
        self.assertEqual(updated[0].work_type, "povidka")

    def test_audit_legie_rows_keeps_approved_exact_databaze_rows(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, že je to všechno jen legrace",
            "Orson Scott Card",
            "approve",
            "https://www.databazeknih.cz/knihy/plast-z-opici-kuze-265268",
            "",
            "exact-title-author",
            "exact-title-author",
            "databazeknih",
            "",
        )

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: self.fail("approved rows must not be searched"),
            sleeper=lambda seconds: self.fail("approved rows must not sleep"),
            sleep_seconds=0,
        )

        self.assertEqual(updated, [row])

    def test_audit_legie_rows_can_review_approved_weak_databaze_row(self):
        row = cme.MatchRow(
            31031,
            "Purpurova mumie",
            "Anatolij Petrovic Dneprov",
            "approve",
            "https://www.databazeknih.cz/knihy/purpurova-planeta-60769",
            "",
            "partial-title",
            "partial-title",
            "databazeknih",
            "",
        )
        legie_html = """
        <a href="https://www.legie.info//povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie">
          Purpurova mumie
        </a>
        <span>Anatolij Petrovic Dneprov</span>
        """

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: legie_html,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "legie")
        self.assertEqual(updated[0].work_type, "povidka")

    def test_audit_legie_rows_tries_databaze_before_legie_for_missing_candidate(self):
        row = cme.MatchRow(
            554,
            "Samuela",
            "Anatolij Petrovic Dneprov",
            "skip",
            "",
            "",
            "none",
            "no-candidates",
            "databazeknih",
            "",
        )
        db_html = """
        <a href="https://www.databazeknih.cz/povidky/samuela-2229">
            <img title="Samuela" />
            Samuela
        </a>
        <p>Povidka od: Anatolij Petrovic Dneprov</p>
        """
        fetched_urls = []

        def fetcher(url: str) -> str:
            fetched_urls.append(url)
            return db_html if "databazeknih.cz" in url else ""

        updated = cme.audit_legie_rows(
            [row],
            fetcher=fetcher,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(fetched_urls[0], cme.build_search_url("Samuela", ["Anatolij Petrovic Dneprov"]))
        self.assertEqual(updated[0].chosen_url, "https://www.databazeknih.cz/povidky/samuela-2229")
        self.assertEqual(updated[0].source, "databazeknih")
        self.assertEqual(updated[0].work_type, "povidka")

    def test_audit_legie_rows_retries_databaze_without_diacritics_and_punctuation(self):
        row = cme.MatchRow(
            459,
            "Stráže stráže",
            "Terry Pratchett",
            "skip",
            "",
            "",
            "none",
            "no-candidates",
            "databazeknih",
            "",
        )
        db_html = """
        <a href="https://www.databazeknih.cz/prehled-knihy/straze-straze-459">
          <img title="Stráže! Stráže!" />
          Stráže! Stráže!
        </a>
        <p>Terry Pratchett</p>
        """
        fetched_urls = []

        def fetcher(url: str) -> str:
            fetched_urls.append(url)
            return db_html if "straze+straze+terry+pratchett" in url else ""

        updated = cme.audit_legie_rows(
            [row],
            fetcher=fetcher,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].chosen_url, "https://www.databazeknih.cz/knihy/straze-straze-459")
        self.assertIn(cme.build_search_url("straze straze", ["terry pratchett"]), fetched_urls)

    def test_audit_legie_rows_rechecks_already_linked_row_when_url_was_cleared(self):
        row = cme.MatchRow(
            12,
            "Sapiens",
            "Yuval Noah Harari",
            "skip",
            "",
            "",
            "none",
            "already-linked",
            "databazeknih",
            "",
        )
        db_html = """
        <a href="https://www.databazeknih.cz/prehled-knihy/sapiens-254943">
          <img title="Sapiens" />
          Sapiens
        </a>
        <p>Yuval Noah Harari</p>
        """

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: db_html,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "approve")
        self.assertEqual(updated[0].chosen_url, "https://www.databazeknih.cz/knihy/sapiens-254943")

    def test_audit_legie_rows_clears_unconfirmed_already_linked_url(self):
        row = cme.MatchRow(
            171,
            "Exercised",
            "Daniel Lieberman",
            "skip",
            "https://www.databazeknih.cz/knihy/basic-grammar-exercises-367677",
            "",
            "none",
            "already-linked",
            "databazeknih",
            "",
        )

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: "",
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].chosen_url, "")
        self.assertEqual(updated[0].reason, "stale-already-linked")

    def test_audit_legie_rows_keeps_manual_url_without_recheck(self):
        row = cme.MatchRow(
            171,
            "Exercised",
            "Daniel Lieberman",
            "review",
            "https://www.goodreads.com/book/show/123-exercised",
            "",
            "manual",
            "manual",
            "goodreads",
            "",
        )

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: self.fail("manual rows must not be searched"),
            sleeper=lambda seconds: self.fail("manual rows must not sleep"),
            sleep_seconds=0,
        )

        self.assertEqual(updated, [row])

    def test_audit_legie_rows_fixes_existing_openlibrary_source(self):
        row = cme.MatchRow(
            196,
            "Homo Deus: A Brief History of Tomorrow",
            "Yuval Noah Harari",
            "review",
            "https://openlibrary.org/books/OL26247313M/Homo_Deus_A_Brief_History_of_Tomorrow",
            "",
            "openlibrary-title-author",
            "openlibrary-title-author",
            "databazeknih",
            "",
            review_published_year="1925",
            review_publisher="Mars",
            review_tags="Literatura světová",
            review_rating_percent="73 %",
            review_original_publication="1923",
        )

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: self.fail("existing Open Library URL should not need search"),
            sleeper=lambda seconds: self.fail("existing Open Library URL should not sleep"),
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "openlibrary")
        self.assertEqual(updated[0].chosen_url, row.chosen_url)
        self.assertEqual(updated[0].review_published_year, "")
        self.assertEqual(updated[0].review_publisher, "")
        self.assertEqual(updated[0].review_tags, "")
        self.assertEqual(updated[0].review_rating_percent, "")
        self.assertEqual(updated[0].review_original_publication, "")

    def test_audit_legie_rows_uses_google_books_for_english_book(self):
        row = cme.MatchRow(
            182,
            "Turn Coat",
            "Jim Butcher",
            "skip",
            "https://www.databazeknih.cz/knihy/turn-100-let-mesta-trnovany-teplice-288904",
            "",
            "none",
            "already-linked",
            "databazeknih",
            "",
        )
        google_json = """
        {"items":[{"id":"cf1Tl4WhhHUC","volumeInfo":{"title":"Turn Coat","authors":["Jim Butcher"]}}]}
        """

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: google_json,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "googlebooks")
        self.assertEqual(updated[0].chosen_url, "https://books.google.com/books?id=cf1Tl4WhhHUC")

    def test_audit_legie_rows_falls_back_to_openlibrary_for_english_book(self):
        row = cme.MatchRow(
            11,
            "Homo Deus: A Brief History of Tomorrow",
            "Yuval Noah Harari",
            "skip",
            "",
            "",
            "none",
            "no-candidates",
            "databazeknih",
            "",
        )
        google_json = '{"items":[]}'
        openlibrary_json = """
        {"docs":[{"title":"Homo Deus: A Brief History of Tomorrow","author_name":["Yuval Noah Harari"],"edition_key":["OL26247313M"]}]}
        """

        def fetcher(url: str) -> str:
            if "googleapis.com" in url:
                return google_json
            if "openlibrary.org/search.json" in url:
                return openlibrary_json
            return ""

        updated = cme.audit_legie_rows(
            [row],
            fetcher=fetcher,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "openlibrary")
        self.assertEqual(updated[0].chosen_url, "https://openlibrary.org/books/OL26247313M")

    def test_audit_legie_rows_retries_title_only_when_author_query_finds_nothing(self):
        row = cme.MatchRow(
            31031,
            "Purpurova mumie",
            "Anatolij Petrovic Dneprov",
            "review",
            "https://www.databazeknih.cz/knihy/purpurova-planeta-60769",
            "",
            "partial-title",
            "partial-title",
            "databazeknih",
            "",
        )
        legie_html = """
        <a href="https://www.legie.info//povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie">
          Purpurova mumie
        </a>
        <span>Anatolij Petrovic Dneprov</span>
        """
        fetched_urls = []

        def fetcher(url: str) -> str:
            fetched_urls.append(url)
            if url == cme.build_legie_search_url("Purpurova mumie", []):
                return legie_html
            return ""

        updated = cme.audit_legie_rows(
            [row],
            fetcher=fetcher,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(
            fetched_urls,
            [
                cme.build_search_url("Purpurova mumie", ["Anatolij Petrovic Dneprov"]),
                cme.build_legie_search_url("Purpurova mumie", ["Anatolij Petrovic Dneprov"]),
                cme.build_legie_search_url("Purpurova mumie", []),
            ],
        )
        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "legie")
        self.assertEqual(updated[0].chosen_url, "https://www.legie.info/povidka/31031-anatolij-petrovic-dneprov-purpurova-mumie")

    def test_audit_legie_rows_retries_shortened_title_when_full_title_finds_nothing(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, ze je to vsechno jen legrace",
            "Orson Scott Card",
            "skip",
            "",
            "",
            "none",
            "no-candidates",
            "databazeknih",
            "",
        )
        legie_html = """
        <a href="https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace">
          A opice si myslely, ze to vsechno je z legrace
        </a>
        <span>Orson Scott Card</span>
        """

        def fetcher(url: str) -> str:
            if url == cme.LEGIE_SEARCH_URL + "A+opice+si+myslely":
                return legie_html
            return ""

        updated = cme.audit_legie_rows(
            [row],
            fetcher=fetcher,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "legie")
        self.assertEqual(updated[0].chosen_url, "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace")

    def test_audit_legie_rows_marks_existing_legie_url_as_review(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, že je to všechno jen legrace",
            "Orson Scott Card",
            "skip",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            "",
            "none",
            "already-linked",
            "databazeknih",
            "",
        )

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: self.fail("existing Legie URL should not need search"),
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "legie")
        self.assertEqual(updated[0].work_type, "povidka")

    def test_audit_legie_rows_can_review_already_linked_databaze_candidate(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, že je to všechno jen legrace",
            "Orson Scott Card",
            "skip",
            "https://www.databazeknih.cz/knihy/plast-z-opici-kuze-265268",
            "",
            "none",
            "already-linked",
            "databazeknih",
            "",
        )
        legie_html = (Path(__file__).parent / "fixtures" / "legie_search_story.html").read_text(encoding="utf-8")

        updated = cme.audit_legie_rows(
            [row],
            fetcher=lambda url: legie_html,
            sleeper=lambda seconds: None,
            sleep_seconds=0,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].source, "legie")
        self.assertEqual(updated[0].work_type, "povidka")

    def test_run_legie_audit_backs_up_and_rewrites_matches_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            matches_path = Path(tmp) / "matches.csv"
            old_row = cme.MatchRow(
                429,
                "A opice si myslely, že je to všechno jen legrace",
                "Orson Scott Card",
                "skip",
                "https://www.databazeknih.cz/knihy/plast-z-opici-kuze-265268",
                "",
                "title-only",
                "title-only",
            )
            cme.write_matches_csv(matches_path, [old_row], overwrite=False)

            original_matches_path = cme.MATCHES_PATH
            original_audit_legie_rows = cme.audit_legie_rows
            try:
                cme.MATCHES_PATH = matches_path
                cme.audit_legie_rows = lambda rows, sleep_seconds: [
                    cme.MatchRow(
                        rows[0].book_id,
                        rows[0].title,
                        rows[0].authors,
                        "review",
                        "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
                        "",
                        "exact-title-author",
                        "legie-story-candidate",
                        "legie",
                        "povidka",
                    )
                ]

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = cme.run_legie_audit(SimpleNamespace(library="library", book_id=None, limit=None, sleep=0))
            finally:
                cme.MATCHES_PATH = original_matches_path
                cme.audit_legie_rows = original_audit_legie_rows

            rows = cme.read_matches_csv(matches_path)
            backup_files = list((Path(tmp) / "backups" / "matches").glob("matches-*.csv"))

        self.assertEqual(result, 0)
        self.assertEqual(rows[0].source, "legie")
        self.assertEqual(rows[0].work_type, "povidka")
        self.assertEqual(len(backup_files), 1)
        self.assertIn("Audit odkazu: zmeneno 1 radku", stdout.getvalue())

    def test_run_legie_audit_uses_selected_book_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            matches_path = Path(tmp) / "matches.csv"
            rows = [
                cme.MatchRow(1, "A", "Autor", "skip", "", "", "none", "no-candidates"),
                cme.MatchRow(2, "B", "Autor", "skip", "", "", "none", "no-candidates"),
                cme.MatchRow(3, "C", "Autor", "skip", "", "", "none", "no-candidates"),
            ]
            cme.write_matches_csv(matches_path, rows, overwrite=False)
            selected_ids = []

            original_matches_path = cme.MATCHES_PATH
            original_audit_legie_rows = cme.audit_legie_rows
            try:
                cme.MATCHES_PATH = matches_path

                def fake_audit_legie_rows(selected_rows, sleep_seconds):
                    selected_ids.extend(row.book_id for row in selected_rows)
                    return list(selected_rows)

                cme.audit_legie_rows = fake_audit_legie_rows

                with contextlib.redirect_stdout(io.StringIO()):
                    result = cme.run_legie_audit(
                        SimpleNamespace(library="library", book_id=None, book_ids=[2, 3], limit=None, sleep=0)
                    )
            finally:
                cme.MATCHES_PATH = original_matches_path
                cme.audit_legie_rows = original_audit_legie_rows

        self.assertEqual(result, 0)
        self.assertEqual(selected_ids, [2, 3])


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

    def test_read_matches_csv_defaults_source_and_work_type_for_old_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "book_id",
                        "title",
                        "authors",
                        "status",
                        "chosen_url",
                        "candidate_urls",
                        "confidence",
                        "reason",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "book_id": "429",
                    "title": "A opice si myslely, ze je to vsechno jen legrace",
                    "authors": "Orson Scott Card",
                    "status": "skip",
                    "chosen_url": "https://www.databazeknih.cz/knihy/plast-z-opici-kuze-265268",
                    "candidate_urls": "",
                    "confidence": "title-only",
                    "reason": "title-only",
                })

            rows = cme.read_matches_csv(path)

        self.assertEqual(rows[0].source, "databazeknih")
        self.assertEqual(rows[0].work_type, "")
        self.assertEqual(rows[0].cover_urls, "")
        self.assertEqual(rows[0].selected_cover_url, "")
        self.assertEqual(rows[0].cover_reason, "")

    def test_write_matches_csv_writes_source_and_work_type_columns(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, ze je to vsechno jen legrace",
            "Orson Scott Card",
            "review",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            "",
            "exact-title-author",
            "legie-story-candidate",
            "legie",
            "povidka",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            cme.write_matches_csv(path, [row], overwrite=False)
            headers = path.read_text(encoding="utf-8-sig").splitlines()[0].split(",")

        self.assertIn("source", headers)
        self.assertIn("work_type", headers)
        self.assertIn("cover_urls", headers)
        self.assertIn("selected_cover_url", headers)
        self.assertIn("cover_reason", headers)

    def test_write_matches_csv_writes_cover_columns(self):
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            "databazeknih",
            "",
            "https://img/1.jpg|https://img/2.jpg",
            "https://img/2.jpg",
            "multiple-cover-candidates",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            cme.write_matches_csv(path, [row], overwrite=False)
            rows = cme.read_matches_csv(path)

        self.assertEqual(rows[0].cover_urls, "https://img/1.jpg|https://img/2.jpg")
        self.assertEqual(rows[0].selected_cover_url, "https://img/2.jpg")
        self.assertEqual(rows[0].cover_reason, "multiple-cover-candidates")

    def test_write_matches_csv_writes_review_override_columns(self):
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://www.databazeknih.cz/knihy/a-1",
            "",
            "manual",
            "manual",
            review_published_year="1999",
            review_publisher="Talpress",
            review_tags="Fantasy, Humor",
            review_rating_percent="87 %",
            review_original_title="Moving Pictures",
            review_original_publication="1990",
            review_original_publisher="Gollancz",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            cme.write_matches_csv(path, [row], overwrite=False)
            rows = cme.read_matches_csv(path)

        self.assertEqual(rows[0].review_published_year, "1999")
        self.assertEqual(rows[0].review_publisher, "Talpress")
        self.assertEqual(rows[0].review_tags, "Fantasy, Humor")
        self.assertEqual(rows[0].review_rating_percent, "87 %")
        self.assertEqual(rows[0].review_original_title, "Moving Pictures")
        self.assertEqual(rows[0].review_original_publication, "1990")
        self.assertEqual(rows[0].review_original_publisher, "Gollancz")

    def test_write_matches_db_roundtrips_rows(self):
        rows = [
            cme.MatchRow(
                2,
                "Dva",
                "Autor",
                "review",
                "https://x",
                "",
                "manual",
                "manual",
                review_publisher="Laser",
                review_original_publisher="Gollancz",
            ),
            cme.MatchRow(1, "Jedna", "Autor", "skip", "", "", "none", "no-candidates"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.db"
            cme.write_matches_csv(path, rows, overwrite=False)
            loaded = cme.read_matches_csv(path)

        self.assertEqual([row.book_id for row in loaded], [2, 1])
        self.assertEqual(loaded[0].review_publisher, "Laser")
        self.assertEqual(loaded[0].review_original_publisher, "Gollancz")

    def test_write_matches_db_refuses_existing_rows_without_overwrite(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "review", "", "", "none", "x")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.db"
            cme.write_matches_csv(path, [row], overwrite=False)

            with self.assertRaises(FileExistsError):
                cme.write_matches_csv(path, [row], overwrite=False)

    def test_read_matches_db_falls_back_to_legacy_csv(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "review", "https://x", "", "manual", "manual")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "matches.db"
            legacy_path = Path(tmp) / "matches.csv"
            cme.write_matches_csv(legacy_path, [row], overwrite=False)

            loaded = cme.read_matches_csv(db_path)

        self.assertEqual(loaded[0].book_id, 1)
        self.assertEqual(loaded[0].chosen_url, "https://x")

    def test_matches_storage_exists_accepts_legacy_csv_next_to_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "matches.db"
            (Path(tmp) / "matches.csv").write_text("book_id\n", encoding="utf-8")

            self.assertTrue(cme.matches_storage_exists(db_path))

    def test_read_matches_db_adds_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """
                    create table match_rows (
                        book_id integer primary key,
                        sort_order integer not null,
                        title text not null default '',
                        authors text not null default '',
                        status text not null default '',
                        chosen_url text not null default '',
                        candidate_urls text not null default '',
                        confidence text not null default '',
                        reason text not null default ''
                    )
                    """
                )
                connection.execute(
                    "insert into match_rows (book_id, sort_order, title, authors, status, chosen_url, candidate_urls, confidence, reason) values (1, 0, 'Kniha', 'Autor', 'review', '', '', 'none', 'x')"
                )
                connection.commit()
            finally:
                connection.close()

            rows = cme.read_matches_csv(path)

        self.assertEqual(rows[0].book_id, 1)
        self.assertEqual(rows[0].review_publisher, "")

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

    def test_prune_missing_book_rows_removes_rows_not_in_calibre_books(self):
        rows = [
            cme.MatchRow(1, "Sirotek", "Autor", "review", "", "", "manual", "manual"),
            cme.MatchRow(4, "Realna", "Autor", "skip", "", "", "none", "x"),
        ]
        books = [cme.Book(4, "Realna", ["Autor"], "")]

        pruned = cme.prune_missing_book_rows(rows, books)

        self.assertEqual([row.book_id for row in pruned], [4])

    def test_replace_match_rows_preserves_review_overrides(self):
        old_row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "review",
            "https://old",
            "",
            "manual",
            "manual",
            review_published_year="1999",
        )
        refreshed = cme.MatchRow(1, "Kniha", "Autor", "skip", "https://new", "", "exact", "exact")

        merged = cme.replace_match_rows([old_row], [refreshed])

        self.assertEqual(merged[0].chosen_url, "https://new")
        self.assertEqual(merged[0].review_published_year, "1999")

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

    def test_run_preview_with_book_ids_refreshes_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matches.csv"
            old_rows = [
                cme.MatchRow(1, "Stara A", "Autor", "skip", "https://old/a", "", "manual", "manual"),
                cme.MatchRow(2, "Stara B", "Autor", "skip", "https://old/b", "", "manual", "manual"),
            ]
            cme.write_matches_csv(path, old_rows, overwrite=False)

            original_matches_path = cme.MATCHES_PATH
            original_read_books = cme.read_books
            original_preview_books = cme.preview_books
            seen_book_ids = []
            try:
                cme.MATCHES_PATH = path
                cme.read_books = lambda library, book_id=None, limit=None: [
                    cme.Book(1, "Nova A", ["Autor"], ""),
                    cme.Book(2, "Nova B", ["Autor"], ""),
                ]

                def fake_preview_books(books, sleep_seconds):
                    seen_book_ids.extend(book.id for book in books)
                    return [
                        cme.MatchRow(2, "Nova B", "Autor", "review", "https://new/b", "", "title-only", "title-only")
                    ]

                cme.preview_books = fake_preview_books

                with contextlib.redirect_stdout(io.StringIO()):
                    result = cme.run_preview(
                        SimpleNamespace(library="library", book_id=None, book_ids=[2], limit=None, sleep=0, overwrite=False)
                    )
            finally:
                cme.MATCHES_PATH = original_matches_path
                cme.read_books = original_read_books
                cme.preview_books = original_preview_books

            rows = cme.read_matches_csv(path)
            self.assertEqual(result, 0)
            self.assertEqual(seen_book_ids, [2])
            self.assertEqual([(row.book_id, row.title, row.chosen_url) for row in rows], [(1, "Stara A", "https://old/a"), (2, "Nova B", "https://new/b")])

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
        self.assertIn("book_ids", inspect.signature(cme.select_match_rows).parameters)
        self.assertEqual([row.book_id for row in cme.select_match_rows(rows, book_id=None, limit=1)], [1])
        self.assertEqual([row.book_id for row in cme.select_match_rows(rows, book_id=2, limit=1)], [2])
        self.assertEqual([row.book_id for row in cme.select_match_rows(rows, book_ids={2}, book_id=None, limit=1)], [2])

    def test_is_valid_apply_url_accepts_only_databaze_knih_book_urls(self):
        self.assertTrue(cme.is_valid_apply_url("https://www.databazeknih.cz/knihy/foo-123"))
        self.assertTrue(cme.is_valid_apply_url("https://www.databazeknih.cz/prehled-knihy/foo-123"))

    def test_is_writable_match_row_accepts_approved_legie_story(self):
        row = cme.MatchRow(
            429,
            "Povidka",
            "Autor",
            "approve",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            "",
            "exact-title-author",
            "legie-story-candidate",
            "legie",
            "povidka",
        )

        self.assertTrue(cme.is_writable_match_row(row))

    def test_is_writable_match_row_accepts_approved_legie_url_with_old_source(self):
        row = cme.MatchRow(
            429,
            "Povidka",
            "Autor",
            "approve",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            "",
            "manual",
            "manual",
            "databazeknih",
            "",
        )

        self.assertTrue(cme.is_writable_match_row(row))

    def test_is_writable_match_row_accepts_databaze_story_url_for_manual_link(self):
        row = cme.MatchRow(
            284,
            "Geroldův neskutečný trik",
            "Raymond Elias Feist",
            "approve",
            "https://www.databazeknih.cz/povidky/gerolduv-neskutecny-trik-geroldov-tajny-trik-13884",
            "",
            "manual",
            "manual",
        )

        self.assertTrue(cme.is_writable_match_row(row))

    def test_is_writable_match_row_accepts_manual_goodreads_url(self):
        row = cme.MatchRow(
            171,
            "Exercised",
            "Daniel Lieberman",
            "approve",
            "https://www.goodreads.com/book/show/53137961-exercised",
            "",
            "manual",
            "manual",
            "goodreads",
            "",
        )

        self.assertTrue(cme.is_writable_match_row(row))

    def test_is_writable_match_row_rejects_approved_empty_url(self):
        row = cme.MatchRow(177, "Change Your Diet", "Georgia Ede", "approve", "", "", "manual", "manual")

        self.assertFalse(cme.is_writable_match_row(row))

    def test_apply_match_row_skips_approved_empty_url(self):
        row = cme.MatchRow(177, "Change Your Diet", "Georgia Ede", "approve", "", "", "manual", "manual")
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: self.fail("empty URL clear should not fetch detail"),
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.chosen_url, "")
        self.assertEqual(result.error, "empty-url")
        self.assertEqual(calls, [])

    def test_apply_match_row_writes_databaze_story_link_only(self):
        row = cme.MatchRow(
            284,
            "Geroldův neskutečný trik",
            "Raymond Elias Feist",
            "approve",
            "https://www.databazeknih.cz/povidky/gerolduv-neskutecny-trik-geroldov-tajny-trik-13884",
            "",
            "manual",
            "manual",
        )
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: self.fail("manual story link should not fetch detail"),
        )

        self.assertEqual(result.status, "updated")
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("https://www.databazeknih.cz/povidky/gerolduv-neskutecny-trik", comments_field)
        self.assertFalse(any(arg.startswith("pubdate:") for arg in calls[0]))
        self.assertFalse(any(arg.startswith("publisher:") for arg in calls[0]))
        self.assertFalse(any(arg.startswith("tags:") for arg in calls[0]))

    def test_apply_match_row_writes_goodreads_manual_link_only(self):
        row = cme.MatchRow(
            171,
            "Exercised",
            "Daniel Lieberman",
            "approve",
            "https://www.goodreads.com/book/show/53137961-exercised",
            "",
            "manual",
            "manual",
            "goodreads",
            "",
        )
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: self.fail("manual Goodreads link should not fetch detail"),
        )

        self.assertEqual(result.status, "updated")
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("https://www.goodreads.com/book/show/53137961-exercised", comments_field)
        self.assertFalse(any(arg.startswith("pubdate:") for arg in calls[0]))
        self.assertFalse(any(arg.startswith("publisher:") for arg in calls[0]))
        self.assertFalse(any(arg.startswith("tags:") for arg in calls[0]))

    def test_apply_match_row_writes_google_books_metadata(self):
        row = cme.MatchRow(
            182,
            "Turn Coat",
            "Jim Butcher",
            "approve",
            "https://books.google.com/books?id=cf1Tl4WhhHUC",
            "",
            "googlebooks-title-author",
            "googlebooks-title-author",
            "googlebooks",
            "",
        )
        detail_json = """
        {
          "id": "cf1Tl4WhhHUC",
          "volumeInfo": {
            "publisher": "Penguin",
            "publishedDate": "2009",
            "description": "Harry Dresden novel.",
            "categories": ["Fantasy"],
            "averageRating": 4.5
          }
        }
        """
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: detail_json,
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.chosen_url, "https://books.google.com/books?id=cf1Tl4WhhHUC")
        self.assertIn("pubdate:2009-00-00", calls[0])
        self.assertIn("publisher:Penguin", calls[0])
        self.assertIn("tags:Fantasy", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("https://books.google.com/books?id=cf1Tl4WhhHUC", comments_field)
        self.assertIn("Harry Dresden novel.", comments_field)

    def test_apply_match_row_writes_openlibrary_metadata(self):
        row = cme.MatchRow(
            11,
            "Homo Deus: A Brief History of Tomorrow",
            "Yuval Noah Harari",
            "approve",
            "https://openlibrary.org/books/OL26247313M/Homo_Deus_A_Brief_History_of_Tomorrow",
            "",
            "openlibrary-title-author",
            "openlibrary-title-author",
            "openlibrary",
            "",
        )
        detail_json = """
        {
          "key": "/books/OL26247313M",
          "publish_date": "2015",
          "publishers": ["Harvill Secker"],
          "subjects": ["Civilization"],
          "description": "Future of humanity."
        }
        """
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: detail_json,
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.chosen_url, "https://openlibrary.org/books/OL26247313M")
        self.assertIn("pubdate:2015-00-00", calls[0])
        self.assertIn("publisher:Harvill Secker", calls[0])
        self.assertIn("tags:Civilization", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("https://openlibrary.org/books/OL26247313M", comments_field)
        self.assertIn("Future of humanity.", comments_field)

    def test_apply_match_row_writes_legie_story_comment_tags_and_identifier(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely, že je to všechno jen legrace",
            "Orson Scott Card",
            "approve",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            "",
            "exact-title-author",
            "legie-story-candidate",
            "legie",
            "povidka",
        )
        fixture = Path(__file__).parent / "fixtures" / "legie_story_7347.html"
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: fixture.read_text(encoding="utf-8"),
            identifiers_reader=lambda library, book_id: {"isbn": "123"},
            tags_reader=lambda library, book_id: ["Sci-fi"],
        )

        self.assertEqual(result.status, "updated")
        self.assertIn("identifiers:isbn:123,legie:7347", calls[0])
        self.assertIn("tags:Sci-fi,povidka", calls[0])
        self.assertFalse(any(arg.startswith("pubdate:") for arg in calls[0]))
        self.assertFalse(any(arg.startswith("publisher:") for arg in calls[0]))
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("https://www.legie.info/povidka/7347", comments_field)
        self.assertIn("<strong>80 %", comments_field)
        self.assertIn("Ikarie 1995/05", comments_field)

    def test_apply_match_row_writes_selected_cover_with_databaze_metadata(self):
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "approve",
            "https://www.databazeknih.cz/knihy/new-2",
            "",
            "exact-title-author",
            "exact-title-author",
            cover_urls="https://img/1.jpg|https://img/2.jpg",
            selected_cover_url="https://img/2.jpg",
        )
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: "<div></div>",
            cover_fetcher=lambda url: b"cover-bytes",
        )

        self.assertEqual(result.status, "updated")
        cover_field = next(arg for arg in calls[0] if arg.startswith("cover:"))
        self.assertTrue(cover_field.endswith(".jpg"))

    def test_apply_match_row_writes_selected_cover_with_legie_metadata(self):
        row = cme.MatchRow(
            429,
            "A opice si myslely",
            "Orson Scott Card",
            "approve",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
            "",
            "exact-title-author",
            "legie-story-candidate",
            "legie",
            "povidka",
            cover_urls="https://img/1.jpg|https://img/2.jpg",
            selected_cover_url="https://img/2.jpg",
        )
        fixture = Path(__file__).parent / "fixtures" / "legie_story_7347.html"
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: fixture.read_text(encoding="utf-8"),
            identifiers_reader=lambda library, book_id: {},
            tags_reader=lambda library, book_id: [],
            cover_fetcher=lambda url: b"cover-bytes",
        )

        self.assertEqual(result.status, "updated")
        cover_field = next(arg for arg in calls[0] if arg.startswith("cover:"))
        self.assertTrue(cover_field.endswith(".jpg"))

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
        self.assertEqual(
            fetched_urls,
            [
                "https://www.databazeknih.cz/prehled-knihy/new-2",
                "https://www.databazeknih.cz/book-detail-more-info/2",
            ],
        )
        self.assertEqual(calls[0][0], r"C:\calibredb.exe")
        self.assertIn("--field", calls[0])
        self.assertIn("pubdate:2013-00-00", calls[0])
        self.assertIn("publisher:Fantom Print", calls[0])
        self.assertIn("tags:Fantasy,draci", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("<strong>89 %</strong>", comments_field)
        self.assertIn("Novy popis.", comments_field)

    def test_apply_match_row_uses_review_override_metadata(self):
        row = cme.MatchRow(
            1,
            "Kniha",
            "Autor",
            "approve",
            "https://www.databazeknih.cz/knihy/new-2",
            "",
            "exact-title-author",
            "exact-title-author",
            review_published_year="1999",
            review_publisher="Rucni vydavatel",
            review_tags="Rucni, Tag",
            review_rating_percent="77 %",
            review_original_title="Rucni original",
            review_original_publication="1988",
        )
        calls = []
        detail_html = """
        <script type="application/ld+json">
        {"@type": "Book", "datePublished": "2013-01-01", "publisher": [{"name": "Fantom Print"}], "genre": ["Fantasy"]}
        </script>
        <div class='ratValue'>89 <em>%</em></div>
        <h2>O knize</h2><p>Popis.</p>
        """

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: detail_html,
        )

        self.assertEqual(result.status, "updated")
        self.assertIn("pubdate:1999-00-00", calls[0])
        self.assertIn("publisher:Rucni vydavatel", calls[0])
        self.assertIn("tags:Rucni,Tag", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("<strong>77 %</strong>", comments_field)
        self.assertIn("Originalni nazev: Rucni original", comments_field)
        self.assertIn("Originalne vyslo: 1988", comments_field)

    def test_apply_match_row_reads_databaze_more_info_original_title(self):
        row = cme.MatchRow(1, "Pohyblive obrazky", "Terry Pratchett", "approve", "https://www.databazeknih.cz/prehled-knihy/pohyblive-obrazky-461", "", "exact-title-author", "exact-title-author")
        calls = []
        detail_html = """
        <script type="application/ld+json">
        {"@type": "Book", "datePublished": "1996-01-01", "publisher": [{"name": "Talpress"}]}
        </script>
        <span id='moreBookDetails' bookId='461'><a>Vice info...</a></span>
        <div class='ratValue'>87 <em>%</em></div>
        <h2>O knize</h2><p>Popis.</p>
        """
        more_info_html = """
        <div class='book-details__row'>
          <dt>Originální název</dt>
          <dd>Moving Pictures, 1990</dd>
        </div>
        """

        def fetcher(url: str) -> str:
            if url.endswith("/book-detail-more-info/461"):
                return more_info_html
            return detail_html

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=fetcher,
        )

        self.assertEqual(result.status, "updated")
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("Originalni nazev: Moving Pictures", comments_field)
        self.assertIn("Originalne vyslo: 1990", comments_field)

    def test_fetch_databaze_book_detail_metadata_returns_written_url_and_detail(self):
        detail_html = """
        <script type="application/ld+json">
        {"@type": "Book", "datePublished": "2016-01-01", "publisher": [{"name": "Argo"}], "genre": ["Fantasy"]}
        </script>
        <a href='/dalsi-vydani/current-2016'>Vydani</a>
        <div class='ratValue'>90 <em>%</em></div>
        <h2>O knize</h2><p>Popis.</p>
        """
        more_info_html = """
        <div class='book-details__row'><dt>Originální název</dt><dd>Original Book, 1990</dd></div>
        """
        editions_html = """
        <a class='bigger' href='/prehled-knihy/oldest-1999'>Kniha</a>
        <p class='new odtopm'>1999<span>,</span><a href='/nakladatelstvi/talpress-82'>Talpress</a></p>
        """

        def fetcher(url: str) -> str:
            if url.endswith("/book-detail-more-info/2016"):
                return more_info_html
            if url.endswith("/dalsi-vydani/current-2016"):
                return editions_html
            return detail_html

        written_url, detail = cme.fetch_databaze_book_detail_metadata(
            "https://www.databazeknih.cz/knihy/current-2016",
            fetcher,
        )

        self.assertEqual(written_url, "https://www.databazeknih.cz/prehled-knihy/oldest-1999")
        self.assertEqual(detail.published_year, "1999")
        self.assertEqual(detail.publisher, "Talpress")
        self.assertEqual(detail.rating_percent, "90 %")
        self.assertEqual(detail.original_title, "Original Book")
        self.assertEqual(detail.original_publication, "1990")

    def test_parse_book_detail_metadata_extracts_cover_url(self):
        detail = cme.parse_book_detail_metadata(
            """
            <script type="application/ld+json">
            {"@type": "Book", "image": "/img/books/123/big-cover.jpg"}
            </script>
            """
        )

        self.assertEqual(detail.cover_url, "https://www.databazeknih.cz/img/books/123/big-cover.jpg")

    def test_parse_databaze_cover_options_reads_json_and_meta_images(self):
        html = """
        <script type="application/ld+json">
        {"@type": "Book", "image": "https://img.databazeknih.cz/img/books/1/main.jpg"}
        </script>
        <meta property="og:image" content="https://img.databazeknih.cz/img/books/1/og.jpg">
        """

        options = cme.parse_databaze_cover_options(html)

        self.assertEqual(
            [option.url for option in options],
            [
                "https://img.databazeknih.cz/img/books/1/main.jpg",
                "https://img.databazeknih.cz/img/books/1/og.jpg",
            ],
        )

    def test_parse_legie_cover_options_reads_multiple_story_covers(self):
        html = """
        <div id="pro_obal">
          <img src="images/kniha-small/1/138-2213.jpg" class="obal_kniha" title="prebal 1" />
          <img src="images/kniha-small/3/394-4329.jpg" class="obal_kniha" title="prebal 2" />
        </div>
        """

        options = cme.parse_legie_cover_options(html)

        self.assertEqual(
            [option.url for option in options],
            [
                "https://www.legie.info/images/kniha-small/1/138-2213.jpg",
                "https://www.legie.info/images/kniha-small/3/394-4329.jpg",
            ],
        )

    def test_cover_candidate_rows_uses_only_books_without_cover_and_supported_url(self):
        rows = [
            cme.MatchRow(1, "Bez obalky", "Autor", "skip", "https://www.databazeknih.cz/knihy/a-1", "", "manual", "manual"),
            cme.MatchRow(2, "Ma obalku", "Autor", "skip", "https://www.databazeknih.cz/knihy/b-2", "", "manual", "manual"),
            cme.MatchRow(3, "Review", "Autor", "review", "https://www.databazeknih.cz/knihy/c-3", "", "manual", "manual"),
            cme.MatchRow(4, "Legie", "Autor", "skip", "https://www.legie.info/povidka/1", "", "manual", "manual", "legie", "povidka"),
        ]

        candidates = cme.cover_candidate_rows(
            rows,
            Path("library"),
            cover_flags_reader=lambda library, book_ids: {1: False, 2: True, 3: False, 4: False},
        )

        self.assertEqual(
            candidates,
            [
                cme.CoverCandidate(1, "Bez obalky", "https://www.databazeknih.cz/prehled-knihy/a-1"),
                cme.CoverCandidate(4, "Legie", "https://www.legie.info/povidka/1"),
            ],
        )

    def test_get_local_cover_path_returns_existing_cover_when_calibre_has_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            book_dir = library / "Autor" / "Kniha (1)"
            book_dir.mkdir(parents=True)
            cover = book_dir / "cover.jpg"
            cover.write_bytes(b"jpg")
            connection = sqlite3.connect(library / "metadata.db")
            connection.execute("create table books (id integer primary key, path text, has_cover bool)")
            connection.execute("insert into books(id, path, has_cover) values(1, ?, 1)", ("Autor/Kniha (1)",))
            connection.commit()
            connection.close()

            self.assertEqual(cme.get_local_cover_path(library, 1), cover)

    def test_get_current_book_metadata_reads_pubdate_publisher_tags_and_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            connection = sqlite3.connect(library / "metadata.db")
            try:
                connection.executescript(
                    """
                    create table books (id integer primary key, pubdate text);
                    create table comments (book integer primary key, text text);
                    create table publishers (id integer primary key, name text);
                    create table books_publishers_link (book integer, publisher integer);
                    create table tags (id integer primary key, name text);
                    create table books_tags_link (book integer, tag integer);
                    insert into books(id, pubdate) values(1, '1987-00-00 00:00:00+00:00');
                    insert into comments(book, text) values(1, '<p>Komentar</p>');
                    insert into publishers(id, name) values(1, 'Ikar');
                    insert into books_publishers_link(book, publisher) values(1, 1);
                    insert into tags(id, name) values(1, 'Fantasy'), (2, 'Humor');
                    insert into books_tags_link(book, tag) values(1, 1), (1, 2);
                    """
                )
                connection.commit()
            finally:
                connection.close()

            metadata = cme.get_current_book_metadata(library, 1)

        self.assertEqual(metadata.published_year, "1987")
        self.assertEqual(metadata.publisher, "Ikar")
        self.assertEqual(metadata.tags, ["Fantasy", "Humor"])
        self.assertEqual(metadata.comment, "<p>Komentar</p>")

    def test_audit_cover_rows_marks_multiple_cover_candidates_review(self):
        rows = [
            cme.MatchRow(1, "Povidka", "Autor", "skip", "https://www.legie.info/povidka/40", "", "manual", "manual", "legie", "povidka"),
        ]

        updated = cme.audit_cover_rows(
            rows,
            "library",
            cover_flags_reader=lambda library, ids: {1: False},
            fetcher=lambda url: """
                <div id="pro_obal">
                  <img src="images/kniha-small/1/a.jpg" class="obal_kniha" />
                  <img src="images/kniha-small/1/b.jpg" class="obal_kniha" />
                </div>
            """,
        )

        self.assertEqual(updated[0].status, "review")
        self.assertEqual(updated[0].cover_reason, "multiple-cover-candidates")
        self.assertEqual(updated[0].selected_cover_url, "")
        self.assertIn("https://www.legie.info/images/kniha-small/1/a.jpg", updated[0].cover_urls)

    def test_audit_cover_rows_selects_single_cover_without_approve(self):
        rows = [
            cme.MatchRow(1, "Kniha", "Autor", "skip", "https://www.databazeknih.cz/knihy/a-1", "", "manual", "manual"),
        ]

        updated = cme.audit_cover_rows(
            rows,
            "library",
            cover_flags_reader=lambda library, ids: {1: False},
            fetcher=lambda url: '<script type="application/ld+json">{"@type":"Book","image":"https://img.databazeknih.cz/img/books/a.jpg"}</script>',
        )

        self.assertEqual(updated[0].status, "skip")
        self.assertEqual(updated[0].cover_urls, "https://img.databazeknih.cz/img/books/a.jpg")
        self.assertEqual(updated[0].selected_cover_url, "https://img.databazeknih.cz/img/books/a.jpg")
        self.assertEqual(updated[0].cover_reason, "single-cover-candidate")

    def test_apply_cover_candidate_writes_cover_field(self):
        candidate = cme.CoverCandidate(1, "Kniha", "https://www.databazeknih.cz/prehled-knihy/a-1")
        calls = []

        result = cme.apply_cover_candidate(
            candidate,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: """
                <script type="application/ld+json">
                {"@type": "Book", "image": "https://img.databazeknih.cz/img/books/1/cover.jpg"}
                </script>
            """,
            binary_fetcher=lambda url: b"jpg",
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.chosen_url, "https://img.databazeknih.cz/img/books/1/cover.jpg")
        self.assertEqual(calls[0][0], r"C:\calibredb.exe")
        self.assertIn("--field", calls[0])
        cover_field = next(arg for arg in calls[0] if arg.startswith("cover:"))
        self.assertTrue(cover_field.endswith(".jpg"))

    def test_apply_cover_candidate_writes_legie_cover_field(self):
        candidate = cme.CoverCandidate(40, "Moře a malé rybky", "https://www.legie.info/povidka/40")
        calls = []

        result = cme.apply_cover_candidate(
            candidate,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: """
                <div id="pro_obal">
                  <img src="images/kniha-small/1/138-2213.jpg" class="obal_kniha" />
                </div>
            """,
            binary_fetcher=lambda url: b"jpg",
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.chosen_url, "https://www.legie.info/images/kniha-small/1/138-2213.jpg")
        self.assertIn("--field", calls[0])
        self.assertTrue(next(arg for arg in calls[0] if arg.startswith("cover:")).endswith(".jpg"))

    def test_apply_match_row_uses_oldest_available_edition_for_pubdate_publisher_and_link(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/current-2016", "", "exact-title-author", "exact-title-author")
        calls = []
        fetched_urls = []
        overview_html = """
        <script type="application/ld+json">
        {"@type": "Book", "datePublished": "2016-01-01", "publisher": [{"name": "Argo"}], "genre": ["Sci-fi"]}
        </script>
        <a href='/dalsi-vydani/current-2016'>Vydani <em>3</em></a>
        <div class='ratValue'>88 <em>%</em></div>
        <h2>O knize <em>Kniha</em></h2><p class='new2 odtop'>Popis.</p>
        """
        editions_html = """
        <a class='bigger' href='/prehled-knihy/current-2016'>Kniha</a>
        <p class='new odtopm'>2016<span>,</span><a href='/nakladatelstvi/argo-50'>Argo</a></p>
        <a class='bigger' href='/prehled-knihy/oldest-1971'>Kniha</a>
        <p class='new odtopm'>1971<span>,</span><a href='/nakladatelstvi/svoboda-5744'>Svoboda</a></p>
        """

        def fetcher(url):
            fetched_urls.append(url)
            if url == "https://www.databazeknih.cz/prehled-knihy/current-2016":
                return overview_html
            if url == "https://www.databazeknih.cz/book-detail-more-info/2016":
                return ""
            if url == "https://www.databazeknih.cz/dalsi-vydani/current-2016":
                return editions_html
            raise AssertionError(url)

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=fetcher,
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.chosen_url, "https://www.databazeknih.cz/prehled-knihy/oldest-1971")
        self.assertEqual(
            fetched_urls,
            [
                "https://www.databazeknih.cz/prehled-knihy/current-2016",
                "https://www.databazeknih.cz/book-detail-more-info/2016",
                "https://www.databazeknih.cz/dalsi-vydani/current-2016",
            ],
        )
        self.assertIn("pubdate:1971-00-00", calls[0])
        self.assertIn("publisher:Svoboda", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn('href="https://www.databazeknih.cz/prehled-knihy/oldest-1971"', comments_field)

    def test_apply_match_row_fails_when_editions_tab_has_no_parseable_edition(self):
        row = cme.MatchRow(1, "Kniha", "Autor", "approve", "https://www.databazeknih.cz/knihy/current-2016", "", "exact-title-author", "exact-title-author")
        calls = []
        overview_html = """
        <script type="application/ld+json">
        {"@type": "Book", "datePublished": "2016-01-01", "publisher": [{"name": "Argo"}]}
        </script>
        <a href='/dalsi-vydani/current-2016'>Vydani <em>3</em></a>
        """

        def fetcher(url):
            if url == "https://www.databazeknih.cz/prehled-knihy/current-2016":
                return overview_html
            if url == "https://www.databazeknih.cz/dalsi-vydani/current-2016":
                return "<p>Bez rozpoznatelneho vydani.</p>"
            raise AssertionError(url)

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=fetcher,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("editions-parse-error", result.error)
        self.assertEqual(calls, [])

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
                        return cme.ApplyResult(row.book_id, row.title, "updated", "https://www.databazeknih.cz/prehled-knihy/a-1", "")
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
        self.assertEqual(updated_rows[0].chosen_url, "https://www.databazeknih.cz/prehled-knihy/a-1")

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


class ImportCoverCommandTests(unittest.TestCase):
    def test_run_metadata_command_with_cover_accepts_cover_bytes(self):
        calls = []

        def runner(args):
            calls.append(args)
            cover_field = next(arg for arg in args if arg.startswith("cover:"))
            self.assertTrue(Path(cover_field.removeprefix("cover:")).exists())
            return cme.CommandResult(0, "ok", "")

        result = cme.run_metadata_command_with_cover(
            ["calibredb", "set_metadata", "1"],
            "",
            runner,
            cover_bytes=b"image-bytes",
            cover_suffix=".jpg",
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(any(arg.startswith("cover:") for arg in calls[0]))

    def test_run_metadata_command_with_cover_prefers_cover_bytes_over_url_fetcher(self):
        calls = []
        fetch_calls = []

        def runner(args):
            calls.append(args)
            cover_field = next(arg for arg in args if arg.startswith("cover:"))
            cover_path = Path(cover_field.removeprefix("cover:"))
            self.assertEqual(cover_path.read_bytes(), b"local-image-bytes")
            return cme.CommandResult(0, "ok", "")

        def cover_fetcher(url):
            fetch_calls.append(url)
            return b"remote-image-bytes"

        result = cme.run_metadata_command_with_cover(
            ["calibredb", "set_metadata", "1"],
            "https://example.test/cover.png",
            runner,
            cover_fetcher=cover_fetcher,
            cover_bytes=b"local-image-bytes",
            cover_suffix=".exe",
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(fetch_calls, [])
        self.assertTrue(any(arg.startswith("cover:") for arg in calls[0]))
        cover_field = next(arg for arg in calls[0] if arg.startswith("cover:"))
        self.assertTrue(cover_field.endswith("cover.jpg"))


if __name__ == "__main__":
    unittest.main()
