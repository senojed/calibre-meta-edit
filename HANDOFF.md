# Handoff

## Current observed git state

State recorded after the original-publisher cleanup merge:

* Current branch: `main`
* `main` HEAD / `origin/main` before this documentation update: `23fb06c`
  (`ui: remove original publisher review field`).
* Main is pushed and the working tree was clean before this documentation update.
* `000d117` is a historical version 0.4.3 baseline only, not the current HEAD.
* Original publisher is no longer user-facing in Review or written into new
  Calibre comments; legacy parsing and persisted-data loading remain tolerated.

## Recent commits

* `23fb06c` Remove original publisher Review field.
* `3103b26` Update handoff baseline after UI polish.
* `8ee9e49` Reorder right toolbar buttons.
* `507a5e9` Bump version to 0.4.4.
* `7a8c746` Auto-fetch cover after a successful import.

## Important project files

* `calibre_meta_edit.py` — core metadata, import, matching, and Calibre operations.
* `calibre_meta_qt.py` — Qt UI.
* `calibre_meta_app.py` — application model/orchestration.
* `tests/test_calibre_meta_edit.py`, `tests/test_calibre_meta_qt.py`, `tests/test_calibre_meta_app.py` — unit tests.
* `requirements.txt` — pins `PySide6==6.11.1`.

## Available tests and verification

* `python -m pytest`
* `python -m unittest discover -s tests`
* `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py`

## Last test result

Verified in this handoff session on 2026-06-22:

* `python -m pytest`: 461 passed.
* `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py`: passed.
* The prior `PytestCacheWarning` is resolved. It was caused by a local ignored
  `.pytest_cache` path conflict at `.pytest_cache\\v\\cache`; deleting only
  `.pytest_cache` restored a clean cache. No tracked repository files were involved.

## Known risks or inconsistencies

* `000d117` is historical only; `main` and `origin/main` were `23fb06c` when this state was recorded.
* `.env`, `settings.json`, match databases/CSVs, backups, and worktree directories exist locally. Their intended tracking status should be confirmed before any cleanup or commits.
* The project uses `unittest` in its test files, but the requested `pytest` command may require a locally available pytest installation.
* Old unchecked boxes in `docs/superpowers/plans/` are historical implementation plans; current code, tests, and git history are the authoritative task-status evidence.

## Suggested safest next task

Take one narrowly scoped, explicitly specified task. The documented feature backlog is OS-keychain API-key storage with GUI support, more import formats, and bulk import.
