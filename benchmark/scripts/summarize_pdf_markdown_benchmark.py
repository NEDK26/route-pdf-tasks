#!/usr/bin/env python3
"""Reveal blind mappings and summarize paired benchmark results after review."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import statistics
import sys
from typing import Any

from benchmark_common import ARM_IDS, load_json, write_json


HUMAN_FIELDS = (
    "facts_and_numbers",
    "completeness",
    "tables",
    "reading_order_and_hierarchy",
    "images_and_figures",
    "markdown_usability",
)


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def load_reviews(
    paths: list[Path], maxima: dict[str, int], critical_cap: int
) -> dict[str, list[dict[str, Any]]]:
    reviews: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("reviewer_id"):
                raise ValueError(f"{path}:{line_number}: reviewer_id is required")
            review_key = (row["candidate_id"], row["reviewer_id"])
            if review_key in seen:
                raise ValueError(
                    f"{path}:{line_number}: duplicate candidate/reviewer pair {review_key}"
                )
            seen.add(review_key)
            total = 0.0
            for field in HUMAN_FIELDS:
                value = row.get(field)
                if not isinstance(value, (int, float)) or not 0 <= value <= maxima[field]:
                    raise ValueError(
                        f"{path}:{line_number}: {field} must be within 0-{maxima[field]}"
                    )
                total += float(value)
            critical_errors = row.get("critical_errors", [])
            if not isinstance(critical_errors, list):
                raise ValueError(f"{path}:{line_number}: critical_errors must be an array")
            capped_total = min(total, critical_cap) if critical_errors else total
            row["raw_total"] = round(total, 4)
            row["capped_total"] = round(capped_total, 4)
            reviews[row["candidate_id"]].append(row)
    return reviews


def bootstrap_ci(values: list[float], *, seed: int, samples: int = 10000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    estimates = [
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(samples)
    ]
    estimates.sort()
    lower = estimates[int(0.025 * (samples - 1))]
    upper = estimates[int(0.975 * (samples - 1))]
    return [round(lower, 4), round(upper, 4)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--review", type=Path, action="append", default=[])
    parser.add_argument("--minimum-reviewers", type=int, default=2)
    parser.add_argument("--allow-incomplete-reviews", action="store_true")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    manifest = load_json(run_dir / "manifest.json")
    scores_report = load_json(run_dir / "scores.json")
    mapping = load_json(run_dir / "blind-map.json")
    protocol = load_json(run_dir / "protocol.json")
    seed = args.seed if args.seed is not None else manifest["seed"]
    maxima = {field: protocol["human_score"][field] for field in HUMAN_FIELDS}
    reviews = load_reviews(args.review, maxima, protocol["human_score"]["critical_error_cap"])
    map_by_key = {
        (item["case_id"], item["arm"], item["repeat"]): item["candidate_id"]
        for item in mapping["candidates"]
    }
    known_candidates = set(map_by_key.values())
    unknown_candidates = set(reviews) - known_candidates
    if unknown_candidates:
        raise ValueError(f"reviews contain unknown candidates: {sorted(unknown_candidates)}")

    runs: list[dict[str, Any]] = []
    for score in scores_report["scores"]:
        candidate_id = map_by_key[(score["case_id"], score["arm"], score["repeat"])]
        candidate_reviews = reviews.get(candidate_id, [])
        human = None
        if score["run_status"] != "completed":
            human = {
                "review_count": len(candidate_reviews),
                "raw_total": 0.0,
                "total": 0.0,
                "has_critical_error": False,
                "critical_error_reviews": 0,
                "reviewer_total_range": None,
                "dimensions": {field: None for field in HUMAN_FIELDS},
                "execution_failure_assigned_zero": True,
            }
        elif len(candidate_reviews) < args.minimum_reviewers:
            if not args.allow_incomplete_reviews:
                raise ValueError(
                    f"{candidate_id} has {len(candidate_reviews)} reviews; "
                    f"minimum is {args.minimum_reviewers}"
                )
        else:
            raw_total = mean([review["raw_total"] for review in candidate_reviews])
            has_critical_error = any(review["critical_errors"] for review in candidate_reviews)
            total = (
                min(raw_total, protocol["human_score"]["critical_error_cap"])
                if has_critical_error
                else raw_total
            )
            human = {
                "review_count": len(candidate_reviews),
                "raw_total": raw_total,
                "total": total,
                "has_critical_error": has_critical_error,
                "critical_error_reviews": sum(
                    bool(review["critical_errors"]) for review in candidate_reviews
                ),
                "reviewer_total_range": [
                    min(review["raw_total"] for review in candidate_reviews),
                    max(review["raw_total"] for review in candidate_reviews),
                ],
                "dimensions": {
                    field: mean([float(review[field]) for review in candidate_reviews])
                    for field in HUMAN_FIELDS
                },
                "execution_failure_assigned_zero": False,
            }
        runs.append({"candidate_id": candidate_id, **score, "human": human})

    arm_summary: dict[str, Any] = {}
    for arm in ARM_IDS:
        arm_runs = [run for run in runs if run["arm"] == arm]
        reviewed = [run for run in arm_runs if run["human"]]
        completed_reviewed = [
            run
            for run in reviewed
            if not run["human"]["execution_failure_assigned_zero"]
        ]
        objective = [run["objective"] for run in arm_runs if "objective" in run]
        arm_summary[arm] = {
            "runs": len(arm_runs),
            "reviewed_runs": len(reviewed),
            "human_total_mean": mean([run["human"]["total"] for run in reviewed]),
            "automatic_pass_rate": round(
                sum(run["automatic_status"] == "passed" for run in arm_runs) / max(len(arm_runs), 1),
                4,
            ),
            "token_recall_mean": mean(
                [item["token"]["recall"] for item in objective if item["token"]["applicable"]]
            ),
            "number_recall_mean": mean(
                [item["number"]["recall"] for item in objective if item["number"]["applicable"]]
            ),
            "page_coverage_mean": mean([item["page_markers"]["coverage"] for item in objective]),
            "total_tokens_mean": mean([float(run["usage"]["total_tokens"]) for run in arm_runs]),
            "wall_seconds_mean": mean([float(run["wall_seconds"]) for run in arm_runs]),
            "protocol_violation_runs": sum(bool(run["protocol_violations"]) for run in arm_runs),
            "critical_error_run_rate": round(
                sum(bool(run["human"]["has_critical_error"]) for run in completed_reviewed)
                / len(completed_reviewed),
                4,
            )
            if completed_reviewed
            else None,
            "execution_failure_rate": round(
                sum(run["run_status"] != "completed" for run in arm_runs)
                / max(len(arm_runs), 1),
                4,
            ),
        }

    categories = sorted({category for run in runs for category in run.get("categories", [])})
    category_summary = {
        category: {
            arm: mean(
                [
                    run["human"]["total"]
                    for run in runs
                    if run["arm"] == arm
                    and category in run.get("categories", [])
                    and run["human"]
                ]
            )
            for arm in ARM_IDS
        }
        for category in categories
    }

    case_arm_human: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        if run["human"]:
            case_arm_human[(run["case_id"], run["arm"])].append(run["human"]["total"])
    pairwise: list[dict[str, Any]] = []
    for left_index, left in enumerate(ARM_IDS):
        for right in ARM_IDS[left_index + 1 :]:
            common_cases = sorted(
                case_id
                for case_id, arm in case_arm_human
                if arm == left and (case_id, right) in case_arm_human
            )
            differences = [
                statistics.fmean(case_arm_human[(case_id, left)])
                - statistics.fmean(case_arm_human[(case_id, right)])
                for case_id in common_cases
            ]
            pairwise.append(
                {
                    "left": left,
                    "right": right,
                    "paired_cases": len(common_cases),
                    "mean_difference_left_minus_right": mean(differences),
                    "bootstrap_95_ci": bootstrap_ci(
                        differences,
                        seed=seed + left_index * 17 + ARM_IDS.index(right),
                    ),
                    "wins_ties_losses": {
                        "wins": sum(value > 0 for value in differences),
                        "ties": sum(value == 0 for value in differences),
                        "losses": sum(value < 0 for value in differences),
                    },
                }
            )

    summary = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "review_files": [str(path.resolve()) for path in args.review],
        "arm_summary": arm_summary,
        "category_human_summary": category_summary,
        "pairwise_human": pairwise,
        "runs": runs,
        "interpretation_rule": (
            "Quality superiority requires >=5 paired human-score points, a 95% CI "
            "excluding zero, no critical-error regression, and broad category support. "
            "Efficiency remains separate."
        ),
    }
    write_json(run_dir / "summary.json", summary)

    lines = ["# PDF-to-Markdown benchmark", "", f"Run: `{manifest['run_id']}`", "", "## Arms", ""]
    lines.append(
        "| Arm | Human | Auto pass | Token recall | Number recall | "
        "Page coverage | Tokens | Seconds |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for arm in ARM_IDS:
        item = arm_summary[arm]
        values = [
            arm,
            item["human_total_mean"],
            item["automatic_pass_rate"],
            item["token_recall_mean"],
            item["number_recall_mean"],
            item["page_coverage_mean"],
            item["total_tokens_mean"],
            item["wall_seconds_mean"],
        ]
        lines.append("| " + " | ".join("—" if value is None else str(value) for value in values) + " |")
    lines.extend(["", "## Paired blind-review differences", ""])
    for item in pairwise:
        lines.append(
            f"- `{item['left']}` − `{item['right']}`: {item['mean_difference_left_minus_right']} "
            f"(95% CI {item['bootstrap_95_ci']}, n={item['paired_cases']})"
        )
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(run_dir / "summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
