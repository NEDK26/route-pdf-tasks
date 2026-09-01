#!/usr/bin/env python3
"""Unit checks for benchmark isolation and metric helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from benchmark_common import (
    counter_metrics,
    numbers,
    parse_thread_id,
    skills_override,
    tokens,
    usage_from_jsonl,
)


def main() -> None:
    jsonl = """\
{"type":"thread.started","thread_id":"11111111-1111-1111-1111-111111111111"}
{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":4,"total_tokens":16}}
"""
    assert parse_thread_id(jsonl) == "11111111-1111-1111-1111-111111111111"
    assert usage_from_jsonl(jsonl)["total_tokens"] == 16
    metric = counter_metrics(tokens("A 12 中文"), tokens("A 12 中"))
    assert metric["recall"] < 1
    assert numbers("v=12.5, x=-3") == {"12.5": 1, "-3": 1}

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = []
        for name in ("pdf", "processing", "extracting", "route"):
            path = root / name / "SKILL.md"
            path.parent.mkdir()
            path.write_text("---\nname: x\ndescription: x\n---\n", encoding="utf-8")
            paths.append(path)
        direct = skills_override(
            "direct",
            pdf_skill=paths[0],
            processing_pdf_skill=paths[1],
            extracting_pdf_text_skill=paths[2],
            route_skill=paths[3],
        )
        assert direct.count("enabled=false") == 4
        route = skills_override(
            "route-pdf-tasks",
            pdf_skill=paths[0],
            processing_pdf_skill=paths[1],
            extracting_pdf_text_skill=paths[2],
            route_skill=paths[3],
        )
        assert route.count("enabled=true") == 4


if __name__ == "__main__":
    main()
