# Folder author + junk demotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When embedded metadata is junk, let a clean filename+folder signal win so the online search finds the right record.

**Architecture:** Two backend changes in `calibre_meta_edit.py`: `import_signal_from_path` derives the author from the parent folder when it looks like a person name; `signal_preview_quality` demotes signals whose title looks filename-derived (junk) below clean signals. Both feed the existing search/scoring/preview machinery unchanged.

**Tech Stack:** Python 3.14 stdlib, `unittest`.

## Global Constraints

- Backend only: `calibre_meta_edit.py` and `tests/test_calibre_meta_edit.py`. No UI, no search/scoring formula changes, no AI changes.
- Pure helpers, testable without network or Calibre.
- Folder name order is kept as-is (no first/last swap).
- Junk marker for phase 1: an underscore in the title.
- Must not change ordering among non-junk signals (EPUB/clean metadata unaffected).
- Tests: `python -m unittest discover -s tests`. Compile: `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py`.

---

## File Structure

- `calibre_meta_edit.py`
  - `_FOLDER_AUTHOR_STOPWORDS` + `folder_author_hint` (new, near `split_author_title_from_filename`, line ~486)
  - `import_signal_from_path` (modify, line ~489)
  - `is_junk_signal` (new, just before `signal_preview_quality`, line ~582)
  - `signal_preview_quality` (modify, line ~582)
- `tests/test_calibre_meta_edit.py` — new `FolderAuthorAndJunkTests` class.

---

### Task 1: `folder_author_hint` helper

**Files:**
- Modify: `calibre_meta_edit.py` (after `split_author_title_from_filename`, line 486)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `repair_filename_text(text) -> str`, `normalize_text(text) -> str` (both module-level; called at runtime so definition order does not matter).
- Produces: `_FOLDER_AUTHOR_STOPWORDS: set[str]`, `folder_author_hint(parent_name: str) -> str`.

- [ ] **Step 1: Write the failing test**

Add a new test class to `tests/test_calibre_meta_edit.py` (place it right before `class ImportDuplicateTests`):

```python
class FolderAuthorAndJunkTests(unittest.TestCase):
    def test_folder_author_hint_person_name(self):
        self.assertEqual(cme.folder_author_hint("Terry_Pratchett"), "Terry Pratchett")

    def test_folder_author_hint_keeps_order(self):
        self.assertEqual(cme.folder_author_hint("Pratchett_Terry"), "Pratchett Terry")

    def test_folder_author_hint_single_token_rejected(self):
        self.assertEqual(cme.folder_author_hint("Knihy"), "")

    def test_folder_author_hint_many_tokens_rejected(self):
        self.assertEqual(cme.folder_author_hint("e-knihy_cast_T_Z"), "")
        self.assertEqual(cme.folder_author_hint("J._R._R._Tolkien"), "")

    def test_folder_author_hint_stoplist_token_rejected(self):
        self.assertEqual(cme.folder_author_hint("Audio_Knihy"), "")

    def test_folder_author_hint_lowercase_rejected(self):
        self.assertEqual(cme.folder_author_hint("various authors"), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: FAIL with `AttributeError: module 'calibre_meta_edit' has no attribute 'folder_author_hint'`

- [ ] **Step 3: Write minimal implementation**

Insert after `split_author_title_from_filename` (ends line 486):

```python
# Obecne slozky co nejsou autor; porovnava se normalizovany token.
_FOLDER_AUTHOR_STOPWORDS = {
    "knihy", "kniha", "books", "book", "ebooks", "ebook", "audiobooks",
    "audioknihy", "kindle", "calibre", "library", "knihovna", "komiksy",
    "stahnute", "downloads", "temp", "tmp", "authors", "various",
}


def folder_author_hint(parent_name: str) -> str:
    """Vrati autora ze jmena slozky kdyz vypada jako jmeno osoby, jinak "".

    Konzervativni: presne dve slova, obe pismenna (vc. diakritiky a teckovych
    iniciel), zacinaji velkym pismenem, zadne stopword. Poradi jmeno/prijmeni
    nehadame - online nalez kanonicky tvar opravi.
    """
    repaired = repair_filename_text(parent_name)
    tokens = repaired.split()
    if len(tokens) != 2:
        return ""
    if {normalize_text(token) for token in tokens} & _FOLDER_AUTHOR_STOPWORDS:
        return ""
    for token in tokens:
        core = token.rstrip(".")
        if not core or not core[0].isupper() or not all(ch.isalpha() or ch == "." for ch in token):
            return ""
    return repaired
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Add folder_author_hint helper"
```

---

### Task 2: Use folder author in `import_signal_from_path`

**Files:**
- Modify: `calibre_meta_edit.py` (`import_signal_from_path`, line 489)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `folder_author_hint` (Task 1), `split_author_title_from_filename`, `repair_filename_text`.
- Produces: `import_signal_from_path(path) -> ImportSourceSignal` now fills `authors` from the parent folder when the filename gives none.

- [ ] **Step 1: Write the failing test**

Add to `FolderAuthorAndJunkTests`:

```python
    def test_path_signal_uses_folder_as_author(self):
        signal = cme.import_signal_from_path(r"E:\Knihy\Terry_Pratchett\Kobercove.pdb")
        self.assertEqual(signal.title, "Kobercove")
        self.assertEqual(signal.authors, "Terry Pratchett")

    def test_path_signal_no_author_when_parent_generic(self):
        signal = cme.import_signal_from_path(r"E:\Knihy\Kobercove.pdb")
        self.assertEqual(signal.title, "Kobercove")
        self.assertEqual(signal.authors, "")

    def test_path_signal_keeps_filename_author_over_folder(self):
        signal = cme.import_signal_from_path(r"E:\Knihy\Jine_Jmeno\Verne - Tajuplny ostrov.epub")
        self.assertEqual(signal.title, "Tajuplny ostrov")
        self.assertEqual(signal.authors, "Verne")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: FAIL on `test_path_signal_uses_folder_as_author` (`'' != 'Terry Pratchett'`)

- [ ] **Step 3: Write minimal implementation**

Replace `import_signal_from_path` (lines 489-499):

```python
def import_signal_from_path(path: str | Path) -> ImportSourceSignal:
    file_path = Path(path)
    title, authors = split_author_title_from_filename(file_path.stem)
    if not authors and len(file_path.parts) >= 2:
        authors = folder_author_hint(file_path.parts[-2])
    folder_text = repair_filename_text(" ".join(part for part in file_path.parts[:-1] if part))
    return ImportSourceSignal(
        source="filename",
        title=title,
        authors=authors,
        text=folder_text,
        confidence=30,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: PASS
Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py`
Expected: OK (existing filename-signal tests still pass)

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Use parent folder as author hint in path signal"
```

---

### Task 3: `is_junk_signal` + junk demotion in `signal_preview_quality`

**Files:**
- Modify: `calibre_meta_edit.py` (add `is_junk_signal` before `signal_preview_quality`, line 582; modify `signal_preview_quality`)
- Test: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `ImportSourceSignal` (fields `title`, `authors`, `confidence`), `has_known_mojibake`.
- Produces:
  - `is_junk_signal(signal: ImportSourceSignal) -> bool`
  - `signal_preview_quality(signal) -> tuple[int, int, int, int]` (now a 4-tuple, leading `not_junk`).

- [ ] **Step 1: Write the failing test**

Add to `FolderAuthorAndJunkTests`:

```python
    def test_is_junk_signal_underscore_title(self):
        junk = cme.ImportSourceSignal(source="ebook-meta", title="Pratchett_Terry-Kobercove", authors="Neznamy")
        clean = cme.ImportSourceSignal(source="filename", title="Kobercove", authors="Terry Pratchett")
        self.assertTrue(cme.is_junk_signal(junk))
        self.assertFalse(cme.is_junk_signal(clean))

    def test_clean_signal_outranks_junk(self):
        junk = cme.ImportSourceSignal(source="ebook-meta", title="Pratchett_Terry-Kobercove", authors="Neznamy", confidence=60)
        clean = cme.ImportSourceSignal(source="filename", title="Kobercove", authors="Terry Pratchett", confidence=30)
        self.assertGreater(cme.signal_preview_quality(clean), cme.signal_preview_quality(junk))

    def test_quality_ordering_unchanged_among_clean_signals(self):
        complete = cme.ImportSourceSignal(source="ebook-meta", title="Mort", authors="Terry Pratchett", confidence=60)
        title_only = cme.ImportSourceSignal(source="filename", title="Mort", authors="", confidence=30)
        self.assertGreater(cme.signal_preview_quality(complete), cme.signal_preview_quality(title_only))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: FAIL with `AttributeError: ... 'is_junk_signal'`

- [ ] **Step 3: Write minimal implementation**

Insert immediately before `signal_preview_quality` (line 582):

```python
def is_junk_signal(signal: ImportSourceSignal) -> bool:
    """Pozna signal jehoz nazev vypada jako z nazvu souboru (junk).

    Marker: podtrzitko v nazvu. Realne nazvy knih '_' nemaji, filename-derived ano.
    """
    return "_" in signal.title
```

Replace `signal_preview_quality` (lines 582-586):

```python
def signal_preview_quality(signal: ImportSourceSignal) -> tuple[int, int, int, int]:
    preview_text = " ".join(part for part in (signal.title, signal.authors) if part.strip())
    clean_bonus = 100 if preview_text and not has_known_mojibake(preview_text) else 0
    completeness = int(bool(signal.title.strip())) + int(bool(signal.authors.strip()))
    not_junk = 0 if is_junk_signal(signal) else 1
    return not_junk, completeness, clean_bonus, signal.confidence
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: PASS
Run: `python -m unittest discover -s tests -p test_calibre_meta_edit.py`
Expected: OK (existing `signal_preview_quality`/`choose_initial_import_preview` tests still pass — clean titles have no underscore, so `not_junk = 1` for all and relative order is preserved)

- [ ] **Step 5: Commit**

```bash
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Demote junk filename-like signals in preview quality"
```

---

### Task 4: Integration — clean signal wins preview and search

**Files:**
- Test only: `tests/test_calibre_meta_edit.py`

**Interfaces:**
- Consumes: `choose_initial_import_preview(signals) -> ImportPreview`, `_signal_book(signals) -> Book` (both existing).

- [ ] **Step 1: Write the failing test (expected to PASS already — this is a regression lock)**

Add to `FolderAuthorAndJunkTests`:

```python
    def test_preview_and_search_prefer_clean_over_junk(self):
        signals = [
            cme.ImportSourceSignal(source="ebook-meta", title="Pratchett_Terry-Kobercove", authors="Neznamy", confidence=60),
            cme.import_signal_from_epub_text(""),
            cme.import_signal_from_path(r"E:\Knihy\Terry_Pratchett\Kobercove.pdb"),
        ]
        preview = cme.choose_initial_import_preview(signals)
        self.assertEqual(preview.title, "Kobercove")
        self.assertEqual(preview.authors, "Terry Pratchett")

        book = cme._signal_book(signals)
        self.assertEqual(book.title, "Kobercove")
        self.assertEqual(book.authors, ["Terry Pratchett"])
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m unittest tests.test_calibre_meta_edit.FolderAuthorAndJunkTests -v`
Expected: PASS (Tasks 2 and 3 together produce this behavior; this test locks it in)

Note: this task has no implementation step — it is a regression-locking integration test that verifies Tasks 2+3 combine correctly. If it fails, the bug is in Task 2 or 3; fix there.

- [ ] **Step 3: Commit**

```bash
git add tests/test_calibre_meta_edit.py
git commit -m "Lock clean-beats-junk preview and search behavior"
```

---

## Final verification (after Task 4)

- [ ] Full suite: `python -m unittest discover -s tests` → expect OK.
- [ ] Compile: `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py` → clean.
- [ ] `git status --short` → working tree clean.
- [ ] Manual smoke (optional, needs Calibre + the PDB): re-import `Kobercove.pdb` from a `Terry_Pratchett` folder; preview author should be `Terry Pratchett` and the databazeknih "Kobercové" candidate should score high / win.

## Self-Review notes

- Spec coverage: folder→author (Tasks 1–2), junk demotion (Task 3), clean-beats-junk for preview+search (Task 4), back-compat for clean signals (Task 3 Step 4 + existing suite). No gaps.
- Type consistency: `folder_author_hint(str) -> str`, `is_junk_signal(ImportSourceSignal) -> bool`, `signal_preview_quality(...) -> 4-tuple` used consistently across tasks.
- Out of scope confirmed untouched: online search functions, candidate scoring, AI resolver, UI, book-start text parsing.
