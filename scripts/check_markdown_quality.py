#!/usr/bin/env python3
"""Validate structural fidelity of PDF-to-Markdown range output.

The report contains metrics and judgment-level symptoms only. It never stores
PDF text snapshots or expected document content.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

import pdfplumber


TOKEN_RE = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]|[±°μ‰σ]+")
TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def parse_pages(value: str, page_count: int) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value)
    if not match:
        raise argparse.ArgumentTypeError("pages must be N or N-M")
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if first < 1 or last < first or last > page_count:
        raise argparse.ArgumentTypeError(f"pages must be within 1-{page_count}")
    return first, last


def tokens(text: str) -> Counter[str]:
    return Counter(token.lower() for token in TOKEN_RE.findall(text))


def without_fenced_code(markdown: str) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            current = marker.group(1)[0]
            if fence is None:
                fence = current
            elif fence == current:
                fence = None
            output.append("")
        elif fence is None:
            output.append(line)
        else:
            output.append("")
    return "\n".join(output)


def markdown_table_metrics(markdown: str) -> tuple[int, int, int, int]:
    rows: list[tuple[int, str]] = [
        (index, line)
        for index, line in enumerate(markdown.splitlines())
        if re.fullmatch(r"\s*\|.*\|\s*", line)
    ]
    separators = sum(bool(TABLE_SEPARATOR_RE.fullmatch(line)) for _, line in rows)
    blocks = 0
    previous = -2
    for index, _ in rows:
        if index != previous + 1:
            blocks += 1
        previous = index
    return len(rows), separators, len(rows) - separators, blocks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--pages", default=None, help="1-based N or N-M; defaults to all pages")
    parser.add_argument(
        "--expected-type",
        choices=("text", "table", "visual-layout", "scan"),
        required=True,
    )
    parser.add_argument("--min-token-recall", type=float, default=0.80)
    parser.add_argument("--min-table-data-rows", type=int, default=3)
    args = parser.parse_args()

    markdown = args.markdown.read_text(encoding="utf-8", errors="replace")
    with pdfplumber.open(args.pdf) as pdf:
        first, last = parse_pages(args.pages or f"1-{len(pdf.pages)}", len(pdf.pages))
        selected = pdf.pages[first - 1 : last]
        source = "\n".join(page.extract_text(layout=True) or "" for page in selected)
        detected_tables = sum(len(page.find_tables()) for page in selected)

    source_tokens = tokens(source)
    output_tokens = tokens(markdown)
    overlap = sum((source_tokens & output_tokens).values())
    recall = overlap / max(sum(source_tokens.values()), 1)

    structural_markdown = without_fenced_code(markdown)
    headings = len(re.findall(r"(?m)^#{1,6}\s+", structural_markdown))
    table_rows, table_separators, table_data_rows, table_blocks = markdown_table_metrics(
        structural_markdown
    )
    list_items = len(re.findall(r"(?m)^\s*(?:[-+*]|\d+\.)\s+", structural_markdown))
    image_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", structural_markdown)
    unresolved_images = [
        ref
        for ref in image_refs
        if not ref.startswith(("http://", "https://", "data:"))
        and not (args.markdown.parent / ref).resolve().exists()
    ]
    nonempty_lines = [line for line in structural_markdown.splitlines() if line.strip()]
    raw_layout_lines = sum(bool(re.search(r"\S\s{8,}\S", line)) for line in nonempty_lines)

    issues: list[str] = []
    if sum(output_tokens.values()) < 10:
        issues.append("markdown-output-too-short")
    if "\f" in markdown:
        issues.append("form-feed-page-separators-remain")
    if sum(source_tokens.values()) >= 20 and recall < args.min_token_recall:
        issues.append("source-token-recall-below-threshold")
    if unresolved_images:
        issues.append("unresolved-markdown-image-reference")

    if args.expected_type == "table":
        if detected_tables == 0:
            issues.append("table-route-lacks-find-tables-evidence")
        if table_separators == 0 or table_blocks == 0:
            issues.append("table-route-has-no-valid-markdown-table")
        if table_data_rows < args.min_table_data_rows:
            issues.append("table-route-has-too-few-data-rows")
    if args.expected_type in {"text", "visual-layout"} and headings == 0:
        issues.append("semantic-markdown-has-no-heading")
    if args.expected_type == "visual-layout":
        if not image_refs and table_rows < 3 and list_items < 2:
            issues.append("visual-route-has-no-visual-or-structural-output")
    if raw_layout_lines >= max(5, len(nonempty_lines) // 5):
        issues.append("raw-pdftotext-shaped-output")

    report = {
        "pages": [first, last],
        "expected_type": args.expected_type,
        "source_token_count": sum(source_tokens.values()),
        "source_token_recall": round(recall, 4),
        "detected_table_count": detected_tables,
        "heading_count": headings,
        "table_row_count": table_rows,
        "table_separator_row_count": table_separators,
        "table_data_row_count": table_data_rows,
        "minimum_table_data_rows": args.min_table_data_rows,
        "table_block_count": table_blocks,
        "list_item_count": list_items,
        "image_reference_count": len(image_refs),
        "unresolved_image_reference_count": len(unresolved_images),
        "raw_layout_line_count": raw_layout_lines,
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
