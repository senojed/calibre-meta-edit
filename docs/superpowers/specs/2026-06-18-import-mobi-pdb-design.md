# Import MOBI / AZW3 / PDB — design

## Goal

Extend single-file book import (today EPUB-only) to also accept **MOBI, AZW3, PDB**.
Today selecting a non-EPUB file via the picker's "all files" option crashes: the
analyzer calls `read_epub_metadata`, which runs `zipfile.ZipFile(path)`, and these
formats are not zip archives.

## Scope

- In scope: MOBI, AZW3, PDB import (metadata + body-text extraction for preview/matching).
- Out of scope: running without Calibre installed (the app is a Calibre support
  utility; Calibre is assumed present). No "Calibre-absent" code path.
- Out of scope: any change to the online lookup, candidate scoring, AI resolver,
  duplicate detection, or preview logic — these run on signals and stay untouched.
- Out of scope: new AI capability (extracting title/author from body text). Current
  AI behavior (choose among online candidates) is kept as-is.

## Key decision: use Calibre CLI tools, not custom parsers

Calibre is already a hard dependency (the app shells out to `calibredb`). It ships
`ebook-meta` (reads metadata from any supported format) and `ebook-convert`
(converts to txt). Reusing them avoids fragile binary parsing of Palm/MOBI containers
(EXTH headers, PalmDOC/HUFF/CDIC compression, KF8, eReader vs PalmDOC variants).

- Metadata: `ebook-meta <file>` → parse stdout.
- Body text: `ebook-convert <file> <tmp>.txt` → read first N chars.

## Architecture

### Format dispatch

A single source of truth for the formats handled via Calibre tools:

```python
EBOOK_TOOL_FORMATS = {".mobi", ".azw3", ".pdb"}
```

New generic entry point dispatches by file suffix (lowercased):

```
analyze_book_for_import(path, library, settings, ...)
  .epub                 -> read_epub_metadata + extract_epub_start_text   (stdlib, unchanged)
  in EBOOK_TOOL_FORMATS -> ebook-meta metadata + ebook-convert body text
  otherwise             -> raise a clean "unsupported-format" error (surfaced as a
                           message, never a crash). The picker prevents reaching here.
```

`analyze_epub_for_import` stays as a thin wrapper delegating to `analyze_book_for_import`
so existing callers and tests keep working unchanged (no public rename).

The file picker filter and the dispatch both derive from `EBOOK_TOOL_FORMATS` (+ `.epub`),
so adding a future format = add one extension + a test. Anything Calibre's tools support
becomes a one-line addition; EPUB is the only permanent special case (its own stdlib path).

### New backend units (each pure or runner-injectable, testable without Calibre)

1. `find_ebook_tool(name, which_func=..., exists_func=...) -> str | None`
   Resolves `ebook-meta` / `ebook-convert` the same way as `find_calibredb`:
   `shutil.which(name)`, else the sibling of the `Calibre2` fallback dir.

2. `parse_ebook_meta_output(text: str) -> EpubMetadata`
   **Pure** function. Parses `ebook-meta` stdout lines of form `Label : value`:
   - Title          -> title
   - Author(s)      -> authors; strip the trailing ` [Sort, Name]` sort form if present;
                        keep the human display order; multiple authors joined with ` & `
   - Publisher      -> publisher
   - Languages      -> language (first listed)
   - Published      -> published_year via existing `extract_year` (value is ISO datetime)
   Unknown/missing labels are ignored; absent fields stay empty.
   Reuses the existing `EpubMetadata` dataclass (its fields title/authors/language/
   publisher/published_year are format-neutral).

3. `read_book_metadata_with_ebook_meta(path, ebook_meta_path, runner) -> EpubMetadata`
   Runs `ebook-meta <path>`, feeds stdout to `parse_ebook_meta_output`. On non-zero exit
   or empty output, returns an empty `EpubMetadata` (treated as "this file has no readable
   metadata" — see Error handling).

4. `extract_book_start_text_with_convert(path, ebook_convert_path, runner, limit=5000) -> str`
   Runs `ebook-convert <path> <tmpfile>.txt` into a temp file, reads up to `limit` chars,
   deletes the temp file. On failure returns "".

### Signals

Reuse the existing 3-signal model:
- metadata signal — built from `EpubMetadata` (whatever source produced it)
- body-text signal — first ~5000 chars (epub spine text, or ebook-convert output)
- filename+folder signal — `import_signal_from_path` (already format-agnostic; gives
  title/author from the filename and folder structure as evidence text). Reused as-is.

`choose_initial_import_preview` currently finds the metadata signal by
`signal.source == "epub-metadata"` to pull publisher/year. Generalize this: introduce a
small set of metadata source labels (e.g. `METADATA_SIGNAL_SOURCES = {"epub-metadata",
"ebook-meta"}`) and select the metadata signal by membership, so non-EPUB formats also
contribute publisher/year to the preview. Behavior for EPUB is unchanged.

### Apply path

`apply_import_preview` adds the file via `calibredb add <path>` — already format-agnostic.
No semantic change. The `epub_path` parameter is a plain file path; it may be renamed to
`book_path` for clarity (back-compat kept if any test uses the keyword) but this is
cosmetic and optional.

## Error handling (graceful, not crash)

Two distinct cases, kept separate:

- **File has missing/corrupt metadata** (`ebook-meta` returns nothing useful): continue
  with the filename+folder signal and online lookup, exactly like an EPUB with empty OPF.
  This covers the user's "metadata missing or damaged" concern.
- **Tool call fails** (non-zero exit, tool not found at the resolved path): surface a clean
  `Import knihy: CHYBA` message (same pattern as the existing EPUB import error path),
  never a stack trace. We do not build a no-Calibre feature path; we just fail cleanly.
- **Unsupported suffix reaches the dispatcher** (only via a manually typed path): clean
  "unsupported-format" error, not a crash.

`is_valid_import_preview` already blocks apply when title or author is empty
(`missing-title-or-author`), so a file that yields no usable metadata cannot be written
silently.

## UI changes (calibre_meta_qt.py only)

- File picker (`_choose_epub_file`): filter derived from `EBOOK_TOOL_FORMATS` + epub →
  `"Knihy (*.epub *.mobi *.azw3 *.pdb);;EPUB (*.epub);;Vsechny soubory (*.*)"`.
- Resolve `ebook-meta` / `ebook-convert` paths once and pass them into the analysis
  `settings`, alongside the existing `epub_text_limit`.
- Rename visible labels "Import EPUB" → **"Import knihy"** (button tooltip, dialog title,
  status/error messages). Behavior, callbacks, signal connections, icon loading unchanged.

## Testing

All without a real Calibre install (inject runners / feed sample text):

- `parse_ebook_meta_output`: full output, partial (some labels missing), empty, author
  with `[Sort, Name]` suffix, multiple authors, ISO `Published` → year.
- `find_ebook_tool`: `which` hit; fallback to Calibre2 sibling; not found → None.
- `read_book_metadata_with_ebook_meta`: injected runner returns sample stdout → expected
  `EpubMetadata`; non-zero exit → empty metadata.
- `extract_book_start_text_with_convert`: injected runner writes a temp txt → first N
  chars returned; failure → "".
- Dispatch: `.mobi`/`.azw3`/`.pdb` route through the ebook-tool path (with injected
  extractors), `.epub` routes through the stdlib path, unknown suffix raises.
- `choose_initial_import_preview`: a non-EPUB metadata signal contributes publisher/year.
- Back-compat: existing `analyze_epub_for_import` tests pass unchanged.

## Commit plan (2 commits)

1. Backend: `EBOOK_TOOL_FORMATS`, dispatch + `analyze_book_for_import`, `find_ebook_tool`,
   `parse_ebook_meta_output`, `read_book_metadata_with_ebook_meta`,
   `extract_book_start_text_with_convert`, metadata-source generalization, + all backend
   tests. `analyze_epub_for_import` becomes a wrapper.
2. UI: picker filter, tool-path resolution into settings, "Import knihy" relabel, + any
   qt-level tests.

## Out of scope / future

- FB2, TXT, PDF: trivial later additions (extend `EBOOK_TOOL_FORMATS` + a test).
- AI extracting title/author from body text when metadata is absent (separate feature,
  own spec).
