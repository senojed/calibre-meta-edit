# AI Text Extraction for Import Identity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let local AI read a book's opening text, extract the real title/author, and use it as the most trusted identity source for the import search query and preview.

**Architecture:** Add an `ai-text` signal produced by a new extractor role on the existing Ollama resolver. Title/author selection and preview honor an explicit source-priority (ai-text > metadata > filename), so junk filenames and series codes no longer poison the search query. When AI is disabled or fails, no `ai-text` signal exists and behavior is unchanged.

**Tech Stack:** Python 3, stdlib `unittest`, existing Ollama HTTP integration (`urllib`), Calibre `ebook-convert` for text extraction.

## Global Constraints

- All backend changes live in `calibre_meta_edit.py`. No UI change needed: the Qt layer already builds and passes the resolver into `analyze_book_for_import` (see `calibre_meta_qt.py:1705`, `:1713`).
- Do NOT change the default Ollama model in code. Model choice is a user settings concern.
- Preserve the locked clean-beats-junk behavior: junk titles (`is_junk_signal`, i.e. `_` in title) and empty titles must never win selection or preview.
- Tests run via: `python -m unittest discover -s tests` (full) or `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k <name> -v` (single).
- py_compile gate: `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py`.
- New tests go in `tests/test_calibre_meta_edit.py`, in a new class `AITextExtractionTests`.

---

### Task 1: Source-priority selection key

Add the priority table and a combined selection key used to choose title/author/preview. The key puts junk/empty signals at the bottom (preserving locked behavior), then ranks by source trust, then by existing quality.

**Files:**
- Modify: `calibre_meta_edit.py` (add near `_best_normalized_title`, ~line 829)
- Test: `tests/test_calibre_meta_edit.py` (new class `AITextExtractionTests`)

**Interfaces:**
- Consumes: `signal_preview_quality(signal) -> tuple[int,int,int,int]` (existing), `ImportSourceSignal` (existing).
- Produces:
  - `_SOURCE_PRIORITY: dict[str, int]`
  - `_source_priority(signal: ImportSourceSignal) -> int`
  - `_import_selection_key(signal: ImportSourceSignal) -> tuple[int, int, int, int, int]`

- [ ] **Step 1: Write the failing test**

```python
class AITextExtractionTests(unittest.TestCase):
    def test_selection_key_junk_ranks_below_clean(self):
        junk = cme.ImportSourceSignal(source="ebook-meta", title="A_b-c", authors="X")
        clean = cme.ImportSourceSignal(source="filename", title="Mort", authors="")
        self.assertLess(cme._import_selection_key(junk), cme._import_selection_key(clean))

    def test_selection_key_ai_text_beats_metadata_when_both_clean(self):
        ai = cme.ImportSourceSignal(source="ai-text", title="Mort", authors="Terry Pratchett", confidence=90)
        meta = cme.ImportSourceSignal(source="ebook-meta", title="Mort", authors="Terry Pratchett", confidence=60)
        self.assertGreater(cme._import_selection_key(ai), cme._import_selection_key(meta))

    def test_selection_key_priority_beats_completeness(self):
        # ai-text with title only must outrank filename with title+author
        ai_title_only = cme.ImportSourceSignal(source="ai-text", title="Mort", authors="", confidence=90)
        filename_full = cme.ImportSourceSignal(source="filename", title="UZ-20-Mort", authors="Terry Pratchett", confidence=30)
        self.assertGreater(cme._import_selection_key(ai_title_only), cme._import_selection_key(filename_full))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_selection_key -v`
Expected: FAIL with `AttributeError: module 'calibre_meta_edit' has no attribute '_import_selection_key'`

- [ ] **Step 3: Write minimal implementation**

Add directly above `def _best_normalized_title` (~line 829):

```python
# Priorita zdroju pro vyber nazvu/autora a nahledu.
# Vyssi cislo = duveryhodnejsi zdroj. Text z AI extrakce je nejjistejsi,
# pak metadata v souboru, pak nazev souboru/slozky, pak holy text.
_SOURCE_PRIORITY = {
    "ai-text": 4,
    "ebook-meta": 3,
    "epub-metadata": 3,
    "filename": 2,
    "epub-text": 1,
}


def _source_priority(signal: ImportSourceSignal) -> int:
    return _SOURCE_PRIORITY.get(signal.source, 0)


def _import_selection_key(signal: ImportSourceSignal) -> tuple[int, int, int, int, int]:
    """Klic pro vyber nejlepsiho signalu.

    Poradi vah: nejdriv ne-junk (junk/prazdny nikdy nevyhraje), pak priorita
    zdroje (ai-text > metadata > nazev souboru), pak uplnost, cistota, confidence.
    """
    not_junk, completeness, clean_bonus, confidence = signal_preview_quality(signal)
    return (not_junk, _source_priority(signal), completeness, clean_bonus, confidence)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_selection_key -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_calibre_meta_edit.py calibre_meta_edit.py
git commit -m "Add source-priority selection key for import signals"
```

---

### Task 2: Wire selection key into title/author/preview

Make query building and preview use `_import_selection_key`. This is where the priority actually takes effect, while keeping junk/empty out.

**Files:**
- Modify: `calibre_meta_edit.py:829-833` (`_best_normalized_title`), `:836-840` (`_best_normalized_authors`), `:628-636` (`choose_initial_import_preview`)
- Test: `tests/test_calibre_meta_edit.py` (`AITextExtractionTests`)

**Interfaces:**
- Consumes: `_import_selection_key` (Task 1), `is_junk_signal`, `METADATA_SIGNAL_SOURCES`, `ImportPreview`, `normalize_author_display_names` (all existing).
- Produces: updated `_best_normalized_title(signals) -> str`, `_best_normalized_authors(signals) -> str`, `choose_initial_import_preview(signals) -> ImportPreview` (same signatures).

- [ ] **Step 1: Write the failing test**

```python
    def test_best_title_prefers_ai_over_junk_filename(self):
        signals = [
            cme.ImportSourceSignal(source="filename", title="UZ-20-Hrrr na ne", authors="Terry Pratchett", confidence=30),
            cme.ImportSourceSignal(source="ai-text", title="Hrr na ně", authors="Terry Pratchett", confidence=90),
        ]
        self.assertEqual(cme._best_normalized_title(signals), "Hrr na ně")

    def test_preview_prefers_ai_text_signal(self):
        signals = [
            cme.ImportSourceSignal(source="ebook-meta", title="_asn_ zem_plocha - 21", authors="Neznámý", confidence=60),
            cme.ImportSourceSignal(source="filename", title="UZ-20-Hrrr na ne", authors="", confidence=30),
            cme.ImportSourceSignal(source="ai-text", title="Hrr na ně", authors="Terry Pratchett", confidence=90),
        ]
        preview = cme.choose_initial_import_preview(signals)
        self.assertEqual(preview.title, "Hrr na ně")
        self.assertEqual(preview.authors, "Terry Pratchett")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_best_title_prefers_ai -v`
Expected: FAIL — returns `UZ-20-Hrrr na ne` (filename still wins under old quality-only ranking)

- [ ] **Step 3: Write minimal implementation**

Replace `_best_normalized_title` and `_best_normalized_authors` bodies:

```python
def _best_normalized_title(signals: Sequence[ImportSourceSignal]) -> str:
    title_signals = [signal for signal in signals if signal.title.strip()]
    if not title_signals:
        return ""
    return max(title_signals, key=_import_selection_key).title


def _best_normalized_authors(signals: Sequence[ImportSourceSignal]) -> str:
    author_signals = [signal for signal in signals if signal.authors.strip()]
    if not author_signals:
        return ""
    return max(author_signals, key=_import_selection_key).authors
```

Replace the `preview_signal` line in `choose_initial_import_preview` (line 629):

```python
    preview_signal = max(signals, key=_import_selection_key) if signals else ImportSourceSignal(source="")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -v`
Expected: PASS, including the previously locked `test_preview_and_search_prefer_clean_over_junk` and `test_clean_signal_outranks_junk`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_calibre_meta_edit.py calibre_meta_edit.py
git commit -m "Select title, author and preview by source priority"
```

---

### Task 3: AIBookIdentity type and ai-text signal constructor

Define the extractor's return type and the helper that turns it into an `ai-text` signal (or nothing when title is empty).

**Files:**
- Modify: `calibre_meta_edit.py` (add `AIBookIdentity` after `ImportSourceSignal`, ~line 196; add constructor near `import_signal_from_epub_text`, ~line 553)
- Test: `tests/test_calibre_meta_edit.py` (`AITextExtractionTests`)

**Interfaces:**
- Consumes: `ImportSourceSignal` (existing).
- Produces:
  - `@dataclass(frozen=True) class AIBookIdentity: title: str = ""; author: str = ""; confidence: int = 0`
  - `import_signal_from_ai_extraction(identity: AIBookIdentity) -> ImportSourceSignal | None`

- [ ] **Step 1: Write the failing test**

```python
    def test_ai_signal_built_from_identity(self):
        identity = cme.AIBookIdentity(title="Hrr na ně", author="Terry Pratchett", confidence=88)
        signal = cme.import_signal_from_ai_extraction(identity)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.source, "ai-text")
        self.assertEqual(signal.title, "Hrr na ně")
        self.assertEqual(signal.authors, "Terry Pratchett")
        self.assertEqual(signal.confidence, 88)

    def test_ai_signal_none_when_title_empty(self):
        self.assertIsNone(cme.import_signal_from_ai_extraction(cme.AIBookIdentity(title="   ", author="X")))

    def test_ai_signal_confidence_clamped(self):
        signal = cme.import_signal_from_ai_extraction(cme.AIBookIdentity(title="T", confidence=999))
        self.assertEqual(signal.confidence, 100)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_ai_signal -v`
Expected: FAIL with `AttributeError: module 'calibre_meta_edit' has no attribute 'AIBookIdentity'`

- [ ] **Step 3: Write minimal implementation**

Add after the `ImportSourceSignal` dataclass (~line 196):

```python
@dataclass(frozen=True)
class AIBookIdentity:
    """Vysledek AI extrakce nazvu a autora z textu knihy."""
    title: str = ""
    author: str = ""
    confidence: int = 0
```

Add near `import_signal_from_epub_text` (~line 553):

```python
def import_signal_from_ai_extraction(identity: AIBookIdentity) -> ImportSourceSignal | None:
    """Z AI extrakce udela signal s nejvyssi prioritou; bez nazvu vrati None."""
    if not identity.title.strip():
        return None
    return ImportSourceSignal(
        source="ai-text",
        title=identity.title.strip(),
        authors=identity.author.strip(),
        confidence=max(0, min(identity.confidence, 100)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_ai_signal -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_calibre_meta_edit.py calibre_meta_edit.py
git commit -m "Add AIBookIdentity and ai-text signal constructor"
```

---

### Task 4: Extractor role on the resolvers

Add an `extract(text) -> AIBookIdentity` method to both resolver classes. `DisabledAIResolver` returns empty; `OllamaAIResolver` queries Ollama and parses JSON, failing silently to empty.

**Files:**
- Modify: `calibre_meta_edit.py:652-656` (`DisabledAIResolver`), `:659-708` (`OllamaAIResolver`)
- Test: `tests/test_calibre_meta_edit.py` (`AITextExtractionTests`)

**Interfaces:**
- Consumes: `AIBookIdentity` (Task 3), existing `OllamaAIResolver.__init__`/`requester` plumbing.
- Produces: `DisabledAIResolver.extract(text: str) -> AIBookIdentity`, `OllamaAIResolver.extract(text: str) -> AIBookIdentity`.

- [ ] **Step 1: Write the failing test**

```python
    def test_disabled_resolver_extract_returns_empty(self):
        identity = cme.DisabledAIResolver().extract("Terry Pratchett\nHRR NA NĚ!")
        self.assertEqual(identity.title, "")

    def test_ollama_resolver_extract_parses_json(self):
        def fake_requester(url, payload, headers):
            return json.dumps({"response": json.dumps({"title": "Hrr na ně", "author": "Terry Pratchett", "confidence": 91})})
        resolver = cme.OllamaAIResolver("dummy", requester=fake_requester)
        identity = resolver.extract("Terry Pratchett\nHRR NA NĚ!")
        self.assertEqual(identity.title, "Hrr na ně")
        self.assertEqual(identity.author, "Terry Pratchett")
        self.assertEqual(identity.confidence, 91)

    def test_ollama_resolver_extract_handles_bad_json(self):
        def fake_requester(url, payload, headers):
            return "not json"
        identity = cme.OllamaAIResolver("dummy", requester=fake_requester).extract("text")
        self.assertEqual(identity.title, "")
```

Add `import json` at the top of the test module if not already present (it likely is — check the existing imports first).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_ollama_resolver_extract -v`
Expected: FAIL with `AttributeError: 'OllamaAIResolver' object has no attribute 'extract'`

- [ ] **Step 3: Write minimal implementation**

In `DisabledAIResolver`, add:

```python
    def extract(self, text: str) -> AIBookIdentity:
        return AIBookIdentity()
```

In `OllamaAIResolver`, add:

```python
    def extract(self, text: str) -> AIBookIdentity:
        prompt = {
            "task": "Extract the real book title and author from this book opening text. The real title and author usually appear near the top, before any filename-derived noise. Return JSON only: {\"title\":\"...\",\"author\":\"...\",\"confidence\":0-100}.",
            "text": text[:4000],
        }
        try:
            raw = self.requester(
                "http://127.0.0.1:11434/api/generate",
                json.dumps({"model": self.model, "prompt": json.dumps(prompt, ensure_ascii=False), "stream": False}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
            data = json.loads(raw)
            answer = json.loads(str(data.get("response", "{}")))
            return AIBookIdentity(
                title=str(answer.get("title", "")),
                author=str(answer.get("author", "")),
                confidence=int(answer.get("confidence", 0) or 0),
            )
        except Exception:
            return AIBookIdentity()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_resolver_extract -v`
Then: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k extract -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_calibre_meta_edit.py calibre_meta_edit.py
git commit -m "Add AI text-extraction method to import resolvers"
```

---

### Task 5: Wire extractor into analyze_book_for_import

Call the extractor on the already-extracted start text and prepend the `ai-text` signal when present. Add a guard helper that tolerates resolvers without `extract` and empty text.

**Files:**
- Modify: `calibre_meta_edit.py` (add `extract_ai_identity` helper near `resolve_import_candidate_with_ai`, ~line 738; modify the signal list build in `analyze_book_for_import`, `:768-772`)
- Test: `tests/test_calibre_meta_edit.py` (`AITextExtractionTests`)

**Interfaces:**
- Consumes: `AIBookIdentity` (Task 3), `import_signal_from_ai_extraction` (Task 3), `analyze_book_for_import` signature (existing, takes `ai_resolver`, `epub_text_reader`, `ebook_text_reader`, etc.).
- Produces: `extract_ai_identity(text: str, resolver: object | None) -> AIBookIdentity`; `analyze_book_for_import` now inserts an `ai-text` signal at index 0 when extraction yields a title.

- [ ] **Step 1: Write the failing test**

```python
    def test_analyze_inserts_ai_text_signal(self):
        class FakeResolver:
            def extract(self, text):
                return cme.AIBookIdentity(title="Hrr na ně", author="Terry Pratchett", confidence=90)
            def resolve(self, signals, candidates):
                return None
        meta = cme.EpubMetadata(title="_asn_ zem_plocha - 21", authors="Neznámý")
        analysis = cme.analyze_book_for_import(
            r"E:\Knihy\UZ-20-Hrrr_na_ne.pdb",
            "B:/",
            {"ebook_meta_path": "x", "ebook_convert_path": "x"},
            online_lookup=lambda signals: [],
            ai_resolver=FakeResolver(),
            ebook_metadata_reader=lambda path, tool: meta,
            ebook_text_reader=lambda path, tool, limit=5000: "Terry Pratchett\nHRR NA NĚ!\n...",
        )
        ai_signals = [s for s in analysis.signals if s.source == "ai-text"]
        self.assertEqual(len(ai_signals), 1)
        self.assertEqual(ai_signals[0].title, "Hrr na ně")
        self.assertEqual(analysis.preview.title, "Hrr na ně")

    def test_analyze_no_ai_signal_when_disabled(self):
        meta = cme.EpubMetadata(title="Mort", authors="Terry Pratchett")
        analysis = cme.analyze_book_for_import(
            r"E:\Knihy\Mort.pdb",
            "B:/",
            {"ebook_meta_path": "x", "ebook_convert_path": "x"},
            online_lookup=lambda signals: [],
            ai_resolver=cme.DisabledAIResolver(),
            ebook_metadata_reader=lambda path, tool: meta,
            ebook_text_reader=lambda path, tool, limit=5000: "some text",
        )
        self.assertFalse(any(s.source == "ai-text" for s in analysis.signals))
```

Note: confirm the exact `EpubMetadata` constructor fields before writing (read `calibre_meta_edit.py:198` area). Use only fields that exist; `title` and `authors` are required-or-defaulted.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_analyze_inserts_ai -v`
Expected: FAIL — no `ai-text` signal present

- [ ] **Step 3: Write minimal implementation**

Add helper near `resolve_import_candidate_with_ai` (~line 738):

```python
def extract_ai_identity(text: str, resolver: object | None) -> AIBookIdentity:
    """Bezpecne zavola AI extraktor; pri vypnute AI nebo chybe vrati prazdny vysledek."""
    extractor = getattr(resolver, "extract", None) if resolver else None
    if not callable(extractor) or not text.strip():
        return AIBookIdentity()
    try:
        result = extractor(text)
    except Exception:
        return AIBookIdentity()
    return result if isinstance(result, AIBookIdentity) else AIBookIdentity()
```

In `analyze_book_for_import`, replace the signal list build (lines 768-772):

```python
    signals = [
        import_signal_from_book_metadata(metadata, source="epub-metadata" if suffix == ".epub" else "ebook-meta"),
        import_signal_from_epub_text(text),
        import_signal_from_path(book_path),
    ]
    ai_signal = import_signal_from_ai_extraction(extract_ai_identity(text, ai_resolver))
    if ai_signal:
        signals.insert(0, ai_signal)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py -k test_analyze -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_calibre_meta_edit.py calibre_meta_edit.py
git commit -m "Insert ai-text signal into import analysis"
```

---

### Task 6: Full regression, compile, and merge readiness

Run the whole suite and the compile gate to confirm nothing regressed, then report.

**Files:**
- None (verification only)

**Interfaces:**
- Consumes: all prior tasks.
- Produces: green test suite + clean compile.

- [ ] **Step 1: Run the full test suite**

Run: `python -m unittest discover -s tests`
Expected: `OK`, count = previous total + the new `AITextExtractionTests` (roughly +13).

- [ ] **Step 2: Run the compile gate**

Run: `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py`
Expected: no output, exit 0.

- [ ] **Step 3: Confirm no UI wiring gap**

Read `calibre_meta_qt.py:1699-1713`. Confirm the resolver passed to `run_import_analysis` is the same object the extractor lives on (it is `OllamaAIResolver`/`DisabledAIResolver`). No code change expected; if the resolver is constructed differently, note it for review.

- [ ] **Step 4: Report**

Report branch, commits, changed files, test count, py_compile result, working-tree status. Do NOT merge to `main` without explicit approval (per project rules and CLAUDE.md).

---

## Self-Review

**Spec coverage:**
- AI extractor (spec "Components 1") → Task 4.
- `ai-text` signal (spec "Components 2") → Task 3.
- Explicit source priority / approach B (spec "Components 3") → Tasks 1, 2.
- Pipeline integration (spec) → Task 5.
- Fallback chain (spec table) → Task 4 (disabled/bad JSON → empty), Task 5 (`extract_ai_identity` guard + None signal), Task 2 (title-only → author from next priority via per-field selection).
- Success criteria (UZ-20 case, disabled = unchanged) → Tasks 2 and 5 tests.
- Model recommendation / out-of-scope → respected (no model change, no folder walk-up, no regex stripping).

**Placeholder scan:** none — every code step shows full code.

**Type consistency:** `AIBookIdentity(title, author, confidence)` used identically in Tasks 3, 4, 5. `_import_selection_key` returns a 5-tuple, consumed by `max(..., key=...)` in Task 2. `import_signal_from_ai_extraction` returns `ImportSourceSignal | None`, and Task 5 guards with `if ai_signal:`. Resolver method name `extract` consistent across Tasks 4 and 5.

**Note for implementer:** Tasks 3 and 5 say to confirm `EpubMetadata` constructor fields by reading the dataclass (~`calibre_meta_edit.py:198`) before writing test fixtures. Use only fields that exist.
