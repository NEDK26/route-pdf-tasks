---
name: pdf-router
description: Route PDF work page by page without parsing content itself, including high-fidelity PDF-to-Markdown conversion. Use when a user asks to 处理PDF、解析PDF、提取文本、OCR、识别扫描件、提取表格、保留图片版式、填写表单、合并PDF、生成PDF, or otherwise process a .pdf file and the work needs probing, a range plan, explicit confirmation, delegated execution, and structural quality validation.
---

# PDF Router

Act only as a thin dispatcher. Never parse, OCR, interpret, summarize, or reconstruct PDF
content inside the router. Delegate extraction to the selected skill or invoke the documented
local command. Do not perform cross-page RAG post-processing.

## Non-negotiable rules

1. Run only probe operations before confirmation. Never extract deliverables, install
   dependencies, alter PDFs, or dispatch an execution skill before explicit confirmation.
2. Present a range plan and wait for one of: confirm, adjust a range, or abandon. Silence and
   ambiguous assent are not confirmation.
3. Treat confirmation as authorization to install only dependencies explicitly listed in that
   plan.
4. Use `pdftotext` as the authoritative text source for text ranges. Never treat raw
   `pdftotext` output with a `.md` suffix as a finished Markdown deliverable.
5. Route scan and `visual-layout` ranges to `processing-pdf`, table ranges to
   `extracting-pdf-text`, and forms, merge, split, manipulation, or generation to `pdf`.
6. Load each target skill at most once for the whole task, even when it serves several ranges.
7. Fall back to local `pdftotext`, `pdftoppm`, or a narrowly scoped Python script only when the
   target skill is missing. Record the fallback in the plan and manifest.

## A. Probe

Read [PROBE.md](PROBE.md) completely, then probe the input. Wrap each external probe command in
`timeout 10s`. Use one full-document `pdftotext -enc UTF-8 -layout` process and split its output
on form feed to obtain page statistics. Detect encryption before extraction. Mark AcroForm only
as a document-level suspicion.

Classify every page as `scan`, `table-suspect`, `visual-layout`, or `text`, retaining the evidence
and thresholds.
Treat low effective-word density as `scan` even if nominal text exists. Probe output is evidence,
not a content deliverable.

## B. Plan and confirm

Read [PLAN_TEMPLATE.md](PLAN_TEMPLATE.md) completely. Merge adjacent pages with the same route
into ranges. Show page range, type, method, estimated cost, output file, and every dependency or
fallback. For `table-suspect`, state that execution will first call `find_tables()`, visually
validate fragments, and may write the range back to `text` or `visual-layout`. For
`visual-layout`, state that the text layer remains authoritative while vision reconstructs
structure and figures.

Ask the user to confirm, adjust one or more ranges, or abandon. If adjusted, regenerate the plan
and ask again. Stop after presenting the plan until explicit confirmation arrives.

## C. Execute confirmed plan

After confirmation only, read [EXECUTE.md](EXECUTE.md) completely. Create
`./pdf-output/<doc>/manifest.json` before range work. Execute ranges in page order while updating
`pending`, `done`, and `failed` atomically. Support resume of only failed ranges when the source
fingerprint and confirmed plan are unchanged.

Write range outputs to `ranges/rXX-YY.md`, then build `full.md` in page order and `tables.md` from
confirmed table ranges. Run the route-specific self-check and
`scripts/check_markdown_quality.py` for Markdown deliverables. On failure, retry once using the
degradation matrix; if it still fails, mark the range `failed` and append a minimal failure
record. Never invent missing output.

## D. Report

Report every planned range with a checked success or failed marker, the actual route, output
path, validation result, and any plan writeback. For each failed range, give the recorded reason
and a command or agent prompt that resumes only failed ranges. State which dependencies were
installed and which fallbacks were used.

Keep user feedback judgment-level only. Apply the regression and iteration disciplines in
[SOURCES.md](SOURCES.md) and [testdata/REGRESSION.md](testdata/REGRESSION.md).
