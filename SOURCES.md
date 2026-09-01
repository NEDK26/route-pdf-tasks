# Sources and iteration discipline

## Community skills

| Installed skill | Upstream | Pinned commit | Local adaptation |
|---|---|---|---|
| `pdf` | https://github.com/boazcstrike/opencode/tree/main/skills/pdf | `151a99940b1b1ae52bb0d1e59917b396f8655ee0` | None; frontmatter preserved |
| `extracting-pdf-text` | https://github.com/boazcstrike/opencode/tree/main/skills/extracting-pdf-text | `151a99940b1b1ae52bb0d1e59917b396f8655ee0` | None; frontmatter preserved |
| `processing-pdf` | https://github.com/osmontero/opencode-skills/tree/main/skills/processing-pdf | `6363688345c688c353ebacb6d50614503a7da9e5` | Replaced the nonexistent `~/.local/opencode-venv` prerequisite with direct system `python3`; updated the bundled `to_images.py` install hint; frontmatter preserved |

The `processing-pdf/scripts/` bundle was checked and includes `to_images.py`, `extract_text.py`,
`extract_tables.py`, `check_forms.py`, `fill_form.py`, and `metadata.py`. If a future upstream copy
lacks image conversion, document `pdftoppm -png -r 200 -f X -l Y` as the equivalent fallback.

## Evaluation methodology

| Source | Applied constraint |
|---|---|
| https://developers.openai.com/api/reference/java/resources/evals/methods/create | Freeze a data schema and the same testing criteria across runs |
| https://developers.openai.com/api/docs/guides/latest-model | Compare representative tasks on success, completeness, evidence, tokens, latency, and cost; do not count efficiency gains unless quality still passes |

The local runner implements these constraints without requiring the hosted Evals API. Keep
objective Python metrics separate from blinded human judgment and preserve the frozen inputs in
each ignored benchmark run directory.

## Mandatory iteration disciplines

1. **Minimal disclosure.** Accept only judgment-level feedback such as “第3页scan判错”. Never
   collect content-level answers, expected extracted passages, or hidden facts.
2. **Held-out regression.** A fix may merge only after the changed rule passes its labeled case and
   produces zero regression on other, previously unlabeled PDFs.
3. **General argument.** Every new rule added to `PROBE.md` must state applicability conditions, a
   counterexample, and its impact surface. A sample-specific exception is not a rule.
