# MOBI / AZW3 / PDB Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let single-file import accept MOBI, AZW3 and PDB by reading metadata/text through Calibre's `ebook-meta`/`ebook-convert`, dispatching by file extension while leaving the EPUB path untouched.

**Architecture:** A new `analyze_book_for_import` dispatches by suffix: `.epub` keeps the existing stdlib path; `.mobi/.azw3/.pdb` use Calibre CLI tools. `analyze_epub_for_import` becomes a thin wrapper. The online lookup, scoring, AI resolver, duplicate detection and preview run on the same signal list as today and are not changed.

**Tech Stack:** Python 3.14 stdlib, `unittest`. Calibre CLI tools (`ebook-meta`, `ebook-convert`) invoked via the existing `run_command`. PySide6 for the UI layer.

## Global Constraints

- Calibre is assumed installed (the app is a Calibre support utility). No "Calibre absent" feature path.
- Do not change online lookup, candidate scoring, AI resolver, duplicate detection, or preview logic.
- Do not change `calibredb` write semantics; `calibredb add <path>` is already format-agnostic.
- EPUB path must stay byte-for-byte behaviorally identical (stdlib extraction, no subprocess).
- Author delimiter is `" & "`. Year is parsed with the existing `extract_year`.
- All new backend units must be testable without a real Calibre install (pure functions or injected runners).
- Tests run with: `python -m unittest discover -s tests`. Compile check: `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py`.
- One source of truth for supported tool formats: `EBOOK_TOOL_FORMATS`.

---

## File Structure

- `calibre_meta_edit.py` — backend: new constants, tool resolution, ebook-meta parser, metadata/text readers, signal-source generalization, format dispatch, epub wrapper.
- `calibre_meta_qt.py` — UI: file-picker filter from `EBOOK_TOOL_FORMATS`, resolve tool paths into analysis settings, relabel "Import EPUB" → "Import knihy".
- `tests/test_calibre_meta_edit.py` — backend tests (new `BookImportFormatTests` class).
- `tests/test_calibre_meta_qt.py` — UI tests (filter helper; updated tooltip assertion).

Phase 1 = backend (Tasks 1–6). Phase 2 = UI (Tasks 7–8). Each task commits on its own; the two phases map to the approved "2 commits" — squash per phase before merge if a 2-commit history is wanted.

---

### Task 1: Tool formats constant + tool resolution

**Files:**
- Modify: `calibre_meta_edit.py` (near `CALIBREDB_FALLBACK`, line 38, and near `find_calibredb`, line 3024)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Produces:
  - `EBOOK_TOOL_FORMATS: set[str]` = `{".mobi", ".azw3", ".pdb"}`
  - `find_ebook_tool(name: str, which_func: Callable[[str], str | None] = shutil.which, exists_func: Callable[[str], bool] | None = None) -> str | None`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_calibre_meta_edit.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: FAIL with `AttributeError: module 'calibre_meta_edit' has no attribute 'EBOOK_TOOL_FORMATS'`

- [ ] **Step 3: Write minimal implementation**

After `CALIBREDB_FALLBACK = r"C:\Program Files\Calibre2\calibredb.exe"` (line 38) add:

```python
# Jeden zdroj pravdy: pripony co umime nacist pres Calibre nastroje (ebook-meta/convert).
EBOOK_TOOL_FORMATS = {".mobi", ".azw3", ".pdb"}
```

After `find_calibredb` (ends line 3032) add:

```python
def find_ebook_tool(
    name: str,
    which_func: Callable[[str], str | None] = shutil.which,
    exists_func: Callable[[str], bool] | None = None,
) -> str | None:
    """Najde Calibre CLI nastroj (ebook-meta/ebook-convert) stejne jako calibredb.

    Nejdriv PATH (which), pak sourozenec ve slozce s calibredb fallbackem.
    Vrati None kdyz neni - volajici to resi ciste, nepada.
    """
    found = which_func(name)
    if found:
        return found
    exists = exists_func or (lambda path: Path(path).exists())
    sibling = str(Path(CALIBREDB_FALLBACK).with_name(name + ".exe"))
    return sibling if exists(sibling) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Add ebook tool format set and tool resolver"
```

---

### Task 2: Pure ebook-meta output parser

**Files:**
- Modify: `calibre_meta_edit.py` (near `read_epub_metadata`, after line 333)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `EpubMetadata` (dataclass, fields `title, authors, language, publisher, published_year`), `extract_year(text) -> str`.
- Produces: `parse_ebook_meta_output(text: str) -> EpubMetadata`

- [ ] **Step 1: Write the failing test**

Add to `BookImportFormatTests`:

```python
    def test_parse_ebook_meta_full(self):
        text = (
            "Title               : Nadace\n"
            "Author(s)           : Isaac Asimov [Asimov, Isaac]\n"
            "Publisher           : Argo\n"
            "Languages           : ces\n"
            "Published           : 1951-06-01T00:00:00+00:00\n"
        )
        meta = cme.parse_ebook_meta_output(text)
        self.assertEqual(meta.title, "Nadace")
        self.assertEqual(meta.authors, "Isaac Asimov")
        self.assertEqual(meta.publisher, "Argo")
        self.assertEqual(meta.language, "ces")
        self.assertEqual(meta.published_year, "1951")

    def test_parse_ebook_meta_multiple_authors_keep_delimiter(self):
        text = "Author(s)           : Jules Verne & H. G. Wells\n"
        meta = cme.parse_ebook_meta_output(text)
        self.assertEqual(meta.authors, "Jules Verne & H. G. Wells")

    def test_parse_ebook_meta_partial_leaves_blanks(self):
        meta = cme.parse_ebook_meta_output("Title               : Solaris\n")
        self.assertEqual(meta.title, "Solaris")
        self.assertEqual(meta.authors, "")
        self.assertEqual(meta.publisher, "")

    def test_parse_ebook_meta_empty(self):
        meta = cme.parse_ebook_meta_output("")
        self.assertEqual(meta, cme.EpubMetadata())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: FAIL with `AttributeError: ... 'parse_ebook_meta_output'`

- [ ] **Step 3: Write minimal implementation**

After `read_epub_metadata` (ends line 333) add:

```python
def parse_ebook_meta_output(text: str) -> EpubMetadata:
    """Prevede vypis 'ebook-meta <soubor>' na EpubMetadata.

    Cte radky tvaru 'Label : hodnota'. Nezname/chybejici labely ignoruje.
    U autoru odstrani razici tvar v hranatych zavorkach (napr. '[Asimov, Isaac]').
    Cista funkce - zadny subprocess, snadno testovatelna.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z()/ ]+?)\s*:\s*(.*)$", line)
        if not match:
            continue
        label = match.group(1).strip().lower()
        value = match.group(2).strip()
        if label and value and label not in fields:
            fields[label] = value
    authors = re.sub(r"\s*\[[^\]]*\]", "", fields.get("author(s)", "")).strip()
    language = fields.get("languages", "").split(",")[0].split("&")[0].strip()
    return EpubMetadata(
        title=fields.get("title", ""),
        authors=authors,
        language=language,
        publisher=fields.get("publisher", ""),
        published_year=extract_year(fields.get("published", "")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Parse ebook-meta output into EpubMetadata"
```

---

### Task 3: Read metadata via ebook-meta (runner-injected)

**Files:**
- Modify: `calibre_meta_edit.py` (after `parse_ebook_meta_output`)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `parse_ebook_meta_output`, `CommandResult(returncode, stdout, stderr)`, `run_command`.
- Produces: `read_book_metadata_with_ebook_meta(path: str | Path, ebook_meta_path: str, runner: Callable[[Sequence[str]], CommandResult] = run_command) -> EpubMetadata`

- [ ] **Step 1: Write the failing test**

Add to `BookImportFormatTests`:

```python
    def test_read_metadata_runs_ebook_meta_and_parses(self):
        calls = []

        def fake_runner(args):
            calls.append(args)
            return cme.CommandResult(0, "Title               : Mlha\n", "")

        meta = cme.read_book_metadata_with_ebook_meta("kniha.mobi", "ebook-meta", runner=fake_runner)
        self.assertEqual(meta.title, "Mlha")
        self.assertEqual(calls[0], ["ebook-meta", "kniha.mobi"])

    def test_read_metadata_nonzero_exit_returns_empty(self):
        meta = cme.read_book_metadata_with_ebook_meta(
            "x.mobi", "ebook-meta", runner=lambda args: cme.CommandResult(1, "", "boom")
        )
        self.assertEqual(meta, cme.EpubMetadata())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: FAIL with `AttributeError: ... 'read_book_metadata_with_ebook_meta'`

- [ ] **Step 3: Write minimal implementation**

```python
def read_book_metadata_with_ebook_meta(
    path: str | Path,
    ebook_meta_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
) -> EpubMetadata:
    """Spusti 'ebook-meta <soubor>' a vrati metadata.

    Pri nenulovem navratu (rozbity/neznamy soubor) vrati prazdne metadata -
    import jede dal na jmenu souboru + online (chybejici metadata neni pad).
    """
    result = runner([ebook_meta_path, str(path)])
    if result.returncode != 0:
        return EpubMetadata()
    return parse_ebook_meta_output(result.stdout)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Read book metadata via ebook-meta"
```

---

### Task 4: Extract body text via ebook-convert (runner-injected)

**Files:**
- Modify: `calibre_meta_edit.py` (after `read_book_metadata_with_ebook_meta`)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `CommandResult`, `run_command`, `tempfile` (already imported, line 15).
- Produces: `extract_book_start_text_with_convert(path: str | Path, ebook_convert_path: str, runner: Callable[[Sequence[str]], CommandResult] = run_command, limit: int = 5000) -> str`

- [ ] **Step 1: Write the failing test**

Add to `BookImportFormatTests`:

```python
    def test_extract_text_via_convert_reads_output_file(self):
        captured = {}

        def fake_runner(args):
            # args: [ebook_convert_path, src, out_txt]
            captured["args"] = args
            Path(args[2]).write_text("Zacatek knihy " * 100, encoding="utf-8")
            return cme.CommandResult(0, "", "")

        text = cme.extract_book_start_text_with_convert(
            "kniha.mobi", "ebook-convert", runner=fake_runner, limit=50
        )
        self.assertEqual(len(text), 50)
        self.assertEqual(captured["args"][0], "ebook-convert")
        self.assertEqual(captured["args"][1], "kniha.mobi")
        self.assertTrue(captured["args"][2].endswith(".txt"))

    def test_extract_text_via_convert_failure_returns_empty(self):
        text = cme.extract_book_start_text_with_convert(
            "x.mobi", "ebook-convert", runner=lambda args: cme.CommandResult(1, "", "boom")
        )
        self.assertEqual(text, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: FAIL with `AttributeError: ... 'extract_book_start_text_with_convert'`

- [ ] **Step 3: Write minimal implementation**

```python
def extract_book_start_text_with_convert(
    path: str | Path,
    ebook_convert_path: str,
    runner: Callable[[Sequence[str]], CommandResult] = run_command,
    limit: int = 5000,
) -> str:
    """Prevede knihu na docasny .txt pres 'ebook-convert' a vrati prvnich `limit` znaku.

    Pri selhani konverze vrati "" - text je jen slaby signal, import jede dal.
    Docasny soubor vzdy uklidi.
    """
    handle, tmp_path = tempfile.mkstemp(suffix=".txt")
    os.close(handle)
    try:
        result = runner([ebook_convert_path, str(path), tmp_path])
        if result.returncode != 0:
            return ""
        return Path(tmp_path).read_text(encoding="utf-8", errors="replace")[:limit]
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
```

Note: `os` is already imported (used at `os.chdir(APP_DIR)`). If a quick `grep -n "^import os" calibre_meta_edit.py` shows it missing, add `import os` with the other stdlib imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Extract book start text via ebook-convert"
```

---

### Task 5: Generalize metadata-signal source

**Files:**
- Modify: `calibre_meta_edit.py` (`import_signal_from_epub_metadata` line 429, `choose_initial_import_preview` line 509)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Produces:
  - `METADATA_SIGNAL_SOURCES: set[str]` = `{"epub-metadata", "ebook-meta"}`
  - `import_signal_from_book_metadata(metadata: EpubMetadata, source: str = "ebook-meta") -> ImportSourceSignal`
- Consumes (unchanged signature, new internal behavior): `choose_initial_import_preview(signals) -> ImportPreview` now finds the metadata signal by membership in `METADATA_SIGNAL_SOURCES`.

- [ ] **Step 1: Write the failing test**

Add to `BookImportFormatTests`:

```python
    def test_ebook_metadata_signal_feeds_preview_publisher_and_year(self):
        signal = cme.import_signal_from_book_metadata(
            cme.EpubMetadata(title="Nadace", authors="Isaac Asimov", publisher="Argo", published_year="1951")
        )
        self.assertEqual(signal.source, "ebook-meta")
        preview = cme.choose_initial_import_preview([signal])
        self.assertEqual(preview.publisher, "Argo")
        self.assertEqual(preview.published_year, "1951")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: FAIL with `AttributeError: ... 'import_signal_from_book_metadata'`

- [ ] **Step 3: Write minimal implementation**

Replace `import_signal_from_epub_metadata` (lines 429-438) with a generic builder plus a thin epub alias, and add the constant just above:

```python
METADATA_SIGNAL_SOURCES = {"epub-metadata", "ebook-meta"}


def import_signal_from_book_metadata(metadata: EpubMetadata, source: str = "ebook-meta") -> ImportSourceSignal:
    return ImportSourceSignal(
        source=source,
        title=metadata.title,
        authors=metadata.authors,
        language=metadata.language,
        publisher=metadata.publisher,
        published_year=metadata.published_year,
        confidence=60 if metadata.title and metadata.authors else 30,
    )


def import_signal_from_epub_metadata(metadata: EpubMetadata) -> ImportSourceSignal:
    return import_signal_from_book_metadata(metadata, source="epub-metadata")
```

In `choose_initial_import_preview` (line 511) change the metadata-signal lookup:

```python
    metadata_signal = next((signal for signal in signals if signal.source in METADATA_SIGNAL_SOURCES), None)
```

- [ ] **Step 4: Run tests to verify they pass (and EPUB unchanged)**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: PASS
Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py`
Expected: OK (existing epub-metadata tests still pass)

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Generalize metadata signal source for non-epub formats"
```

---

### Task 6: Format dispatch + epub wrapper

**Files:**
- Modify: `calibre_meta_edit.py` (`analyze_epub_for_import` line 621)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `read_epub_metadata`, `extract_epub_start_text`, `read_book_metadata_with_ebook_meta`, `extract_book_start_text_with_convert`, `import_signal_from_book_metadata`, `import_signal_from_epub_text`, `import_signal_from_path`, `score_import_candidates`, `lookup_import_candidates`, `resolve_import_candidate_with_ai`, `choose_initial_import_preview`, `import_preview_from_candidate`, `EBOOK_TOOL_FORMATS`.
- Produces:
  - `analyze_book_for_import(path, library, settings, online_lookup=None, ai_resolver=None, epub_metadata_reader=read_epub_metadata, epub_text_reader=extract_epub_start_text, ebook_metadata_reader=read_book_metadata_with_ebook_meta, ebook_text_reader=extract_book_start_text_with_convert) -> ImportAnalysis`
  - `analyze_epub_for_import(path, library, settings, online_lookup=None, ai_resolver=None) -> ImportAnalysis` (now delegates to `analyze_book_for_import`)
  - Settings keys read on the ebook-tool path: `"ebook_meta_path"`, `"ebook_convert_path"`, plus existing `"epub_text_limit"`.

- [ ] **Step 1: Write the failing test**

Add to `BookImportFormatTests`:

```python
    def test_dispatch_routes_mobi_through_ebook_tools(self):
        used = {}

        def meta_reader(path, settings):
            used["meta_path"] = path
            return cme.EpubMetadata(title="Nadace", authors="Isaac Asimov")

        def text_reader(path, settings):
            used["text_path"] = path
            return "zacatek"

        analysis = cme.analyze_book_for_import(
            "kniha.mobi",
            library="B:\\",
            settings={},
            online_lookup=lambda signals: [],
            ebook_metadata_reader=lambda path, ebook_meta_path, runner=None: meta_reader(path, None),
            ebook_text_reader=lambda path, ebook_convert_path, runner=None, limit=5000: text_reader(path, None),
        )
        self.assertEqual(used["meta_path"], "kniha.mobi")
        self.assertEqual(analysis.preview.title, "Nadace")
        self.assertEqual(analysis.preview.authors, "Isaac Asimov")

    def test_dispatch_unsupported_suffix_raises(self):
        with self.assertRaises(ValueError):
            cme.analyze_book_for_import("kniha.cbz", library="B:\\", settings={}, online_lookup=lambda s: [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: FAIL with `AttributeError: ... 'analyze_book_for_import'`

- [ ] **Step 3: Write minimal implementation**

Replace `analyze_epub_for_import` (lines 621-651) with:

```python
def analyze_book_for_import(
    path: str | Path,
    library: str | Path,
    settings: dict[str, object],
    online_lookup: Callable[[Sequence[ImportSourceSignal]], list[ImportCandidate]] | None = None,
    ai_resolver: object | None = None,
    epub_metadata_reader: Callable[..., EpubMetadata] = read_epub_metadata,
    epub_text_reader: Callable[..., str] = extract_epub_start_text,
    ebook_metadata_reader: Callable[..., EpubMetadata] = read_book_metadata_with_ebook_meta,
    ebook_text_reader: Callable[..., str] = extract_book_start_text_with_convert,
) -> ImportAnalysis:
    """Analyza importu podle pripony souboru.

    .epub jede stdlib cestou (beze zmeny). .mobi/.azw3/.pdb pres Calibre nastroje.
    Jine pripony vyhodi ValueR error - picker je nepusti, tady jen ciste selze.
    Spolecna cast (online lookup, scoring, AI, preview) je pro vsechny stejna.
    """
    book_path = Path(path)
    suffix = book_path.suffix.lower()
    limit = int(settings.get("epub_text_limit", 5000) or 5000)
    if suffix == ".epub":
        metadata = epub_metadata_reader(book_path)
        text = epub_text_reader(book_path, limit=limit)
    elif suffix in EBOOK_TOOL_FORMATS:
        metadata = ebook_metadata_reader(book_path, str(settings.get("ebook_meta_path", "ebook-meta")))
        text = ebook_text_reader(book_path, str(settings.get("ebook_convert_path", "ebook-convert")), limit=limit)
    else:
        raise ValueError("unsupported-format")
    signals = [
        import_signal_from_book_metadata(metadata, source="epub-metadata" if suffix == ".epub" else "ebook-meta"),
        import_signal_from_epub_text(text),
        import_signal_from_path(book_path),
    ]
    try:
        candidates = score_import_candidates(signals, online_lookup(signals)) if online_lookup else lookup_import_candidates(signals)
    except Exception:
        candidates = []
    recommended = resolve_import_candidate_with_ai(signals, candidates, ai_resolver)
    fallback_preview = choose_initial_import_preview(signals)
    preview = import_preview_from_candidate(recommended, fallback_preview)
    return ImportAnalysis(
        epub_path=str(book_path),
        signals=signals,
        candidates=candidates,
        recommended=recommended,
        duplicates=[],
        preview=preview,
        messages=[],
    )


def analyze_epub_for_import(
    path: str | Path,
    library: str | Path,
    settings: dict[str, object],
    online_lookup: Callable[[Sequence[ImportSourceSignal]], list[ImportCandidate]] | None = None,
    ai_resolver: object | None = None,
) -> ImportAnalysis:
    """Zpetne kompatibilni vstup pro EPUB; deleguje na analyze_book_for_import."""
    return analyze_book_for_import(path, library, settings, online_lookup, ai_resolver)
```

Note: the `ebook_metadata_reader`/`ebook_text_reader` defaults take `(path, tool_path)` and `(path, tool_path, limit=...)`; the dispatcher calls them positionally with the tool path so the test's lambdas match.

- [ ] **Step 4: Run tests (routing + full backend back-compat)**

Run: `python -m unittest tests.test_calibre_meta_edit.BookImportFormatTests -v`
Expected: PASS
Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py`
Expected: OK (existing `analyze_epub_for_import` tests still pass via the wrapper)

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Dispatch book import by format, keep epub wrapper"
```

---

### Task 7: UI — picker filter + tool paths into settings

**Files:**
- Modify: `calibre_meta_qt.py` (`_build_import_analyze_callable` line 1693, `_choose_epub_file` line 1705; add a pure filter helper near the other module helpers, e.g. after `asset_icon_path`)
- Test: `tests/test_calibre_meta_qt.py`

**Interfaces:**
- Consumes: `cme.EBOOK_TOOL_FORMATS`, `cme.find_ebook_tool`.
- Produces: `book_import_file_filter() -> str` (module-level, pure, testable).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_calibre_meta_qt.py` (a new small test method in an existing suitable test class, or a new class):

```python
    def test_book_import_filter_lists_all_supported_formats(self):
        import calibre_meta_qt as qt

        filter_text = qt.book_import_file_filter()
        for pattern in ("*.epub", "*.mobi", "*.azw3", "*.pdb"):
            self.assertIn(pattern, filter_text)
        self.assertIn("Vsechny soubory (*.*)", filter_text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_qt.py`
Expected: FAIL with `AttributeError: module 'calibre_meta_qt' has no attribute 'book_import_file_filter'`

- [ ] **Step 3: Write minimal implementation**

Add module-level helper (after `asset_icon_path`):

```python
def book_import_file_filter() -> str:
    """Slozi filtr pro vyber knihy z podporovanych pripon (epub + Calibre nastroje)."""
    patterns = " ".join("*" + ext for ext in sorted({".epub", *cme.EBOOK_TOOL_FORMATS}))
    return f"Knihy ({patterns});;EPUB (*.epub);;Vsechny soubory (*.*)"
```

In `_choose_epub_file` (lines 1705-1712) use the helper and relabel the dialog title:

```python
        def _choose_epub_file(self) -> str:
            path, _filter = QFileDialog.getOpenFileName(
                self,
                "Vyber knihu k importu",
                "",
                book_import_file_filter(),
            )
            return path
```

In `_build_import_analyze_callable` (line 1702) add the tool paths to settings:

```python
            settings = {
                "epub_text_limit": ai_settings.get("text_limit", 5000),
                "ebook_meta_path": cme.find_ebook_tool("ebook-meta") or "ebook-meta",
                "ebook_convert_path": cme.find_ebook_tool("ebook-convert") or "ebook-convert",
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -p test_calibre_meta_qt.py`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_qt.py tests/test_calibre_meta_qt.py
git commit -m "Wire multi-format book picker and tool paths"
```

---

### Task 8: UI — relabel "Import EPUB" to "Import knihy"

**Files:**
- Modify: `calibre_meta_qt.py` (lines 395, 744, 1681, 1682, 1720, 1721, 1722, 1724, and any further `"Import EPUB"` message strings in `start_epub_import`/`finish_import_analysis`/`run_import_apply`)
- Modify test: `tests/test_calibre_meta_qt.py:1077`

**Interfaces:**
- None new. Pure string/label changes. Behavior, callbacks, signal connections, icon loading unchanged. Method name `_choose_epub_file` is kept (private, still patched by tests at lines 1157/1177).

- [ ] **Step 1: Update the tooltip assertion test first (it will fail until code changes)**

In `tests/test_calibre_meta_qt.py` line 1077 change:

```python
        self.assertEqual(window.import_button.toolTip(), "Import knihy")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_qt.py`
Expected: FAIL on the tooltip assertion (`'Import EPUB' != 'Import knihy'`)

- [ ] **Step 3: Relabel the user-visible strings**

In `calibre_meta_qt.py` replace the user-facing label text `Import EPUB` → `Import knihy` at these locations (leave the code comment on line 796 unchanged):

- line 395: `self.setWindowTitle("Import knihy")`
- line 744: toolbar button text `"Import knihy"`
- line 1681: `self.write_output(f"Import knihy: analyza {epub_path}...")`
- line 1682: `self.set_status("Import knihy: analyza")`
- line 1720: `self.write_output(f"Import knihy: CHYBA\n{message}")`
- line 1721: `self.set_status("Import knihy: CHYBA")`
- line 1722: `QMessageBox.warning(self, "Import knihy", message)`
- line 1724: `self.write_output("Import knihy: nahled pripraven")`

Then grep for any remaining occurrences and update the user-facing ones:

```bash
grep -n "Import EPUB" calibre_meta_qt.py
```

Update every match that is a displayed string (status text, write_output, QMessageBox title, set_status) to `Import knihy`. Do not change the comment on line 796.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -p test_calibre_meta_qt.py`
Expected: OK
Run: `grep -n "Import EPUB" calibre_meta_qt.py`
Expected: only the code comment (line ~796) remains, no displayed strings.

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_qt.py tests/test_calibre_meta_qt.py
git commit -m "Relabel import UI to Import knihy"
```

---

## Final verification (after Task 8)

- [ ] Run full suite: `python -m unittest discover -s tests` → expect OK.
- [ ] Compile: `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py` → expect clean.
- [ ] `git status --short` → working tree clean.
- [ ] Manual smoke (optional, needs Calibre): import a real `.mobi` and `.pdb`, confirm preview shows metadata and apply adds the book.

## Self-Review notes

- Spec coverage: ebook-meta (Tasks 2,3), ebook-convert (Task 4), tool resolution (Task 1), `EBOOK_TOOL_FORMATS` single source (Tasks 1,7), dispatch + epub wrapper (Task 6), metadata-source generalization (Task 5), missing/corrupt metadata → empty metadata then filename/online (Tasks 3,6), unsupported suffix raises (Task 6), tool failure surfaced cleanly (existing qt error path reused, unchanged), UI picker from constant + tool paths (Task 7), relabel (Task 8), tests without real Calibre (all tasks via injected runners/pure functions). No gaps.
- Type consistency: `read_book_metadata_with_ebook_meta(path, ebook_meta_path, runner)` and `extract_book_start_text_with_convert(path, ebook_convert_path, runner, limit)` are called by `analyze_book_for_import` with the tool path positionally; the routing test injects lambdas with matching positional signatures. `import_signal_from_book_metadata(metadata, source)` used in Task 5 and Task 6 consistently.
- Out of scope confirmed untouched: online lookup, scoring, AI resolver, duplicates, `apply_import_preview` semantics.
