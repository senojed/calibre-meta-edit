# CLAUDE.md

## Project

Calibre Meta Edit is a Python/Qt application for reviewing book metadata, matching metadata sources, importing EPUB files, and safely writing metadata to a Calibre library.

Repository:

```text
C:\Users\Honza\Nextcloud\Jan\PROJECTS\calibre-meta-edit
```

GitHub:

```text
https://github.com/senojed/calibre-meta-edit
```

## Current baseline

Current stable baseline is `main`. It is the only branch; there is no develop or
release branch.

Last recorded state (2026-07-17):

```text
main HEAD: bf7faa0 Merge fix/cover-source-errors-visible
Visible app version: 0.4.9
Tests: 733 OK
py_compile: OK
```

This section rots. It sat at `0.4.4` while the app shipped `0.4.9`, so treat it as
a hint, not a fact, and check git before starting work:

```powershell
git log --oneline -3
git status --short
```

Two files are expected to show up dirty and are not yours to fix: `AGENTS.md`
belongs to Codex, and the markdown under `docs/superpowers/` is untracked on
purpose.

## Development rules

* Work in small, task-based changes.
* Prefer one logical task = one commit.
* Do not silently broaden scope.
* Do not start the next task until the current task is reviewed, tested, committed, and clean.
* Preserve backend behavior unless the current task explicitly requires backend changes.
* Keep UI and backend concerns separated.
* For UI-only tasks, prefer changes only in `calibre_meta_qt.py`.
* Do not touch `calibre_meta_edit.py` during UI tasks unless strictly necessary.
* Do not rename public methods unless necessary.
* Do not change callbacks, signal connections, or behavior unless explicitly requested.
* Do not add generated files, backup files, exported diffs, temporary files, or local `.work/` files to git.
* Do not commit uploaded/exported `*.diff` review files.
* If SVG/icon/assets are added, make sure the asset files are staged and committed.
* If a file is missing at runtime, the app should degrade gracefully rather than crash, where practical.

## Git workflow

Before starting a task:

```powershell
git checkout main
git pull
git status --short
```

For larger tasks, create a branch:

```powershell
git checkout -b <task-name>
```

For very small approved polish changes, working directly on `main` is acceptable, but only if the change is narrow and immediately committed.

Before commit:

```powershell
git status --short
git diff --stat
git diff -- <changed-files>
```

Commit only the intended files.

After commit:

```powershell
git status --short
```

If the task was done on a branch and approved, merge to `main`:

```powershell
git checkout main
git pull
git merge <task-branch>
python -m unittest discover -s tests
python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py
git push
```

Only delete branches that are confirmed merged into `main`.

## Test commands

Use these commands before reporting completion:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
python -m unittest discover -s tests -p test_calibre_meta_qt.py
python -m unittest discover -s tests
python -m py_compile calibre_meta_edit.py calibre_meta_qt.py calibre_meta_app.py
```

Note:

```powershell
python -m unittest discover
```

without `-s tests` may not discover tests in this project layout.

## Diff export on Windows

Avoid PowerShell redirection for review diffs because it can cause encoding artifacts.

Use Python byte-preserving export instead:

```powershell
python -c "import subprocess, pathlib; pathlib.Path('review.diff').write_bytes(subprocess.check_output(['git','diff','--','calibre_meta_edit.py','calibre_meta_qt.py','calibre_meta_app.py']))"
```

Do not commit `review.diff`.

## UI rules

* Toolbar buttons should remain icon-only unless explicitly requested otherwise.
* Toolbar buttons should remain square and same fixed size.
* Keep tooltips for icon-only buttons.
* Keep custom SVG icons loaded from `assets/icons/`.
* Do not embed SVG strings in Python code.
* Missing icon files must not crash the app.
* Keep toolbar layout intentional:

  * left group: load, save, preferences
  * stretch / large spacer
  * right group: load from Calibre, audit/link, covers, import, delete from Calibre
  * small gap
  * final right button: write to Calibre

## Versioning

Visible app version is currently `0.4.9`.

If bumping version:

* update all existing version constants
* update tests that assert the visible version
* do not invent a second versioning system
* keep Qt/app variants in sync

Known version locations:

```text
calibre_meta_qt.py
calibre_meta_app.py
tests/test_calibre_meta_qt.py
tests/test_calibre_meta_app.py
```

## What is already built

Do not maintain a feature changelog here. The list that used to live in this spot
went five versions stale, which is what a hand-written changelog next to a git log
always does. Read the history instead:

```powershell
git log --oneline -30
```

Commit messages in this repo carry the reasoning, not just the what, so the log is
the honest record of why something looks the way it does.

Two traps when judging what exists:

* Unchecked boxes in `docs/superpowers/plans/` are historical plans, not a todo
  list. Some are shipped, some abandoned. Decide from code, tests, and git.
* `docs/superpowers/specs/2026-07-08-unified-import-selector-design.md` is about
  choosing input files. It explicitly excludes redesigning the import dialogs, so
  it is not the import dialog revamp.

## Next task

Awaiting next task assignment. Do not start speculative work.

On the table, in rough order of how concrete they are:

* **Import dialog revamp** - merge the single `ImportDialog` and
  `MultiImportResultsDialog` into one master-detail dialog, treating a single
  import as a batch of one. Three deferred items ride along and should not be done
  before it: clickable column sorting (rows are index-mapped today, so sorting
  breaks them), the missing AI-failure warning in single import, and the disabled
  button fill in the `system` theme (base stylesheet still hardcodes light
  `#bdbdbd`, so disabled reads louder than enabled on a dark Windows palette).
* **Stop button** in progress dialogs. Not small: work runs synchronously on the UI
  thread and cannot be interrupted. The real fix is moving analysis/write to a
  worker thread (`WorkerBridge` already exists for single import). Only worth doing
  alongside that move.
* **API key storage into the OS keychain** (`keyring`) + a GUI field, for
  distributing the app to other people. `read_api_key` in `calibre_meta_edit.py` is
  the single swap point.
* **More import formats.**

## Reporting format

After each task, report:

* current branch
* commit hash, if committed
* changed files
* summary of changes
* tests run
* test results
* py_compile result
* untracked files
* whether working tree is clean
* whether branch was pushed
* whether merge to `main` was done
* whether the next task was started

Stop after each task and wait for review unless the user explicitly approved commit/merge/push.
