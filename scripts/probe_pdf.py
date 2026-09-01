#!/usr/bin/env python3
"""Probe PDF structure and emit content-free routing metrics as JSON."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata


FIELD_RE = re.compile(r"\S(?:[^ ]| (?! ))*")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )


def aligned_clusters(starts: Counter[int], minimum_lines: int) -> int:
    clusters: list[tuple[int, int]] = []
    for position, count in sorted(starts.items()):
        if clusters and position - clusters[-1][0] <= 2:
            _, total = clusters[-1]
            clusters[-1] = (position, total + count)
        else:
            clusters.append((position, count))
    return sum(total >= minimum_lines for _, total in clusters)


def image_metrics(output: str, page_area_points: float, page_count: int) -> list[dict[str, object]]:
    metrics = [
        {"image_count": 0, "aggregate_area_ratio": 0.0, "images_ge_1pct": 0}
        for _ in range(page_count)
    ]
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 14 or not fields[0].isdigit() or fields[2] in {"mask", "smask"}:
            continue
        page = int(fields[0]) - 1
        if not 0 <= page < page_count:
            continue
        width, height = int(fields[3]), int(fields[4])
        x_ppi, y_ppi = float(fields[12]), float(fields[13])
        if x_ppi <= 0 or y_ppi <= 0 or page_area_points <= 0:
            continue
        area = (width / x_ppi * 72) * (height / y_ppi * 72) / page_area_points
        metrics[page]["image_count"] += 1
        metrics[page]["aggregate_area_ratio"] += area
        if area >= 0.01:
            metrics[page]["images_ge_1pct"] += 1
    for metric in metrics:
        metric["aggregate_area_ratio"] = round(metric["aggregate_area_ratio"], 4)
    return metrics


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} input.pdf", file=sys.stderr)
        return 2

    source = Path(sys.argv[1]).resolve(strict=True)
    hasher = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    pdfinfo = run(["pdfinfo", str(source)]).stdout

    pages_match = re.search(r"(?m)^Pages:\s*(\d+)", pdfinfo)
    encrypted_match = re.search(r"(?m)^Encrypted:\s*(\S+)", pdfinfo)
    size_match = re.search(r"(?m)^Page size:\s*([0-9.]+)\s+x\s+([0-9.]+)\s+pts", pdfinfo)
    if not pages_match or not encrypted_match:
        raise RuntimeError("pdfinfo did not report Pages and Encrypted")
    page_count = int(pages_match.group(1))
    encrypted = encrypted_match.group(1).lower() != "no"
    result: dict[str, object] = {
        "source": {
            "path": str(source),
            "sha256": digest,
            "size_bytes": source.stat().st_size,
            "pages": page_count,
            "encrypted": encrypted,
        },
        "acroform_suspect": False,
        "page_boundary_mismatch": False,
        "pages": [],
    }
    if encrypted:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    with tempfile.TemporaryDirectory(prefix="pdf-router-probe-") as temporary:
        probe_path = Path(temporary) / "probe.txt"
        run(["pdftotext", "-enc", "UTF-8", "-layout", str(source), str(probe_path)])
        text = probe_path.read_text(encoding="utf-8", errors="replace")

    parts = text.split("\f")
    if len(parts) == page_count + 1 and not parts[-1]:
        parts.pop()
    mismatch = len(parts) != page_count
    result["page_boundary_mismatch"] = mismatch
    parts = (parts + [""] * page_count)[:page_count]

    page_area = float(size_match.group(1)) * float(size_match.group(2)) if size_match else 0.0
    images = image_metrics(run(["pdfimages", "-list", str(source)]).stdout, page_area, page_count)
    strings_output = run(["strings", str(source)]).stdout
    result["acroform_suspect"] = "AcroForm" in strings_output

    page_results: list[dict[str, object]] = []
    for page_number, page in enumerate(parts, 1):
        non_ws = [char for char in page if not char.isspace()]
        chars = len(non_ws)
        effective = sum(
            unicodedata.category(char).startswith("L") or "\u4e00" <= char <= "\u9fff"
            for char in non_ws
        )
        printable = sum(char.isprintable() for char in non_ws)
        invalid = sum(
            char == "\ufffd" or unicodedata.category(char).startswith("C") for char in non_ws
        )
        lines = [line for line in page.splitlines() if line.strip()]
        numeric_heavy = 0
        two_field_lines = 0
        three_field_lines = 0
        two_starts: Counter[int] = Counter()
        three_starts: Counter[int] = Counter()
        gap_runs = 0
        for line in lines:
            compact = [char for char in line if not char.isspace()]
            if compact:
                digitish = sum(char.isdigit() or char in ".,%+-:/()[]" for char in compact)
                numeric_heavy += digitish / len(compact) >= 0.5
            fields = [(match.start(), match.group().rstrip()) for match in FIELD_RE.finditer(line.rstrip())]
            gap_runs += len(re.findall(r" {2,}", line))
            if len(fields) >= 2:
                two_field_lines += 1
                two_starts.update(start for start, _ in fields)
            if len(fields) >= 3:
                three_field_lines += 1
                three_starts.update(start for start, _ in fields)

        numeric_ratio = numeric_heavy / max(len(lines), 1)
        letter_ratio = effective / max(printable, 1)
        invalid_ratio = invalid / max(chars, 1)
        aligned_two = aligned_clusters(two_starts, 6)
        aligned_three = aligned_clusters(three_starts, 4)
        table_signal = (
            aligned_three >= 3 and three_field_lines >= 4
        ) or (
            aligned_two >= 2 and two_field_lines >= 6
        ) or numeric_ratio >= 0.35
        image_signal = (
            images[page_number - 1]["aggregate_area_ratio"] >= 0.05
            or images[page_number - 1]["images_ge_1pct"] >= 2
        )

        if mismatch:
            label, rule = "scan", "page-boundary-mismatch"
        elif chars <= 20:
            label, rule = "scan", "empty-text"
        elif letter_ratio < 0.35 or invalid_ratio > 0.05:
            label, rule = "scan", "invalid-mapping"
        elif table_signal:
            label, rule = "table-suspect", "table-signals"
        elif image_signal:
            label, rule = "visual-layout", "visual-layout-signals"
        else:
            label, rule = "text", "otherwise"

        page_results.append(
            {
                "page": page_number,
                "non_ws_chars": chars,
                "letters_cjk": effective,
                "letter_ratio": round(letter_ratio, 4),
                "replacement_control": invalid,
                "invalid_ratio": round(invalid_ratio, 4),
                "nonempty_lines": len(lines),
                "numeric_heavy_ratio": round(numeric_ratio, 4),
                "two_field_lines": two_field_lines,
                "three_field_lines": three_field_lines,
                "aligned_two_field_starts": aligned_two,
                "aligned_three_field_starts": aligned_three,
                "horizontal_gap_runs": gap_runs,
                **images[page_number - 1],
                "label": label,
                "rule": rule,
            }
        )

    result["pages"] = page_results
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
