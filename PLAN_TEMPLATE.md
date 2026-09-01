# B-stage plan template

Merge adjacent pages only when their selected type and method are identical. Use zero-padded
range filenames sized to the document page count, for example `r03-07.md`.

## Plan

Document: `<absolute path>`

Fingerprint: `sha256:<digest>`

Pages: `<count>`

Form suspicion: `<none|acroform-suspect>`

| Page range | Type | Method | Estimated cost | Output file |
|---|---|---|---|---|
| `1-4` | `text` | `pdftotext` to `work/r01-04.txt`; for Markdown, delegate semantic formatting to `processing-pdf` | low / local | `ranges/r01-04.md` |
| `5-6` | `scan` | load `processing-pdf` once; render and use agent vision | high / vision | `ranges/r05-06.md` |
| `7-9` | `table-suspect` | load `extracting-pdf-text` once; `pdfplumber.find_tables()` then extract or write back to text | medium / local | `ranges/r07-09.md` |
| `10` | `visual-layout` | load `processing-pdf` once; use text layer for values and vision for headings, lists, figures, and reading order | high / vision | `ranges/r10.md` |

Remove example rows that do not apply. For Markdown output, state how semantic structure will be
created; raw `pdftotext` renamed to `.md` is not a valid method. Add form, merge, split,
manipulation, or generation work as an explicit row routed to `pdf`. Do not disguise
document-wide operations as page extraction.

## Dependencies and fallbacks

List exact missing dependencies and installation commands. Confirmation authorizes only this list.

| Dependency | Why needed | Installation | Fallback if target skill is missing |
|---|---|---|---|
| `poppler-utils` | probe, text extraction, image oracle | platform package command | none for probe; stop clearly |
| `pdfplumber` | table confirmation/extraction | `python3 -m pip install --user pdfplumber` | inline scoped Python only |
| `pypdfium2` | `processing-pdf/scripts/to_images.py` | `python3 -m pip install --user pypdfium2` | `pdftoppm -png -r 200` |
| `qpdf` | confirmed decryption/manipulation | platform package command | `pypdf` only when suitable |

Delete unneeded rows and replace generic platform commands with the exact detected command before
asking for confirmation. Note any target skill that is absent.

## Confirmation prompt

> 探测已完成，尚未执行解析、安装依赖或修改 PDF。请回复：
> 1. **确认**：按以上计划执行，并授权安装表中列出的依赖；
> 2. **调整 `<页区间>` 为 `<类型/方法>`**：我会更新计划后再次确认；
> 3. **放弃**：停止，不产生解析结果。

Only an unambiguous confirmation advances to execution. Preserve the confirmed plan and timestamp
in the manifest. A changed fingerprint, range, route, dependency list, or output target requires
new confirmation.
