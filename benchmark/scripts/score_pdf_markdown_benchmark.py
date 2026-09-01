#!/usr/bin/env python3
"""Compute objective PDF-to-Markdown benchmark metrics without a single composite score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

import pdfplumber

from benchmark_common import (
    PAGE_MARKER_RE,
    counter_metrics,
    load_json,
    markdown_table_metrics,
    numbers,
    tokens,
    without_fenced_code,
    write_json,
)


METHOD_LEAK_RE = re.compile(
    r"(?:route-pdf-tasks|processing-pdf|extracting-pdf-text|\$pdf\b|pdfplumber|pdftotext)",
    re.IGNORECASE,
)


def score_markdown(
    source_text: str,
    markdown: str,
    *,
    page_count: int,
    detected_tables: int,
    detected_images: int,
    markdown_path: Path,
) -> dict[str, Any]:
    structural = without_fenced_code(markdown)
    semantic_text = PAGE_MARKER_RE.sub("", markdown)
    semantic_text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", semantic_text)
    semantic_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", semantic_text)
    token_metrics = counter_metrics(tokens(source_text), tokens(semantic_text))
    number_metrics = counter_metrics(numbers(source_text), numbers(semantic_text))
    token_metrics["applicable"] = token_metrics["reference_count"] >= 20
    number_metrics["applicable"] = number_metrics["reference_count"] >= 5
    table_metrics = markdown_table_metrics(structural)
    markers = [int(value) for value in PAGE_MARKER_RE.findall(structural)]
    expected_pages = set(range(1, page_count + 1))
    marked_pages = set(markers)
    image_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", structural)
    unresolved_images = [
        ref
        for ref in image_refs
        if not ref.startswith(("http://", "https://", "data:"))
        and not (markdown_path.parent / ref).resolve().is_file()
    ]
    nonempty_lines = [line for line in structural.splitlines() if line.strip()]
    raw_layout_lines = sum(bool(re.search(r"\S\s{8,}\S", line)) for line in nonempty_lines)
    headings = len(re.findall(r"(?m)^#{1,6}\s+", structural))
    list_items = len(re.findall(r"(?m)^\s*(?:[-+*]|\d+\.)\s+", structural))

    issues: list[str] = []
    warnings: list[str] = []
    if sum(tokens(markdown).values()) < 10:
        issues.append("markdown-output-too-short")
    if "\f" in markdown:
        issues.append("form-feed-page-separators-remain")
    if token_metrics["applicable"] and token_metrics["recall"] < 0.80:
        issues.append("source-token-recall-below-0.80")
    if not token_metrics["applicable"]:
        warnings.append("text-layer-insufficient-for-token-metrics")
    if marked_pages != expected_pages:
        issues.append("page-marker-coverage-incomplete")
    if len(markers) != len(marked_pages):
        warnings.append("duplicate-page-markers")
    if unresolved_images:
        issues.append("unresolved-image-reference")
    if raw_layout_lines >= max(5, len(nonempty_lines) // 5):
        warnings.append("raw-layout-shaped-output-needs-review")
    if detected_tables and table_metrics["separator_rows"] == 0:
        warnings.append("table-detector-found-candidates-but-markdown-has-no-table")
    if detected_images and not image_refs:
        warnings.append("source-has-images-but-markdown-has-no-image-reference")
    if METHOD_LEAK_RE.search(markdown):
        warnings.append("possible-method-identity-leakage")

    return {
        "token": token_metrics,
        "number": number_metrics,
        "page_markers": {
            "expected": page_count,
            "found": len(markers),
            "unique": len(marked_pages),
            "coverage": round(len(marked_pages & expected_pages) / max(page_count, 1), 4),
            "missing": sorted(expected_pages - marked_pages),
            "out_of_range": sorted(marked_pages - expected_pages),
        },
        "source_structure": {
            "detected_tables": detected_tables,
            "detected_images": detected_images,
        },
        "markdown_structure": {
            "headings": headings,
            "list_items": list_items,
            "image_references": len(image_refs),
            "unresolved_image_references": len(unresolved_images),
            "raw_layout_lines": raw_layout_lines,
            "tables": table_metrics,
        },
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "warnings": warnings,
    }


def score_run(run_path: Path) -> dict[str, Any]:
    run = load_json(run_path)
    workspace = run_path.parent / "workspace"
    source = workspace / "input.pdf"
    markdown_path = workspace / "deliverable" / "full.md"
    if not source.is_file() or not markdown_path.is_file():
        return {
            "case_id": run["case_id"],
            "arm": run["arm"],
            "repeat": run["repeat"],
            "run_status": run["status"],
            "automatic_status": "failed",
            "issues": ["source-or-full-md-missing"],
            "protocol_violations": run["protocol_violations"],
            "usage": run["usage"],
            "wall_seconds": sum(
                turn["wall_seconds"] for turn in (run["turn_1"], run["turn_2"]) if turn
            ),
        }

    with pdfplumber.open(source) as pdf:
        source_text = "\n".join(page.extract_text(layout=True) or "" for page in pdf.pages)
        detected_tables = sum(len(page.find_tables()) for page in pdf.pages)
        detected_images = sum(len(page.images) for page in pdf.pages)
        page_count = len(pdf.pages)
    markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
    objective = score_markdown(
        source_text,
        markdown,
        page_count=page_count,
        detected_tables=detected_tables,
        detected_images=detected_images,
        markdown_path=markdown_path,
    )
    return {
        "case_id": run["case_id"],
        "split": run["split"],
        "categories": run["categories"],
        "arm": run["arm"],
        "repeat": run["repeat"],
        "run_status": run["status"],
        "automatic_status": objective["status"],
        "objective": objective,
        "protocol_violations": run["protocol_violations"],
        "usage": run["usage"],
        "wall_seconds": round(
            sum(turn["wall_seconds"] for turn in (run["turn_1"], run["turn_2"]) if turn), 3
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    scores = [score_run(path) for path in sorted(run_dir.glob("executions/*/*/repeat-*/run.json"))]
    if not scores:
        raise ValueError("no benchmark run.json files found")
    for score, run_path in zip(scores, sorted(run_dir.glob("executions/*/*/repeat-*/run.json"))):
        write_json(run_path.parent / "score.json", score)
    report = {
        "schema_version": 1,
        "run_id": load_json(run_dir / "manifest.json")["run_id"],
        "scores": scores,
    }
    write_json(run_dir / "scores.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(score["automatic_status"] == "passed" for score in scores) else 1


if __name__ == "__main__":
    sys.exit(main())
