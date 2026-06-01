# Legie Story Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe Legie audit support so likely povidky are found, shown as `review`, and only written to Calibre after manual approval.

**Architecture:** Keep Databaze knih as the main source. Add Legie as a separate source with its own URL helpers, parsers, matching, audit command, and apply path. Preserve existing safety: no direct SQLite writes for metadata, backup before writes, conservative `review` status for Legie candidates.

**Tech Stack:** Python standard library, `unittest`, `HTMLParser`, `csv`, `sqlite3` read-only, `calibredb`, Tkinter app.

---

## File Structure

- Version discipline for implementation commits:
  - This planning commit is `0.0.17`.
  - Task 1 commit bumps app version to `0.0.18`.
  - Task 2 commit bumps app version to `0.0.19`.
  - Task 3 commit bumps app version to `0.0.20`.
  - Task 4 commit bumps app version to `0.0.21`.
  - Task 5 commit bumps app version to `0.0.22`.
  - Task 6 commit bumps app version to `0.0.23`.
  - Task 7 commit bumps app version to `0.0.24`.
  - Every commit updates `calibre_meta_app.py`, `tests/test_calibre_meta_app.py`, and `POSTUP.md` with the same version.
- Modify `calibre_meta_edit.py`
  - Add `source` and `work_type` to `MatchRow`.
  - Add Legie URL helpers, search parser, story detail parser.
  - Add Legie audit flow over existing `matches.csv`.
  - Split apply into Databaze knih and Legie paths.
  - Add read-only helpers for current identifiers and tags.
- Modify `calibre_meta_app.py`
  - Add `source` and `work_type` columns to the table.
  - Add `Audit Legie` button and background action.
  - Bump `APP_VERSION`.
- Modify `tests/test_calibre_meta_edit.py`
  - Add CSV compatibility tests.
  - Add Legie parser, matching, audit, and apply tests.
- Modify `tests/test_calibre_meta_app.py`
  - Add table column and action tests.
  - Bump version test.
- Add `tests/fixtures/legie_story_7347.html`
  - Fixture from `https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace`.
- Modify `POSTUP.md` and `PLAN.md`
  - Document Legie audit usage and version.

---

### Task 1: CSV Schema With Source And Work Type

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Write failing tests for old and new CSV rows**

Add tests under `CsvAndFilesystemTests`:

```python
def test_read_matches_csv_defaults_source_and_work_type_for_old_csv(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "matches.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "book_id", "title", "authors", "status", "chosen_url",
                "candidate_urls", "confidence", "reason",
            ])
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.CsvAndFilesystemTests.test_read_matches_csv_defaults_source_and_work_type_for_old_csv tests.test_calibre_meta_edit.CsvAndFilesystemTests.test_write_matches_csv_writes_source_and_work_type_columns -v
```

Expected: fail because `MatchRow` has no `source` / `work_type`.

- [ ] **Step 3: Extend `MatchRow` and CSV fields**

In `calibre_meta_edit.py`, update fields:

```python
MATCHES_FIELDS = [
    "book_id",
    "title",
    "authors",
    "status",
    "chosen_url",
    "candidate_urls",
    "confidence",
    "reason",
    "source",
    "work_type",
]
```

Update dataclass:

```python
@dataclass(frozen=True)
class MatchRow:
    book_id: int
    title: str
    authors: str
    status: str
    chosen_url: str
    candidate_urls: str
    confidence: str
    reason: str
    source: str = "databazeknih"
    work_type: str = ""
```

Update `read_matches_csv()` constructor:

```python
MatchRow(
    int(raw["book_id"]),
    raw["title"],
    raw["authors"],
    raw["status"],
    raw["chosen_url"],
    raw["candidate_urls"],
    raw["confidence"],
    raw["reason"],
    raw.get("source") or "databazeknih",
    raw.get("work_type") or "",
)
```

- [ ] **Step 4: Update existing `MatchRow(...)` call sites**

Search:

```powershell
rg -n "MatchRow\\(" calibre_meta_edit.py tests
```

Leave existing 8-argument calls valid because defaults cover them. Only update tests where source/work_type behavior is explicit.

- [ ] **Step 5: Run all CSV tests**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.CsvAndFilesystemTests -v
```

Expected: OK.

- [ ] **Step 6: Bump version and commit**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.18`.

```powershell
git add calibre_meta_edit.py calibre_meta_app.py tests\test_calibre_meta_edit.py tests\test_calibre_meta_app.py POSTUP.md
git commit -m "Add match row source fields"
```

---

### Task 2: Legie URL Helpers And Story Parser

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`
- Create: `tests/fixtures/legie_story_7347.html`

- [ ] **Step 1: Add fixture**

Create `tests/fixtures/legie_story_7347.html` with a compact copy of the relevant Legie HTML:

```html
<div id="hodnoceni" itemprop="aggregateRating">
  <div>hodnotilo: <span itemprop="ratingCount">11</span></div>
  <div id="procenta"><span itemprop="ratingValue">80</span>%<span itemprop="bestRating">100</span></div>
</div>
<h3><a href="autor/189-orson-scott-card">Orson Scott Card</a></h3>
<h2 id="nazev_povidky">A opice si myslely, že to všechno je z legrace</h2>
<p>Kategorie: sci-fi</p>
<p id="jine_nazvy">originální název: The Monkeys Thought 'Twas All in Fun<br />
originál vyšel: 05/1979</p>
<div id="zarazena_do_knih">Nachází se v těchto knihách:<br />
  <a href="kniha/4315-ikarie-1995-05">Ikarie 1995/05</a>
</div>
<div id="anotace">Informace / Anotace k povídce: <strong>A opice si myslely, že to všechno je z legrace</strong>
<hr>
<p><strong>Poprvé uveřejněna v magazínu:</strong><br>
<em>Analog Science Fiction/Science Fact</em></p>
<hr>
<p><strong>Překlad:</strong><br>
● Petr Kotrle<br>
<em>(Ikarie 1995/05)</em></p>
<hr>
</div>
```

- [ ] **Step 2: Write failing parser test**

Add under `ParserAndMatchingTests`:

```python
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
```

- [ ] **Step 3: Run test and verify it fails**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.ParserAndMatchingTests.test_parse_legie_story_detail_reads_story_metadata -v
```

Expected: fail because `parse_legie_story_detail` is missing.

- [ ] **Step 4: Add Legie dataclass and helpers**

In `calibre_meta_edit.py`, near constants:

```python
LEGIE_BASE_URL = "https://www.legie.info"
LEGIE_SEARCH_URL = LEGIE_BASE_URL + "/vyhledavani?text="
```

Near metadata dataclasses:

```python
@dataclass(frozen=True)
class LegieStoryMetadata:
    legie_id: str = ""
    title: str = ""
    author: str = ""
    category: str = ""
    rating_percent: str = ""
    rating_count: str = ""
    original_title: str = ""
    original_publication: str = ""
    czech_publication: str = ""
    about_text: str = ""
```

Add URL helpers:

```python
def legie_absolute_url(url: str) -> str:
    clean = url.strip().split("#", 1)[0].split("?", 1)[0]
    if clean.startswith("/"):
        clean = LEGIE_BASE_URL + clean
    if clean.startswith("povidka/") or clean.startswith("kniha/") or clean.startswith("autor/"):
        clean = LEGIE_BASE_URL + "/" + clean
    return clean.replace("http://www.legie.info/", "https://www.legie.info/", 1)


def legie_id_from_url(url: str) -> str:
    match = re.search(r"/povidka/(\d+)", legie_absolute_url(url))
    return match.group(1) if match else ""
```

- [ ] **Step 5: Add `LegieStoryParser`**

Add an `HTMLParser` class focused on IDs from the fixture:

```python
class LegieStoryParser(HTMLParser):
    """Parser detailu povidky na Legii."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.author = ""
        self.category = ""
        self.rating_percent = ""
        self.rating_count = ""
        self.original_title = ""
        self.original_publication = ""
        self.czech_publication = ""
        self.about_text = ""

        self._capture = ""
        self._parts: list[str] = []
        self._author_next = False
        self._inside_rating_value = False
        self._inside_rating_count = False
        self._inside_publications = False
        self._inside_about = False
        self._about_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        element_id = attrs_dict.get("id", "")
        itemprop = attrs_dict.get("itemprop", "")

        if tag == "h3":
            self._author_next = True
        if tag == "h2" and element_id == "nazev_povidky":
            self._capture = "title"
            self._parts = []
        if tag == "p" and element_id == "jine_nazvy":
            self._capture = "other_names"
            self._parts = []
        if tag == "div" and element_id == "zarazena_do_knih":
            self._inside_publications = True
        if tag == "div" and element_id == "anotace":
            self._inside_about = True
            self._about_depth = 1
            self._parts = []
        elif self._inside_about:
            self._about_depth += 1
        if itemprop == "ratingValue":
            self._inside_rating_value = True
        if itemprop == "ratingCount":
            self._inside_rating_count = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._capture == "title" and tag == "h2":
            self.title = _clean_text(" ".join(self._parts))
            self._capture = ""
        if self._capture == "other_names" and tag == "p":
            text = _clean_text(" ".join(self._parts))
            original = re.search(r"originální název:\s*(.*?)\s*originál vyšel:", text)
            published = re.search(r"originál vyšel:\s*(.*)$", text)
            self.original_title = original.group(1).strip() if original else ""
            self.original_publication = published.group(1).strip() if published else ""
            self._capture = ""
        if self._inside_publications and tag == "div":
            self._inside_publications = False
        if self._inside_about:
            self._about_depth -= 1
            if self._about_depth == 0:
                self.about_text = _clean_text(" ".join(self._parts))
                self._inside_about = False
        if self._inside_rating_value and tag == "span":
            self._inside_rating_value = False
        if self._inside_rating_count and tag == "span":
            self._inside_rating_count = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._author_next:
            self.author = text
            self._author_next = False
        if text.startswith("Kategorie:"):
            self.category = _clean_text(text.replace("Kategorie:", "", 1))
        if self._capture:
            self._parts.append(text)
        if self._inside_rating_value:
            self.rating_percent = _clean_text(text) + " %"
        if self._inside_rating_count:
            self.rating_count = _clean_text(text)
        if self._inside_publications and text != "Nachází se v těchto knihách:":
            self.czech_publication = text
        if self._inside_about:
            self._parts.append(text)
```

Add parse function:

```python
def parse_legie_story_detail(html_text: str, url: str) -> LegieStoryMetadata:
    parser = LegieStoryParser()
    parser.feed(html_text)
    parser.close()
    return LegieStoryMetadata(
        legie_id=legie_id_from_url(url),
        title=parser.title,
        author=parser.author,
        category=parser.category,
        rating_percent=parser.rating_percent,
        rating_count=parser.rating_count,
        original_title=parser.original_title,
        original_publication=parser.original_publication,
        czech_publication=parser.czech_publication,
        about_text=parser.about_text,
    )
```

- [ ] **Step 6: Run parser test**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.ParserAndMatchingTests.test_parse_legie_story_detail_reads_story_metadata -v
```

Expected: OK.

- [ ] **Step 7: Bump version and commit**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.19`.

```powershell
git add calibre_meta_edit.py calibre_meta_app.py tests\test_calibre_meta_edit.py tests\test_calibre_meta_app.py tests\fixtures\legie_story_7347.html POSTUP.md
git commit -m "Parse Legie story detail"
```

---

### Task 3: Legie Search And Conservative Matching

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`
- Create: `tests/fixtures/legie_search_story.html`

- [ ] **Step 1: Add search fixture**

Create `tests/fixtures/legie_search_story.html`:

```html
<div class="vysledky">
  <a href="povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace">A opice si myslely, že to všechno je z legrace</a>
  <span>Orson Scott Card</span>
</div>
```

- [ ] **Step 2: Write failing search and match tests**

Add under `ParserAndMatchingTests`:

```python
def test_parse_legie_search_results_reads_story_candidates(self):
    fixture = Path(__file__).parent / "fixtures" / "legie_search_story.html"

    candidates = cme.parse_legie_search_results(fixture.read_text(encoding="utf-8"))

    self.assertEqual(candidates[0].title, "A opice si myslely, že to všechno je z legrace")
    self.assertEqual(candidates[0].url, "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace")
    self.assertIn("Orson Scott Card", candidates[0].text)

def test_match_legie_story_candidate_returns_review_never_approve(self):
    book = cme.Book(429, "A opice si myslely, že je to všechno jen legrace", ["Orson Scott Card"], "")
    candidates = [
        cme.Candidate(
            "A opice si myslely, že to všechno je z legrace",
            "Orson Scott Card",
            "https://www.legie.info/povidka/7347-a-opice-si-myslely-ze-to-vsechno-je-z-legrace",
        )
    ]

    row = cme.match_legie_story(book, candidates)

    self.assertEqual(row.status, "review")
    self.assertEqual(row.source, "legie")
    self.assertEqual(row.work_type, "povidka")
    self.assertEqual(row.reason, "legie-story-candidate")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.ParserAndMatchingTests.test_parse_legie_search_results_reads_story_candidates tests.test_calibre_meta_edit.ParserAndMatchingTests.test_match_legie_story_candidate_returns_review_never_approve -v
```

Expected: fail because functions are missing.

- [ ] **Step 4: Implement Legie search parser**

Add:

```python
def build_legie_search_url(title: str, authors: Sequence[str]) -> str:
    query = title + " " + " ".join(authors)
    return LEGIE_SEARCH_URL + urllib.parse.quote_plus(query.strip())
```

Add simple parser:

```python
class LegieSearchParser(HTMLParser):
    """Parser vysledku hledani na Legii pro odkazy na povidky."""

    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[Candidate] = []
        self._current: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        href = attrs_dict.get("href", "")
        if tag.lower() == "a" and "povidka/" in href:
            self._finish_current()
            self._current = {"url": legie_absolute_url(href), "parts": []}

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = data.strip()
        if text:
            parts = self._current["parts"]
            assert isinstance(parts, list)
            parts.append(text)

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        parts = [str(part) for part in self._current.get("parts", [])]
        title = parts[0] if parts else ""
        text = " ".join(parts)
        url = str(self._current.get("url") or "")
        if title and url:
            self.candidates.append(Candidate(title, text, url))
        self._current = None


def parse_legie_search_results(html_text: str) -> list[Candidate]:
    parser = LegieSearchParser()
    parser.feed(html_text)
    parser.close()
    return parser.candidates
```

- [ ] **Step 5: Implement conservative Legie matching**

Add:

```python
def _titles_close(left: str, right: str) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    return left_norm == right_norm or left_norm in right_norm or right_norm in left_norm


def match_legie_story(book: Book, candidates: Sequence[Candidate]) -> MatchRow | None:
    authors_text = " & ".join(book.authors)
    for candidate in candidates:
        if not _titles_close(book.title, candidate.title):
            continue
        if not any(normalize_text(author) in normalize_text(candidate.text) for author in book.authors):
            continue
        return MatchRow(
            book.id,
            book.title,
            authors_text,
            "review",
            candidate.url,
            _candidate_urls(candidates),
            "exact-title-author",
            "legie-story-candidate",
            "legie",
            "povidka",
        )
    return None
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.ParserAndMatchingTests.test_parse_legie_search_results_reads_story_candidates tests.test_calibre_meta_edit.ParserAndMatchingTests.test_match_legie_story_candidate_returns_review_never_approve -v
```

Expected: OK.

- [ ] **Step 7: Bump version and commit**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.20`.

```powershell
git add calibre_meta_edit.py calibre_meta_app.py tests\test_calibre_meta_edit.py tests\test_calibre_meta_app.py tests\fixtures\legie_search_story.html POSTUP.md
git commit -m "Add Legie story matching"
```

---

### Task 4: Preview And Audit Legie Candidates

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Write failing tests for preview fallback and audit**

Add under `ParserAndMatchingTests`:

```python
def test_preview_books_uses_legie_for_uncertain_databaze_match(self):
    db_html = "<a href='/prehled-knihy/plast-z-opici-kuze-265268'>Plast z opici kuze</a>"
    legie_html = (Path(__file__).parent / "fixtures" / "legie_search_story.html").read_text(encoding="utf-8")
    calls = []

    def fetcher(url):
        calls.append(url)
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

    updated = cme.audit_legie_rows([row], fetcher=lambda url: legie_html, sleeper=lambda seconds: None, sleep_seconds=0)

    self.assertEqual(updated[0].status, "review")
    self.assertEqual(updated[0].source, "legie")
    self.assertEqual(updated[0].work_type, "povidka")
```

- [ ] **Step 2: Run tests and verify fail**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.ParserAndMatchingTests.test_preview_books_uses_legie_for_uncertain_databaze_match tests.test_calibre_meta_edit.ParserAndMatchingTests.test_audit_legie_rows_turns_suspicious_skip_into_review -v
```

Expected: fail.

- [ ] **Step 3: Add Legie fallback decision helpers**

Add:

```python
LEGIE_FALLBACK_REASONS = {"no-candidates", "title-only", "multiple-title-matches", "partial-title", "http-error"}


def should_try_legie(row: MatchRow) -> bool:
    if row.source == "legie":
        return False
    if row.status == "approve" and row.reason == "exact-title-author":
        return False
    return row.reason in LEGIE_FALLBACK_REASONS
```

- [ ] **Step 4: Update `preview_books` to use Legie fallback**

Change signature:

```python
def preview_books(
    books: Sequence[Book],
    fetcher: Callable[[str], str] = fetch_text,
    robots_checker: Callable[[], bool] = robots_allows_search,
    sleeper: Callable[[float], None] = time.sleep,
    sleep_seconds: float = 1.0,
) -> list[MatchRow]:
```

Inside loop after Databaze match:

```python
html = fetcher(build_search_url(book.title, book.authors))
row = match_book(book, parse_search_results(html))
if should_try_legie(row):
    sleeper(sleep_seconds)
    legie_html = fetcher(build_legie_search_url(book.title, book.authors))
    legie_row = match_legie_story(book, parse_legie_search_results(legie_html))
    if legie_row is not None:
        row = legie_row
rows.append(row)
```

For fetch errors, create the existing `http-error` row, then try Legie with a guarded `try`.

- [ ] **Step 5: Add audit helper and CLI command**

Add:

```python
def audit_legie_rows(
    rows: Sequence[MatchRow],
    fetcher: Callable[[str], str] = fetch_text,
    sleeper: Callable[[float], None] = time.sleep,
    sleep_seconds: float = 1.0,
) -> list[MatchRow]:
    updated: list[MatchRow] = []
    for row in rows:
        if row.source == "legie" or row.status == "approve":
            updated.append(row)
            continue
        book = Book(row.book_id, row.title, [part.strip() for part in row.authors.split("&") if part.strip()], "")
        sleeper(sleep_seconds)
        try:
            legie_html = fetcher(build_legie_search_url(book.title, book.authors))
            legie_row = match_legie_story(book, parse_legie_search_results(legie_html))
        except Exception:
            legie_row = None
        updated.append(legie_row if legie_row is not None else row)
    return updated
```

Add `run_legie_audit(args)`:

```python
def run_legie_audit(args: argparse.Namespace) -> int:
    rows = read_matches_csv(MATCHES_PATH)
    selected_rows = select_match_rows(rows, book_id=args.book_id, limit=args.limit)
    selected_ids = {row.book_id for row in selected_rows}
    audited = audit_legie_rows(selected_rows, sleep_seconds=args.sleep)
    replacements = {row.book_id: row for row in audited}
    merged = [replacements.get(row.book_id, row) if row.book_id in selected_ids else row for row in rows]
    backup_path = backup_matches_csv(MATCHES_PATH, Path("backups") / "matches")
    if backup_path:
        print(f"Zaloha matches.csv: {backup_path}")
    write_matches_csv(MATCHES_PATH, merged, overwrite=True)
    changed = sum(1 for old, new in zip(rows, merged) if old != new)
    print(f"Legie audit: zmeneno {changed} radku")
    return 0
```

Register CLI:

```python
legie_audit = subparsers.add_parser("legie-audit", help="Najde mozne povidky na Legii a da je do review.")
legie_audit.add_argument("--library", default=DEFAULT_LIBRARY)
legie_audit.add_argument("--limit", type=int)
legie_audit.add_argument("--book-id", type=int)
legie_audit.add_argument("--sleep", type=float, default=1.0)
legie_audit.set_defaults(func=run_legie_audit)
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.ParserAndMatchingTests.test_preview_books_uses_legie_for_uncertain_databaze_match tests.test_calibre_meta_edit.ParserAndMatchingTests.test_audit_legie_rows_turns_suspicious_skip_into_review -v
```

Expected: OK.

- [ ] **Step 7: Bump version and commit**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.21`.

```powershell
git add calibre_meta_edit.py calibre_meta_app.py tests\test_calibre_meta_edit.py tests\test_calibre_meta_app.py POSTUP.md
git commit -m "Audit Legie story candidates"
```

---

### Task 5: Apply Approved Legie Story Rows

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Write failing apply test**

Add under `CalibreDbAndApplyTests`:

```python
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
    self.assertIn("tags:Sci-fi,sci-fi,povidka", calls[0])
    self.assertFalse(any(arg.startswith("pubdate:") for arg in calls[0]))
    self.assertFalse(any(arg.startswith("publisher:") for arg in calls[0]))
    comments_field = next(arg for arg in calls[0] if arg.startswith("comments:"))
    self.assertIn("https://www.legie.info/povidka/7347", comments_field)
    self.assertIn("<strong>80 %</strong>", comments_field)
    self.assertIn("Ikarie 1995/05", comments_field)
```

- [ ] **Step 2: Run test and verify fail**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.CalibreDbAndApplyTests.test_apply_match_row_writes_legie_story_comment_tags_and_identifier -v
```

Expected: fail because Legie URLs are invalid and `apply_match_row` has no readers.

- [ ] **Step 3: Add Legie URL validation and readers**

Update URL validation:

```python
def is_valid_legie_story_url(url: str) -> bool:
    return legie_absolute_url(url).startswith(LEGIE_BASE_URL + "/povidka/")
```

Add read-only helpers:

```python
def get_current_identifiers(library: str | Path, book_id: int) -> dict[str, str]:
    connection = open_calibre_db_readonly(library)
    try:
        rows = connection.execute("select type, val from identifiers where book = ?", (book_id,)).fetchall()
    finally:
        connection.close()
    return {row["type"]: row["val"] for row in rows}


def get_current_tags(library: str | Path, book_id: int) -> list[str]:
    connection = open_calibre_db_readonly(library)
    try:
        rows = connection.execute(
            """
            select t.name
            from tags t
            join books_tags_link btl on btl.tag = t.id
            where btl.book = ?
            order by t.name
            """,
            (book_id,),
        ).fetchall()
    finally:
        connection.close()
    return [row["name"] for row in rows]
```

- [ ] **Step 4: Add Legie comment/field formatting**

Add:

```python
def format_legie_comment(url: str, detail: LegieStoryMetadata) -> str:
    safe_url = html.escape(url, quote=True)
    parts = [
        "<div>",
        f'<p><a href="{safe_url}" target="_blank"><span style="color: #6cb4ee">{safe_url}</span></a></p>',
    ]
    if detail.rating_percent:
        rating = html.escape(detail.rating_percent)
        if detail.rating_count:
            rating += f" ({html.escape(detail.rating_count)} hodnoceni)"
        parts.append(f"<p><strong>{rating}</strong></p>")
    facts = []
    if detail.original_title:
        facts.append(f"Originalni nazev: {detail.original_title}")
    if detail.original_publication:
        facts.append(f"Originalne vyslo: {detail.original_publication}")
    if detail.czech_publication:
        facts.append(f"Cesky vyslo: {detail.czech_publication}")
    if facts:
        parts.append("<p>" + "<br />".join(html.escape(item) for item in facts) + "</p>")
    if detail.about_text:
        parts.append(f"<p>{html.escape(detail.about_text)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def identifiers_field_value(identifiers: dict[str, str]) -> str:
    return ",".join(f"{key}:{value}" for key, value in identifiers.items() if key and value)
```

- [ ] **Step 5: Split apply by source**

Change `apply_match_row` signature:

```python
def apply_match_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
    fetcher: Callable[[str], str] | None = None,
    identifiers_reader: Callable[[str | Path, int], dict[str, str]] = get_current_identifiers,
    tags_reader: Callable[[str | Path, int], list[str]] = get_current_tags,
) -> ApplyResult:
```

Early dispatch:

```python
if row.source == "legie":
    return apply_legie_story_row(row, library, calibredb_path, runner, fetcher or fetch_text, identifiers_reader, tags_reader)
```

Add:

```python
def apply_legie_story_row(
    row: MatchRow,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult],
    fetcher: Callable[[str], str],
    identifiers_reader: Callable[[str | Path, int], dict[str, str]],
    tags_reader: Callable[[str | Path, int], list[str]],
) -> ApplyResult:
    if row.status != "approve":
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "")
    if not is_valid_legie_story_url(row.chosen_url):
        return ApplyResult(row.book_id, row.title, "skipped", row.chosen_url, "invalid-url")
    try:
        detail = parse_legie_story_detail(fetcher(row.chosen_url), row.chosen_url)
    except Exception as exc:
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, f"legie-detail-fetch-error: {exc}")

    identifiers = identifiers_reader(library, row.book_id)
    identifiers["legie"] = detail.legie_id
    tags = _dedupe_tags(tags_reader(library, row.book_id) + [detail.category, "povidka"])
    args = [
        calibredb_path,
        "set_metadata",
        str(row.book_id),
        "--with-library",
        str(library),
        "--field",
        "comments:" + format_legie_comment(row.chosen_url, detail),
        "--field",
        "tags:" + ",".join(tags),
        "--field",
        "identifiers:" + identifiers_field_value(identifiers),
    ]
    result = runner(args)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "calibredb failed").strip()
        return ApplyResult(row.book_id, row.title, "failed", row.chosen_url, error)
    return ApplyResult(row.book_id, row.title, "updated", row.chosen_url, "")
```

- [ ] **Step 6: Run apply test**

Run:

```powershell
python -m unittest tests.test_calibre_meta_edit.CalibreDbAndApplyTests.test_apply_match_row_writes_legie_story_comment_tags_and_identifier -v
```

Expected: OK.

- [ ] **Step 7: Bump version and commit**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.22`.

```powershell
git add calibre_meta_edit.py calibre_meta_app.py tests\test_calibre_meta_edit.py tests\test_calibre_meta_app.py POSTUP.md
git commit -m "Apply approved Legie story rows"
```

---

### Task 6: App Columns And Audit Button

**Files:**
- Modify: `calibre_meta_app.py`
- Modify: `tests/test_calibre_meta_app.py`

- [ ] **Step 1: Write failing app model tests**

Add under `AppModelTests`:

```python
def test_table_columns_include_source_and_work_type(self):
    self.assertIn("source", app.TABLE_COLUMNS)
    self.assertIn("work_type", app.TABLE_COLUMNS)

def test_primary_toolbar_order_includes_legie_audit(self):
    self.assertEqual(
        app.primary_toolbar_order(),
        ("Nacist CSV", "Nacist nove knihy", "Audit Legie", "Ulozit CSV"),
    )

def test_make_legie_audit_action_runs_backend(self):
    args = app.make_script_args("D:\\Knihy")
    calls = []

    action = app.make_legie_audit_action(
        args=args,
        audit_runner=lambda received_args: calls.append(received_args) or 0,
    )

    result = action()

    self.assertEqual(result, 0)
    self.assertEqual(calls, [args])
```

Update version test to `0.0.23` for this implementation commit.

- [ ] **Step 2: Run tests and verify fail**

Run:

```powershell
python -m unittest tests.test_calibre_meta_app.AppModelTests.test_table_columns_include_source_and_work_type tests.test_calibre_meta_app.AppModelTests.test_primary_toolbar_order_includes_legie_audit tests.test_calibre_meta_app.AppModelTests.test_make_legie_audit_action_runs_backend -v
```

Expected: fail.

- [ ] **Step 3: Update table columns and toolbar labels**

Change:

```python
TABLE_COLUMNS = ("book_id", "title", "authors", "status", "source", "work_type", "chosen_url", "reason")
PRIMARY_TOOLBAR_LABELS = ("Nacist CSV", "Nacist nove knihy", "Audit Legie", "Ulozit CSV")
```

Add widths/headings in `_build_ui()`:

```python
"source": 90,
"work_type": 90,
```

```python
"source": "Zdroj",
"work_type": "Typ",
```

Update toolbar construction so `Audit Legie` calls `self.run_legie_audit`.

- [ ] **Step 4: Add action factory and UI method**

Add:

```python
def make_legie_audit_action(
    args: SimpleNamespace,
    audit_runner: Callable[[SimpleNamespace], int] = cme.run_legie_audit,
) -> Callable[[], int]:
    """Pripravi audit Legie nad matches.csv."""
    return lambda: audit_runner(args)
```

Add method on `CalibreMetaApp`:

```python
def run_legie_audit(self) -> None:
    if not self.save_csv(show_message=False):
        return
    args = make_script_args(self.library_path())
    action = make_legie_audit_action(args)
    self._run_background("Audit Legie", action, reload_after=True)
```

- [ ] **Step 5: Run app tests**

Run:

```powershell
python -m unittest tests.test_calibre_meta_app -v
```

Expected: OK.

- [ ] **Step 6: Bump version and commit**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.23`.

```powershell
git add calibre_meta_app.py tests\test_calibre_meta_app.py POSTUP.md
git commit -m "Add Legie audit UI"
```

---

### Task 7: Documentation And Final Verification

**Files:**
- Modify: `POSTUP.md`
- Modify: `PLAN.md`
- Modify: `calibre_meta_app.py`
- Modify: `tests/test_calibre_meta_app.py`

- [ ] **Step 1: Update version**

Bump `APP_VERSION`, app version test, and `POSTUP.md` to `0.0.24`.

- [ ] **Step 2: Update docs**

In `POSTUP.md`, add:

```markdown
`Audit Legie` udela:

1. ulozi aktualni `matches.csv`
2. zalohuje `matches.csv` do `backups\matches\`
3. projde existujici radky a hleda mozne povidky na Legii
4. nalezene povidky nastavi na `review`, zdroj `legie`, typ `povidka`
5. nic nezapisuje do Calibre

Legie radky zapisuj az po rucnim prepnuti na `approve`.
```

In `PLAN.md`, add update section:

```markdown
## Update 0.0.24 - audit povidek pres Legii

- Pridan konzervativni Legie audit.
- Legie kandidati jsou vzdy `review`.
- Zapis Legie radku uklada komentar, tag `povidka` a identifikator `legie:ID`.
```

- [ ] **Step 3: Run full tests**

Run:

```powershell
python -m unittest discover -s tests -v
python -m py_compile calibre_meta_edit.py calibre_meta_app.py CalibreMetaEdit.pyw tests\test_calibre_meta_edit.py tests\test_calibre_meta_app.py
git diff --check
```

Expected:

- all tests OK
- py_compile no output
- diff check no errors

- [ ] **Step 4: Manual dry run for one row**

Use a local dry run with injected runner, not a real Calibre write:

```powershell
$env:PYTHONIOENCODING='utf-8'
@'
from pathlib import Path
import calibre_meta_edit as cme
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
calls = []
fixture = Path("tests/fixtures/legie_story_7347.html").read_text(encoding="utf-8")
result = cme.apply_match_row(
    row,
    Path("library"),
    r"C:\calibredb.exe",
    runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
    fetcher=lambda url: fixture,
    identifiers_reader=lambda library, book_id: {},
    tags_reader=lambda library, book_id: [],
)
print(result)
print([arg for arg in calls[0] if arg.startswith("identifiers:") or arg.startswith("tags:")])
'@ | python -
```

Expected output includes:

```text
ApplyResult(... status='updated' ...)
identifiers:legie:7347
tags:sci-fi,povidka
```

- [ ] **Step 5: Commit and push**

```powershell
git status --short
git add POSTUP.md PLAN.md calibre_meta_app.py tests\test_calibre_meta_app.py
git commit -m "Document Legie audit workflow"
git push origin main
```

---

## Self-Review Checklist

- Spec coverage:
  - Legie as second source: Tasks 3 and 4.
  - Always `review`: Tasks 3 and 4.
  - No automatic Databaze overwrite: Task 4 updates `matches.csv` only and leaves Calibre untouched.
  - CSV source/type: Task 1.
  - Legie metadata parser: Task 2.
  - Apply Legie approved rows: Task 5.
  - App visibility and action: Task 6.
  - Docs and verification: Task 7.
- No open markers:
  - No unresolved marker strings or undefined implementation step remains.
- Type consistency:
  - `MatchRow.source` / `MatchRow.work_type` are defined in Task 1 and used later.
  - `LegieStoryMetadata` is defined in Task 2 and used in Task 5.
  - `run_legie_audit` is defined in Task 4 and used by app in Task 6.
