#!/usr/bin/env python3
"""Benchmark evaluation: blind the run outputs, validate Codex score files, compare arms.

    blind      copy each attempt's answer, reports, figures, small outputs and code into a folder named
               by a random ID, so the judge cannot see the arm; the ID-to-arm map is written separately
    validate   check score files against the task rubrics (criteria, 0-4 scores, weighted total)
    freeze     hash-lock a pre-registration file before any test run
    summarize  join scores with the map, apply the pre-registered comparisons, write report.md

Nothing here runs an agent, a model or the agents' code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import secrets
import shutil
import statistics
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
TASKS = BENCH / "tasks"
TEXT = {".md", ".py", ".ipynb", ".csv", ".json", ".txt"}
IMAGES = {".png", ".jpg", ".jpeg", ".svg"}
MAX_TEXT, MAX_OUTPUT, MAX_TOTAL = 2 * 1024**2, 20 * 1024**2, 400 * 1024**2
# Research-tree exports carry the policy (frontier mode, policy version), so they would reveal the arm.
NEVER_COPY = {"research_tree.json", "research_tree.sqlite3", "research_tree.lock", "arm.json", "arm_lessons.json"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rubric(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "evaluator" / "rubric.json").read_text())


def task_info(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "task_info.json").read_text())


def breakdown(diffs, tasks, field):
    """Mean paired difference per value of a task field (question type, or private versus public data)."""
    groups = {}
    for diff, task in zip(diffs, tasks):
        groups.setdefault(task_info(task)[field], []).append(diff)
    return {value: {"mean_diff": statistics.fmean(v), "tasks": len(v)} for value, v in sorted(groups.items())}


# ------------------------------------------------------------------------------------------ blind
def latest_attempts(arm_dir: Path):
    for case in sorted(p for p in arm_dir.iterdir() if p.is_dir() and (p.name[:1] in "QE")):
        attempts = sorted(case.glob("attempt-*/result.json"))
        if attempts:
            yield case.name, attempts[-1].parent


def evidence_files(attempt: Path):
    """Answer, Agent reports, published outputs and small code/tables; never state, logs or the tree."""
    yield attempt / "answer.md"
    tasks_root = attempt / "workspace" / "OceanX Tasks"
    for path in sorted(tasks_root.rglob("*")) if tasks_root.is_dir() else []:
        if not path.is_file() or path.is_symlink() or path.name in NEVER_COPY:
            continue
        parts = set(path.relative_to(tasks_root).parts)
        if ".runtime" in parts or "kernel" in parts:
            continue
        suffix = path.suffix.lower()
        size = path.stat().st_size
        if "outputs" in parts and (suffix in IMAGES or suffix == ".nc") and size <= MAX_OUTPUT or suffix in TEXT and size <= MAX_TEXT:
            yield path


def blind(args) -> dict:
    out = args.out.expanduser().resolve()
    mapping_path = args.map.expanduser().resolve()
    if mapping_path.is_relative_to(out):
        raise SystemExit("ERROR: keep the blind map outside the folder the judge reads")
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    seen = {entry["attempt"] for entry in mapping.values()}
    created = 0
    for arm_dir in args.runs:
        arm_dir = arm_dir.expanduser().resolve()
        arm = json.loads((arm_dir / "arm.json").read_text())
        for task_id, attempt in latest_attempts(arm_dir):
            if str(attempt) in seen:
                continue
            blind_id = "b" + secrets.token_hex(6)
            target = out / blind_id
            target.mkdir(parents=True)
            total = 0
            for source in evidence_files(attempt):
                if not source.is_file():
                    continue
                relative = source.relative_to(attempt)
                destination = target / "evidence" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                total += source.stat().st_size
                if total > MAX_TOTAL:
                    break
                if source.suffix.lower() in TEXT:
                    # Absolute run paths contain the arm folder name; replace them.
                    text = source.read_text(encoding="utf-8", errors="replace").replace(str(arm_dir), "<RUN>")
                    destination.write_text(text, encoding="utf-8")
                else:
                    shutil.copyfile(source, destination)
            result = json.loads((attempt / "result.json").read_text())
            query = json.loads((attempt / "query.json").read_text())["query"]
            write_json(target / "task.json", {"blind_id": blind_id, "task_id": task_id, "query": query,
                                              "status": result.get("status")})
            mapping[blind_id] = {"task_id": task_id, "arm": arm["arm"], "policy": arm.get("policy"),
                                 "lessons_version": (arm.get("lessons") or {}).get("version"),
                                 "arm_dir": str(arm_dir), "attempt": str(attempt), "status": result.get("status"),
                                 "elapsed_seconds": result.get("elapsed_seconds"), "tokens": tokens(result)}
            created += 1
    write_json(mapping_path, mapping)
    return {"created": created, "total": len(mapping), "blind_folder": str(out), "map": str(mapping_path)}


def tokens(result: dict) -> int:
    usages = [result.get("coordinator_usage") or {}]
    if isinstance(result.get("expert_usage"), dict):
        usages += list(result["expert_usage"].values())
    return sum(int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
               for u in usages if isinstance(u, dict))


# ------------------------------------------------------------------------------------------ validate
def validate_score(score: dict) -> list[str]:
    errors = []
    try:
        ref = rubric(score["task_id"])
    except (KeyError, FileNotFoundError):
        return ["unknown task_id"]
    weights = {c["id"]: c["weight"] for c in ref["criteria"]}
    given = {c.get("id"): c for c in score.get("criteria", [])}
    if set(given) != set(weights):
        errors.append(f"criteria ids {sorted(given)} != rubric {sorted(weights)}")
    for cid, item in given.items():
        if item.get("score") not in (0, 1, 2, 3, 4):
            errors.append(f"{cid}: score must be an integer 0-4")
        if not str(item.get("evidence", "")).strip():
            errors.append(f"{cid}: evidence is required")
    if not errors:
        total = sum(weights[cid] * given[cid]["score"] / 4 for cid in weights)
        if abs(total - float(score.get("total", -1))) > 0.01:
            errors.append(f"total {score.get('total')} != weighted sum {total:.2f}")
    if score.get("rubric_status") != "frozen" and score.get("status") == "completed":
        errors.append("rubric was not frozen when judged (references and tolerances must be frozen first)")
    for key in ("blind_id", "judge"):
        if not score.get(key):
            errors.append(f"missing {key}")
    return errors


def validate(args) -> dict:
    report = {}
    for path in sorted(args.scores.glob("*.json")):
        report[path.name] = validate_score(json.loads(path.read_text()))
    bad = {k: v for k, v in report.items() if v}
    return {"files": len(report), "invalid": bad}


# ------------------------------------------------------------------------------------------ freeze / summarize
def freeze(args) -> dict:
    digest = sha256(args.prereg)
    lock = args.prereg.with_name(args.prereg.name + ".sha256")
    if lock.exists():
        raise SystemExit("ERROR: already frozen; a changed pre-registration needs a new experiment name")
    lock.write_text(digest + "\n")
    return {"frozen": str(args.prereg), "sha256": digest}


def bootstrap_ci(values, resamples, seed):
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def decide(rule: dict, comparison: dict) -> bool:
    if rule["type"] == "superior":
        return comparison["ci_low"] > rule.get("margin", 0)
    if rule["type"] == "noninferior_and_better_or_cheaper":
        return comparison["ci_low"] >= rule["margin"] and (
            comparison["mean_diff"] > 0 or (comparison["token_reduction"] or 0) >= rule["token_reduction"])
    raise ValueError(f"unknown rule type {rule['type']}")


def summarize(args) -> dict:
    import yaml
    prereg_text = args.prereg.read_bytes()
    lock = args.prereg.with_name(args.prereg.name + ".sha256")
    if not lock.exists() or lock.read_text().strip() != hashlib.sha256(prereg_text).hexdigest():
        raise SystemExit("ERROR: the pre-registration is not frozen or changed after freezing")
    prereg = yaml.safe_load(prereg_text)
    mapping = json.loads(args.map.read_text())
    scores = {}
    for path in sorted(args.scores.glob("*.json")):
        score = json.loads(path.read_text())
        if validate_score(score):
            raise SystemExit(f"ERROR: invalid score file {path.name}; run validate first")
        scores[score["blind_id"]] = score
    failed_score = float(prereg.get("failed_attempt_score", 0))
    rows = []
    for blind_id, entry in mapping.items():
        score = scores.get(blind_id)
        if score is None and entry["status"] == "completed":
            raise SystemExit(f"ERROR: completed attempt {blind_id} has no score")
        total = float(score["total"]) if score else failed_score
        rows.append({**entry, "blind_id": blind_id, "total": total,
                     "type": rubric(entry["task_id"])["type"]})
    by = {}
    for row in rows:
        by.setdefault((row["arm"], row["task_id"]), []).append(row)
    cell = {key: {"score": statistics.fmean(r["total"] for r in group),
                  "tokens": statistics.fmean(r["tokens"] for r in group),
                  "elapsed": statistics.fmean(r["elapsed_seconds"] or 0 for r in group),
                  "failures": sum(r["status"] != "completed" for r in group), "n": len(group)}
            for key, group in by.items()}
    arms = sorted({arm for arm, _ in cell})
    per_arm = {arm: {"mean_score": statistics.fmean(v["score"] for (a, _), v in cell.items() if a == arm),
                     "failures": sum(v["failures"] for (a, _), v in cell.items() if a == arm),
                     "tokens": sum(v["tokens"] for (a, _), v in cell.items() if a == arm),
                     "elapsed_hours": sum(v["elapsed"] for (a, _), v in cell.items() if a == arm) / 3600}
               for arm in arms}
    boot = prereg.get("bootstrap", {})
    comparisons = []
    for spec in prereg["comparisons"]:
        treat, control = spec["treatment"], spec["control"]
        tasks = sorted(t for a, t in cell if a == treat and (control, t) in cell)
        diffs = [cell[(treat, t)]["score"] - cell[(control, t)]["score"] for t in tasks]
        if not diffs:
            comparisons.append({**spec, "tasks": 0, "decision": None})
            continue
        low, high = bootstrap_ci(diffs, int(boot.get("resamples", 10000)), int(boot.get("seed", 7)))
        tokens_t = sum(cell[(treat, t)]["tokens"] for t in tasks)
        tokens_c = sum(cell[(control, t)]["tokens"] for t in tasks)
        comparison = {"name": spec["name"], "treatment": treat, "control": control, "tasks": len(tasks),
                      "mean_diff": statistics.fmean(diffs), "ci_low": low, "ci_high": high,
                      "wins": sum(d > 0 for d in diffs), "losses": sum(d < 0 for d in diffs),
                      "token_reduction": (tokens_c - tokens_t) / tokens_c if tokens_c else None,
                      "by_type": breakdown(diffs, tasks, "type"), "by_data": breakdown(diffs, tasks, "data_access")}
        comparison["decision"] = decide(spec["rule"], comparison)
        comparisons.append(comparison)
    summary = {"experiment": prereg["experiment"], "arms": per_arm, "comparisons": comparisons,
               "cells": {f"{a}|{t}": v for (a, t), v in sorted(cell.items())}}
    out = args.out.expanduser().resolve()
    write_json(out / "summary.json", summary)
    lines = [f"# {prereg['experiment']}", "", "| Arm | Mean score | Failures | Tokens | Hours |", "|---|---|---|---|---|"]
    lines += [f"| {a} | {v['mean_score']:.1f} | {v['failures']} | {v['tokens']:.3g} | {v['elapsed_hours']:.1f} |"
              for a, v in per_arm.items()]
    lines += ["", "| Comparison | Tasks | Mean diff | 95% CI | Wins/losses | Token cut | Decision |",
              "|---|---|---|---|---|---|---|"]
    for c in comparisons:
        if c.get("decision") is None:
            lines.append(f"| {c['name']} | 0 | | | | | no paired tasks |")
            continue
        cut = f"{c['token_reduction']:.0%}" if c["token_reduction"] is not None else "n/a"
        lines.append(f"| {c['name']} ({c['treatment']} vs {c['control']}) | {c['tasks']} | {c['mean_diff']:+.1f} | "
                     f"[{c['ci_low']:+.1f}, {c['ci_high']:+.1f}] | {c['wins']}/{c['losses']} | {cut} | "
                     f"{'meets rule' if c['decision'] else 'does not meet rule'} |")
    for c in comparisons:
        for field in ("by_type", "by_data"):
            if c.get(field):
                parts = ", ".join(f"{k} {v['mean_diff']:+.1f} ({v['tasks']} tasks)" for k, v in c[field].items())
                lines.append(f"\n{c['name']}, mean difference {field.replace('_', ' ')}: {parts}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out / "report.md"), "comparisons": [(c["name"], c.get("decision")) for c in comparisons]}


def lessons_check(args) -> dict:
    """Every attempt of a lesson arm must report its lessons unchanged."""
    problems = []
    for record in sorted(args.runs.expanduser().rglob("arm_lessons.json")):
        if not json.loads(record.read_text()).get("unchanged"):
            problems.append(str(record))
    return {"checked": len(list(args.runs.expanduser().rglob("arm_lessons.json"))), "changed_or_unfinished": problems}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("blind")
    b.add_argument("--runs", type=Path, nargs="+", required=True, help="Arm output folders (with arm.json)")
    b.add_argument("--out", type=Path, required=True, help="Folder the judge reads")
    b.add_argument("--map", type=Path, required=True, help="Blind-ID map, kept outside --out")
    v = sub.add_parser("validate")
    v.add_argument("--scores", type=Path, required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--prereg", type=Path, required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--prereg", type=Path, required=True)
    s.add_argument("--map", type=Path, required=True)
    s.add_argument("--scores", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    lc = sub.add_parser("lessons-check")
    lc.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args(argv)
    handler = {"blind": blind, "validate": validate, "freeze": freeze, "summarize": summarize,
               "lessons-check": lessons_check}[args.command]
    print(json.dumps(handler(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
