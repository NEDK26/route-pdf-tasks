#!/usr/bin/env python3
"""Offline end-to-end check using a fake Codex executable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from pypdf import PdfWriter


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise AssertionError(
            f"command failed ({completed.returncode}): {command}\n{completed.stdout}\n{completed.stderr}"
        )
    return completed


def main() -> None:
    benchmark_root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "sample.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with source.open("wb") as handle:
            writer.write(handle)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        corpus = root / "corpus.json"
        corpus.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cases": [
                        {
                            "id": "sample",
                            "split": "calibration",
                            "categories": ["born-digital-text"],
                            "default_path": str(source),
                            "sha256": digest,
                            "size_bytes": source.stat().st_size,
                            "pages": 1,
                            "redistribution": "test-generated",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        fake = root / "fake-codex"
        fake.write_text(
            """#!/usr/bin/env python3
import json
from pathlib import Path
import sys

args = sys.argv[1:]
state = Path(__file__).with_suffix('.state')
thread = '11111111-1111-1111-1111-111111111111'
if args == ['--version']:
    print('fake-codex 1.0')
elif args and args[0] == 'delete':
    state.unlink(missing_ok=True)
elif args[:2] == ['exec', 'resume']:
    workspace = Path(state.read_text())
    output = workspace / 'deliverable' / 'full.md'
    output.write_text(
        '<!-- page: 1 -->\\n# Benchmark\\nComplete benchmark output with enough '
        'factual words for structural validation number 123.\\n',
        encoding='utf-8',
    )
    if '-o' in args:
        Path(args[args.index('-o') + 1]).write_text('Done\\n', encoding='utf-8')
    print(json.dumps({'type':'turn.completed','usage':{
        'input_tokens':5,'output_tokens':5,'total_tokens':10}}))
elif args and args[0] == 'exec':
    workspace = Path(args[args.index('-C') + 1])
    state.write_text(str(workspace))
    if '-o' in args:
        Path(args[args.index('-o') + 1]).write_text('Plan\\n', encoding='utf-8')
    print(json.dumps({'type':'thread.started','thread_id':thread}))
    print(json.dumps({'type':'turn.completed','usage':{
        'input_tokens':10,'output_tokens':5,'total_tokens':15}}))
else:
    raise SystemExit(2)
""",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        output_root = root / "output"
        run(
            [
                sys.executable,
                str(benchmark_root / "scripts/run_pdf_markdown_benchmark.py"),
                "--execute",
                "--model",
                "test-model",
                "--reasoning-effort",
                "low",
                "--arms",
                "direct",
                "--corpus",
                str(corpus),
                "--codex-bin",
                str(fake),
                "--output-root",
                str(output_root),
                "--run-id",
                "test-run",
            ],
            benchmark_root,
        )
        run_dir = output_root / "test-run"
        run(
            [sys.executable, str(benchmark_root / "scripts/score_pdf_markdown_benchmark.py"), str(run_dir)],
            benchmark_root,
        )
        run(
            [sys.executable, str(benchmark_root / "scripts/anonymize_pdf_markdown_benchmark.py"), str(run_dir)],
            benchmark_root,
        )

        template = [
            json.loads(line)
            for line in (run_dir / "blind/review-form.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        reviews = []
        for reviewer in ("reviewer-a", "reviewer-b"):
            path = root / f"{reviewer}.jsonl"
            rows = []
            for row in template:
                row = dict(row)
                row.update(
                    {
                        "reviewer_id": reviewer,
                        "facts_and_numbers": 25,
                        "completeness": 20,
                        "tables": 20,
                        "reading_order_and_hierarchy": 15,
                        "images_and_figures": 10,
                        "markdown_usability": 10,
                    }
                )
                if reviewer == "reviewer-b":
                    row["critical_errors"] = ["invented-critical-number"]
                rows.append(json.dumps(row))
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            reviews.extend(["--review", str(path)])
        run(
            [
                sys.executable,
                str(benchmark_root / "scripts/summarize_pdf_markdown_benchmark.py"),
                str(run_dir),
                *reviews,
            ],
            benchmark_root,
        )
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["arm_summary"]["direct"]["human_total_mean"] == 59
        assert summary["arm_summary"]["direct"]["critical_error_run_rate"] == 1.0
        result = json.loads(
            next(run_dir.glob("executions/*/*/repeat-*/run.json")).read_text(encoding="utf-8")
        )
        assert result["status"] == "completed"
        assert result["thread_id_deleted"] is True
        assert result["pre_confirmation_files"] == []


if __name__ == "__main__":
    main()
