#!/usr/bin/env python3
"""Prepare runner inputs (JSONL) for the test or evolution suite from the shared data root, without copying data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

BENCH = Path(__file__).resolve().parents[1]
TASKS = BENCH / "tasks"
EVOLUTION = BENCH / "evolution"
MANIFEST = BENCH / "download" / "data_manifest.json"
SUITE_DIRS = {"test": TASKS, "evolution": EVOLUTION}
DATA_SUFFIXES = {".nc", ".nc4", ".cdf"}
# Never an agent input: evaluator rubrics, references, answer-key data and legacy reference folders.
FORBIDDEN_PARTS = {"evaluator", "target_study", "_evaluator_only", "checklist.json", "rubric.json"}


def task_file(task_id: str) -> Path:
    if not re.fullmatch(r"Q(?:0[1-9]|[12][0-9]|30)|E(?:0[1-9]|1[0-9]|2[0-4])", task_id):
        raise ValueError(f"Invalid task ID: {task_id}")
    return (TASKS if task_id.startswith("Q") else EVOLUTION) / task_id / "task_info.json"


def suite_tasks(suite: str, evolution_set: str | None = None) -> list[str]:
    """The suite's tasks; for the evolution suite, optionally one of its two sets (A or B)."""
    tasks = sorted(p.name for p in SUITE_DIRS[suite].iterdir() if (p / "task_info.json").is_file())
    if evolution_set is None:
        return tasks
    return [t for t in tasks if json.loads(task_file(t).read_text()).get("evolution_set") == evolution_set]


def read_coverage(root):
    manifest = json.loads(MANIFEST.read_text())
    coverage = json.loads((Path(root) / "_download_all" / "coverage.json").read_text())
    if coverage.get("catalogue") != manifest["version"]:
        raise ValueError("Download catalogue differs from the current benchmark; rerun download_all.py")
    return manifest, coverage


def manifest_bindings(task_ids, root):
    """Agent data folders from the one canonical manifest, after the downloader's completion reports."""
    manifest, coverage = read_coverage(root)
    control = Path(root) / "_download_all"
    result = {}
    for task_id in task_ids:
        state = coverage.get("tasks", {}).get(task_id, {})
        if state.get("numerical_inputs_complete") is not True:
            raise ValueError(f"{task_id}: inputs incomplete ({state.get('missing_groups')}); run download_all.py public/services/private first")
        task = json.loads(task_file(task_id).read_text())
        if task["catalog_version"] != manifest["version"] or task["data_groups"] != manifest["tasks"][task_id]:
            raise ValueError(f"{task_id}: task and data manifest disagree")
        for group in task["data_groups"]:
            identity = hashlib.sha256(json.dumps(manifest["groups"][group], sort_keys=True).encode()).hexdigest()
            report = json.loads((control / f"{group}.report.json").read_text())
            if report.get("group_sha256") != identity or report.get("complete") is not True:
                raise ValueError(f"{task_id}: data group {group} is incomplete or from another manifest version")
        folders = [f"{manifest['groups'][g]['data_type']}/{f}" for g in task["data_groups"]
                   for f in manifest["groups"][g]["folders"]]
        result[task_id] = {"datasets": list(dict.fromkeys(folders))}
    return result


def resolve_resource(root, value):
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if ".." in candidate.parts:
        raise ValueError(f"Parent traversal is not allowed: {value}")
    if FORBIDDEN_PARTS & set(candidate.parts):
        raise ValueError(f"Evaluator-only material is not an agent input: {candidate}")
    for part in [candidate, *candidate.parents]:
        if part.is_symlink():
            raise ValueError(f"Use the original resource, not a symlink: {candidate}")
    candidate = candidate.resolve(strict=True)
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError("Resources must be below --data-root, not the entire data root")
    if candidate.is_file():
        if candidate.suffix.lower() not in DATA_SUFFIXES | {".pdf", ".json", ".csv"} or not candidate.stat().st_size:
            raise ValueError(f"Unsupported or empty input file: {candidate}")
        return str(candidate)
    if not candidate.is_dir():
        raise ValueError(f"Not a regular file or directory: {candidate}")
    found = False
    for parent, dirs, files in os.walk(candidate, followlinks=False):
        for name in dirs + files:
            item = Path(parent) / name
            if item.is_symlink():
                raise ValueError(f"Symlink inside input directory: {item}")
            if name in FORBIDDEN_PARTS:
                raise ValueError(f"Evaluator material must not be exposed: {item}")
            if item.is_file() and item.suffix.lower() in DATA_SUFFIXES and item.stat().st_size:
                found = True
    if not found:
        raise ValueError(f"No nonempty data files in directory: {candidate}")
    return str(candidate)


def build_cases(task_ids, root, bindings, timeout=10800, literature_mode="search_only"):
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError("Provide a dedicated existing data root")
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("Choose unique task IDs")
    if not 0 < timeout <= 604800:
        raise ValueError("Timeout must be in (0, 604800]")
    cases = []
    for task_id in task_ids:
        task = json.loads(task_file(task_id).read_text())
        binding = bindings.get(task_id)
        if not isinstance(binding, dict) or not binding.get("datasets"):
            raise ValueError(f"{task_id}: no dataset binding; no product or run is guessed")
        paths = binding["datasets"] + binding.get("papers", [])
        resolved = list(dict.fromkeys(resolve_resource(root, p) for p in paths))
        if len(resolved) > 64:
            raise ValueError(f"{task_id}: more than 64 resources; bind variable folders instead of files")
        cases.append({"id": task_id, "query": task["query"], "datasets": resolved,
                      "timeout_seconds": timeout, "literature_mode": literature_mode,
                      "workflow_mode": "research"})
    return cases


def prepare_selection(root, suite, *, tasks=None, evolution_set=None, available_only=False,
                      bindings_path=None, timeout=10800, literature_mode='search_only'):
    """Validate and select once, shared by the explicit CLI and .env-driven runners."""
    if evolution_set and suite != 'evolution':
        raise ValueError('--set applies to the evolution suite only')
    available = suite_tasks(suite, evolution_set)
    tasks = tasks or available
    if len(tasks) != len(set(tasks)):
        raise ValueError('Choose unique task IDs')
    if set(tasks) - set(available):
        raise ValueError(f'Not in the {suite} suite: {sorted(set(tasks) - set(available))}')
    root = Path(root).expanduser().resolve(strict=True)
    if available_only:
        if bindings_path:
            raise ValueError('--available uses verified manifest coverage, not --bindings overrides')
        _, coverage = read_coverage(root)
        selected = []
        for task in tasks:
            state = coverage.get('tasks', {}).get(task, {})
            if state.get('numerical_inputs_complete') is True:
                selected.append(task)
            else:
                print(f"{task}: excluded; missing groups: {state.get('missing_groups', 'no completion record')}")
        tasks = selected
        if not tasks:
            raise ValueError('No tasks with complete numerical inputs; no query file written')
    bindings = (json.loads(Path(bindings_path).read_text()) if bindings_path
                else manifest_bindings(tasks, root))
    return build_cases(tasks, root, bindings, timeout, literature_mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--suite", choices=sorted(SUITE_DIRS), required=True)
    parser.add_argument("--tasks", nargs="+", help="Subset of the suite; default: all of it")
    parser.add_argument("--available", action="store_true",
                        help="Select only tasks whose numerical inputs are complete; print every excluded task")
    parser.add_argument("--set", dest="evolution_set", choices=["A", "B"],
                        help="Evolution suite only: set A (E01-E12, learns L1) or set B (E13-E24, learns L2)")
    parser.add_argument("--bindings", type=Path, help="Optional JSON overriding the manifest folders per task")
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file outside the data root")
    parser.add_argument("--timeout", type=float, default=10800,
                        help="Per-case wall-clock limit in seconds (default: 3 hours; a timed-out attempt scores 0)")
    parser.add_argument("--literature-mode", choices=["search_only", "ask_before_download", "auto_download_open_access"],
                        default="search_only")
    args = parser.parse_args(argv)
    root = args.data_root.expanduser().resolve(strict=True)
    cases = prepare_selection(root, args.suite, tasks=args.tasks, evolution_set=args.evolution_set,
                              available_only=args.available, bindings_path=args.bindings,
                              timeout=args.timeout, literature_mode=args.literature_mode)
    target = args.output.expanduser().absolute()
    if target.resolve().is_relative_to(root):
        raise ValueError("Write runner inputs outside the shared data root")
    target.parent.mkdir(parents=True, exist_ok=True)
    # All resources are checked before anything is created. Never replace an existing query set.
    with target.open("x", encoding="utf-8") as stream:
        for case in cases:
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")
    for case in cases:
        print(f"{case['id']}: {len(case['datasets'])} read-only references; query SHA256={hashlib.sha256(case['query'].encode()).hexdigest()[:16]}")
    print(f"Wrote {target} ({len(cases)} cases). No data copied; no agent started.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(f"ERROR: {exc}")
