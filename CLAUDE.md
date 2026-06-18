# CLAUDE.md

## Project

Calibre Meta Edit is a Python/Qt application for reviewing book metadata, matching metadata sources, importing EPUB files, and safely writing metadata to a Calibre library.

## Current branch/worktree

Work is done on the `epub-import` branch/worktree.

## Development rules

* Work in small task-based commits.
* One task = one commit.
* Do not start the next task until the current task is reviewed and clean.
* Preserve backend behavior unless the current task explicitly requires backend changes.
* Prefer small, test-first changes.
* Keep UI and backend concerns separated.
* Do not silently broaden scope.
* Do not add generated files, backup files, exported diffs, or local `.work/` files to git.

## Test commands

Use these commands before reporting completion:

```powershell
python -m unittest discover -s tests -p test_calibre_meta_edit.py
python -m unittest discover -s tests -p test_calibre_meta_qt.py
python -m unittest discover -s tests
python -m py_compile calibre_meta_edit.py calibre_meta_qt.py
```

Note: `python -m unittest discover` without `-s tests` may not discover tests in this project layout.

## Current completed task state

* Task 7: Support import cover bytes
* Task 8: Apply EPUB import preview
* Task 9: Add optional Ollama import resolver
* Task 10: Qt Import Dialog Skeleton
* Task 11: Qt Import Button And Analysis Worker
* Task 12: Qt Apply Worker And Import Commit
* Task 13: Preferences UI
* Latest clean Task 13 commit: `7d218f8 Add AI import settings to Preferences UI`

### Post-Task 13 smoke-test/UX fixes

* Fix disabled EPUB import toolbar button
* Fix EPUB import toolbar click
* Improve EPUB import dialog candidate UX
* Mark imported EPUB rows for review
* Show review rows after EPUB import

## Final smoke test state

EPUB import flow was manually smoke tested.

Verified manually:

* Preferences
* Import EPUB button
* file picker
* analysis dialog
* candidate selection including low-score candidates
* duplicate detection
* apply/import
* backup creation
* table reload
* imported rows marked review
* review filter shown after import

Pre-merge AI resolver edge-case tests (backend-only, added):

* malformed Ollama response returns None gracefully
* AI confidence below threshold falls back to scored candidate

Final pre-merge EPUB import UX simplification (completed):

* simplified import dialog to decision/confirmation workflow
* removed redundant editable metadata fields from the import dialog
* candidate selection updates the final import preview
* success confirmation popup after import removed
* error/warning dialogs kept
* EPUB import toolbar icon made distinct
* hidden candidate metadata leak between candidate selections fixed

Final automated verification:

* `python -m unittest discover -s tests`: 323 OK
* `python -m py_compile calibre_meta_edit.py calibre_meta_qt.py`: OK

Next state: ready for merge/release review.

## Next task

Awaiting next task assignment.

## Reporting format

After each task, report:

* commit hash
* changed files
* tests run
* test results
* py_compile result
* untracked files
* whether worktree is clean
* whether the next task was started

Stop after each task and wait for review.
