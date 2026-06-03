# Qt Desktop Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build first PySide6 desktop UI for Calibre Meta Edit 0.1.0 without removing the current Tkinter app.

**Architecture:** Keep `calibre_meta_edit.py` as backend. Add small shared UI helper functions to `calibre_meta_app.py` only where both frontends need them. Add `calibre_meta_qt.py` as a new frontend that reads/writes `matches.csv` and calls backend actions.

**Tech Stack:** Python stdlib, PySide6, existing `calibre_meta_edit.py`, unittest.

---

## File Structure

- Create `calibre_meta_qt.py`: Qt frontend, window, table model, filters, preferences dialog.
- Modify `calibre_meta_app.py`: version bump to `0.1.0`; keep Tk fallback.
- Modify `tests/test_calibre_meta_app.py`: version test.
- Create `tests/test_calibre_meta_qt.py`: tests for pure Qt-helper logic. Tests must skip cleanly when PySide6 is not installed.
- Modify `POSTUP.md`: document Qt launch command and Tk fallback.
- Modify `PLAN.md`: add update `0.1.0`.

## Task 1: Dependency Gate

**Files:**
- Create: `tests/test_calibre_meta_qt.py`
- Create: `calibre_meta_qt.py`

- [ ] **Step 1: Write skip-safe import test**

```python
# Testy hlidaji Qt app helpery bez nutnosti otevirat okno.

import importlib.util
import unittest


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 neni nainstalovane")
class QtImportTests(unittest.TestCase):
    def test_qt_app_title_includes_version(self):
        import calibre_meta_qt as qt

        self.assertEqual(qt.APP_VERSION, "0.1.0")
        self.assertEqual(qt.app_title(), "Calibre Meta Edit 0.1.0")
```

- [ ] **Step 2: Run test before implementation**

Run:

```powershell
python -m unittest tests.test_calibre_meta_qt
```

Expected now: skipped when PySide6 missing, or fail because `calibre_meta_qt.py` missing when PySide6 exists.

- [ ] **Step 3: Install PySide6 if missing**

Run:

```powershell
python -m pip install PySide6
```

Expected: PySide6 installed.

- [ ] **Step 4: Create minimal Qt module**

```python
# Qt desktop appka pro pohodlne schvalovani metadat v modernim Windows okne.

from __future__ import annotations

APP_VERSION = "0.1.0"


def app_title() -> str:
    """Vrati titulek hlavniho okna vcetne verze."""
    return f"Calibre Meta Edit {APP_VERSION}"
```

- [ ] **Step 5: Run import test**

Run:

```powershell
python -m unittest tests.test_calibre_meta_qt
```

Expected: `OK`.

## Task 2: Shared Data Helpers

**Files:**
- Modify: `calibre_meta_qt.py`
- Test: `tests/test_calibre_meta_qt.py`

- [ ] **Step 1: Add tests for filter/statusbar helpers**

```python
class QtHelperTests(unittest.TestCase):
    def test_filter_rows_supports_title_author_status_source_type(self):
        import calibre_meta_qt as qt
        import calibre_meta_edit as cme

        rows = [
            cme.MatchRow(1, "Kat", "Martin Moudry", "approve", "https://x", "a", "b", "c", "databazeknih", ""),
            cme.MatchRow(2, "Samuela", "Anatolij Dneprov", "skip", "https://y", "a", "b", "c", "legie", "povidka"),
        ]

        result = qt.filter_rows(rows, title="kat", author="moudry", status="approve", source="databazeknih", work_type="")

        self.assertEqual([row.book_id for row in result], [1])

    def test_statusbar_text_contains_ready_calibre_csv_and_version(self):
        import calibre_meta_qt as qt

        text = qt.statusbar_text("Ready", calibre_running=False, csv_loaded=True)

        self.assertEqual(text, "Ready | Calibre vypnuto | matches.csv nacteno | 0.1.0")
```

- [ ] **Step 2: Implement helpers**

```python
import calibre_meta_edit as cme


def filter_rows(
    rows: list[cme.MatchRow],
    title: str = "",
    author: str = "",
    status: str = "",
    source: str = "",
    work_type: str = "",
) -> list[cme.MatchRow]:
    """Vrati jen radky, ktere odpovidaji filtrum v horni liste."""
    title_query = cme.normalize_text(title)
    author_query = cme.normalize_text(author)
    result: list[cme.MatchRow] = []
    for row in rows:
        if title_query and title_query not in cme.normalize_text(row.title):
            continue
        if author_query and author_query not in cme.normalize_text(row.authors):
            continue
        if status and row.status != status:
            continue
        if source and row.source != source:
            continue
        if work_type and row.work_type != work_type:
            continue
        result.append(row)
    return result


def statusbar_text(status: str, calibre_running: bool, csv_loaded: bool) -> str:
    """Slozi kratky text do spodni status listy."""
    calibre_text = "Calibre zapnuto" if calibre_running else "Calibre vypnuto"
    csv_text = "matches.csv nacteno" if csv_loaded else "matches.csv nenacteno"
    return f"{status} | {calibre_text} | {csv_text} | {APP_VERSION}"
```

- [ ] **Step 3: Run tests**

Run:

```powershell
python -m unittest tests.test_calibre_meta_qt
```

Expected: `OK`.

## Task 3: Qt Window Skeleton

**Files:**
- Modify: `calibre_meta_qt.py`

- [ ] **Step 1: Add main window skeleton**

Implement:

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CalibreMetaQtWindow(QMainWindow):
    """Hlavni Qt okno. Drzi tabulku, filtry, detail a statusbar."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[cme.MatchRow] = []
        self.filtered_rows: list[cme.MatchRow] = []
        self.setWindowTitle(app_title())
        self.resize(1280, 760)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(self._build_toolbar())
        layout.addLayout(self._build_filterbar())
        layout.addWidget(self._build_main_area(), stretch=1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.set_status("Ready")
```

- [ ] **Step 2: Add `main()`**

```python
def main() -> int:
    """Spusti Qt appku."""
    app = QApplication([])
    window = CalibreMetaQtWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run syntax + tests**

Run:

```powershell
python -m py_compile calibre_meta_qt.py
python -m unittest discover -s tests
```

Expected: `OK`.

## Task 4: Table, Filters, Detail Panel

**Files:**
- Modify: `calibre_meta_qt.py`

- [ ] **Step 1: Implement table columns**

Columns:

```python
TABLE_COLUMNS = ("ID", "Kniha", "Autor", "Status", "Zdroj", "Typ", "Odkaz", "Rok", "Vydavatel", "Stitky")
```

- [ ] **Step 2: Add filter controls**

Controls:

```python
self.title_filter = QLineEdit()
self.author_filter = QLineEdit()
self.status_filter = QComboBox()
self.source_filter = QComboBox()
self.type_filter = QComboBox()
```

Connect each change to `self.refresh_table`.

- [ ] **Step 3: Add table fill**

For each filtered row, fill:

```python
values = [
    str(row.book_id),
    row.title,
    row.authors,
    row.status,
    row.source,
    row.work_type,
    row.chosen_url,
    "",
    "",
    "",
]
```

- [ ] **Step 4: Add right detail panel**

Show selected row:

```text
Kniha
Autor
Status
Odkaz input
Approve Review Skip Povidka
Log/preview text
```

- [ ] **Step 5: Manual smoke**

Run:

```powershell
python calibre_meta_qt.py
```

Expected: window opens, table area visible, filters visible, statusbar visible.

## Task 5: Actions

**Files:**
- Modify: `calibre_meta_qt.py`

- [ ] **Step 1: Add toolbar actions**

Toolbar buttons:

```text
Nacist CSV
Nacist nove knihy
Audit odkazu
Update vybrane
Ulozit CSV
Zapsat
Preferences
```

- [ ] **Step 2: Wire CSV actions**

Use:

```python
self.rows = cme.read_matches_csv(cme.MATCHES_PATH)
cme.write_matches_csv(cme.MATCHES_PATH, self.rows)
```

- [ ] **Step 3: Wire status/link actions**

Reuse row update rules equivalent to Tk app:

```python
import calibre_meta_app as tk_app
updated = tk_app.update_row(row, status, chosen_url)
```

- [ ] **Step 4: Wire backend long actions via thread**

For preview/audit/apply, use a worker thread so Qt UI does not freeze.

- [ ] **Step 5: Verify no backend behavior changed**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: `OK`.

## Task 6: Preferences

**Files:**
- Modify: `calibre_meta_qt.py`

- [ ] **Step 1: Add preferences dialog**

Dialog contains:

```text
Knihovna path
Zmenit
Pouzit z Calibre
Rebuild CSV
Rollback
```

- [ ] **Step 2: Reuse existing helpers**

Use from `calibre_meta_app.py`:

```python
initial_library_path
save_library_path
read_calibre_library_path
```

- [ ] **Step 3: Statusbar update**

After library change, statusbar shows `Ready | Calibre vypnuto | matches.csv nacteno | 0.1.0`.

## Task 7: Docs, Version, Final Verify

**Files:**
- Modify: `calibre_meta_app.py`
- Modify: `tests/test_calibre_meta_app.py`
- Modify: `POSTUP.md`
- Modify: `PLAN.md`

- [ ] **Step 1: Bump version**

Set:

```python
APP_VERSION = "0.1.0"
```

- [ ] **Step 2: Update tests**

Expected:

```python
self.assertEqual(app.APP_VERSION, "0.1.0")
self.assertEqual(app.app_title(), "Calibre Meta Edit 0.1.0")
```

- [ ] **Step 3: Update docs**

Document:

```text
Qt app:
python calibre_meta_qt.py

Tk fallback:
CalibreMetaEdit.bat
```

- [ ] **Step 4: Final verify**

Run:

```powershell
python -m unittest discover -s tests
python -m py_compile calibre_meta_edit.py calibre_meta_app.py calibre_meta_qt.py CalibreMetaEdit.pyw
```

Expected: all tests pass, syntax OK.
