# C-stage execution

Execute only a confirmed plan. The router coordinates commands and skills but never reads PDF
content as the parser. Create outputs under `./pdf-output/<sanitized-doc-stem>/`.

## Output layout

```text
pdf-output/<doc>/
├── manifest.json
├── full.md
├── tables.md
├── assets/               # retained meaningful figures referenced by Markdown
├── ranges/rXX-YY.md
└── work/                 # transient images and table files; may be removed after validation
```

Build `full.md` by concatenating successful range Markdown in page order. Build `tables.md` only
from confirmed table outputs, with range/page provenance headings. Never include failed-range
placeholders that look like extracted content.

## Manifest schema

Write updates atomically through a sibling temporary file followed by rename.

```json
{
  "schema_version": 1,
  "source": {
    "path": "/abs/doc.pdf",
    "sha256": "...",
    "size_bytes": 0,
    "pages": 0
  },
  "plan": {
    "revision": 1,
    "confirmed_at": "RFC3339 timestamp",
    "dependencies_authorized": [],
    "acroform_suspect": false
  },
  "ranges": [
    {
      "id": "r01-03",
      "pages": [1, 3],
      "probe_type": "text",
      "planned_type": "text",
      "actual_type": "text",
      "extractor": "pdftotext",
      "output": "ranges/r01-03.md",
      "status": "pending",
      "attempts": 0,
      "validation": null,
      "plan_writeback": null
    }
  ],
  "failures": [
    {
      "range_id": "r01-03",
      "page_type": "text",
      "extractor": "pdftotext",
      "symptom": "timeout|empty|mojibake|no-model-output|tool-error",
      "document_fingerprint": "sha256:...",
      "attempt": 2,
      "at": "RFC3339 timestamp"
    }
  ]
}
```

Allowed range status is exactly `pending`, `done`, or `failed`. Keep symptoms judgment-level and
never store content, expected answers, or text snapshots in `failures`.

## Route execution

- `text`: run one `pdftotext -f X -l Y -enc UTF-8 -layout input.pdf work/range.txt` per range. For
  plain-text output this may be the deliverable. For Markdown output, load `processing-pdf` once
  and delegate semantic headings and paragraph construction from that authoritative text source.
  Render only when visual evidence is needed for structure. The router must not write or rewrite
  deliverable prose, and raw layout text must never be copied directly to a `.md` file.
- `scan`: load `processing-pdf` once. Prefer its bundled `scripts/to_images.py`; render the source
  once and consume only planned scan pages. Ask the agent vision model for Markdown per range and
  require an explicit page result for every page.
- `visual-layout`: load `processing-pdf` once. Render at 200–250 DPI, retain the PDF text layer as
  the authority for wording, numbers, and units, and use vision only to recover reading order,
  headings, lists, tables, and meaningful figures. Save retained figures under `assets/` and use
  correct relative paths in both range files and `full.md`. Do not satisfy this route by embedding
  only a full-page screenshot.
- `table-suspect`: load `extracting-pdf-text` once. Before extraction, use `pdfplumber` and call
  `page.find_tables()` on every page in the range. Visually compare detected boxes with the page;
  fragmentary table detection is not complete extraction. If no page has a table, set
  `actual_type` to `text` or `visual-layout`, record the reason, and run that route. Otherwise
  extract complete tables with page provenance into both the range file and `tables.md`.
- `form`, `merge`, `split`, `manipulate`, `generate`: load `pdf` once and follow that skill. Confirm
  AcroForm with its form checker; the strings precheck alone is insufficient.

## Self-checks

- Text: output non-whitespace count must be at least `max(20, floor(0.5 * probe_chars))`; effective
  letter/CJK ratio must be `>= 0.35`; replacement/control ratio must be `<= 0.05`. Markdown output
  must contain semantic structure appropriate to the page and must not retain form-feed separators.
- Scan: every planned page must have a rendered image and non-empty model-produced Markdown. The
  agent must visually compare output against the PNG before marking done.
- Visual-layout: every page must have a render, non-empty Markdown, a visual comparison result, and
  text-layer reconciliation when text exists. Every local image reference must resolve.
- Table: `find_tables()` evidence must exist for at least one retained table page; every emitted
  table needs range/page provenance and visual completeness validation. No-table writeback is a
  successful text or visual-layout downgrade.
- Forms/manipulation/generation: use the delegated `pdf` skill's validation and verify page count,
  expected fields or operation, and output readability.

For every Markdown range, run:

```bash
python3 scripts/check_markdown_quality.py input.pdf ranges/rXX-YY.md \
  --pages X-Y --expected-type text|table|visual-layout|scan
```

Store only its metrics and judgment-level issues in the manifest. For table routes, require
`find_tables()` evidence, a Markdown separator row, and at least three non-separator rows. A `.md`
file with no headings, tables, lists, or image references must fail when the source page visibly
contains those structures. Dense raw-layout spacing fails even if an incidental list marker exists.

## One-retry degradation matrix

| Initial route and symptom | Single retry | Result after retry fails |
|---|---|---|
| text: empty, too short, or mojibake | route the same range through scan at 300 DPI | `failed` |
| text: command timeout/error | rerun once on only that range; if output exists but fails quality, use scan instead | `failed` |
| scan: missing page/model output | rerender only affected pages at 300 DPI and run vision page by page | `failed` |
| visual-layout: missing structure or unresolved figure | rerender at 300 DPI, rebuild page by page, and reconcile against text layer | `failed` |
| table: `find_tables()` returns none | write back to text or visual-layout; this is not a failure | selected route self-check decides |
| table: extractor returns fragments or invalid table output | retry with visual-layout while preserving text-layer values | `failed` if visual-layout check fails |
| delegated PDF operation fails | retry once with the delegated skill's safest alternate method | `failed` |

Use local-script fallbacks only if the corresponding target skill is absent. Record the missing
skill, fallback command, and validation in the manifest.

## Resume failed ranges

Resume only when source `sha256`, confirmed plan revision, dependencies, and output root match the
manifest. Select only `status == "failed"`, reset those ranges to `pending`, keep failure history,
and rerun the same one-retry policy. Reconfirm if anything material changed.

Example agent command:

```bash
codex exec '使用 $route-pdf-tasks 按 ./pdf-output/<doc>/manifest.json 只重跑 failed 区间；校验原文件指纹和已确认计划不变。'
```
