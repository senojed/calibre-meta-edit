# Folder author + junk-metadata demotion — design (phase 1)

## Background

After adding MOBI/AZW3/PDB import, manual testing showed weak embedded metadata
(typical for PDB) winning over better local hints. Example: `Kobercove.pdb` in a
`Terry_Pratchett` folder produced preview title `Pratchett_Terry-Kobercove`, author
`Neznámý`, even though the folder names the author and the book is on databazeknih.

Root cause (verified in code): both the online search query and candidate scoring are
driven by `_signal_book(signals)`, which picks the single highest-quality signal via
`signal_preview_quality`. The embedded-metadata signal wins because it has both fields
filled (completeness 2) and confidence 60, while the filename signal has only a title
and confidence 30. So junk metadata drives a bad search, the correct online record
scores low (databazeknih "Kobercové" got 11%), and nothing recovers.

## Goal

When embedded metadata is junk, let a clean local signal win so the online search finds
the right record (online stays the primary source of truth). Two changes:

1. **Folder → author:** derive the author from the immediate parent folder when it looks
   like a person name, filling the otherwise-empty author on the path signal.
2. **Junk demotion:** rank signals whose title looks filename-derived (junk) below clean
   signals in `signal_preview_quality`, so a clean filename+folder signal beats junk
   embedded metadata for both search and the fallback preview.

Net effect on the example: the path signal becomes `Kobercove` + `Terry Pratchett`
(clean), outranks the junk `Pratchett_Terry-Kobercove` / `Neznámý`, drives a good search,
databazeknih "Kobercové" scores high and wins.

## Scope

- In scope: `import_signal_from_path` (folder author), `signal_preview_quality` (junk
  demotion), two small pure helpers, backend tests. `calibre_meta_edit.py` only.
- Out of scope (phase 2): reading the book-start text for title/author. No change to the
  online search functions, candidate scoring formulas, AI resolver, or UI.
- Out of scope: configurable behavior / settings. The stoplist and junk markers are
  small static constants.

## Design

### 1. Folder → author in `import_signal_from_path`

Today (`calibre_meta_edit.py:489`):

```python
def import_signal_from_path(path):
    file_path = Path(path)
    title, authors = split_author_title_from_filename(file_path.stem)
    folder_text = repair_filename_text(" ".join(part for part in file_path.parts[:-1] if part))
    return ImportSourceSignal(source="filename", title=title, authors=authors, text=folder_text, confidence=30)
```

Change: when `split_author_title_from_filename` yields no author, try the immediate
parent folder. New pure helper:

```python
_FOLDER_AUTHOR_STOPWORDS = {
    "knihy", "kniha", "books", "book", "ebooks", "ebook", "e-knihy", "audiobooks",
    "audioknihy", "kindle", "calibre", "library", "knihovna", "komiksy", "stahnute",
    "downloads", "temp", "tmp",
}


def folder_author_hint(parent_name: str) -> str:
    """Vrati autora ze jmena slozky kdyz vypada jako jmeno osoby, jinak "".

    Konzervativni: presne dve slova, obe pismenna (vc. diakritiky a teckovych
    iniciel), zacinaji velkym pismenem, a slozka neni v stoplistu obecnych nazvu.
    Poradi jmeno/prijmeni nehadame - online nalez kanonicky tvar opravi.
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

`import_signal_from_path` then becomes:

```python
def import_signal_from_path(path):
    file_path = Path(path)
    title, authors = split_author_title_from_filename(file_path.stem)
    if not authors and len(file_path.parts) >= 2:
        authors = folder_author_hint(file_path.parts[-2])
    folder_text = repair_filename_text(" ".join(part for part in file_path.parts[:-1] if part))
    return ImportSourceSignal(source="filename", title=title, authors=authors, text=folder_text, confidence=30)
```

The folder name order is kept as-is (no first/last swap). For search this is irrelevant
(query concatenates title + authors); for display the online match supplies the canonical
form, and `normalize_author_display_names` already handles comma forms.

### 2. Junk demotion in `signal_preview_quality`

A signal is "junk" when its title looks filename-derived. The simplest reliable marker is
an underscore in the title (real book titles don't contain `_`; filename-derived ones do,
e.g. `Pratchett_Terry-Kobercove`, `_asn_ zem_plocha - 21`). New pure helper:

```python
def is_junk_signal(signal: ImportSourceSignal) -> bool:
    """Pozna signal jehoz nazev vypada jako z nazvu souboru (junk).

    Marker: podtrzitko v nazvu. Realne nazvy knih '_' nemaji, filename-derived ano.
    """
    return "_" in signal.title
```

`signal_preview_quality` gains a leading "not junk" component so any non-junk signal
outranks any junk signal, while the existing ordering among non-junk signals is unchanged:

```python
def signal_preview_quality(signal: ImportSourceSignal) -> tuple[int, int, int, int]:
    preview_text = " ".join(part for part in (signal.title, signal.authors) if part.strip())
    clean_bonus = 100 if preview_text and not has_known_mojibake(preview_text) else 0
    completeness = int(bool(signal.title.strip())) + int(bool(signal.authors.strip()))
    not_junk = 0 if is_junk_signal(signal) else 1
    return not_junk, completeness, clean_bonus, signal.confidence
```

Because `signal_preview_quality` feeds `choose_initial_import_preview`,
`_best_normalized_title`, and `_best_normalized_authors`, junk demotion applies uniformly
to the fallback preview and to the search/scoring inputs.

## Data flow (example: Kobercove.pdb in Terry_Pratchett/)

- ebook-meta signal: title `Pratchett_Terry-Kobercove` (underscore → junk), author `Neznámý`.
  Quality `(0, 2, 100, 60)`.
- path signal: title `Kobercove`, author `Terry Pratchett` (from folder). Quality `(1, 2, 100, 30)`.
- Path signal outranks junk (`1 > 0`). `_signal_book` → `Kobercove` / `Terry Pratchett`.
- Online search finds databazeknih "Kobercové", scores high, wins → preview shows the clean
  online record. If online finds nothing, the fallback preview is the clean path signal,
  not the junk.

## Error handling

- No new external calls; pure string logic. No new failure modes.
- A path with no parent (`len(parts) < 2`) skips the folder hint. Empty/odd folder names
  fail the guard and yield `""` (author stays empty, as today).

## Testing (backend, no network/Calibre)

- `folder_author_hint`: `"Terry_Pratchett"` → `"Terry Pratchett"`; `"Pratchett_Terry"` →
  `"Pratchett Terry"` (kept as-is); `"Knihy"` → `""` (one token); `"e-knihy_cast_T_Z"` →
  `""` (not two tokens); `"Audio_Knihy"` → `""` (stoplist token `knihy`);
  `"J. R. R. Tolkien"` (4 tokens) → `""`.
- `import_signal_from_path`: file in `...\Terry_Pratchett\Kobercove.pdb` → author
  `Terry Pratchett`; file directly in `E:\Knihy\Kobercove.pdb` → author `""`; a filename
  that already yields an author (`Author - Title.epub`) keeps the filename author (folder
  not consulted).
- `is_junk_signal`: underscore title → True; clean title → False.
- `signal_preview_quality`: a clean path signal outranks a junk metadata signal; ordering
  among two clean signals is unchanged (regression guard).
- `choose_initial_import_preview`: given junk metadata + clean filename+folder signals,
  the preview title/author come from the clean signal.
- `_signal_book`/`_best_normalized_title`/`_best_normalized_authors`: with junk + clean
  signals, return the clean title/author (drives the search).
- Back-compat: existing `signal_preview_quality`, `choose_initial_import_preview`, and
  EPUB analyze tests still pass (clean titles have no underscore → `not_junk = 1` for all,
  so existing relative ordering is preserved).

## Out of scope / future (phase 2)

- Use the book-start text (via ebook-convert / epub spine) as additional search terms and,
  offline, a heuristic title/author parse. Separate spec.
- Smarter junk markers (no-space-all-dashes titles, placeholder-author detection) if the
  underscore marker proves insufficient in practice.
