#!/usr/bin/env python3
"""Run isolated, randomized, two-turn PDF-to-Markdown benchmark sessions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from typing import Any

from benchmark_common import (
    ARM_IDS,
    build_initial_prompt,
    load_json,
    parse_case_paths,
    parse_thread_id,
    skills_override,
    sha256_file,
    sha256_tree,
    usage_from_jsonl,
    verify_case,
    write_json,
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "wall_seconds": round(time.monotonic() - started, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "returncode": None,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
            "wall_seconds": round(time.monotonic() - started, 3),
            "timed_out": True,
        }


def deliverable_files(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file())


def version_output(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return output or None


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def base_command(args: argparse.Namespace, workspace: Path, skills: str) -> list[str]:
    command = [
        args.codex_bin,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ignore-rules",
        "-C",
        str(workspace),
        "-s",
        "workspace-write",
        "--approve-for-me",
        "-m",
        args.model,
        "-c",
        f"model_reasoning_effort={json.dumps(args.reasoning_effort)}",
        "-c",
        "features.multi_agent=false",
        "-c",
        "features.multi_agent_v2=false",
        "-c",
        "features.memories=false",
        "-c",
        "features.plugins=false",
        "-c",
        f"skills.config={skills}",
    ]
    if args.ignore_user_config:
        command.append("--ignore-user-config")
    return command


def resume_command(
    args: argparse.Namespace,
    thread_id: str,
    last_message: Path,
    confirmation: str,
    skills: str,
) -> list[str]:
    command = [
        args.codex_bin,
        "exec",
        "resume",
        "--json",
        "--skip-git-repo-check",
        "--ignore-rules",
        "-m",
        args.model,
        "-c",
        f"model_reasoning_effort={json.dumps(args.reasoning_effort)}",
        "-c",
        "features.multi_agent=false",
        "-c",
        "features.multi_agent_v2=false",
        "-c",
        "features.memories=false",
        "-c",
        "features.plugins=false",
        "-c",
        f"skills.config={skills}",
    ]
    if args.ignore_user_config:
        command.append("--ignore-user-config")
    command.extend(["-o", str(last_message), thread_id, confirmation])
    return command


def execute_job(
    args: argparse.Namespace,
    protocol: dict[str, Any],
    run_root: Path,
    job: dict[str, Any],
) -> dict[str, Any]:
    case = job["case"]
    arm = job["arm"]
    repeat = job["repeat"]
    job_root = run_root / "executions" / case["id"] / arm / f"repeat-{repeat:02d}"
    workspace = job_root / "workspace"
    deliverable = workspace / "deliverable"
    workspace.mkdir(parents=True, exist_ok=False)
    deliverable.mkdir()
    source_copy = workspace / "input.pdf"
    shutil.copyfile(case["source_path"], source_copy)
    source_copy.chmod(0o444)

    skill_config = skills_override(
        arm,
        pdf_skill=args.pdf_skill,
        processing_pdf_skill=args.processing_pdf_skill,
        extracting_pdf_text_skill=args.extracting_pdf_text_skill,
        route_skill=args.route_skill,
    )
    initial_prompt = build_initial_prompt(protocol, arm)
    confirmation = protocol["turns"]["confirmation"]
    (job_root / "initial-prompt.txt").write_text(initial_prompt + "\n", encoding="utf-8")
    (job_root / "confirmation-prompt.txt").write_text(confirmation + "\n", encoding="utf-8")

    first_last_message = job_root / "turn-1-last-message.txt"
    first_command = base_command(args, workspace, skill_config)
    first_command.extend(["-o", str(first_last_message), initial_prompt])
    first = run_command(first_command, args.timeout)
    (job_root / "turn-1-events.jsonl").write_text(first["stdout"], encoding="utf-8")
    (job_root / "turn-1-stderr.txt").write_text(first["stderr"], encoding="utf-8")
    pre_confirmation_files = deliverable_files(deliverable)
    thread_id = parse_thread_id(first["stdout"])

    second: dict[str, Any] | None = None
    if first["returncode"] == 0 and thread_id:
        second_last_message = job_root / "turn-2-last-message.txt"
        second = run_command(
            resume_command(
                args,
                thread_id,
                second_last_message,
                confirmation,
                skill_config,
            ),
            args.timeout,
        )
        (job_root / "turn-2-events.jsonl").write_text(second["stdout"], encoding="utf-8")
        (job_root / "turn-2-stderr.txt").write_text(second["stderr"], encoding="utf-8")

    deletion: dict[str, Any] | None = None
    if thread_id and not args.keep_sessions:
        deletion = run_command([args.codex_bin, "delete", "--force", thread_id], 60)

    full_markdown = deliverable / "full.md"
    protocol_violations: list[str] = []
    if pre_confirmation_files:
        protocol_violations.append("deliverable-written-before-confirmation")
    if not thread_id:
        protocol_violations.append("session-id-not-found")
    if not full_markdown.is_file():
        protocol_violations.append("required-full-md-missing")
    if thread_id and not args.keep_sessions and not (deletion and deletion["returncode"] == 0):
        protocol_violations.append("session-delete-failed")

    first_usage = usage_from_jsonl(first["stdout"])
    second_usage = usage_from_jsonl(second["stdout"]) if second else {key: 0 for key in first_usage}
    usage = {key: first_usage[key] + second_usage[key] for key in first_usage}
    result = {
        "schema_version": 1,
        "case_id": case["id"],
        "split": case["split"],
        "categories": case["categories"],
        "arm": arm,
        "repeat": repeat,
        "source": {
            "sha256": case["sha256"],
            "size_bytes": case["size_bytes"],
            "pages": case["pages"],
        },
        "started_at": job["started_at"],
        "finished_at": iso_now(),
        "thread_id_deleted": bool(deletion and deletion["returncode"] == 0),
        "turn_1": {
            "returncode": first["returncode"],
            "timed_out": first["timed_out"],
            "wall_seconds": first["wall_seconds"],
        },
        "turn_2": None
        if second is None
        else {
            "returncode": second["returncode"],
            "timed_out": second["timed_out"],
            "wall_seconds": second["wall_seconds"],
        },
        "usage": usage,
        "pre_confirmation_files": pre_confirmation_files,
        "deliverable_files": deliverable_files(deliverable),
        "protocol_violations": protocol_violations,
        "status": "completed"
        if second is not None
        and second["returncode"] == 0
        and full_markdown.is_file()
        and not first["timed_out"]
        and not second["timed_out"]
        else "failed",
    }
    write_json(job_root / "run.json", result)
    return result


def main() -> int:
    benchmark_root = Path(__file__).resolve().parent.parent
    skill_root = benchmark_root.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        type=Path,
        default=benchmark_root / "testdata/benchmark-protocol.json",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=benchmark_root / "testdata/benchmark-cases.json",
    )
    parser.add_argument("--case-path", action="append", default=[])
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--split", action="append", choices=("calibration", "test"), default=[])
    parser.add_argument("--arms", default=",".join(ARM_IDS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        required=True,
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--output-root", type=Path, default=benchmark_root / "output")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--allow-missing-cases", action="store_true")
    parser.add_argument("--keep-sessions", action="store_true")
    parser.add_argument("--ignore-user-config", action="store_true")
    parser.add_argument("--pdf-skill", type=Path, default=Path.home() / ".codex/skills/pdf/SKILL.md")
    parser.add_argument("--pdf-skill-provenance", default="unspecified")
    parser.add_argument(
        "--processing-pdf-skill",
        type=Path,
        default=Path.home() / ".codex/skills/processing-pdf/SKILL.md",
    )
    parser.add_argument(
        "--extracting-pdf-text-skill",
        type=Path,
        default=Path.home() / ".codex/skills/extracting-pdf-text/SKILL.md",
    )
    parser.add_argument("--route-skill", type=Path, default=skill_root / "SKILL.md")
    args = parser.parse_args()

    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    protocol = load_json(args.protocol)
    corpus = load_json(args.corpus)
    if protocol.get("schema_version") != 1 or corpus.get("schema_version") != 1:
        raise ValueError("unsupported benchmark schema")
    if set(protocol["arms"]) != set(ARM_IDS):
        raise ValueError("protocol arms do not match runner arms")
    score_total = sum(
        protocol["human_score"][key]
        for key in protocol["human_score"]
        if key != "critical_error_cap"
    )
    if score_total != 100:
        raise ValueError("human score dimensions must total 100")
    overrides = parse_case_paths(args.case_path)
    selected_ids = set(args.only)
    selected_splits = set(args.split)
    selected_arms = tuple(part for part in args.arms.split(",") if part)
    if not selected_arms or any(arm not in ARM_IDS for arm in selected_arms):
        raise ValueError(f"--arms must contain only: {', '.join(ARM_IDS)}")

    corpus_ids = [case["id"] for case in corpus["cases"]]
    if len(corpus_ids) != len(set(corpus_ids)):
        raise ValueError("corpus contains duplicate case ids")
    missing_selected_ids = selected_ids - set(corpus_ids)
    if missing_selected_ids:
        raise ValueError(f"unknown --only case ids: {sorted(missing_selected_ids)}")

    cases: list[dict[str, Any]] = []
    validation_issues: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        if selected_ids and case["id"] not in selected_ids:
            continue
        if selected_splits and case["split"] not in selected_splits:
            continue
        source = overrides.get(case["id"])
        if source is None and case.get("default_path"):
            source = Path(case["default_path"]).expanduser().resolve()
        issues = ["case-path-not-configured"] if source is None else verify_case(case, source)
        if issues:
            validation_issues.append({"case_id": case["id"], "issues": issues})
            continue
        resolved = dict(case)
        resolved["source_path"] = str(source)
        cases.append(resolved)
    if validation_issues and not args.allow_missing_cases:
        raise ValueError(f"selected cases failed validation: {validation_issues}")
    if not cases:
        raise ValueError(f"no runnable cases: {validation_issues}")

    seed = args.seed if args.seed is not None else protocol["seed"]
    timeout = args.timeout or protocol["limits"]["default_timeout_seconds"]
    args.timeout = timeout
    jobs = [
        {"case": case, "arm": arm, "repeat": repeat}
        for case in cases
        for arm in selected_arms
        for repeat in range(1, args.repeats + 1)
    ]
    random.Random(seed).shuffle(jobs)
    if args.formal:
        requirements = protocol["formal_requirements"]
        if selected_splits != {"test"}:
            raise ValueError("--formal requires exactly --split test")
        if args.repeats < requirements["minimum_repeats"]:
            raise ValueError("--formal repeat count is below the frozen minimum")
        if set(selected_arms) != set(requirements["required_arms"]):
            raise ValueError("--formal requires every frozen arm")
        if len(cases) < requirements["minimum_test_cases"]:
            raise ValueError("--formal test corpus is below the frozen minimum")
        observed_categories = {category for case in cases for category in case["categories"]}
        missing_categories = set(requirements["required_categories"]) - observed_categories
        if missing_categories:
            raise ValueError(f"--formal corpus lacks categories: {sorted(missing_categories)}")
    plan = {
        "benchmark_id": protocol["benchmark_id"],
        "seed": seed,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "timeout_seconds": timeout,
        "job_count": len(jobs),
        "validation_issues": validation_issues,
        "jobs": [
            {"order": index, "case_id": job["case"]["id"], "arm": job["arm"], "repeat": job["repeat"]}
            for index, job in enumerate(jobs, 1)
        ],
    }
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "reference_pdf_skill_provenance": args.pdf_skill_provenance,
                    **plan,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if shutil.which(args.codex_bin) is None:
        raise FileNotFoundError(args.codex_bin)
    if "reference-pdf" in selected_arms and args.pdf_skill_provenance == "unspecified":
        raise ValueError(
            "--pdf-skill-provenance is required when executing the reference-pdf arm"
        )
    for skill_path in (
        args.pdf_skill,
        args.processing_pdf_skill,
        args.extracting_pdf_text_skill,
        args.route_skill,
    ):
        if not skill_path.is_file():
            raise FileNotFoundError(skill_path)

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = args.output_root.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": iso_now(),
        "status": "running",
        **plan,
        "results": [],
    }
    write_json(run_root / "protocol.json", protocol)
    write_json(run_root / "corpus.json", corpus)
    manifest["frozen_inputs"] = {
        "protocol_sha256": sha256_file(args.protocol.resolve()),
        "corpus_sha256": sha256_file(args.corpus.resolve()),
        "skills": {
            "pdf": {
                "sha256": sha256_tree(args.pdf_skill.resolve().parent),
                "provenance": args.pdf_skill_provenance,
            },
            "processing-pdf": sha256_tree(args.processing_pdf_skill.resolve().parent),
            "extracting-pdf-text": sha256_tree(args.extracting_pdf_text_skill.resolve().parent),
            "route-pdf-tasks": sha256_tree(args.route_skill.resolve().parent),
        },
        "runtime": {
            "codex": version_output([args.codex_bin, "--version"]),
            "python": sys.version,
            "pdfplumber": package_version("pdfplumber"),
            "pypdf": package_version("pypdf"),
            "pdftotext": version_output(["pdftotext", "-v"]),
            "pdfinfo": version_output(["pdfinfo", "-v"]),
            "route_git_head": version_output(
                ["git", "-C", str(args.route_skill.resolve().parent), "rev-parse", "HEAD"]
            ),
        },
    }
    write_json(run_root / "manifest.json", manifest)

    for index, job in enumerate(jobs, 1):
        job["started_at"] = iso_now()
        print(
            f"[{index}/{len(jobs)}] {job['case']['id']} "
            f"{job['arm']} repeat-{job['repeat']:02d}",
            flush=True,
        )
        result = execute_job(args, protocol, run_root, job)
        manifest["results"].append(
            {
                "case_id": result["case_id"],
                "arm": result["arm"],
                "repeat": result["repeat"],
                "status": result["status"],
                "protocol_violations": result["protocol_violations"],
            }
        )
        write_json(run_root / "manifest.json", manifest)

    manifest["status"] = "completed"
    manifest["finished_at"] = iso_now()
    write_json(run_root / "manifest.json", manifest)
    print(run_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
