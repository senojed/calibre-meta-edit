# Testy hlidaji chovani skriptu pro nahled, parovani a bezpecny zapis Calibre komentaru.

import contextlib
import csv
import io
import inspect
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

    def test_build_legie_search_url_uses_quote_plus_for_title_and_authors(self):
        url = cme.build_legie_search_url("A opice si myslely", ["Orson Scott Card"])
        self.assertEqual(
            url,
            "https://www.legie.info/index.php?search_text=A+opice+si+myslely+Orson+Scott+Card",
        )

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

    def test_is_writable_match_row_accepts_approved_empty_url_for_comment_clear(self):
        row = cme.MatchRow(177, "Change Your Diet", "Georgia Ede", "approve", "", "", "manual", "manual")

        self.assertTrue(cme.is_writable_match_row(row))

    def test_apply_match_row_clears_comment_for_approved_empty_url(self):
        row = cme.MatchRow(177, "Change Your Diet", "Georgia Ede", "approve", "", "", "manual", "manual")
        calls = []

        result = cme.apply_match_row(
            row,
            Path("library"),
            r"C:\calibredb.exe",
            runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
            fetcher=lambda url: self.fail("empty URL clear should not fetch detail"),
        )

        self.assertEqual(result.status, "updated")
        self.assertEqual(result.chosen_url, "")
        self.assertIn("comments:", calls[0])

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
        self.assertEqual(fetched_urls, ["https://www.databazeknih.cz/prehled-knihy/new-2"])
        self.assertEqual(calls[0][0], r"C:\calibredb.exe")
        self.assertIn("--field", calls[0])
        self.assertIn("pubdate:2013-00-00", calls[0])
        self.assertIn("publisher:Fantom Print", calls[0])
        self.assertIn("tags:Fantasy,draci", calls[0])
        comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
        self.assertIn("<strong>89 %</strong>", comments_field)
        self.assertIn("Novy popis.", comments_field)

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


if __name__ == "__main__":
    unittest.main()
