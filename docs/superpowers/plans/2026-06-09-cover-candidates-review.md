# Cover Candidates Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automaticky najit kandidatni obalky bez zapisu, zobrazit vice obalek v gridu, vyzadovat vyber jedne obalky pred `approve`, a pri zapisu ulozit vybranou obalku spolu s metadaty.

**Architecture:** Kandidati obalek budou soucasti `matches.csv`, stejne jako odkazy. Start appky spusti preview/audit odkazu a potom cover audit bez zapisu. Qt detail panel zobrazi grid kandidatu; vybrana obalka se ulozi do CSV a pouzije se pri `apply`.

**Tech Stack:** Python stdlib, SQLite read-only, `calibredb`, PySide6, unittest.

---

## Future Storage Note

For this `0.2.x` cover workflow, keep `matches.csv`. It is still useful as a visible working queue and keeps this change small.

When book import starts in `0.3.x`, reconsider moving app state to a separate app-owned SQLite database, for example `calibre-meta-edit.db`. That database must be separate from Calibre `metadata.db`; Calibre `metadata.db` stays read-only except through `calibredb`.

## File Structure

- Modify `calibre_meta_edit.py`
  - rozsirit `MATCHES_FIELDS` a `MatchRow`
  - pridat `CoverOption`
  - pridat parser vice obalek z Databaze knih a Legie
  - pridat `audit_cover_rows`
  - upravit `apply_match_row`, aby pri approve zapsal i vybranou obalku
- Modify `calibre_meta_app.py`
  - helpery pro cover audit akci
  - helper pro validaci, ze `approve` nejde pri vice obalkach bez vyberu
- Modify `calibre_meta_qt.py`
  - po startup preview spustit cover audit bez zapisu
  - detail panel: grid malych obalek
  - klik na obalku ulozi vybranou obalku do row
  - `Approve` blokovat, kdyz je vice obalek a zadna vybrana
- Modify tests:
  - `tests/test_calibre_meta_edit.py`
  - `tests/test_calibre_meta_app.py`
  - `tests/test_calibre_meta_qt.py`
- Modify docs:
  - `POSTUP.md`
  - `PLAN.md`

---

### Task 1: Rozsirit CSV model pro obalky

**Files:**
- Modify: `calibre_meta_edit.py`
- Test: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing tests for old and new CSV**

Add tests:

```python
def test_read_matches_csv_defaults_cover_columns_for_old_csv(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "matches.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["book_id", "title", "authors", "status", "chosen_url", "candidate_urls", "confidence", "reason"])
            writer.writeheader()
            writer.writerow({
                "book_id": "1",
                "title": "Kniha",
                "authors": "Autor",
                "status": "review",
                "chosen_url": "https://www.databazeknih.cz/knihy/a-1",
                "candidate_urls": "",
                "confidence": "manual",
                "reason": "manual",
            })

        rows = cme.read_matches_csv(path)

        self.assertEqual(rows[0].cover_urls, "")
        self.assertEqual(rows[0].selected_cover_url, "")
        self.assertEqual(rows[0].cover_reason, "")


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

        text = path.read_text(encoding="utf-8-sig")

        self.assertIn("cover_urls", text)
        self.assertIn("selected_cover_url", text)
        self.assertIn("cover_reason", text)
```

- [ ] **Step 2: Run tests and verify fail**

Run:

```text
python -m unittest tests.test_calibre_meta_edit.CalibreDbAndApplyTests
```

Expected: fail because `MatchRow` has no cover fields.

- [ ] **Step 3: Implement model**

Change:

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
    "cover_urls",
    "selected_cover_url",
    "cover_reason",
]
```

Change `MatchRow`:

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
    cover_urls: str = ""
    selected_cover_url: str = ""
    cover_reason: str = ""
```

Update `read_matches_csv()` constructor to read:

```python
raw.get("cover_urls", ""),
raw.get("selected_cover_url", ""),
raw.get("cover_reason", ""),
```

- [ ] **Step 4: Run tests**

Run:

```text
python -m unittest discover -s tests
```

Expected: all pass.

- [ ] **Step 5: Commit**

```text
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Add cover fields to matches CSV"
```

---

### Task 2: Najit vice kandidatnich obalek bez zapisu

**Files:**
- Modify: `calibre_meta_edit.py`
- Test: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing parser tests**

Add:

```python
def test_parse_databaze_cover_options_reads_json_and_meta_images(self):
    html = """
    <script type="application/ld+json">
    {"@type": "Book", "image": "https://img.databazeknih.cz/img/books/1/main.jpg"}
    </script>
    <meta property="og:image" content="https://img.databazeknih.cz/img/books/1/og.jpg">
    """

    options = cme.parse_databaze_cover_options(html)

    self.assertEqual([option.url for option in options], [
        "https://img.databazeknih.cz/img/books/1/main.jpg",
        "https://img.databazeknih.cz/img/books/1/og.jpg",
    ])


def test_parse_legie_cover_options_reads_multiple_story_covers(self):
    html = """
    <div id="pro_obal">
      <img src="images/kniha-small/1/138-2213.jpg" class="obal_kniha" title="prebal 1" />
      <img src="images/kniha-small/3/394-4329.jpg" class="obal_kniha" title="prebal 2" />
    </div>
    """

    options = cme.parse_legie_cover_options(html)

    self.assertEqual([option.url for option in options], [
        "https://www.legie.info/images/kniha-small/1/138-2213.jpg",
        "https://www.legie.info/images/kniha-small/3/394-4329.jpg",
    ])
```

- [ ] **Step 2: Implement `CoverOption` and parsers**

Add:

```python
@dataclass(frozen=True)
class CoverOption:
    url: str
    source: str
    label: str = ""
```

Add:

```python
def _dedupe_cover_options(options: Sequence[CoverOption]) -> list[CoverOption]:
    seen: set[str] = set()
    result: list[CoverOption] = []
    for option in options:
        if option.url and option.url not in seen:
            seen.add(option.url)
            result.append(option)
    return result
```

Add `parse_databaze_cover_options(html_text: str) -> list[CoverOption]` using existing `BookDetailParser` and JSON image helper.

Add `parse_legie_cover_options(html_text: str) -> list[CoverOption]` by extending `LegieStoryParser` with `cover_urls: list[str]`.

- [ ] **Step 3: Add cover audit tests**

Add:

```python
def test_audit_cover_rows_marks_multiple_cover_candidates_review(self):
    rows = [
        cme.MatchRow(1, "Povidka", "Autor", "skip", "https://www.legie.info/povidka/40", "", "manual", "manual", "legie", "povidka"),
    ]

    updated = cme.audit_cover_rows(
        rows,
        "library",
        cover_flags_reader=lambda library, ids: {1: False},
        fetcher=lambda url: '''
            <div id="pro_obal">
              <img src="images/kniha-small/1/a.jpg" class="obal_kniha" />
              <img src="images/kniha-small/1/b.jpg" class="obal_kniha" />
            </div>
        ''',
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
        fetcher=lambda url: '<script type="application/ld+json">{"@type":"Book","image":"https://img/a.jpg"}</script>',
    )

    self.assertEqual(updated[0].status, "skip")
    self.assertEqual(updated[0].cover_urls, "https://img/a.jpg")
    self.assertEqual(updated[0].selected_cover_url, "https://img/a.jpg")
    self.assertEqual(updated[0].cover_reason, "single-cover-candidate")
```

- [ ] **Step 4: Implement `audit_cover_rows`**

Rules:
- if Calibre has cover: keep row unchanged
- if no supported URL: keep row unchanged
- one cover: set `cover_urls`, `selected_cover_url`, `cover_reason=single-cover-candidate`
- multiple covers: set `cover_urls`, clear `selected_cover_url`, set row status `review`, `cover_reason=multiple-cover-candidates`
- zero covers: set `cover_reason=cover-not-found`, keep status unchanged

- [ ] **Step 5: Commit**

```text
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Audit cover candidates without writing"
```

---

### Task 3: Spustit cover audit automaticky po startu

**Files:**
- Modify: `calibre_meta_app.py`
- Modify: `calibre_meta_qt.py`
- Test: `tests/test_calibre_meta_app.py`

- [ ] **Step 1: Add failing app helper test**

Add:

```python
def test_preview_audit_then_cover_audit_runs_cover_after_link_audit(self):
    calls = []

    result = app.run_preview_audit_then_cover_audit(
        preview_func=lambda: calls.append("preview") or 0,
        link_audit_func=lambda: calls.append("link-audit") or 0,
        cover_audit_func=lambda: calls.append("cover-audit") or 0,
    )

    self.assertEqual(result, 0)
    self.assertEqual(calls, ["preview", "link-audit", "cover-audit"])
```

- [ ] **Step 2: Implement helper**

Add:

```python
def run_preview_audit_then_cover_audit(
    preview_func: Callable[[], int],
    link_audit_func: Callable[[], int],
    cover_audit_func: Callable[[], int],
) -> int:
    preview_result = preview_func()
    if preview_result != 0:
        return preview_result
    link_result = link_audit_func()
    if link_result != 0:
        return link_result
    return cover_audit_func()
```

Add `make_cover_audit_action(args, matches_path=...)`.

- [ ] **Step 3: Wire Qt startup**

Change `run_preview()` in `calibre_meta_qt.py` to run:
- existing preview + link audit
- then cover audit
- reload CSV

No Calibre write. No backup. No Calibre shutdown.

- [ ] **Step 4: Commit**

```text
git add calibre_meta_app.py calibre_meta_qt.py tests/test_calibre_meta_app.py
git commit -m "Run cover audit after startup preview"
```

---

### Task 4: Cover grid selection in Qt detail

**Files:**
- Modify: `calibre_meta_qt.py`
- Modify: `calibre_meta_app.py`
- Test: `tests/test_calibre_meta_qt.py`, `tests/test_calibre_meta_app.py`

- [ ] **Step 1: Add pure helper tests**

Add helper in `calibre_meta_app.py`:

```python
def cover_options_from_row(row: cme.MatchRow) -> list[str]:
    return [url for url in row.cover_urls.split("|") if url.strip()]
```

Add test:

```python
def test_cover_options_from_row_splits_urls(self):
    row = cme.MatchRow(1, "K", "A", "review", "", "", "x", "x", cover_urls="u1|u2")

    self.assertEqual(app.cover_options_from_row(row), ["u1", "u2"])
```

- [ ] **Step 2: Replace single candidate preview with grid**

In `calibre_meta_qt.py`:
- keep local cover preview for `Obalka v Calibre`
- add `self.cover_grid = QGridLayout()`
- for each URL in `row.cover_urls`, create small clickable `QToolButton` or `QLabel`
- selected URL gets visible border
- clicking option calls `set_selected_cover_url(url)`

- [ ] **Step 3: Persist selected cover URL**

Add:

```python
def set_selected_cover_url(self, url: str) -> None:
    selected = self.selected_book_ids()
    if len(selected) != 1:
        return
    book_id = next(iter(selected))
    self.rows = shared.update_rows_selected_cover(self.rows, book_id, url)
    self.save_csv(show_message=False)
    self.refresh_table()
```

Add `update_rows_selected_cover()` in `calibre_meta_app.py`.

- [ ] **Step 4: Commit**

```text
git add calibre_meta_qt.py calibre_meta_app.py tests/test_calibre_meta_qt.py tests/test_calibre_meta_app.py
git commit -m "Add selectable cover grid"
```

---

### Task 5: Block approve when multiple covers have no selection

**Files:**
- Modify: `calibre_meta_app.py`
- Modify: `calibre_meta_qt.py`
- Test: `tests/test_calibre_meta_app.py`

- [ ] **Step 1: Add validation tests**

Add:

```python
def test_row_requires_cover_choice_when_multiple_candidates_and_no_selection(self):
    row = cme.MatchRow(
        1,
        "K",
        "A",
        "review",
        "https://www.legie.info/povidka/40",
        "",
        "x",
        "x",
        "legie",
        "povidka",
        "u1|u2",
        "",
        "multiple-cover-candidates",
    )

    self.assertTrue(app.row_requires_cover_choice(row))


def test_row_does_not_require_cover_choice_when_selected(self):
    row = cme.MatchRow(1, "K", "A", "review", "", "", "x", "x", cover_urls="u1|u2", selected_cover_url="u1")

    self.assertFalse(app.row_requires_cover_choice(row))
```

- [ ] **Step 2: Implement helper**

```python
def row_requires_cover_choice(row: cme.MatchRow) -> bool:
    cover_count = len([url for url in row.cover_urls.split("|") if url.strip()])
    return cover_count > 1 and not row.selected_cover_url.strip()
```

- [ ] **Step 3: Block `Approve`**

In `CalibreMetaQtWindow.set_selected_status()`:

```python
if status == "approve":
    blocked = [row for row in self.selected_rows() if shared.row_requires_cover_choice(row)]
    if blocked:
        QMessageBox.warning(self, "Vyber obalku", "Knihy s vice obalkami nejdou schvalit bez vybrane obalky.")
        return
```

- [ ] **Step 4: Commit**

```text
git add calibre_meta_app.py calibre_meta_qt.py tests/test_calibre_meta_app.py
git commit -m "Require cover choice before approve"
```

---

### Task 6: Write selected cover during apply

**Files:**
- Modify: `calibre_meta_edit.py`
- Test: `tests/test_calibre_meta_edit.py`

- [ ] **Step 1: Add failing apply test**

Add:

```python
def test_apply_match_row_writes_selected_cover_with_metadata(self):
    row = cme.MatchRow(
        1,
        "Kniha",
        "Autor",
        "approve",
        "https://www.databazeknih.cz/knihy/new-2",
        "",
        "manual",
        "manual",
        "databazeknih",
        "",
        "https://img/a.jpg|https://img/b.jpg",
        "https://img/b.jpg",
        "multiple-cover-candidates",
    )
    calls = []

    result = cme.apply_match_row(
        row,
        Path("library"),
        r"C:\calibredb.exe",
        runner=lambda args: calls.append(args) or cme.CommandResult(0, "ok", ""),
        fetcher=lambda url: '<script type="application/ld+json">{"@type":"Book"}</script>',
        binary_fetcher=lambda url: b"jpg",
    )

    self.assertEqual(result.status, "updated")
    self.assertTrue(any(arg.startswith("cover:") for arg in calls[0]))
```

- [ ] **Step 2: Modify `apply_match_row` signature**

Add optional parameter:

```python
binary_fetcher: Callable[[str], bytes] | None = None
```

- [ ] **Step 3: Add selected cover to `set_metadata` args**

Before runner:

```python
if row.selected_cover_url.strip():
    cover_bytes = (binary_fetcher or fetch_binary)(row.selected_cover_url.strip())
    cover_path = write_temp_cover_file(cover_bytes, row.selected_cover_url.strip())
    args.extend(["--field", "cover:" + str(cover_path)])
```

Use a helper context so temp file exists during `runner(args)`.

- [ ] **Step 4: Mark finished rows skip as today**

No behavior change: successful apply still changes row to `skip`.

- [ ] **Step 5: Commit**

```text
git add calibre_meta_edit.py tests/test_calibre_meta_edit.py
git commit -m "Write selected cover during apply"
```

---

### Task 7: Docs, version, full verification

**Files:**
- Modify: `calibre_meta_app.py`
- Modify: `calibre_meta_qt.py`
- Modify: `POSTUP.md`
- Modify: `PLAN.md`
- Test: all tests

- [ ] **Step 1: Bump version**

Set `APP_VERSION = "0.2.6"` or next patch version in both app files.

- [ ] **Step 2: Update docs**

Document:
- startup cover audit does not write anything
- books with existing Calibre cover are skipped
- multiple covers force review
- approve is blocked until one cover is selected
- selected cover is written during `Zapsat do Calibre`

- [ ] **Step 3: Run full verification**

Run:

```text
python -m unittest discover -s tests
python -m py_compile calibre_meta_edit.py calibre_meta_app.py calibre_meta_qt.py CalibreMetaEdit.pyw
```

Expected:

```text
OK
```

- [ ] **Step 4: Qt smoke**

Run offscreen smoke:

```text
$env:QT_QPA_PLATFORM='offscreen'; python -c "import sys; from PySide6.QtWidgets import QApplication; import calibre_meta_qt as q; app=QApplication(sys.argv); w=q.CalibreMetaQtWindow(); assert hasattr(w, 'cover_status'); print('qt ok')"
```

- [ ] **Step 5: Commit and push**

```text
git add .
git commit -m "Document cover review workflow"
git push origin main
```

---

## Self-Review

- Spec coverage:
  - No automatic write on startup: Task 3 explicitly runs audit only.
  - Books with existing cover skipped: Task 2 cover flags rule.
  - Startup candidate loading like links: Task 3.
  - Multiple covers review: Task 2.
  - Cannot approve without selected cover: Task 5.
  - Grid thumbnails, select one: Task 4.
  - Selected cover writes with approved metadata: Task 6.
- Placeholder scan: no TBD/TODO/implement later.
- Type consistency:
  - `cover_urls`, `selected_cover_url`, `cover_reason` added in Task 1 and used later.
  - `CoverOption` used only for parsing options; `MatchRow` persists string URLs.
