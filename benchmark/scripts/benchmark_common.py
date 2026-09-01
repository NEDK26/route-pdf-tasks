#!/usr/bin/env python3
"""Shared helpers for the isolated PDF-to-Markdown benchmark."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


ARM_IDS = ("direct", "reference-pdf", "route-pdf-tasks")
TOKEN_RE = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]|[±°μ‰σ]+")
NUMBER_RE = re.compile(r"(?<![\w.])[+-]?\d+(?:\.\d+)?(?:%|‰)?(?![\w.])")
PAGE_MARKER_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->", re.IGNORECASE)
TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash relevant files in a skill bundle without runtime or VCS artifacts."""
    ignored_parts = {".git", "__pycache__", "pdf-output", "benchmark-output"}
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        is_benchmark_output = relative.parts[:2] == ("benchmark", "output")
        if (
            any(part in ignored_parts for part in relative.parts)
            or is_benchmark_output
            or path.suffix == ".pyc"
        ):
            continue
        digest.update(str(relative).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def parse_case_paths(values: Iterable[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        case_id, separator, raw_path = value.partition("=")
        if not separator or not case_id or not raw_path:
            raise ValueError("--case-path must be CASE_ID=/absolute/file.pdf")
        path = Path(raw_path).expanduser().resolve()
        if case_id in parsed:
            raise ValueError(f"duplicate --case-path for {case_id}")
        parsed[case_id] = path
    return parsed


def verify_case(case: dict[str, Any], source: Path) -> list[str]:
    issues: list[str] = []
    if not source.is_file():
        return ["case-pdf-missing"]
    if source.stat().st_size != case["size_bytes"]:
        issues.append("size-mismatch")
    if sha256_file(source) != case["sha256"]:
        issues.append("fingerprint-mismatch")
    return issues


def tokens(text: str) -> Counter[str]:
    return Counter(token.lower() for token in TOKEN_RE.findall(text))


def numbers(text: str) -> Counter[str]:
    return Counter(match.group(0).lower() for match in NUMBER_RE.finditer(text))


def counter_metrics(reference: Counter[str], candidate: Counter[str]) -> dict[str, float | int]:
    overlap = sum((reference & candidate).values())
    reference_count = sum(reference.values())
    candidate_count = sum(candidate.values())
    recall = overlap / max(reference_count, 1)
    precision = overlap / max(candidate_count, 1)
    f1 = 2 * recall * precision / max(recall + precision, 1e-12)
    return {
        "reference_count": reference_count,
        "candidate_count": candidate_count,
        "overlap_count": overlap,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
    }


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


def markdown_table_metrics(markdown: str) -> dict[str, int]:
    rows = [
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
    return {
        "rows": len(rows),
        "separator_rows": separators,
        "data_rows": len(rows) - separators,
        "blocks": blocks,
    }


def parse_thread_id(jsonl: str) -> str | None:
    def find_id(value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("thread_id", "session_id", "conversation_id"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate:
                    return candidate
            for nested in value.values():
                found = find_id(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = find_id(nested)
                if found:
                    return found
        return None

    fallback: str | None = None
    for raw_line in jsonl.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        found = find_id(event)
        if found and event.get("type") in {"thread.started", "session.started"}:
            return found
        fallback = fallback or found
    return fallback


def usage_from_jsonl(jsonl: str) -> dict[str, int]:
    maxima = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in maxima:
                candidate = value.get(key)
                if isinstance(candidate, int):
                    maxima[key] = max(maxima[key], candidate)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for raw_line in jsonl.splitlines():
        try:
            visit(json.loads(raw_line))
        except json.JSONDecodeError:
            continue
    return maxima


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def skills_override(
    arm: str,
    *,
    pdf_skill: Path,
    processing_pdf_skill: Path,
    extracting_pdf_text_skill: Path,
    route_skill: Path,
) -> str:
    if arm not in ARM_IDS:
        raise ValueError(f"unknown arm: {arm}")
    enabled = {
        "direct": set(),
        "reference-pdf": {"pdf"},
        "route-pdf-tasks": {
            "pdf",
            "processing-pdf",
            "extracting-pdf-text",
            "route-pdf-tasks",
        },
    }[arm]
    entries = [
        (pdf_skill, "pdf"),
        (processing_pdf_skill, "processing-pdf"),
        (extracting_pdf_text_skill, "extracting-pdf-text"),
        (route_skill, "route-pdf-tasks"),
    ]
    rendered = ",".join(
        "{path=" + toml_string(str(path.resolve())) + ",enabled=" + str(name in enabled).lower() + "}"
        for path, name in entries
    )
    return "[" + rendered + "]"


def build_initial_prompt(protocol: dict[str, Any], arm: str) -> str:
    return protocol["arms"][arm]["invocation"] + "\n\n" + protocol["turns"]["initial"]
