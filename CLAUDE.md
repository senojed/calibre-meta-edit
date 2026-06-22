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

Current stable baseline is `main`.

Latest known stable state:

```text
main HEAD / origin/main before this documentation update: 23fb06c ui: remove original publisher review field
000d117: historical version 0.4.3 baseline only; not the current HEAD
Visible app version: 0.4.4
Tests: 461 OK (edit 293 + app 65 + qt 103)
py_compile: OK
Working tree: clean when this state was recorded
```

Do not assume this section is current forever. Always check actual git state before starting work.

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

Visible app version is currently `0.4.4`.

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

## Current completed work

Recent completed tasks on `main`:

* Anthropic + OpenAI cloud AI providers for import (alongside Ollama)
* API key read from env var / `.env` (never settings.json); `.env` gitignored
* AI text extraction, source-priority import selection, folder-author hints, junk
  filename demotion, and all-caps title/author normalization
* Multi-format import for EPUB, MOBI, AZW3, and PDB
* Manual-link enrichment, candidate re-search, duplicate controls, and Calibre deletion
* databazeknih search queries author before title (order-sensitive fulltext)
* auto-fetch cover after a successful import
* version bump to `0.4.4`
* right-side Qt toolbar button order: import, covers, link, load from Calibre,
  delete, write
* original publisher removed from Review UI, `REVIEW_EDITABLE_FIELDS`, Review
  display, and generated Calibre comments; legacy parsing/loading remains tolerated

Known good commits:

```text
000d117 Bump version to 0.4.3
7a8c746 Auto-fetch cover after a successful import
9792bae Merge databaze-search-author-order (author before title)
74cea1b Wire cloud providers into Preferences and import
f1167c9 Normalize all-caps title and author from AI extraction
8ee9e49 Reorder right toolbar buttons
23fb06c Remove original publisher review field
0660d77 Ignore .env to keep API keys out of git
```

Old unchecked boxes in `docs/superpowers/plans/` are historical implementation
plans. Determine task status from current code, tests, and git history instead.

## Next task

Awaiting next task assignment.

Do not start speculative work.

Likely future tasks:

* move API key storage to OS keychain (`keyring`) + GUI field for distribution
  (or own proxy server if the dev pays for all users); `read_api_key` in
  calibre_meta_edit.py is the single swap point
* more cosmetic UI polish
* more book import formats
* bulk book import brainstorming/task

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
