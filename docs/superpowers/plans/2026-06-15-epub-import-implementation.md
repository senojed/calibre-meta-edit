# EPUB Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Calibre Meta Edit `0.4.0` with one-file EPUB import, review window, duplicate checks, optional Ollama AI resolver, safe Calibre write, and post-import table refresh.

**Architecture:** Keep import logic in backend helpers inside `calibre_meta_edit.py`, with Qt only orchestrating file selection, review UI, and background workers. Reuse existing Calibre safety helpers: `shared.quit_calibre`, `create_backup`, `find_calibredb`, `run_metadata_command_with_cover`, `read_matches_csv`, and `write_matches_csv`. Implement in small test-first slices; each task leaves the app working.

**Tech Stack:** Python stdlib, PySide6, `unittest`, Calibre `calibredb`, SQLite read-only access, existing scraping parsers for Databaze knih, Legie, Google Books, Open Library, optional local Ollama HTTP API.

---

## Source Spec

Read first:

- `docs/superpowers/specs/2026-06-15-epub-import-design.md`
- `calibre_meta_edit.py`
- `calibre_meta_qt.py`
- `calibre_meta_app.py`
- `tests/test_calibre_meta_edit.py`
- `tests/test_calibre_meta_qt.py`
- `tests/test_calibre_meta_app.py`

## File Structure

Modify:

- `calibre_meta_edit.py`
  - import data models
  - EPUB metadata/text extraction
  - filename/path signal extraction
  - candidate scoring
  - duplicate detection
  - Ollama resolver abstraction
  - import apply workflow
  - `run_metadata_command_with_cover` bytes support
  - `calibredb add` ID parsing

- `calibre_meta_qt.py`
  - app version `0.4.0`
  - AI settings in Preferences
  - `Import EPUB` toolbar button
  - modal import review dialog
  - background analysis worker
  - import apply worker
  - post-import selection in main table

- `calibre_meta_app.py`
  - app version `0.4.0`
  - small shared helpers for import action if needed

- `tests/test_calibre_meta_edit.py`
  - backend tests for all import units

- `tests/test_calibre_meta_qt.py`
  - Qt helper and window tests

- `tests/test_calibre_meta_app.py`
  - version/shared helper tests

- `POSTUP.md`
  - user-facing import section

Create:

- `tests/fixtures/import_epub.py` only if repeated EPUB fixture creation becomes noisy. Prefer inline temp EPUB builders first.

Do not create:

- new CLI command in `0.4.0`
- new separate database
- direct Calibre SQLite writer
- separate temp cover path helper that returns a path after cleanup

---

### Task 1: Version Bump And Import Data Models

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `calibre_meta_qt.py`
- Modify: `calibre_meta_app.py`
- Modify: `tests/test_calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_app.py`
- Modify: `POSTUP.md`

- [ ] **Step 1: Add failing backend data model tests**

Add this test class near existing dataclass/helper tests in `tests/test_calibre_meta_edit.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL with `AttributeError: module 'calibre_meta_edit' has no attribute 'ImportPreview'`.

- [ ] **Step 3: Add import dataclasses**

In `calibre_meta_edit.py`, after `CoverCandidate`, add:

```python
@dataclass(frozen=True)
class ImportSourceSignal:
    source: str
    title: str = ""
    authors: str = ""
    language: str = ""
    publisher: str = ""
    published_year: str = ""
    text: str = ""
    confidence: int = 0


@dataclass(frozen=True)
class ImportCandidate:
    source: str
    title: str
    authors: str
    url: str
    score: int = 0
    reason: str = ""
    work_type: str = ""
    evidence_text: str = ""
    detail: BookDetailMetadata | None = None


@dataclass(frozen=True)
class DuplicateCandidate:
    book_id: int
    title: str
    authors: str
    series: str = ""
    score: int = 0
    reason: str = ""
    strong: bool = False


@dataclass(frozen=True)
class ImportPreview:
    title: str = ""
    authors: str = ""
    series: str = ""
    series_index: str = ""
    published_year: str = ""
    publisher: str = ""
    tags: str = ""
    url: str = ""
    source: str = ""
    work_type: str = ""
    rating_percent: str = ""
    original_title: str = ""
    original_publication: str = ""
    original_publisher: str = ""
    comment: str = ""
    selected_cover_url: str = ""
    cover_bytes: bytes = b""
    allow_strong_duplicate: bool = False


@dataclass(frozen=True)
class ImportAnalysis:
    epub_path: str
    signals: list[ImportSourceSignal]
    candidates: list[ImportCandidate]
    recommended: ImportCandidate | None
    duplicates: list[DuplicateCandidate]
    preview: ImportPreview
    messages: list[str]
```

Add helper:

```python
def is_valid_import_preview(preview: ImportPreview) -> bool:
    return bool(preview.title.strip() and preview.authors.strip())
```

- [ ] **Step 4: Bump versions**

Change:

```python
APP_VERSION = "0.4.0"
```

in:

- `calibre_meta_qt.py`
- `calibre_meta_app.py`

Update tests:

```python
self.assertEqual(qt.APP_VERSION, "0.4.0")
self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.4.0")
self.assertEqual(text, "Ready | pracovni data nactena | 0.4.0")
```

```python
self.assertEqual(app.APP_VERSION, "0.4.0")
self.assertEqual(app.app_title(), "Calibre Meta Edit 0.4.0")
```

Update `POSTUP.md`:

```markdown
Aktualni verze: `0.4.0`
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py tests/test_calibre_meta_edit.py tests/test_calibre_meta_qt.py tests/test_calibre_meta_app.py POSTUP.md
git commit -m "Add import models"
```

---

### Task 2: EPUB Metadata And Text Extraction

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing EPUB fixture helper and tests**

Add imports at top of `tests/test_calibre_meta_edit.py`:

```python
import zipfile
```

Add helper near top-level test helpers:

```python
def write_test_epub(path: Path, title: str = "Imagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b", creator: str = "John Irving", language: str = "cs", body: str = "John Irving\\nImagin\u00e1rn\u00ed p\u0159\u00edtelkyn\u011b\\nCopyright 1996") -> None:
    container_xml = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{creator}</dc:creator>
    <dc:language>{language}</dc:language>
    <dc:publisher>Odeon</dc:publisher>
    <dc:date>1996</dc:date>
  </metadata>
  <manifest>
    <item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="title"/>
  </spine>
</package>"""
    xhtml = f"""<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{body}</p></body></html>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container_xml)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/title.xhtml", xhtml)
```

Add tests:

```python
class ImportEpubParsingTests(unittest.TestCase):
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

    def test_extract_epub_start_text_reads_spine_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_test_epub(epub, body="Tituln\u00ed strana\\nSpr\u00e1vn\u00fd n\u00e1zev\\nAutor")

            text = cme.extract_epub_start_text(epub, limit=80)

        self.assertIn("Tituln\u00ed strana", text)
        self.assertIn("Spr\u00e1vn\u00fd n\u00e1zev", text)
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL with missing `read_epub_metadata`.

- [ ] **Step 3: Implement EPUB parsing**

In `calibre_meta_edit.py`, add imports:

```python
import xml.etree.ElementTree as ET
import zipfile
```

Add dataclass after `ImportSourceSignal`:

```python
@dataclass(frozen=True)
class EpubMetadata:
    title: str = ""
    authors: str = ""
    language: str = ""
    publisher: str = ""
    published_year: str = ""
```

Add helpers:

```python
def _epub_opf_path(archive: zipfile.ZipFile) -> str:
    try:
        container = archive.read("META-INF/container.xml")
    except KeyError as exc:
        raise ValueError("epub-missing-container") from exc
    root = ET.fromstring(container)
    namespace = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = root.find(".//c:rootfile", namespace)
    if rootfile is None:
        raise ValueError("epub-missing-rootfile")
    full_path = rootfile.attrib.get("full-path", "").strip()
    if not full_path:
        raise ValueError("epub-empty-rootfile")
    return full_path


def _opf_text(root: ET.Element, tag: str) -> str:
    namespace = {"dc": "http://purl.org/dc/elements/1.1/"}
    value = root.findtext(f".//dc:{tag}", default="", namespaces=namespace)
    return html.unescape(value or "").strip()


def read_epub_metadata(path: str | Path) -> EpubMetadata:
    with zipfile.ZipFile(path) as archive:
        opf_path = _epub_opf_path(archive)
        root = ET.fromstring(archive.read(opf_path))
    return EpubMetadata(
        title=_opf_text(root, "title"),
        authors=_opf_text(root, "creator"),
        language=_opf_text(root, "language"),
        publisher=_opf_text(root, "publisher"),
        published_year=extract_year(_opf_text(root, "date")),
    )
```

If `extract_year` does not exist, add:

```python
def extract_year(text: str) -> str:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", text or "")
    return match.group(1) if match else ""
```

Add HTML text parser:

```python
class PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            self.parts.append(clean)

    def text(self) -> str:
        return "\n".join(self.parts)


def _epub_spine_item_paths(archive: zipfile.ZipFile, opf_path: str, root: ET.Element) -> list[str]:
    namespace = {"opf": "http://www.idpf.org/2007/opf"}
    manifest: dict[str, str] = {}
    base = str(Path(opf_path).parent).replace("\\", "/")
    for item in root.findall(".//opf:manifest/opf:item", namespace):
        item_id = item.attrib.get("id", "")
        href = item.attrib.get("href", "")
        media_type = item.attrib.get("media-type", "")
        if item_id and href and "html" in media_type:
            manifest[item_id] = (base + "/" + href if base != "." else href).replace("\\", "/")
    paths: list[str] = []
    for itemref in root.findall(".//opf:spine/opf:itemref", namespace):
        href = manifest.get(itemref.attrib.get("idref", ""))
        if href and href in archive.namelist():
            paths.append(href)
    return paths


def extract_epub_start_text(path: str | Path, limit: int = 5000) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        opf_path = _epub_opf_path(archive)
        root = ET.fromstring(archive.read(opf_path))
        for item_path in _epub_spine_item_paths(archive, opf_path, root):
            parser = PlainTextHTMLParser()
            parser.feed(archive.read(item_path).decode("utf-8", errors="replace"))
            texts.append(parser.text())
            joined = "\n".join(texts).strip()
            if len(joined) >= limit:
                return joined[:limit]
    return "\n".join(texts).strip()[:limit]
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Add EPUB import parsing"
```

---

### Task 3: Filename/Path Signals And Import Analysis Skeleton

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing signal tests**

Add to `ImportEpubParsingTests`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL with missing `import_signal_from_path`.

- [ ] **Step 3: Implement filename and skeleton analysis**

Add helpers in `calibre_meta_edit.py`:

```python
MOJIBAKE_REPLACEMENTS = {
    "p\u00b2": "p\u0159",
    "\u256a": "\u011b",
    "\u2563": "\u016f",
    "\u00de": "\u0161",
    "\u010e": "\u011b",
}


def repair_filename_text(text: str) -> str:
    repaired = text.replace("_", " ")
    for broken, fixed in MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(broken, fixed)
    repaired = re.sub(r"\s+", " ", repaired)
    return repaired.strip(" -_.")


def split_author_title_from_filename(stem: str) -> tuple[str, str]:
    clean = repair_filename_text(stem)
    parts = [part.strip() for part in re.split(r"\s+-\s+", clean, maxsplit=1)]
    if len(parts) != 2:
        return clean, ""
    left, right = parts
    words = left.split()
    if len(words) == 2:
        author = f"{words[1]} {words[0]}"
    else:
        author = left
    return right, author


def import_signal_from_path(path: str | Path) -> ImportSourceSignal:
    file_path = Path(path)
    title, authors = split_author_title_from_filename(file_path.stem)
    folder_text = repair_filename_text(" ".join(part for part in file_path.parts[:-1] if part))
    return ImportSourceSignal(
        source="filename",
        title=title,
        authors=authors,
        text=folder_text,
        confidence=30,
    )


def import_signal_from_epub_metadata(metadata: EpubMetadata) -> ImportSourceSignal:
    return ImportSourceSignal(
        source="epub-metadata",
        title=metadata.title,
        authors=metadata.authors,
        language=metadata.language,
        publisher=metadata.publisher,
        published_year=metadata.published_year,
        confidence=60 if metadata.title and metadata.authors else 30,
    )


def import_signal_from_epub_text(text: str) -> ImportSourceSignal:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ImportSourceSignal(source="epub-text", text="\n".join(lines[:20]), confidence=20)


def choose_initial_import_preview(signals: Sequence[ImportSourceSignal]) -> ImportPreview:
    title = next((signal.title for signal in signals if signal.title.strip()), "")
    authors = next((signal.authors for signal in signals if signal.authors.strip()), "")
    metadata_signal = next((signal for signal in signals if signal.source == "epub-metadata"), None)
    return ImportPreview(
        title=title,
        authors=authors,
        published_year=metadata_signal.published_year if metadata_signal else "",
        publisher=metadata_signal.publisher if metadata_signal else "",
    )


def analyze_epub_for_import(
    path: str | Path,
    library: str | Path,
    settings: dict[str, object],
    online_lookup: Callable[[Sequence[ImportSourceSignal]], list[ImportCandidate]] | None = None,
) -> ImportAnalysis:
    epub_path = Path(path)
    metadata = read_epub_metadata(epub_path)
    text = extract_epub_start_text(epub_path, limit=int(settings.get("epub_text_limit", 5000) or 5000))
    signals = [
        import_signal_from_epub_metadata(metadata),
        import_signal_from_epub_text(text),
        import_signal_from_path(epub_path),
    ]
    candidates = online_lookup(signals) if online_lookup else []
    preview = choose_initial_import_preview(signals)
    return ImportAnalysis(
        epub_path=str(epub_path),
        signals=signals,
        candidates=candidates,
        recommended=candidates[0] if candidates else None,
        duplicates=[],
        preview=preview,
        messages=[],
    )
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Add import source signals"
```

---

### Task 4: Candidate Scoring And Online Lookup Routing

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing candidate scoring tests**

Add:

```python
class ImportCandidateScoringTests(unittest.TestCase):
    def test_score_import_candidates_prefers_title_and_author_match(self):
        signals = [
            cme.ImportSourceSignal("epub-metadata", "Str\u00e1\u017ee! Str\u00e1\u017ee!", "Terry Pratchett", language="cs"),
            cme.ImportSourceSignal("filename", "Str\u00e1\u017ee str\u00e1\u017ee", "Terry Pratchett"),
        ]
        candidates = [
            cme.ImportCandidate("databazeknih", "Str\u00e1\u017ee! Str\u00e1\u017ee!", "Terry Pratchett", "https://dk/good"),
            cme.ImportCandidate("databazeknih", "Str\u00e1\u017ee stromy", "Jin\u00fd Autor", "https://dk/bad"),
        ]

        scored = cme.score_import_candidates(signals, candidates)

        self.assertEqual(scored[0].url, "https://dk/good")
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
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL with missing `score_import_candidates`.

- [ ] **Step 3: Implement scoring**

Add:

```python
def _best_normalized_title(signals: Sequence[ImportSourceSignal]) -> str:
    return next((signal.title for signal in signals if signal.title.strip()), "")


def _best_normalized_authors(signals: Sequence[ImportSourceSignal]) -> str:
    return next((signal.authors for signal in signals if signal.authors.strip()), "")


def _word_overlap_score(left: str, right: str) -> int:
    left_words = set(normalize_text(left).split())
    right_words = set(normalize_text(right).split())
    if not left_words or not right_words:
        return 0
    overlap = left_words & right_words
    if len(overlap) == 1 and max(len(left_words), len(right_words)) > 1:
        return 10
    return int(60 * len(overlap) / max(len(left_words), len(right_words)))


def _title_similarity_score(left: str, right: str) -> int:
    if normalize_text(left) == normalize_text(right) and left:
        return 70
    return min(70, int(_word_overlap_score(left, right) * 70 / 60))


def _author_similarity_score(signals_author: str, candidate: ImportCandidate) -> int:
    if normalize_text(candidate.authors) == normalize_text(signals_author) and signals_author:
        return 30
    if candidate.authors:
        return min(30, int(_word_overlap_score(signals_author, candidate.authors) * 30 / 60))
    if signals_author and candidate.evidence_text and _author_matches_text(signals_author, candidate.evidence_text):
        return 30
    return 0


def score_import_candidate(signals: Sequence[ImportSourceSignal], candidate: ImportCandidate) -> ImportCandidate:
    title = _best_normalized_title(signals)
    authors = _best_normalized_authors(signals)
    title_score = _title_similarity_score(title, candidate.title)
    author_score = _author_similarity_score(authors, candidate)
    score = title_score + author_score
    reason = f"title={title_score};author={author_score}"
    return replace(candidate, score=score, reason=reason)


def score_import_candidates(signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> list[ImportCandidate]:
    scored = [score_import_candidate(signals, candidate) for candidate in candidates]
    return sorted(scored, key=lambda candidate: candidate.score, reverse=True)
```

- [ ] **Step 4: Add online routing tests**

Add:

```python
    def test_import_source_names_for_czech_english_and_unknown(self):
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="cs")]), ["databazeknih", "legie"])
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="en")]), ["googlebooks", "openlibrary"])
        self.assertEqual(cme.import_lookup_sources([cme.ImportSourceSignal("epub", language="")]), ["databazeknih", "legie", "googlebooks", "openlibrary"])
```

- [ ] **Step 5: Implement source routing**

Add:

```python
def import_lookup_sources(signals: Sequence[ImportSourceSignal]) -> list[str]:
    languages = {signal.language.lower().strip() for signal in signals if signal.language.strip()}
    text = normalize_text(" ".join([signal.title + " " + signal.authors + " " + signal.text for signal in signals]))
    if languages == {"cs"} or "prelozil" in text or "vydalo" in text:
        return ["databazeknih", "legie"]
    if languages == {"en"}:
        return ["googlebooks", "openlibrary"]
    return ["databazeknih", "legie", "googlebooks", "openlibrary"]
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Score import candidates"
```

---

### Task 5: Online Candidate Lookup

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing tests with fake fetcher**

Add:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL with missing `lookup_import_candidates`.

- [ ] **Step 3: Implement online lookup using existing parsers**

Add:

```python
def _signal_book(signals: Sequence[ImportSourceSignal]) -> Book:
    title = _best_normalized_title(signals)
    authors = [part.strip() for part in _best_normalized_authors(signals).split("&") if part.strip()]
    return Book(0, title, authors)


def import_candidate_from_search_candidate(
    source: str,
    candidate: Candidate,
    signals: Sequence[ImportSourceSignal],
    work_type: str = "",
) -> ImportCandidate:
    authors = candidate.text.strip() if source in {"googlebooks", "openlibrary"} else ""
    return ImportCandidate(
        source=source,
        title=candidate.title,
        authors=authors,
        url=candidate.url,
        work_type=work_type,
        evidence_text=candidate.text,
    )


def lookup_import_candidates(
    signals: Sequence[ImportSourceSignal],
    fetcher: Callable[[str], str] | None = None,
    sleep_seconds: float = 0.0,
) -> list[ImportCandidate]:
    fetch = fetcher or fetch_text
    book = _signal_book(signals)
    candidates: list[ImportCandidate] = []
    for source in import_lookup_sources(signals):
        if source == "databazeknih":
            html_text = fetch(build_search_url(book.title, book.authors))
            candidates.extend(import_candidate_from_search_candidate("databazeknih", item, signals) for item in parse_search_results(html_text))
        elif source == "legie":
            html_text = fetch(build_legie_search_url(book.title, book.authors))
            candidates.extend(import_candidate_from_search_candidate("legie", item, signals, "povidka") for item in parse_legie_search_results(html_text))
        elif source == "googlebooks":
            json_text = fetch(build_google_books_search_url(book.title, book.authors))
            candidates.extend(import_candidate_from_search_candidate("googlebooks", item, signals) for item in parse_google_books_search_results(json_text))
        elif source == "openlibrary":
            json_text = fetch(build_openlibrary_search_url(book.title, book.authors))
            candidates.extend(import_candidate_from_search_candidate("openlibrary", item, signals) for item in parse_openlibrary_search_results(json_text))
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return score_import_candidates(signals, candidates)
```

- [ ] **Step 4: Wire lookup into analysis**

Change `analyze_epub_for_import` default:

```python
candidates = online_lookup(signals) if online_lookup else lookup_import_candidates(signals)
candidates = score_import_candidates(signals, candidates)
recommended = candidates[0] if candidates and candidates[0].score >= 80 else None
preview = import_preview_from_candidate(recommended, choose_initial_import_preview(signals)) if recommended else choose_initial_import_preview(signals)
```

Add helper:

```python
def import_preview_from_candidate(candidate: ImportCandidate | None, fallback: ImportPreview) -> ImportPreview:
    if candidate is None:
        return fallback
    return replace(
        fallback,
        title=candidate.title or fallback.title,
        authors=candidate.authors or fallback.authors,
        url=candidate.url,
        source=candidate.source,
        work_type=candidate.work_type,
    )
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Lookup import candidates"
```

---

### Task 6: Duplicate Detection Against Calibre DB

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing duplicate tests**

Add:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL with missing `find_import_duplicates`.

- [ ] **Step 3: Implement duplicate scoring**

Add:

```python
def _authors_text(authors: Sequence[str] | str) -> str:
    if isinstance(authors, str):
        return authors
    return " & ".join(authors)


def duplicate_score(preview: ImportPreview, book: Book) -> tuple[int, str]:
    title_score = 100 if normalize_text(preview.title) == normalize_text(book.title) else _word_overlap_score(preview.title, book.title)
    author_score = 100 if normalize_text(preview.authors) == normalize_text(_authors_text(book.authors)) else _word_overlap_score(preview.authors, _authors_text(book.authors))
    if author_score >= 80 and title_score >= 80:
        return 100, "title-author"
    if author_score >= 50 and title_score >= 50:
        return 70, "similar-title-author"
    if title_score >= 80 and author_score < 50:
        return 55, "same-title-different-author"
    return 0, ""


def find_import_duplicates(preview: ImportPreview, books: Sequence[Book]) -> list[DuplicateCandidate]:
    duplicates: list[DuplicateCandidate] = []
    for book in books:
        score, reason = duplicate_score(preview, book)
        if score <= 0:
            continue
        duplicates.append(
            DuplicateCandidate(
                book_id=book.id,
                title=book.title,
                authors=_authors_text(book.authors),
                score=score,
                reason=reason,
                strong=score >= 90,
            )
        )
    return sorted(duplicates, key=lambda item: item.score, reverse=True)
```

- [ ] **Step 4: Add DB wrapper test**

Add:

```python
    def test_find_calibre_import_duplicates_uses_books_reader(self):
        preview = cme.ImportPreview(title="Mort", authors="Terry Pratchett")

        duplicates = cme.find_calibre_import_duplicates(
            "B:\\",
            preview,
            books_reader=lambda library: [cme.Book(2, "Mort", ["Terry Pratchett"])],
        )

        self.assertEqual(duplicates[0].book_id, 2)
```

Implement:

```python
def find_calibre_import_duplicates(
    library: str | Path,
    preview: ImportPreview,
    books_reader: Callable[[str | Path], list[Book]] = read_books,
) -> list[DuplicateCandidate]:
    return find_import_duplicates(preview, books_reader(library))
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Detect import duplicates"
```

---

### Task 7: Import Cover Support In Existing Metadata Command Helper

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing cover bytes test**

Add:

```python
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
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: FAIL because `run_metadata_command_with_cover` has no `cover_bytes`.

- [ ] **Step 3: Extend helper without returning temp path**

Change signature:

```python
def run_metadata_command_with_cover(
    args: Sequence[str],
    selected_cover_url: str,
    runner: Callable[[Sequence[str]], CommandResult],
    cover_fetcher: Callable[[str], bytes] = fetch_binary,
    cover_bytes: bytes = b"",
    cover_suffix: str = ".jpg",
) -> CommandResult:
```

Replace body with:

```python
    cover_url = selected_cover_url.strip()
    bytes_to_write = cover_bytes
    suffix = cover_suffix
    if cover_url and not bytes_to_write:
        try:
            bytes_to_write = cover_fetcher(cover_url)
        except Exception as exc:
            return CommandResult(1, "", f"cover-fetch-error: {exc}")
        suffix = _cover_suffix(cover_url)
    if not cover_url and not bytes_to_write:
        return runner(args)
    if not bytes_to_write:
        return CommandResult(1, "", "cover-empty")
    with tempfile.TemporaryDirectory() as tmp:
        cover_path = Path(tmp) / ("cover" + suffix)
        cover_path.write_bytes(bytes_to_write)
        args_with_cover = list(args) + ["--field", "cover:" + str(cover_path)]
        return runner(args_with_cover)
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Support import cover bytes"
```

---

### Task 8: Calibredb Add ID Parsing And Safe Import Apply

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing ID parser tests**

Add:

```python
class ImportApplyTests(unittest.TestCase):
    def test_parse_calibredb_add_book_ids_reads_single_id(self):
        self.assertEqual(cme.parse_calibredb_add_book_ids("Added book ids: 123"), [123])

    def test_parse_calibredb_add_book_ids_reads_multiple_ids(self):
        self.assertEqual(cme.parse_calibredb_add_book_ids("Added book ids: 10, 11"), [10, 11])
```

- [ ] **Step 2: Implement parser**

Add:

```python
def parse_calibredb_add_book_ids(output: str) -> list[int]:
    match = re.search(r"Added book ids?:\s*([0-9,\s]+)", output or "", re.IGNORECASE)
    if not match:
        return []
    return [int(value) for value in re.findall(r"\d+", match.group(1))]
```

- [ ] **Step 3: Add failing apply workflow test**

Add:

```python
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
        self.assertEqual(rows_written[0].status, "skip")
        self.assertTrue(any(call[1] == "add" for call in calls))
        self.assertTrue(any(call[1] == "set_metadata" for call in calls))
```

- [ ] **Step 4: Implement import apply result and workflow**

Add:

```python
@dataclass(frozen=True)
class ImportApplyResult:
    book_id: int
    status: str
    error: str = ""
    backup_path: str = ""
```

Add:

```python
def read_calibre_book_ids(library: str | Path) -> set[int]:
    with open_calibre_db_readonly(library) as connection:
        return {int(row["id"]) for row in connection.execute("select id from books").fetchall()}


def _import_set_metadata_args(calibredb_path: str, library: str | Path, book_id: int, preview: ImportPreview) -> list[str]:
    args = [
        calibredb_path,
        "set_metadata",
        str(book_id),
        "--with-library",
        str(library),
        "--field",
        "title:" + preview.title,
        "--field",
        "authors:" + preview.authors,
    ]
    if preview.comment:
        args.extend(["--field", "comments:" + preview.comment])
    if preview.published_year:
        args.extend(["--field", "pubdate:" + calibre_pubdate_value(preview.published_year)])
    if preview.publisher:
        args.extend(["--field", "publisher:" + preview.publisher])
    if preview.tags:
        args.extend(["--field", "tags:" + preview.tags])
    if preview.series:
        args.extend(["--field", "series:" + preview.series])
    if preview.series_index:
        args.extend(["--field", "series_index:" + preview.series_index])
    return args


def import_preview_to_match_row(book_id: int, preview: ImportPreview) -> MatchRow:
    return MatchRow(
        book_id,
        preview.title,
        preview.authors,
        "skip",
        preview.url,
        "",
        "imported",
        "imported",
        preview.source or source_and_work_type_for_url(preview.url)[0],
        preview.work_type,
        "",
        preview.selected_cover_url,
        "",
        preview.published_year,
        preview.publisher,
        preview.tags,
        preview.rating_percent,
        preview.original_title,
        preview.original_publication,
        preview.original_publisher,
    )
```

Add:

```python
def apply_import_preview(
    preview: ImportPreview,
    epub_path: str | Path,
    library: str | Path,
    calibredb_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
    existing_ids_reader: Callable[[str | Path], set[int]] = read_calibre_book_ids,
    duplicate_reader: Callable[[str | Path, ImportPreview], list[DuplicateCandidate]] = find_calibre_import_duplicates,
    backup_func: Callable[[str | Path, Path], Path] = create_backup,
    rows_reader: Callable[[Path], list[MatchRow]] = read_matches_csv,
    rows_writer: Callable[[Path, Iterable[MatchRow], bool], None] = write_matches_csv,
    quit_func: Callable[[bool], int] | None = None,
    allow_force: bool = True,
    matches_path: Path = MATCHES_PATH,
) -> ImportApplyResult:
    if not is_valid_import_preview(preview):
        return ImportApplyResult(0, "failed", "missing-title-or-author")
    if any(item.strong for item in duplicate_reader(library, preview)) and not preview.allow_strong_duplicate:
        return ImportApplyResult(0, "failed", "strong-duplicate")
    quit_runner = quit_func or (lambda force: 0)
    quit_result = quit_runner(allow_force)
    if quit_result != 0:
        return ImportApplyResult(0, "failed", "quit-calibre-failed")
    backup_path = backup_func(library, Path("backups"))
    before_ids = existing_ids_reader(library)
    fresh_duplicates = duplicate_reader(library, preview)
    if any(item.strong for item in fresh_duplicates) and not preview.allow_strong_duplicate:
        return ImportApplyResult(0, "failed", "strong-duplicate-after-close", str(backup_path))
    add_result = runner([calibredb_path, "add", str(epub_path), "--with-library", str(library)])
    if add_result.returncode != 0:
        return ImportApplyResult(0, "failed", (add_result.stderr or add_result.stdout).strip(), str(backup_path))
    new_ids = parse_calibredb_add_book_ids(add_result.stdout + "\n" + add_result.stderr)
    if len(new_ids) != 1:
        diff = existing_ids_reader(library) - before_ids
        new_ids = sorted(diff)
    if len(new_ids) != 1:
        return ImportApplyResult(0, "failed", "new-book-id-not-unique", str(backup_path))
    book_id = new_ids[0]
    metadata_result = run_metadata_command_with_cover(
        _import_set_metadata_args(calibredb_path, library, book_id, preview),
        preview.selected_cover_url,
        runner,
        cover_bytes=preview.cover_bytes,
    )
    if metadata_result.returncode != 0:
        return ImportApplyResult(book_id, "failed", (metadata_result.stderr or metadata_result.stdout).strip(), str(backup_path))
    rows = rows_reader(matches_path) if matches_storage_exists(matches_path) else []
    rows_writer(matches_path, [*rows, import_preview_to_match_row(book_id, preview)], True)
    return ImportApplyResult(book_id, "updated", "", str(backup_path))
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Apply EPUB import preview"
```

---

### Task 9: Ollama AI Resolver Settings And Backend

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Add backend AI resolver tests**

Add:

```python
class ImportAIResolverTests(unittest.TestCase):
    def test_disabled_ai_resolver_returns_no_choice(self):
        resolver = cme.DisabledAIResolver()

        result = resolver.resolve([], [])

        self.assertIsNone(result)

    def test_ollama_unavailable_returns_no_choice(self):
        resolver = cme.OllamaAIResolver(model="llama3", requester=lambda payload: (_ for _ in ()).throw(OSError("down")))

        result = resolver.resolve([], [])

        self.assertIsNone(result)

    def test_ai_choice_can_promote_matching_candidate(self):
        candidates = [
            cme.ImportCandidate("openlibrary", "Bad", "Autor", "https://bad", score=70),
            cme.ImportCandidate("openlibrary", "Good", "Autor", "https://good", score=60),
        ]

        class FixedResolver:
            def resolve(self, signals, candidates):
                return cme.AIImportChoice("https://good", 90, "best")

        selected = cme.resolve_import_candidate_with_ai([], candidates, FixedResolver())

        self.assertEqual(selected.url, "https://good")

    def test_low_score_candidate_is_not_recommended_without_ai_confidence(self):
        candidates = [cme.ImportCandidate("databazeknih", "Weak", "", "https://weak", score=10)]

        selected = cme.resolve_import_candidate_with_ai([], candidates, cme.DisabledAIResolver())

        self.assertIsNone(selected)
```

- [ ] **Step 2: Implement AI resolver classes**

Add:

```python
@dataclass(frozen=True)
class AIImportChoice:
    url: str
    confidence: int
    reason: str
    requires_review: bool = True


class DisabledAIResolver:
    def resolve(self, signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> AIImportChoice | None:
        return None


class OllamaAIResolver:
    def __init__(
        self,
        model: str,
        endpoint: str = "http://127.0.0.1:11434/api/generate",
        requester: Callable[[dict[str, object]], str] | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.requester = requester

    def resolve(self, signals: Sequence[ImportSourceSignal], candidates: Sequence[ImportCandidate]) -> AIImportChoice | None:
        if not candidates:
            return None
        compact_candidates = [
            replace(candidate, evidence_text=candidate.evidence_text[:500])
            for candidate in candidates[:5]
        ]
        payload = {
            "model": self.model,
            "stream": False,
            "prompt": json.dumps(
                {
                    "signals": [signal.__dict__ for signal in signals],
                    "candidates": [candidate.__dict__ for candidate in compact_candidates],
                },
                ensure_ascii=False,
            ),
        }
        try:
            raw = self.requester(payload) if self.requester else self._post(payload)
            data = json.loads(raw)
            response = json.loads(data.get("response", "{}"))
            return AIImportChoice(
                url=str(response.get("url", "")),
                confidence=int(response.get("confidence", 0)),
                reason=str(response.get("reason", "")),
                requires_review=bool(response.get("requires_review", True)),
            )
        except Exception:
            return None

    def _post(self, payload: dict[str, object]) -> str:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")


def resolve_import_candidate_with_ai(
    signals: Sequence[ImportSourceSignal],
    candidates: Sequence[ImportCandidate],
    resolver: DisabledAIResolver | OllamaAIResolver,
    minimum_score: int = 80,
) -> ImportCandidate | None:
    if not candidates:
        return None
    choice = resolver.resolve(signals, candidates)
    if choice is not None and choice.confidence >= 80:
        for candidate in candidates:
            if candidate.url == choice.url:
                return replace(candidate, reason=f"{candidate.reason};ai={choice.confidence}:{choice.reason}")
    return candidates[0] if candidates[0].score >= minimum_score else None
```

- [ ] **Step 3: Wire AI resolver into import analysis**

Change `analyze_epub_for_import` signature:

```python
def analyze_epub_for_import(
    path: str | Path,
    library: str | Path,
    settings: dict[str, object],
    online_lookup: Callable[[Sequence[ImportSourceSignal]], list[ImportCandidate]] | None = None,
    ai_resolver: DisabledAIResolver | OllamaAIResolver | None = None,
) -> ImportAnalysis:
```

Inside `analyze_epub_for_import`, after candidates are scored:

```python
    resolver = ai_resolver or DisabledAIResolver()
    recommended = resolve_import_candidate_with_ai(signals, candidates, resolver)
    preview = import_preview_from_candidate(recommended, choose_initial_import_preview(signals)) if recommended else choose_initial_import_preview(signals)
```

Keep AI non-fatal: `DisabledAIResolver` returns `None`, `OllamaAIResolver` catches errors and returns `None`.

- [ ] **Step 4: Add Qt settings tests**

Add to `tests/test_calibre_meta_qt.py`:

```python
    def test_normalize_ai_settings_defaults_to_disabled(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.normalize_ai_settings({}), {"provider": "off", "model": "llama3", "text_limit": 5000})

    def test_normalize_ai_settings_reads_ollama(self):
        import calibre_meta_qt as qt

        settings = qt.normalize_ai_settings({"ai": {"provider": "ollama", "model": "mistral", "text_limit": 2000}})

        self.assertEqual(settings["provider"], "ollama")
        self.assertEqual(settings["model"], "mistral")
        self.assertEqual(settings["text_limit"], 2000)
```

- [ ] **Step 5: Implement Qt AI settings helpers**

In `calibre_meta_qt.py`, add:

```python
AI_PROVIDER_VALUES = ("off", "ollama")
AI_SETTING_DEFAULTS = {"provider": "off", "model": "llama3", "text_limit": 5000}
```

Add helper near settings helpers:

```python
def normalize_ai_settings(raw: Any) -> dict[str, str | int]:
    ai = raw.get("ai") if isinstance(raw, dict) else {}
    ai = ai if isinstance(ai, dict) else {}
    provider = ai.get("provider")
    model = ai.get("model")
    text_limit = ai.get("text_limit")
    return {
        "provider": provider if provider in AI_PROVIDER_VALUES else "off",
        "model": model if isinstance(model, str) and model.strip() else "llama3",
        "text_limit": text_limit if isinstance(text_limit, int) and 500 <= text_limit <= 20000 else 5000,
    }
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add calibre_meta_edit.py calibre_meta_qt.py tests/test_calibre_meta_edit.py tests/test_calibre_meta_qt.py
git commit -m "Add optional Ollama import resolver"
```

---

### Task 10: Qt Import Dialog Skeleton

**Files:**
- Modify: `calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Add Qt dialog tests**

Add:

```python
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
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_qt.py
```

Expected: FAIL with missing `ImportDialog`.

- [ ] **Step 3: Implement modal dialog skeleton**

In `calibre_meta_qt.py`, inside `if PYSIDE6_AVAILABLE:` before `CalibreMetaQtWindow`, add:

```python
    class ImportDialog(QDialog):
        """Modalni okno pro kontrolu jednoho EPUB importu pred zapisem."""

        def __init__(self, analysis: cme.ImportAnalysis, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.analysis = analysis
            self.setWindowTitle("Import EPUB")
            self.resize(1180, 720)
            root = QVBoxLayout(self)
            body = QHBoxLayout()
            root.addLayout(body, stretch=1)

            left = QVBoxLayout()
            body.addLayout(left, stretch=1)
            left.addWidget(QLabel("Soubor"))
            self.file_label = QLabel(analysis.epub_path)
            self.file_label.setWordWrap(True)
            left.addWidget(self.file_label)
            left.addWidget(QLabel("Signaly"))
            self.signals_list = QListWidget()
            for signal in analysis.signals:
                self.signals_list.addItem(f"{signal.source}: {signal.title} / {signal.authors}")
            left.addWidget(self.signals_list, stretch=1)
            left.addWidget(QLabel("Kandidati"))
            self.candidates_list = QListWidget()
            for candidate in analysis.candidates:
                self.candidates_list.addItem(f"{candidate.score} {candidate.source}: {candidate.title} / {candidate.authors}")
            left.addWidget(self.candidates_list, stretch=1)
            left.addWidget(QLabel("Duplicity"))
            self.duplicates_list = QListWidget()
            for duplicate in analysis.duplicates:
                self.duplicates_list.addItem(f"{duplicate.score} {duplicate.book_id}: {duplicate.title} / {duplicate.authors}")
            left.addWidget(self.duplicates_list, stretch=1)

            right = QFormLayout()
            body.addLayout(right, stretch=1)
            self.title_edit = QLineEdit(analysis.preview.title)
            self.authors_edit = QLineEdit(analysis.preview.authors)
            self.series_edit = QLineEdit(analysis.preview.series)
            self.series_index_edit = QLineEdit(analysis.preview.series_index)
            self.year_edit = QLineEdit(analysis.preview.published_year)
            self.publisher_edit = QLineEdit(analysis.preview.publisher)
            self.tags_edit = QLineEdit(analysis.preview.tags)
            self.url_edit = QLineEdit(analysis.preview.url)
            self.comment_edit = QTextEdit(analysis.preview.comment)
            right.addRow("Nazev", self.title_edit)
            right.addRow("Autor/autori", self.authors_edit)
            right.addRow("Serie", self.series_edit)
            right.addRow("Cislo serie", self.series_index_edit)
            right.addRow("Rok vydani", self.year_edit)
            right.addRow("Vydavatel", self.publisher_edit)
            right.addRow("Tagy", self.tags_edit)
            right.addRow("Odkaz", self.url_edit)
            right.addRow("Komentar", self.comment_edit)

            buttons = QHBoxLayout()
            root.addLayout(buttons)
            buttons.addStretch(1)
            self.import_button = QPushButton("Importovat")
            self.cancel_button = QPushButton("Zrusit")
            buttons.addWidget(self.import_button)
            buttons.addWidget(self.cancel_button)
            self.cancel_button.clicked.connect(self.reject)
            self.import_button.clicked.connect(self.accept)
            self.title_edit.textChanged.connect(self.update_import_enabled)
            self.authors_edit.textChanged.connect(self.update_import_enabled)
            self.update_import_enabled()

        def update_import_enabled(self) -> None:
            self.import_button.setEnabled(bool(self.title_edit.text().strip() and self.authors_edit.text().strip()))

        def preview(self) -> cme.ImportPreview:
            return replace(
                self.analysis.preview,
                title=self.title_edit.text(),
                authors=self.authors_edit.text(),
                series=self.series_edit.text(),
                series_index=self.series_index_edit.text(),
                published_year=self.year_edit.text(),
                publisher=self.publisher_edit.text(),
                tags=self.tags_edit.text(),
                url=self.url_edit.text(),
                comment=self.comment_edit.toPlainText(),
            )
```

Add missing Qt imports:

```python
QFormLayout,
QListWidget,
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_qt.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add calibre_meta_qt.py tests/test_calibre_meta_qt.py
git commit -m "Add EPUB import dialog"
```

---

### Task 11: Qt Import Button And Analysis Worker

**Files:**
- Modify: `calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Verify current Qt integration points**

Before editing, grep these names in `calibre_meta_qt.py` and confirm signatures still match the plan:

```powershell
rg -n "class WorkerBridge|finished = Signal|def finish_background|self.buttons|def set_ui_enabled|def restore_selection|def selected_book_ids|class PreferencesDialog|def _build_toolbar" calibre_meta_qt.py
```

Expected facts:

- `WorkerBridge.finished` accepts `title`, `result`, `text`, `reload_after`
- `finish_background(self, title, result, text, reload_after)` exists
- `self.buttons` stores toolbar buttons
- `set_ui_enabled`, `restore_selection`, and `selected_book_ids` exist
- `PreferencesDialog` uses a grid layout where extra AI rows do not overlap existing rows
- `_build_toolbar` is where the import button belongs

If one fact differs, update this task's code to match current names before changing files.

- [ ] **Step 2: Add import button test**

Add:

```python
    def test_qt_window_has_import_epub_button(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()

        tooltips = [button.toolTip() for button in window.buttons]

        self.assertIn("Import EPUB", tooltips)
        app.processEvents()
```

- [ ] **Step 3: Add import button**

In `_build_toolbar`, after save button:

```python
self._add_button(toolbar, "Import EPUB", self.choose_import_epub, "neutralButton", "open", show_text=False)
```

Add method:

```python
        def choose_import_epub(self) -> None:
            if not self.save_csv(show_message=False):
                return
            path, _filter = QFileDialog.getOpenFileName(
                self,
                "Vyber EPUB",
                "",
                "EPUB knihy (*.epub);;Vsechny soubory (*.*)",
            )
            if not path:
                return
            self.run_import_analysis(Path(path))
```

- [ ] **Step 4: Add worker signal**

Change `WorkerBridge`:

```python
import_ready = Signal(object)
import_failed = Signal(str)
```

Connect in `__init__`:

```python
self.bridge.import_ready.connect(self.show_import_dialog)
self.bridge.import_failed.connect(lambda text: QMessageBox.critical(self, "Import EPUB", text))
```

Add methods:

```python
        def run_import_analysis(self, epub_path: Path) -> None:
            if self.worker_running:
                QMessageBox.information(self, "Bezi akce", "Pockej, az skonci aktualni akce.")
                return
            self.worker_running = True
            self.set_ui_enabled(False)
            self.detail_tabs.setCurrentWidget(self.log_tab)
            self.write_output(f"Analyzuju EPUB: {epub_path}")

            def worker() -> None:
                try:
                    settings = read_app_settings()
                    ai_settings = normalize_ai_settings(settings)
                    resolver = (
                        cme.OllamaAIResolver(str(ai_settings["model"]))
                        if ai_settings["provider"] == "ollama"
                        else cme.DisabledAIResolver()
                    )
                    analysis = cme.analyze_epub_for_import(
                        epub_path,
                        self.library_path,
                        {"epub_text_limit": ai_settings["text_limit"]},
                        ai_resolver=resolver,
                    )
                    self.bridge.import_ready.emit(analysis)
                except Exception as exc:
                    self.bridge.import_failed.emit(str(exc))

            threading.Thread(target=worker, daemon=True).start()

        def show_import_dialog(self, analysis: cme.ImportAnalysis) -> None:
            self.worker_running = False
            self.set_ui_enabled(True)
            dialog = ImportDialog(analysis, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.run_import_apply(dialog.preview(), Path(analysis.epub_path))
```

- [ ] **Step 5: Add temporary apply stub**

Add:

```python
        def run_import_apply(self, preview: cme.ImportPreview, epub_path: Path) -> None:
            QMessageBox.information(self, "Import EPUB", "Import zapis bude pridan v dalsim kroku.")
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_qt.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add calibre_meta_qt.py tests/test_calibre_meta_qt.py
git commit -m "Wire EPUB import analysis"
```

---

### Task 12: Qt Import Apply Worker And Post-Import Selection

**Files:**
- Modify: `calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Add helper test for selecting imported row**

Add:

```python
    def test_select_book_id_selects_imported_row_after_refresh(self):
        from PySide6.QtWidgets import QApplication
        import sys
        import calibre_meta_qt as qt

        app = QApplication.instance() or QApplication(sys.argv)
        window = qt.CalibreMetaQtWindow()
        window.rows = [cme.MatchRow(42, "Kniha", "Autor", "skip", "", "", "imported", "imported")]
        window.refresh_table()

        window.select_book_id(42)

        self.assertEqual(window.selected_book_ids(), {42})
        app.processEvents()
```

- [ ] **Step 2: Implement selection helper**

Add to `CalibreMetaQtWindow`:

```python
        def select_book_id(self, book_id: int) -> None:
            self.restore_selection({book_id})
            self.detail_tabs.setCurrentIndex(0)
            self.on_selection_changed()
```

- [ ] **Step 3: Replace apply stub**

Replace `run_import_apply` with:

```python
        def run_import_apply(self, preview: cme.ImportPreview, epub_path: Path) -> None:
            confirmed, allow_force = self.ask_import_confirmation(preview)
            if not confirmed:
                return
            calibredb_path = cme.find_calibredb()
            if not calibredb_path:
                QMessageBox.critical(self, "Import EPUB", "calibredb nenalezen.")
                return
            action = lambda: cme.apply_import_preview(
                preview,
                epub_path,
                self.library_path,
                calibredb_path,
                quit_func=lambda force: shared.quit_calibre(allow_force=force),
                allow_force=allow_force,
            )
            self.run_import_apply_background(action)
```

Add:

```python
        def ask_import_confirmation(self, preview: cme.ImportPreview) -> tuple[bool, bool]:
            box = QMessageBox(self)
            box.setWindowTitle("Import EPUB")
            box.setText(
                "Appka udela:\n"
                "1. zavre Calibre\n"
                "2. zazalohuje metadata.db\n"
                "3. prida EPUB do Calibre\n"
                "4. zapise metadata a obalku\n\n"
                f"{preview.title}\n{preview.authors}"
            )
            force = QCheckBox("Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F")
            force.setChecked(True)
            box.setCheckBox(force)
            box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Ok)
            return box.exec() == QMessageBox.StandardButton.Ok, force.isChecked()

        def run_import_apply_background(self, action: Callable[[], cme.ImportApplyResult]) -> None:
            if self.worker_running:
                QMessageBox.information(self, "Bezi akce", "Pockej, az skonci aktualni akce.")
                return
            self.worker_running = True
            self.set_ui_enabled(False)
            self.detail_tabs.setCurrentWidget(self.log_tab)
            self.write_output("Import EPUB...")

            def worker() -> None:
                try:
                    result = action()
                    self.bridge.finished.emit("Import EPUB", 0 if result.status == "updated" else 1, json.dumps(result.__dict__, ensure_ascii=False), True)
                except Exception as exc:
                    self.bridge.finished.emit("Import EPUB", 1, str(exc), True)

            threading.Thread(target=worker, daemon=True).start()
```

In `finish_background`, after reload:

```python
            imported_id = 0
            if title == "Import EPUB" and text.strip().startswith("{"):
                with contextlib.suppress(Exception):
                    imported_id = int(json.loads(text).get("book_id") or 0)
            if reload_after and result == 0:
                self.load_csv(show_message=False)
                if imported_id:
                    self.select_book_id(imported_id)
```

Remove the older duplicate `if reload_after and result == 0: self.load_csv(show_message=False)` block so reload happens once.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_qt.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add calibre_meta_qt.py tests/test_calibre_meta_qt.py
git commit -m "Apply EPUB imports from Qt"
```

---

### Task 13: Preferences UI For AI Settings

**Files:**
- Modify: `calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Add save settings test**

Add:

```python
    def test_save_app_settings_preserves_ai_settings(self):
        import calibre_meta_qt as qt

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(json.dumps({"ai": {"provider": "ollama", "model": "mistral", "text_limit": 2000}}), encoding="utf-8")

            qt.save_app_settings("B:\\", "dark", settings_path)

            data = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ai"]["provider"], "ollama")
        self.assertEqual(data["ai"]["model"], "mistral")
```

- [ ] **Step 2: Extend PreferencesDialog UI**

In `PreferencesDialog.__init__`, after auto checks:

```python
            ai_settings = normalize_ai_settings(read_app_settings())
            form.addWidget(QLabel("AI import"), 5, 0)
            self.ai_provider_combo = QComboBox()
            self.ai_provider_combo.addItems(AI_PROVIDER_VALUES)
            self.ai_provider_combo.setCurrentText(str(ai_settings["provider"]))
            form.addWidget(self.ai_provider_combo, 5, 1)
            form.addWidget(QLabel("AI model"), 6, 0)
            self.ai_model_edit = QLineEdit(str(ai_settings["model"]))
            form.addWidget(self.ai_model_edit, 6, 1, 1, 3)
            form.addWidget(QLabel("EPUB text limit"), 7, 0)
            self.ai_text_limit_edit = QLineEdit(str(ai_settings["text_limit"]))
            form.addWidget(self.ai_text_limit_edit, 7, 1)
```

In `save_library`, before writing settings:

```python
            try:
                text_limit = int(self.ai_text_limit_edit.text())
            except ValueError:
                text_limit = 5000
            settings["ai"] = {
                "provider": self.ai_provider_combo.currentText(),
                "model": self.ai_model_edit.text().strip() or "llama3",
                "text_limit": text_limit,
            }
```

- [ ] **Step 3: Run tests**

Run:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_qt.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add calibre_meta_qt.py tests/test_calibre_meta_qt.py
git commit -m "Add import AI preferences"
```

---

### Task 14: Candidate Selection, Metadata Refresh, And Covers In Dialog

**Files:**
- Modify: `calibre_meta_edit.py`
- Modify: `calibre_meta_qt.py`
- Modify: `tests/test_calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Add backend preview-from-detail test**

Add:

```python
class ImportPreviewDetailTests(unittest.TestCase):
    def test_import_preview_from_detail_formats_comment_and_metadata(self):
        candidate = cme.ImportCandidate("openlibrary", "Homo Deus", "Yuval Noah Harari", "https://openlibrary.org/books/OL1M/X")
        detail = cme.BookDetailMetadata(published_year="2016", publisher="Harvill", tags=["Literatura svetova"], rating_percent="", about_text="Popis")

        preview = cme.import_preview_from_detail(candidate, detail)

        self.assertEqual(preview.title, "Homo Deus")
        self.assertEqual(preview.authors, "Yuval Noah Harari")
        self.assertEqual(preview.publisher, "Harvill")
        self.assertIn("https://openlibrary.org/books/OL1M/X", preview.comment)
```

- [ ] **Step 2: Implement preview-from-detail helper**

Add:

```python
def import_preview_from_detail(candidate: ImportCandidate, detail: BookDetailMetadata) -> ImportPreview:
    return ImportPreview(
        title=candidate.title,
        authors=candidate.authors,
        published_year=detail.published_year,
        publisher=detail.publisher,
        tags=",".join(detail.tags or []),
        url=candidate.url,
        source=candidate.source,
        work_type=candidate.work_type,
        rating_percent=detail.rating_percent,
        original_title=detail.original_title,
        original_publication=detail.original_publication,
        original_publisher=detail.original_publisher,
        comment=format_enriched_comment(candidate.url, detail),
        selected_cover_url=detail.cover_url,
    )
```

- [ ] **Step 3: Extend dialog candidate click**

Add backend detail loader:

```python
def import_preview_for_candidate(
    candidate: ImportCandidate,
    fetcher: Callable[[str], str] | None = None,
) -> ImportPreview:
    fetch = fetcher or fetch_text
    if candidate.source == "databazeknih":
        written_url, detail = fetch_databaze_book_detail_metadata(candidate.url, fetch)
    elif candidate.source == "googlebooks":
        written_url, detail = fetch_google_books_detail_metadata(candidate.url, fetch)
    elif candidate.source == "openlibrary":
        written_url, detail = fetch_openlibrary_detail_metadata(candidate.url, fetch)
    elif candidate.source == "legie":
        story = parse_legie_story_detail(fetch(legie_absolute_url(candidate.url)), candidate.url)
        written_url = legie_absolute_url(candidate.url)
        return ImportPreview(
            title=candidate.title or story.title,
            authors=candidate.authors or story.author,
            published_year=extract_year(story.czech_publication),
            url=written_url,
            source="legie",
            work_type="povidka",
            rating_percent=story.rating_percent,
            original_title=story.original_title,
            original_publication=story.original_publication,
            comment=format_legie_comment(written_url, story),
            selected_cover_url=story.cover_url,
        )
    else:
        written_url = candidate.url
        detail = candidate.detail or BookDetailMetadata()
    return import_preview_from_detail(replace(candidate, url=written_url), detail)
```

In `ImportDialog.__init__`, connect:

```python
self.candidates_list.currentRowChanged.connect(self.select_candidate)
```

Change `ImportDialog.__init__` signature:

```python
        def __init__(
            self,
            analysis: cme.ImportAnalysis,
            parent: QWidget | None = None,
            preview_loader: Callable[[cme.ImportCandidate], cme.ImportPreview] | None = None,
            duplicate_loader: Callable[[cme.ImportPreview], list[cme.DuplicateCandidate]] | None = None,
        ) -> None:
```

Inside `__init__`, store loaders:

```python
            self.preview_loader = preview_loader or cme.import_preview_for_candidate
            self.duplicate_loader = duplicate_loader
```

Add helper methods:

```python
        def select_candidate(self, index: int) -> None:
            if index < 0 or index >= len(self.analysis.candidates):
                return
            candidate = self.analysis.candidates[index]
            try:
                preview = self.preview_loader(candidate)
            except Exception as exc:
                QMessageBox.warning(self, "Kandidat", f"Metadata kandidata nejde nacist:\n{exc}")
                preview = cme.import_preview_from_candidate(candidate, self.preview())
            self.apply_preview(preview)

        def apply_preview(self, preview: cme.ImportPreview) -> None:
            self.title_edit.setText(preview.title)
            self.authors_edit.setText(preview.authors)
            self.series_edit.setText(preview.series)
            self.series_index_edit.setText(preview.series_index)
            self.year_edit.setText(preview.published_year)
            self.publisher_edit.setText(preview.publisher)
            self.tags_edit.setText(preview.tags)
            self.url_edit.setText(preview.url)
            self.comment_edit.setPlainText(preview.comment)
            if self.duplicate_loader is not None:
                self.duplicates_list.clear()
                for duplicate in self.duplicate_loader(preview):
                    self.duplicates_list.addItem(f"{duplicate.score} {duplicate.book_id}: {duplicate.title} / {duplicate.authors}")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add calibre_meta_edit.py calibre_meta_qt.py tests/test_calibre_meta_edit.py tests/test_calibre_meta_qt.py
git commit -m "Refresh import preview from candidates"
```

---

### Task 15: Final Polish, Docs, And Manual Smoke

**Files:**
- Modify: `POSTUP.md`
- Modify: `calibre_meta_qt.py`
- Modify: `calibre_meta_edit.py`
- Modify: `tests/test_calibre_meta_edit.py`, `tests/test_calibre_meta_qt.py`, or `tests/test_calibre_meta_app.py` for any focused regression found during smoke testing

- [ ] **Step 1: Add POSTUP import section**

Add section:

```markdown
## Import EPUB

Tlacitko `Import EPUB` prida jednu EPUB knihu do Calibre.

Postup:

1. klikni `Import EPUB`
2. vyber `.epub`
3. appka nacte metadata, zacatek knihy, nazev souboru a online kandidaty
4. zkontroluj navrh v importnim okne
5. uprav nazev, autora, serii, metadata, komentar nebo obalku
6. pokud appka najde duplicitu, potvrdis import navic
7. klikni `Importovat`

Appka pred zapisem:

- ulozi `matches.db`
- zavre Calibre
- zazalohuje `metadata.db`
- znovu overi duplicity

Puvodni EPUB se nemeni a nepresouva. Calibre si vytvori vlastni kopii.
```

- [ ] **Step 2: Run full automated tests**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: Manual smoke without writing to real library**

Use a temporary Calibre library or a disposable copy. Do not run against production library first.

Run app:

```powershell
python CalibreMetaEdit.pyw
```

Manual checks:

- `Import EPUB` button appears.
- Choosing non-EPUB is blocked by file filter.
- Choosing test EPUB opens wide modal dialog.
- Empty title or author disables `Importovat`.
- Candidate list displays if online lookup finds candidates.
- Duplicate list displays for known existing test book.
- Cancel closes dialog without writing.

- [ ] **Step 4: Manual smoke with disposable Calibre library**

Create or copy small test library. Then:

- import one EPUB
- verify `metadata.db` backup created in `backups`
- verify new book appears in Calibre library
- verify metadata/comment written
- verify `matches.db` contains new row with `status=skip`
- verify main table selects new row
- verify original EPUB still exists

- [ ] **Step 5: Fix any smoke issue with focused tests**

For every bug found, add a test first. Example for a duplicate prompt regression:

```python
def test_apply_import_preview_blocks_unconfirmed_strong_duplicate_after_close(self):
    preview = cme.ImportPreview(title="Kniha", authors="Autor")
    result = cme.apply_import_preview(
        preview,
        epub_path=Path("book.epub"),
        library="B:\\",
        calibredb_path="calibredb",
        duplicate_reader=lambda library, preview: [cme.DuplicateCandidate(1, "Kniha", "Autor", strong=True)],
        backup_func=lambda library, backups_dir: Path("backups/metadata-test.db"),
        quit_func=lambda allow_force: 0,
    )
    self.assertEqual(result.status, "failed")
    self.assertEqual(result.error, "strong-duplicate")
```

Run full tests after fixes.

- [ ] **Step 6: Final commit**

```powershell
git add POSTUP.md calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py tests/test_calibre_meta_edit.py tests/test_calibre_meta_qt.py tests/test_calibre_meta_app.py
git commit -m "Finish EPUB import workflow"
```

---

## Final Verification

- [ ] Run:

```powershell
python -m unittest discover -s tests
```

Expected:

```text
OK
```

- [ ] Run:

```powershell
git status --short --untracked-files=no
```

Expected: no output.

- [ ] Push:

```powershell
git push
```

---

## Self-Review Notes

Spec coverage:

- one EPUB only: Tasks 2, 10, 11
- no write before confirmation: Tasks 10, 12
- save `matches.db` before import: Task 11
- backup `metadata.db`: Task 8
- `calibredb add` then `set_metadata`: Task 8
- parse `calibredb add` ID then fallback diff: Task 8
- duplicate analysis and final re-check: Tasks 6 and 8
- original EPUB unchanged: Task 8 and Task 15
- optional Ollama AI: Task 9
- import dialog wide review: Task 10
- candidate selection: Task 14
- cover temp handling inside helper: Task 7
- new row in `matches.db` as `skip`: Task 8 and Task 12

Known deliberate limits:

- no batch import
- no drag and drop
- no PDF/MOBI/AZW3/PDB import
- no OCR
- no cloud AI provider implementation
- no CLI import
