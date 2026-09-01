#!/usr/bin/env python3
"""Run content-free structural regression cases for route-pdf-tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def parse_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        case_id, separator, path = value.partition("=")
        if not separator or not case_id or not path:
            raise ValueError("--case-path must be CASE_ID=/absolute/file.pdf")
        overrides[case_id] = Path(path)
    return overrides


def main() -> int:
    skill_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=skill_root / "testdata" / "structural-cases.json",
    )
    parser.add_argument("--case-path", action="append", default=[])
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    if inventory.get("schema_version") != 1:
        raise ValueError("unsupported inventory schema")
    overrides = parse_overrides(args.case_path)
    selected = set(args.only)
    results: list[dict[str, object]] = []

    for case in inventory["cases"]:
        case_id = case["id"]
        if selected and case_id not in selected:
            continue
        configured = overrides.get(case_id)
        if configured is None and case.get("default_path"):
            configured = Path(case["default_path"])

        issues: list[str] = []
        actual_labels: list[str] = []
        if configured is None or not configured.is_file():
            issues.append("case-pdf-missing")
        else:
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(skill_root / "scripts" / "probe_pdf.py"),
                        str(configured),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                issues.append("probe-timeout")
                completed = None
            if completed is not None and completed.returncode:
                issues.append("probe-failed")
            elif completed is not None:
                try:
                    probe = json.loads(completed.stdout)
                except json.JSONDecodeError:
                    issues.append("invalid-probe-json")
                    probe = None
                if probe is None:
                    results.append(
                        {
                            "id": case_id,
                            "role": case["role"],
                            "status": "failed",
                            "issues": issues,
                            "actual_labels": actual_labels,
                        }
                    )
                    continue
                source = probe["source"]
                actual_labels = [page["label"] for page in probe["pages"]]
                if source["sha256"] != case["sha256"]:
                    issues.append("fingerprint-mismatch")
                if source["size_bytes"] != case["size_bytes"]:
                    issues.append("size-mismatch")
                if source["pages"] != case["pages"]:
                    issues.append("page-count-mismatch")
                if actual_labels != case["expected_labels"]:
                    issues.append("route-label-regression")

        results.append(
            {
                "id": case_id,
                "role": case["role"],
                "status": "passed" if not issues else "failed",
                "issues": issues,
                "actual_labels": actual_labels,
            }
        )

    suite_issues: list[str] = []
    if not results:
        suite_issues.append("no-cases-selected")
    if not any(result["role"] == "held-out" for result in results):
        suite_issues.append("no-held-out-case-selected")
    if any(result["status"] == "failed" for result in results):
        suite_issues.append("case-failure")

    report = {
        "status": "passed" if not suite_issues else "failed",
        "suite_issues": suite_issues,
        "cases": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not suite_issues else 1


if __name__ == "__main__":
    sys.exit(main())
