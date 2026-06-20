# AI text extraction for import identity

Date: 2026-06-20
Status: approved design, pending implementation plan

## Problem

Import pipeline identifies a book by building an online search query from its
signals. The query is built from the "best" title + author signal, which today
comes from the filename or embedded metadata.

This fails when both filename and metadata are unreliable at the same time.
Observed failures (manual test on `.pdb` files):

- `UZ-20-Hrrr_na_ne.pdb` -> query `UZ-20-Hrrr na ne`. `UZ-20-` is a series code
  (Uzasna Zemeplocha dil 20), not part of the title. Online search returns junk.
- `Terry_Pratchett\UZ-20-Hrrr_na_ne.pdb` -> same junk title, even though folder
  gives the author.
- `Terry_Pratchett\x2nesmydl#asd.pdb` -> garbage filename, no usable title.

In all three the embedded metadata was also junk (e.g. `_asn_ zem_plocha - 21`).

Series codes and garbage filenames are unbounded - regex stripping cannot scale.

## Key insight (verified with data)

The actual book text is the most reliable identity source. Running
`ebook-convert` on `UZ-20-Hrrr_na_ne.pdb` returned text starting exactly with:

```
Terry Pratchett

HRR NA NĚ!
```

We already extract this start text (`extract_book_start_text_with_convert`,
`limit` chars) and pass it into the pipeline as the `epub-text` signal. Today
that signal carries only raw text - nobody pulls a title/author out of it.

## Solution

Add a local-AI extraction step: feed the book start text to Ollama, ask it to
return the real title and author, and turn that into a new high-priority signal.

### Reliability priority (user requirement)

```
ai-text  >  metadata  >  filename / folder
```

The AI-extracted identity is the most trusted, then embedded metadata, then the
filename/folder guess. This priority governs both:

1. the online search query
2. the preview shown in the import dialog

## Components

### 1. AI extractor

New capability on the existing Ollama layer (reuse endpoint, model, requester
config - do not introduce a second AI configuration).

- Input: book start text (the same string already produced for the `epub-text`
  signal).
- Output: `(title, author, confidence)`. Empty title means "could not extract".
- Prompt: ask for JSON only, e.g.
  `{"title":"...","author":"...","confidence":0-100}`. Instruct the model the
  text is the opening of a book and the real title/author usually appear near
  the top, ahead of any filename-derived noise.
- On any error (request fails, bad JSON, empty title): return empty -> no signal.

This is a distinct role from the existing `OllamaAIResolver.resolve`, which
picks among already-found online candidates. Both roles stay. The extractor
improves the query; the resolver still validates against the online DB.

### 2. New signal `ai-text`

`import_signal_from_ai_extraction(title, author, confidence) -> ImportSourceSignal`
with `source="ai-text"`.

Created only when the extractor returns a non-empty title. When Ollama is
disabled or extraction fails, no `ai-text` signal exists and the pipeline
behaves exactly as today.

### 3. Explicit source priority (approach B)

Introduce an explicit source-priority ordering used by title/author selection
and preview, independent of the existing `signal_preview_quality` completeness
ranking.

```
ai-text        : highest
ebook-meta     : metadata
epub-metadata  : metadata
filename       : filename / folder
epub-text      : lowest (raw text, no parsed title)
```

Selection rule for best title (and, separately, best author):
among signals whose value is non-empty AND not junk, pick the one from the
highest-priority source. This directly encodes the user's hierarchy and avoids
the cross-field flaw of approach A.

Approach A (just bump `ai-text` confidence to ~95) was rejected: the existing
quality tuple ranks by completeness (title+author present) before confidence,
so a filename signal with both fields filled (junk title + folder author) could
outrank a clean AI signal that only recovered the title. Approach B selects by
source trust, so this cannot happen.

Junk and empty values are still skipped, so the locked clean-beats-junk
behavior is preserved.

## Pipeline integration

In `analyze_book_for_import`, after the existing text extraction and before
building signals:

1. Keep current signals: metadata, epub-text, path.
2. If an AI resolver is present and enabled, call the extractor on the start
   text. If it returns a title, prepend/insert an `ai-text` signal.
3. Query building (`_signal_book` -> `_best_normalized_title` /
   `_best_normalized_authors`) and preview (`choose_initial_import_preview`)
   honor the source priority, so `ai-text` wins when present.
4. Online lookup, scoring, and the existing candidate resolver run unchanged.

## Fallback chain

| Situation                                   | Result                          |
|---------------------------------------------|---------------------------------|
| Ollama disabled (`DisabledAIResolver`)      | no `ai-text`, today's behavior  |
| Ollama on, request fails / bad JSON / empty | no `ai-text`, metadata/filename |
| AI returns title but no author              | `ai-text` title only; author from next priority source |
| AI returns title + author                   | `ai-text` wins title and author |

## Cost / tradeoffs

- Adds one LLM call per analyzed book (the extractor), on top of the existing
  resolver call. Noticeable for large batch imports.
- More code: new signal, extractor, source-priority logic, tests.
- Book text is not always clean (front matter, table of contents, dedication).
  The model usually handles it, not guaranteed 100%.

## Model recommendation (not code change)

The current configured Ollama model is `qwen2.5-coder:14b`, a code model, poorly
suited to extracting prose identity. Recommend an instruct model such as
`qwen2.5:14b` or `llama3.1:8b`. This is a user settings change, not part of this
task; noted here only as guidance.

## Revision 2026-06-20: online-arbitrated multi-seed lookup

Manual testing exposed a flaw in the "ai-text always wins" priority. For
`Strata.pdb` the book text opens with `TERRY PRATCHETT / STRATA`, but a few lines
down an epigraph quotes a fictional in-world book, `dr. Carl Untermond /
Přeplněný Eden`. The local `llama3.1:8b` model returned `Přeplněný Eden` as the
title - a real string from the text, but the epigraph, not the heading. Because
`ai-text` had top priority it overrode the correct `filename: Strata` and
`ebook-meta: Strata`, making the result worse than with AI disabled (plain
filename "Strata" finds the book).

Conclusion: a local 8B model is not reliable enough to be trusted
unconditionally over agreeing conventional sources. A fixed priority is the
wrong arbiter.

New approach: let the online database arbitrate.

- Build multiple query seeds: a conventional seed (best non-junk title/author
  ignoring `ai-text`) and an AI seed (the `ai-text` title/author). Deduplicate
  identical seeds so an agreeing AI costs no extra lookup.
- Run the online lookup for each seed.
- Score each returned candidate against the seed that produced it (a query that
  finds an exact DB match scores high; a wrong query that finds only loose
  matches scores low - the DB decides what actually exists).
- Deduplicate candidates by URL, keeping the highest score, and pick the best.
- The final preview title/author/URL come from the winning DB candidate, not
  from a possibly-wrong seed.

Worked examples:
- `Strata`: conventional "Strata" -> exact DB match (high). AI "Přeplněný Eden"
  -> only ~11% loose matches. Strata wins. Correct.
- `UZ-20-Hrrr_na_ne`: conventional "UZ-20-Hrrr na ne" -> weak. AI "Hrr na ně"
  -> strong DB match. AI wins. Correct.

Residual edge case (accepted): if a wrong AI title happens to be a real, indexed
book, its candidate could score high. Rare; deferred.

Candidate-resolver guard: the existing `resolve_import_candidate_with_ai` could
still let the AI candidate-picker choose a low-scoring candidate. Add a guard so
an AI-chosen candidate is only accepted when its own score meets the minimum
(same threshold used for the score-based fallback). This stops the AI picker
from selecting an 11% candidate over a 100% one.

Role of the earlier source-priority work (Tasks 1-2): retained, but now only
governs the fallback preview used when the online lookup returns nothing for any
seed. When the DB returns matches, online score arbitrates and overrides the
fixed priority.

Diagnostics: route the `calibre_meta` logger output produced during an import
analysis into the app's "Log" tab, so AI extraction steps and failures are
visible in the app (not only on a console the app may not have).

## Out of scope

- Changing the default Ollama model in code.
- Folder author hint walk-up for `Author/Series/file` layouts (separate finding).
- Stripping series codes by regex (the reason we chose AI extraction instead).
- Smarter prompt engineering to skip epigraphs (the online arbitration makes a
  perfect extraction unnecessary; a wrong AI title simply loses to a better
  online match).

## Success criteria

- `UZ-20-Hrrr_na_ne.pdb` -> AI extracts `Hrr na ně` / `Terry Pratchett` -> query
  finds the correct book.
- `Terry_Pratchett\x2nesmydl#asd.pdb` -> AI recovers identity from text despite
  garbage filename.
- Ollama disabled -> behavior identical to current main.
- Existing test suite stays green; new tests cover extractor, `ai-text` signal,
  source-priority selection, and the fallback chain.
