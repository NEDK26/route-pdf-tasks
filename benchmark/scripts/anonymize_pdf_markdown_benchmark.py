#!/usr/bin/env python3
"""Create a blind-review package while keeping the arm mapping private."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import random
import shutil
import sys

from benchmark_common import load_json, write_json


def candidate_id(run_id: str, seed: int, case_id: str, arm: str, repeat: int) -> str:
    raw = f"{run_id}:{seed}:{case_id}:{arm}:{repeat}".encode()
    return "candidate-" + hashlib.sha256(raw).hexdigest()[:10]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    manifest = load_json(run_dir / "manifest.json")
    seed = args.seed if args.seed is not None else manifest["seed"]
    blind_root = run_dir / "blind"
    mapping_path = run_dir / "blind-map.json"
    if blind_root.exists() or mapping_path.exists():
        raise FileExistsError("blind package already exists")

    run_paths = sorted(run_dir.glob("executions/*/*/repeat-*/run.json"))
    entries = []
    for run_path in run_paths:
        run = load_json(run_path)
        cid = candidate_id(
            manifest["run_id"], seed, run["case_id"], run["arm"], run["repeat"]
        )
        entries.append((cid, run_path, run))
    random.Random(f"{manifest['run_id']}:{seed}").shuffle(entries)

    mapping = {"schema_version": 1, "run_id": manifest["run_id"], "candidates": []}
    review_rows = []
    copied_sources: set[str] = set()
    for cid, run_path, run in entries:
        deliverable = run_path.parent / "workspace" / "deliverable"
        source = run_path.parent / "workspace" / "input.pdf"
        candidate_root = blind_root / "candidates" / run["case_id"] / cid
        if deliverable.is_dir():
            shutil.copytree(deliverable, candidate_root)
        if run["case_id"] not in copied_sources and source.is_file():
            source_target = blind_root / "sources" / f"{run['case_id']}.pdf"
            source_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, source_target)
            copied_sources.add(run["case_id"])
        mapping["candidates"].append(
            {
                "candidate_id": cid,
                "case_id": run["case_id"],
                "arm": run["arm"],
                "repeat": run["repeat"],
                "status": run["status"],
            }
        )
        if (candidate_root / "full.md").is_file():
            review_rows.append(
                {
                    "reviewer_id": None,
                    "case_id": run["case_id"],
                    "candidate_id": cid,
                    "facts_and_numbers": None,
                    "completeness": None,
                    "tables": None,
                    "reading_order_and_hierarchy": None,
                    "images_and_figures": None,
                    "markdown_usability": None,
                    "critical_errors": [],
                    "notes": "",
                }
            )

    write_json(mapping_path, mapping)
    blind_root.mkdir(parents=True, exist_ok=True)
    with (blind_root / "review-form.jsonl").open("w", encoding="utf-8") as handle:
        import json

        for row in review_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(
        blind_root / "package.json",
        {
            "schema_version": 1,
            "run_id": manifest["run_id"],
            "candidate_count": len(review_rows),
            "instructions": (
                "Review sources and candidates without opening ../blind-map.json. "
                "Fill one copy of review-form.jsonl per reviewer."
            ),
        },
    )
    print(blind_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
