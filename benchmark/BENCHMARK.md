# Blind PDF-to-Markdown benchmark

Use this workflow only for comparative evaluation. Never treat a PDF used to tune a rule as a
held-out test case.

## Fairness contract

Run every command below from the repository root.

1. Freeze `benchmark/testdata/benchmark-protocol.json`, corpus fingerprints, model, reasoning
   effort, Skill hashes, tool versions, prompt, timeout, repeat count, and random seed before the
   test run.
2. Run `direct`, `reference-pdf`, and `route-pdf-tasks` in randomized order. Give every arm the same
   source filename, writable layout, base tools, two turns, timeout, and output contract.
3. Disable the competing PDF skills explicitly. Never rely only on a prompt telling the model not
   to use them.
4. On turn one, require a plan and prohibit deliverable writes. On turn two, send the same fixed
   confirmation. Record early writes as protocol violations.
5. Start a new Codex thread for every case, arm, and repeat. Delete the thread after capture unless
   debugging was explicitly requested. Never expose other outputs, expected answers, labels, or
   reviewer conclusions to a generation thread.
6. Keep calibration and test splits separate. The LG695P sample is calibration-only because it
   influenced this skill.
7. Store generated content only under ignored `benchmark/output/`. Public testdata may contain
   fingerprints and judgment-level metrics, never restricted PDF text, images, outputs, or the
   private blind mapping.

## Prepare the corpus

Add only metadata to `benchmark/testdata/benchmark-cases.json`. Use six balanced categories:
born-digital text, Chinese/English technical text, dense tables, multi-column text, visual layout,
and scanned or mixed pages. Target six calibration documents and 24 held-out documents.

For local or restricted files, leave `default_path` null and provide:

```bash
--case-path 'case-id=/absolute/path/document.pdf'
```

The runner verifies SHA-256 and byte size before scheduling a case.

## Dry run

Dry run is the default and makes no model calls:

```bash
python3 benchmark/scripts/run_pdf_markdown_benchmark.py \
  --model gpt-5.6-sol \
  --reasoning-effort high \
  --pdf-skill-provenance 'community:boazcstrike/opencode@151a999' \
  --repeats 1 \
  --case-path 'lg695p-product-sheet=/absolute/path/LG695P.pdf'
```

Inspect the randomized job list and every corpus validation issue. Do not execute when a fingerprint
changed or the frozen test split is incomplete.

## Execute

Execution creates billable, independent Codex sessions:

```bash
python3 benchmark/scripts/run_pdf_markdown_benchmark.py \
  --execute \
  --model gpt-5.6-sol \
  --reasoning-effort high \
  --pdf-skill-provenance 'verified-source-and-version' \
  --repeats 3 \
  --split test \
  --case-path 'case-id=/absolute/path/document.pdf'
```

Add `--formal` only after the frozen test inventory contains at least 24 verified cases, three
repeats, all three arms, and every required category. Formal mode requires exactly `--split test`
and refuses incomplete inputs. `--allow-missing-cases` is for exploratory calibration only and its
outputs must never be promoted into a formal report.

Use `--ignore-user-config` only when the selected model provider remains available without the user
config. The runner always disables plugins, agent memory, and multi-agent execution to reduce hidden
variance.
Use `--keep-sessions` only for a declared debugging run; never mix those results into the frozen
benchmark.

`reference-pdf` means the exact Skill file passed by `--pdf-skill`; it does not imply OpenAI
authorship. Record provenance separately and verify the frozen Skill hash. The repository's current
local `$pdf` dependency is community-sourced as documented in [`SOURCES.md`](../SOURCES.md). To
claim an OpenAI comparison, supply an independently verified OpenAI-distributed Skill path.

## Score and blind

Run objective scoring before human review:

```bash
python3 benchmark/scripts/score_pdf_markdown_benchmark.py benchmark/output/<run-id>
python3 benchmark/scripts/anonymize_pdf_markdown_benchmark.py benchmark/output/<run-id>
```

Objective metrics remain separate: token and number precision/recall/F1, page-marker coverage,
Markdown structures, unresolved assets, protocol violations, tokens, and wall time. Do not invent a
weighted automatic quality score.

Give reviewers only `blind/sources/`, `blind/candidates/`, `blind/package.json`, and separate copies
of `blind/review-form.jsonl`. Do not give them `blind-map.json`, execution logs, manifests, or scores.
Use at least two reviewers; adjudicate material disagreements with a third reviewer.
The summarizer rejects duplicate reviewer/candidate pairs and completed candidates with fewer than
two reviewers. Failed executions receive zero human points rather than disappearing from the arm
mean. Use `--allow-incomplete-reviews` only while checking a partial calibration package.

Each human dimension uses its point maximum from the protocol. Any critical factual fabrication,
whole-page omission, table-value displacement, broken required asset, or unusable output caps the
candidate at 59.

## Reveal and summarize

After all review files are final and immutable:

```bash
python3 benchmark/scripts/summarize_pdf_markdown_benchmark.py \
  benchmark/output/<run-id> \
  --review /absolute/path/reviewer-a.jsonl \
  --review /absolute/path/reviewer-b.jsonl
```

Treat a quality lead as established only when the paired document-level human difference is at
least five points, its 95% bootstrap interval excludes zero, critical-error rate does not regress,
and category results are broad rather than driven by one document type. Report cost and latency as
separate tradeoffs, not deductions from quality.
