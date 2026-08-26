# C-stage execution

Execute only a confirmed plan. The router coordinates commands and skills but never reads PDF
content as the parser. Create outputs under `./pdf-output/<sanitized-doc-stem>/`.

## Output layout

```text
pdf-output/<doc>/
├── manifest.json
├── full.md
├── tables.md
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

- `text`: run one `pdftotext -f X -l Y -enc UTF-8 -layout input.pdf output.md` per range. This is
  inline execution and loads no skill.
- `scan`: load `processing-pdf` once. Prefer its bundled `scripts/to_images.py`; render the source
  once and consume only planned scan pages. Ask the agent vision model for Markdown per range and
  require an explicit page result for every page.
- `table-suspect`: load `extracting-pdf-text` once. Before extraction, use `pdfplumber` and call
  `page.find_tables()` on every page in the range. If no page has a table, set `actual_type` to
  `text`, set `plan_writeback` to `no-tables-found`, and run the text route. Otherwise extract
  tables with page provenance into both the range file and `tables.md`.
- `form`, `merge`, `split`, `manipulate`, `generate`: load `pdf` once and follow that skill. Confirm
  AcroForm with its form checker; the strings precheck alone is insufficient.

## Self-checks

- Text: output non-whitespace count must be at least `max(20, floor(0.5 * probe_chars))`; effective
  letter/CJK ratio must be `>= 0.35`; replacement/control ratio must be `<= 0.05`.
- Scan: every planned page must have a rendered image and non-empty model-produced Markdown. The
  agent must visually compare output against the PNG before marking done.
- Table: `find_tables()` evidence must exist for at least one retained table page; every emitted
  table needs range/page provenance. No-table writeback is a successful text downgrade.
- Forms/manipulation/generation: use the delegated `pdf` skill's validation and verify page count,
  expected fields or operation, and output readability.

## One-retry degradation matrix

| Initial route and symptom | Single retry | Result after retry fails |
|---|---|---|
| text: empty, too short, or mojibake | route the same range through scan at 300 DPI | `failed` |
| text: command timeout/error | rerun once on only that range; if output exists but fails quality, use scan instead | `failed` |
| scan: missing page/model output | rerender only affected pages at 300 DPI and run vision page by page | `failed` |
| table: `find_tables()` returns none | write back to text; this is not a failure | text self-check decides |
| table: extractor error or invalid table output | retry the range as text and record table loss | `failed` if text check fails |
| delegated PDF operation fails | retry once with the delegated skill's safest alternate method | `failed` |

Use local-script fallbacks only if the corresponding target skill is absent. Record the missing
skill, fallback command, and validation in the manifest.

## Resume failed ranges

Resume only when source `sha256`, confirmed plan revision, dependencies, and output root match the
manifest. Select only `status == "failed"`, reset those ranges to `pending`, keep failure history,
and rerun the same one-retry policy. Reconfirm if anything material changed.

Example agent command:

```bash
codex exec '使用 $pdf-router 按 ./pdf-output/<doc>/manifest.json 只重跑 failed 区间；校验原文件指纹和已确认计划不变。'
```
