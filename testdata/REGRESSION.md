# Structural regression assertions

Never store PDF text, page images, expected answers, or other content snapshots in this directory.
Store only file fingerprints, structural metrics, labels, thresholds, similarities, and reviewer
judgments. Keep user feedback judgment-level.

## Required inventory

| Sample role | Minimum source | Structural expectation |
|---|---|---|
| Chinese text | User/system Chinese manual | text pages have effective letter/CJK ratio `>= 0.35` |
| Two-column paper | System or public paper | text unless table signals survive `find_tables()` |
| Table manual | Hardware/data-sheet PDF | candidate pages become confirmed table or explained text downgrade |
| Two-column specification table | Hardware product sheet | `table-suspect` from repeated two-field alignment; complete Markdown table after visual validation |
| Product one-pager | Digital PDF with text, diagrams, and icon grid | `visual-layout`; retain semantic text and at least one meaningful figure or visual description |
| Real scan | User-provided `scanned.pdf` | scan classification; user validates key facts |
| Mixed | `pdfunite <text.pdf> scanned.pdf mixed.pdf` | text and scan ranges split at the join |

Record only `sha256`, byte size, page count, source category, and whether redistribution is allowed.

### Labeled local case

| SHA-256 | Bytes | Pages | Category | Redistribution | Reviewer judgment |
|---|---:|---:|---|---|---|
| `bf6e98f73d729d21513e628d53cd7045af26865427368a332c4905486ae48976` | 486433 | 3 | Chinese product one-pager + two-column specification tables | no; user-supplied | page 1 visual-layout; pages 2–3 table |

## Classification oracle

For every page, assert the production label against both structural signals:

- character count, effective letter/CJK ratio, and aligned two-field/three-field starts from the
  one-process `pdftotext` probe;
- raster/image evidence from `pdfimages -list`, summarized as image count and page coverage ratio.

Four sample classes must have zero final route errors. Treat `table-suspect` as an intermediate
label: final table/text judgment includes the mandatory `find_tables()` check and plan writeback.
Any disagreement requires an explanation recorded as a structural reason, never a content answer.

## Extraction oracle

- Run `pdftotext -enc UTF-8 -layout` and `pdfplumber` on text/table candidate pages.
- Normalize whitespace only, then compute `difflib.SequenceMatcher(...).ratio()`.
- Default assertion: ratio `>= 0.80` for ordinary text. A lower ratio is allowed only with a
  structural explanation such as column order, headers/footers, table cell ordering, or glyph map.
- Have the agent visually inspect four pages per document against rendered PNGs. Retain only
  `pass/fail` plus a short structural symptom.
- Run `scripts/check_markdown_quality.py` on every Markdown range. A known-bad raw `pdftotext`
  dump must fail, while the corrected semantic Markdown must pass.
- For scan pages, compare the rendered PNG to model output visually; the user who supplied the scan
  is final reviewer for key facts.

## Boundaries and invariants

- `scan` when non-whitespace characters `<= 20`.
- `scan` when effective letter/CJK ratio `< 0.35` or replacement/control ratio `> 0.05`.
- `table-suspect` never becomes table output unless `find_tables()` confirms at least one page.
- Repeated two-field alignment across at least 6 lines is eligible for `table-suspect`; visual
  validation decides whether it is a table or two-column prose.
- `visual-layout` uses the text layer for values and vision for structure; it never replaces
  available digital text with unconstrained OCR.
- Raw `pdftotext` output renamed to `.md` is not a valid Markdown deliverable.
- Every range output covers exactly its planned page interval.
- `full.md` orders successful ranges monotonically; `tables.md` contains table ranges only.
- Manifest status belongs to `{pending, done, failed}` and every failed range has a `failures[]`
  entry with fingerprint, page type, extractor, and symptom.

## Failure and resume test

1. On a disposable confirmed plan, make one selected range extractor unavailable or feed that range
   a deliberately truncated disposable PDF so both attempts fail.
2. Assert only that range becomes `failed`, other ranges remain `done`, and one or two minimal
   failure records exist without content.
3. Restore the extractor/input and invoke failed-only resume.
4. Assert the source fingerprint and confirmed plan are checked, only the failed range's attempt
   count changes, it becomes `done`, and prior failure history remains.

## Held-out gate

When changing a threshold or rule, designate the motivating PDF as labeled. Re-run all assertions
on at least one other PDF that was not inspected while designing the change. Merge only with zero
held-out regression and a generality argument in `PROBE.md`.
