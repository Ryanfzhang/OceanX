#!/usr/bin/env python3
"""Benchmark evaluation: blind the run outputs, validate Codex score files, compare arms.

    blind      copy each attempt's answer, reports, figures, small outputs and code into a folder named
               by a random ID, so the judge cannot see the arm; the ID-to-arm map is written separately
    validate   check score files against the task rubrics (criteria, 0-4 scores, weighted total)
    freeze     hash-lock a pre-registration file before any test run
    summarize  join scores with the map, apply the pre-registered comparisons, write report.md
    process    measure how each attempt's research tree went (needs OceanX importable), compare arms
               on the pre-registered process metric, write process.md
    inventory  write run_record.json and run_record.md into every attempt (time, tokens, code runs, what
               each question of the tree cost, every .md file, disk use) and check that nothing needed
               for a later evaluation is missing

Nothing here runs an agent, a model or the agents' code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import secrets
import shutil
import sqlite3
import statistics
from contextlib import closing
from datetime import datetime
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
TASKS = BENCH / "tasks"
TEXT = {".md", ".py", ".ipynb", ".csv", ".json", ".txt"}
IMAGES = {".png", ".jpg", ".jpeg", ".svg"}
MAX_TEXT, MAX_OUTPUT, MAX_TOTAL = 2 * 1024**2, 20 * 1024**2, 400 * 1024**2
# Research-tree exports carry the policy (frontier mode, policy version), so they would reveal the arm.
NEVER_COPY = {"research_tree.json", "research_tree.sqlite3", "research_tree.lock", "arm.json",
              "arm_library.json", "arm_lessons.json"}


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
    manifest = attempt / "evidence_manifest.json"
    if manifest.is_file():
        # External baselines export an explicit allowlist, not an OceanX workspace.
        # Never follow an input mount/link or expose raw transcripts/credentials.
        for name in json.loads(manifest.read_text()).get("files", []):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError("Unsafe external evidence path")
            if relative.parts[0] not in {"workspace", "outputs", "figures", "code"}:
                raise ValueError("External evidence must be a notebook or a published output")
            if {"inputs", "scratch", "state", ".runtime", "kernel"} & set(relative.parts):
                continue
            path = attempt / relative
            if path.name in NEVER_COPY or any(p.is_symlink() for p in (path, *path.parents)):
                continue
            if not path.is_file():
                continue
            suffix, size = path.suffix.lower(), path.stat().st_size
            if suffix in TEXT and size <= MAX_TEXT or suffix in IMAGES | {".nc", ".pdf"} and size <= MAX_OUTPUT:
                yield path
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
            spent = usage(attempt, result)
            mapping[blind_id] = {"task_id": task_id, "arm": arm["arm"], "policy": arm.get("policy"),
                                 "library_version": library_version(arm),
                                 "arm_dir": str(arm_dir), "attempt": str(attempt), "status": result.get("status"),
                                 "elapsed_seconds": result.get("elapsed_seconds"),
                                 "tokens": (spent["input_tokens"] + spent["output_tokens"]
                                            if spent["input_tokens"] is not None and spent["output_tokens"] is not None
                                            else None), "usage": spent}
            created += 1
    write_json(mapping_path, mapping)
    return {"created": created, "total": len(mapping), "blind_folder": str(out), "map": str(mapping_path)}


def library_version(arm: dict) -> str | None:
    """The lessons and tools an arm ran with ("lessons" in arm records written before tools existed)."""
    return (arm.get("library") or arm.get("lessons") or {}).get("version")


def state_rows(attempt: Path, sql: str) -> list[tuple]:
    """Rows from the attempt's own state database, read-only; empty when it has none."""
    database = attempt / "state" / "workspace.sqlite3"
    if not database.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
            return connection.execute(sql).fetchall()
    except sqlite3.Error:
        return []


def ledger(attempt: Path) -> list[dict]:
    """Every model call of the attempt, oldest first."""
    return [json.loads(row[0]) for row in state_rows(
        attempt, "SELECT record_json FROM model_call_observations ORDER BY rowid")]


def call_tokens(call: dict, key: str) -> int:
    return int((call.get("usage") or {}).get(key) or 0)


def usage(attempt: Path, result: dict, calls: list[dict] | None = None) -> dict:
    """Tokens and model time of one attempt, from its ledger of model calls.

    The total a run reports when it ends covers the Coordinator's own stream and can be zero,
    and a failed or timed-out attempt reports none. The ledger has every call of every agent.
    result.json is used only when the attempt has no state database.
    """
    if isinstance(result.get("external_usage"), dict):
        return result["external_usage"]
    calls = ledger(attempt) if calls is None else calls
    if not calls:
        reported = result.get("coordinator_usage") or {}
        return {"source": "result.json", "calls": None, "failed_calls": None,
                "input_tokens": int(reported.get("input_tokens") or 0), "cached_input_tokens": None,
                "output_tokens": int(reported.get("output_tokens") or 0), "model_seconds": None, "by_role": {}}
    by_role = {}
    for call in calls:
        role = by_role.setdefault(call.get("role") or "unknown", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        role["calls"] += 1
        role["input_tokens"] += call_tokens(call, "input_tokens")
        role["output_tokens"] += call_tokens(call, "output_tokens")
    return {"source": "ledger", "calls": len(calls),
            "failed_calls": sum(call.get("state") != "completed" for call in calls),
            "input_tokens": sum(call_tokens(call, "input_tokens") for call in calls),
            # Part of the input that the provider served from its cache; it is billed at a lower rate.
            "cached_input_tokens": sum(int(((call.get("usage") or {}).get("input_token_details") or {})
                                           .get("cache_read") or 0) for call in calls),
            "output_tokens": sum(call_tokens(call, "output_tokens") for call in calls),
            "model_seconds": round(sum(float(call.get("duration_seconds") or 0) for call in calls), 1),
            "by_role": by_role}


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
    if rule["type"] == "lower":  # for measures where less is better, such as wasted effort
        return comparison["ci_high"] < rule.get("margin", 0)
    if rule["type"] == "noninferior_and_better_or_cheaper":
        return comparison["ci_low"] >= rule["margin"] and (
            comparison["mean_diff"] > 0 or (comparison["token_reduction"] or 0) >= rule["token_reduction"])
    raise ValueError(f"unknown rule type {rule['type']}")


def frozen_prereg(path: Path) -> dict:
    import yaml
    text = path.read_bytes()
    lock = path.with_name(path.name + ".sha256")
    if not lock.exists() or lock.read_text().strip() != hashlib.sha256(text).hexdigest():
        raise SystemExit("ERROR: the pre-registration is not frozen or changed after freezing")
    return yaml.safe_load(text)


def summarize(args) -> dict:
    prereg = frozen_prereg(args.prereg)
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
    def known_mean(values):
        values = list(values)
        return statistics.fmean(values) if values and all(v is not None for v in values) else None

    def known_sum(values):
        values = list(values)
        return sum(values) if values and all(v is not None for v in values) else None

    cell = {key: {"score": statistics.fmean(r["total"] for r in group),
                  "tokens": known_mean(r["tokens"] for r in group),
                  "elapsed": statistics.fmean(r["elapsed_seconds"] or 0 for r in group),
                  "failures": sum(r["status"] != "completed" for r in group), "n": len(group)}
            for key, group in by.items()}
    arms = sorted({arm for arm, _ in cell})
    per_arm = {arm: {"mean_score": statistics.fmean(v["score"] for (a, _), v in cell.items() if a == arm),
                     "failures": sum(v["failures"] for (a, _), v in cell.items() if a == arm),
                     "tokens": known_sum(v["tokens"] for (a, _), v in cell.items() if a == arm),
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
        tokens_t = known_sum(cell[(treat, t)]["tokens"] for t in tasks)
        tokens_c = known_sum(cell[(control, t)]["tokens"] for t in tasks)
        elapsed_t = sum(cell[(treat, t)]["elapsed"] for t in tasks)
        elapsed_c = sum(cell[(control, t)]["elapsed"] for t in tasks)
        comparison = {"name": spec["name"], "treatment": treat, "control": control, "tasks": len(tasks),
                      "mean_diff": statistics.fmean(diffs), "ci_low": low, "ci_high": high,
                      "wins": sum(d > 0 for d in diffs), "losses": sum(d < 0 for d in diffs),
                      "token_reduction": ((tokens_c - tokens_t) / tokens_c
                                          if tokens_c and tokens_t is not None else None),
                      "time_reduction": (elapsed_c - elapsed_t) / elapsed_c if elapsed_c else None,
                      "by_type": breakdown(diffs, tasks, "type"), "by_data": breakdown(diffs, tasks, "data_access")}
        comparison["decision"] = decide(spec["rule"], comparison)
        comparisons.append(comparison)
    summary = {"experiment": prereg["experiment"], "arms": per_arm, "comparisons": comparisons,
               "cells": {f"{a}|{t}": v for (a, t), v in sorted(cell.items())}}
    out = args.out.expanduser().resolve()
    write_json(out / "summary.json", summary)
    lines = [f"# {prereg['experiment']}", "", "| Arm | Mean score | Failures | Tokens | Hours |", "|---|---|---|---|---|"]
    lines += [f"| {a} | {v['mean_score']:.1f} | {v['failures']} | "
              f"{format(v['tokens'], '.3g') if v['tokens'] is not None else 'n/a'} | {v['elapsed_hours']:.1f} |"
              for a, v in per_arm.items()]
    lines += ["", "| Comparison | Tasks | Mean diff | 95% CI | Wins/losses | Token cut | Time cut | Decision |",
              "|---|---|---|---|---|---|---|---|"]
    for c in comparisons:
        if c.get("decision") is None:
            lines.append(f"| {c['name']} | 0 | | | | | | no paired tasks |")
            continue
        cut, faster = (f"{c[key]:.0%}" if c[key] is not None else "n/a" for key in ("token_reduction", "time_reduction"))
        lines.append(f"| {c['name']} ({c['treatment']} vs {c['control']}) | {c['tasks']} | {c['mean_diff']:+.1f} | "
                     f"[{c['ci_low']:+.1f}, {c['ci_high']:+.1f}] | {c['wins']}/{c['losses']} | {cut} | {faster} | "
                     f"{'meets rule' if c['decision'] else 'does not meet rule'} |")
    for c in comparisons:
        for field in ("by_type", "by_data"):
            if c.get(field):
                parts = ", ".join(f"{k} {v['mean_diff']:+.1f} ({v['tasks']} tasks)" for k, v in c[field].items())
                lines.append(f"\n{c['name']}, mean difference {field.replace('_', ' ')}: {parts}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out / "report.md"), "comparisons": [(c["name"], c.get("decision")) for c in comparisons]}


# ------------------------------------------------------------------------------------------ process
# Measures averaged per arm; a pre-registered process metric must be one of them.
PROCESS_MEASURES = ("nondecisive_token_share", "last_decisive_fraction", "tokens", "wall_minutes",
                    "questions_run", "followups_adopted", "attempts_without_report",
                    "code_failure_share", "helper_calls", "lessons_cited")


def tree_store(attempt: Path) -> Path | None:
    stores = sorted((attempt / "workspace" / "OceanX Tasks").glob("*/agents/coordinator/research_tree.sqlite3"))
    return stores[0] if stores else None


def attempt_measures(attempt: Path) -> dict | None:
    """Process measures of one attempt's research tree; None when it has no finished tree."""
    from oceanx.research.lessons import LessonBook
    from oceanx.research.memory import build_digest, run_measures
    store = tree_store(attempt)
    digest = build_digest(store) if store else None
    if not digest or not digest.get("finished"):
        return None
    measures = run_measures(digest)
    # Whether the skills that hold lessons were opened by the agents they are for.
    holds = {"coordinator": set(), "expert": set()}
    for skill, region in LessonBook.regions().items():
        holds[LessonBook.reader(skill, region)].add(skill)
    opened = measures["coordinator_skills_read"]
    measures["planning_skill_opened"] = None if opened is None else bool(set(opened) & holds["coordinator"])
    by_question = [digest["outcomes"].get(n, {}).get("skills_read") for n, node in digest["outline"].items()
                   if node.get("parent") is not None and node.get("attempts")]
    measures["questions_reading_an_analysis_skill"] = (
        None if any(names is None for names in by_question)
        else sum(bool(set(names) & holds["expert"]) for names in by_question))
    # What the learned library is meant to change: code that fails, helpers that are called,
    # lessons that the agents name. None for a run recorded before these were logged.
    states = [row[0] for row in state_rows(attempt, "SELECT state FROM code_executions")]
    measures["code_failure_share"] = (
        sum(state not in {"succeeded", "running"} for state in states) / len(states) if states else None)
    calls, cited = digest.get("tool_calls"), digest.get("lessons_cited")
    measures["helper_calls"] = None if calls is None else sum(calls.values())
    measures["lessons_cited"] = None if cited is None else len(cited)
    return measures


def mean(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return statistics.fmean(values) if values else None


def process(args) -> dict:
    """Process measures per attempt and arm, their spread between repeats, and the pre-registered
    process comparisons (paired by task, like the score comparisons)."""
    rows = []
    for arm_dir in args.runs:
        arm_dir = arm_dir.expanduser().resolve()
        arm = json.loads((arm_dir / "arm.json").read_text())["arm"]
        for task_id, attempt in latest_attempts(arm_dir):
            rows.append({"arm": arm, "task_id": task_id, "attempt": str(attempt),
                         "measures": attempt_measures(attempt)})
    repeats = {}  # (arm, task, measure) -> the value of every repeat that has one
    for row in rows:
        for name in PROCESS_MEASURES:
            value = (row["measures"] or {}).get(name)
            if value is not None:
                repeats.setdefault((row["arm"], row["task_id"], name), []).append(float(value))
    cell = {key: statistics.fmean(values) for key, values in repeats.items()}
    per_arm = {}
    for arm in sorted({row["arm"] for row in rows}):
        finished = [row["measures"] for row in rows if row["arm"] == arm and row["measures"]]
        questions = sum(m["questions_run"] for m in finished)
        reading = [m["questions_reading_an_analysis_skill"] for m in finished]
        per_arm[arm] = {
            "attempts": sum(row["arm"] == arm for row in rows), "finished_trees": len(finished),
            **{name: mean(v for (a, _, n), v in cell.items() if a == arm and n == name)
               for name in PROCESS_MEASURES},
            # Mean over tasks of the spread between repeats: a difference between arms below this is noise.
            "repeat_noise": {name: mean(max(v) - min(v) for (a, _, n), v in repeats.items()
                                        if a == arm and n == name and len(v) > 1)
                             for name in PROCESS_MEASURES},
            "planning_skill_opened": mean(m["planning_skill_opened"] for m in finished),
            "questions_reading_an_analysis_skill": (
                sum(reading) / questions if questions and None not in reading else None),
            "rule_only_labels": sum(m["label_sources"].get("auto", 0) for m in finished),
        }
    comparisons = []
    prereg = frozen_prereg(args.prereg) if args.prereg else {}
    boot = prereg.get("bootstrap", {})
    for spec in prereg.get("process_comparisons", []):
        metric, treat, control = spec["metric"], spec["treatment"], spec["control"]
        if metric not in PROCESS_MEASURES:
            raise SystemExit(f"ERROR: unknown process metric {metric}")
        tasks = sorted(t for (a, t, n) in cell if a == treat and n == metric and (control, t, metric) in cell)
        diffs = [cell[(treat, t, metric)] - cell[(control, t, metric)] for t in tasks]
        if not diffs:
            comparisons.append({**spec, "tasks": 0, "decision": None})
            continue
        low, high = bootstrap_ci(diffs, int(boot.get("resamples", 10000)), int(boot.get("seed", 7)))
        comparison = {"name": spec["name"], "metric": metric, "treatment": treat, "control": control,
                      "tasks": len(tasks), "mean_diff": statistics.fmean(diffs), "ci_low": low, "ci_high": high,
                      "control_repeat_noise": per_arm[control]["repeat_noise"][metric]}
        comparison["decision"] = decide(spec["rule"], comparison)
        comparisons.append(comparison)
    out = args.out.expanduser().resolve()
    write_json(out / "process.json", {"arms": per_arm, "comparisons": comparisons, "attempts": rows})

    def show(value, percent=False):
        return "n/a" if value is None else f"{value:.0%}" if percent else f"{value:.3g}"

    header = ("| Arm | Finished trees | Tokens in non-decisive questions | Last decisive result, share of run time | "
              "Tokens | Minutes | Questions run | Follow-ups adopted | Attempts without a report | "
              "Coordinator opened its planning skill | Questions whose Expert opened an analysis skill | "
              "Code runs that failed | Helper calls | Lessons named |")
    lines = ["# Process measures", "", header, "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, v in per_arm.items():
        lines.append(f"| {arm} | {v['finished_trees']}/{v['attempts']} | {show(v['nondecisive_token_share'], True)} | "
                     f"{show(v['last_decisive_fraction'], True)} | {show(v['tokens'])} | {show(v['wall_minutes'])} | "
                     f"{show(v['questions_run'])} | {show(v['followups_adopted'])} | "
                     f"{show(v['attempts_without_report'])} | {show(v['planning_skill_opened'], True)} | "
                     f"{show(v['questions_reading_an_analysis_skill'], True)} | "
                     f"{show(v['code_failure_share'], True)} | {show(v['helper_calls'])} | "
                     f"{show(v['lessons_cited'])} |")
    unjudged = {arm: v["rule_only_labels"] for arm, v in per_arm.items() if v["rule_only_labels"]}
    if unjudged:
        lines += ["", f"Questions labelled by the log rules only (run judge-labels first): {unjudged}"]
    if comparisons:
        lines += ["", "| Comparison | Metric | Tasks | Mean diff | 95% CI | Spread between control repeats | Decision |",
                  "|---|---|---|---|---|---|---|"]
    for c in comparisons:
        if c.get("decision") is None:
            lines.append(f"| {c['name']} | {c['metric']} | 0 | | | | no paired tasks |")
            continue
        lines.append(f"| {c['name']} ({c['treatment']} vs {c['control']}) | {c['metric']} | {c['tasks']} | "
                     f"{c['mean_diff']:+.3g} | [{c['ci_low']:+.3g}, {c['ci_high']:+.3g}] | "
                     f"{show(c['control_repeat_noise'])} | {'meets rule' if c['decision'] else 'does not meet rule'} |")
    (out / "process.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out / "process.md"), "arms": {arm: v["finished_trees"] for arm, v in per_arm.items()},
            "comparisons": [(c["name"], c.get("decision")) for c in comparisons]}


# ------------------------------------------------------------------------------------------ inventory
# An empty checkpoint file is a few bytes; one saved conversation is far larger.
MIN_CONVERSATION_BYTES = 1000


def documents(attempt: Path) -> list[dict]:
    """Every Markdown file the run wrote in its task workspace: the final report, the report of each
    answered question, earlier versions of a report, what an agent said and read before its context
    was compacted, and any other notes. The copies of skills and reference pages that each agent is
    given are left out."""
    root = attempt / "workspace" / "OceanX Tasks"
    found = []
    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        parts = path.relative_to(root).parts
        written_by_the_run = {"report-history", "conversation_history"} & set(parts)
        if path.is_symlink() or not path.is_file() or (".runtime" in parts and not written_by_the_run):
            continue
        kind, node = "other", None
        if parts[1:] == ("agents", "coordinator", "report.md"):
            kind = "final report"
        elif "report-history" in parts:
            kind, node = "report version", parts[-2]
        elif "conversation_history" in parts:
            kind = "conversation history"
        elif len(parts) == 6 and parts[1] == "agents" and parts[3] == "reports" and parts[5] == "report.md":
            kind, node = "question report", parts[4]
        found.append({"path": str(path.relative_to(attempt)), "kind": kind, "node": node,
                      "bytes": path.stat().st_size})
    return found


def wall_minutes(calls: list[dict]) -> float:
    """Minutes the calls span, attempt by attempt. Code runs and waiting between calls are included,
    and so is an attempt that returned no report."""
    attempts = {}
    for call in calls:
        if call.get("started_at"):
            attempts.setdefault(call.get("attempt_id"), []).append(call)
    seconds = 0.0
    for group in attempts.values():
        start = min(datetime.fromisoformat(call["started_at"]) for call in group)
        end = max(datetime.fromisoformat(call.get("ended_at") or call["started_at"]) for call in group)
        seconds += (end - start).total_seconds()
    return round(seconds / 60, 1)


def questions(digest: dict, calls: list[dict], files: list[dict]) -> list[dict]:
    """One row per node of the research tree, in the order the nodes were created: who answered it,
    what it cost, and where its report is. The Coordinator's own calls are on the first root."""
    by_node = {}
    for call in calls:
        by_node.setdefault(call.get("node_id"), []).append(call)
    outline = digest["outline"]
    root = next((n for n, node in outline.items() if node.get("parent") is None), None)
    reports = {item["node"]: item["path"] for item in files if item["kind"] == "question report"}
    versions = [item["node"] for item in files if item["kind"] == "report version"]
    rows = []
    for node_id, node in outline.items():
        mine = by_node.get(None if node_id == root else node_id, [])
        runs = node.get("attempts") or []
        rows.append({
            "node": node_id, "parent": node.get("parent"), "kind": node.get("kind"), "status": node.get("status"),
            "expert": "coordinator" if node_id == root else node.get("expert"), "question": node.get("question"),
            "label": (digest.get("labels", {}).get(node_id) or {}).get("label"),
            "attempts": len(runs), "attempts_without_report": sum(run["end"] is None for run in runs),
            "minutes": wall_minutes(mine),
            "model_calls": len(mine),
            "input_tokens": sum(call_tokens(call, "input_tokens") for call in mine),
            "output_tokens": sum(call_tokens(call, "output_tokens") for call in mine),
            "skills_read": sorted({name for call in mine for name in call.get("skills_read") or []}),
            "report": reports.get(node_id), "report_versions": versions.count(node_id),
        })
    return rows


def disk(attempt: Path) -> dict:
    """Current bytes plus scratch bytes already released by validated collection."""
    total = scratch = 0
    for folder, _, names in os.walk(attempt):
        inside = Path(folder).relative_to(attempt).parts
        for name in names:
            path = Path(folder, name)
            try:
                size = 0 if path.is_symlink() else path.stat().st_size
            except OSError:
                continue
            total += size
            # workspace / OceanX Tasks / <task> / agents / <agent> / scratch
            scratch += size if inside[3:4] == ("agents",) and inside[5:6] == ("scratch",) else 0
    released = 0
    cleanup = attempt / "scratch_cleanup.json"
    if cleanup.is_file() and not cleanup.is_symlink():
        try:
            record = json.loads(cleanup.read_text(encoding="utf-8"))
            if record.get("status") in ("cleaned", "partial"):
                released = max(0, int(record.get("bytes_released") or 0))
        except (OSError, ValueError, TypeError):
            pass
    return {"total": total, "scratch": scratch, "scratch_released": released}


def code_failures(code: list[tuple[str, dict]]) -> dict:
    """Classify observed failures, not their causes or whose fault they are.

    A read-only refusal may be correctly protecting another node's files; a time limit
    may reflect slow computation. Kernel-start messages alone do not establish the cause.
    """
    found = {"kernel_start": 0, "time_limit": 0, "read_only": 0, "cancelled": 0, "code": 0}
    for state, body in code:
        if state in ("succeeded", "running"):
            continue
        text = f"{body.get('error') or ''} {body.get('stderr') or ''}"
        if "kernel_info" in text or "Kernel died" in text:
            found["kernel_start"] += 1
        elif state == "timed_out" or body.get("limit_trigger") == "wall_time":
            found["time_limit"] += 1
        elif "Read-only file system" in text:
            found["read_only"] += 1
        elif state == "cancelled":
            found["cancelled"] += 1
        else:
            found["code"] += 1
    return found


def run_record(attempt: Path, arm: dict) -> dict:
    """What one attempt cost and kept, and what a later evaluation would find missing."""
    result = json.loads((attempt / "result.json").read_text())
    if result.get("agent") == "finch-local":
        return external_run_record(attempt, arm, result)
    if result.get("agent") == "claude-code":
        return claude_run_record(attempt, arm, result)
    completed = result.get("status") == "completed"
    calls = ledger(attempt)
    spent = usage(attempt, result, calls)
    code = [(state, json.loads(body or "{}")) for state, body in
            state_rows(attempt, "SELECT state, result_json FROM code_executions")]
    files = documents(attempt)
    store, digest = tree_store(attempt), None
    if store is not None:
        from oceanx.research.memory import build_digest
        digest = build_digest(store)
    outline = (digest or {}).get("outline", {})
    answered = [n for n, node in outline.items() if node.get("parent") is not None and node.get("result")]
    reported = {item["node"] for item in files if item["kind"] == "question report"}
    histories = [item for item in files if item["kind"] == "conversation history"]
    saved = list((attempt / "state" / ".langgraph_api").glob(".langgraph_checkpoint.*.pckl"))
    checkpoints = sum(p.stat().st_size for p in saved)
    # The checkpoints are whole only if they were written after the last model call ended.
    last_call = max((datetime.fromisoformat(call.get("ended_at") or call["started_at"]).timestamp()
                     for call in calls if call.get("started_at")), default=0)
    whole = checkpoints >= MIN_CONVERSATION_BYTES and max(p.stat().st_mtime for p in saved) >= last_call
    answer = attempt / "answer.md"
    missing = []
    if completed and not (answer.is_file() and answer.read_text(encoding="utf-8").strip()):
        missing.append("answer.md")
    if completed and not any(item["kind"] == "final report" for item in files):
        missing.append("final report")
    if spent["source"] != "ledger":
        missing.append("model-call ledger")
    if digest is None:
        missing.append("research tree")
    elif completed and not digest.get("finished"):
        missing.append("tree outcomes")
    missing += [f"report of {node}" for node in answered if node not in reported]
    if checkpoints < MIN_CONVERSATION_BYTES:
        missing.append("agent conversations")
    elif not whole:
        missing.append("end of agent conversations")
    if result.get("events_truncated"):
        missing.append("part of events.jsonl")
    return {
        "task_id": attempt.parent.name, "attempt": attempt.name, "arm": arm.get("arm"),
        "policy": arm.get("policy"), "library_version": library_version(arm),
        "commit": arm.get("commit"), "status": result.get("status"),
        "time": {key: result.get(key) for key in ("elapsed_seconds", "setup_seconds", "analysis_seconds")}
        | {"model_seconds": spent["model_seconds"],
           "code_seconds": round(sum(float(body.get("duration_seconds") or 0) for _, body in code), 1)},
        "tokens": spent,
        "code_runs": {"total": len(code),
                      "by_state": {state: sum(s == state for s, _ in code) for state in sorted({s for s, _ in code})},
                      "failures": code_failures(code)},
        "tree": None if digest is None else {
            "finished": bool(digest.get("finished")), "nodes": len(outline), "questions_answered": len(answered),
            "decisions": sum(digest.get("event_counts", {}).values()), "minutes": digest.get("wall_minutes")},
        "questions": [] if digest is None else questions(digest, calls, files),
        "documents": files,
        # Checkpoints hold every agent's whole conversation in the framework's own format. The history
        # files are readable text, written only for the part of a conversation that was compacted.
        "conversations": {"checkpoint_bytes": checkpoints, "written_after_last_model_call": whole,
                          "history_files": len(histories),
                          "history_bytes": sum(item["bytes"] for item in histories)},
        "disk": disk(attempt),
        "complete": not missing, "missing": missing,
    }


def external_run_record(attempt: Path, arm: dict, result: dict) -> dict:
    """Finch keeps JSONL conversations and a notebook, not an OceanX tree/checkpoint."""
    def records(name):
        found = []
        path = attempt / name
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    found.append(json.loads(line))
                except ValueError:
                    continue
        return found

    executions = {r["execution_id"]: r for r in records("code_runs.jsonl")}
    calls = records("model_calls.jsonl")
    conversations = attempt / "transcript.jsonl"
    missing = []
    if result.get("status") == "completed":
        answer = attempt / "answer.md"
        if not answer.is_file() or not answer.read_text().strip():
            missing.append("answer.md")
        if not (attempt / "workspace/notebook.ipynb").is_file():
            missing.append("notebook.ipynb")
    if not calls:
        missing.append("model-call ledger")
    if not conversations.is_file() or not conversations.stat().st_size:
        missing.append("agent conversations")
    documents_ = [{"path": str(p.relative_to(attempt)), "bytes": p.stat().st_size,
                   "kind": ("final report" if p.name == "answer.md" else
                            "notebook" if p.name in {"notebook.ipynb", "notebook.md"} else "output")}
                  for p in evidence_files(attempt) if p.is_file()]
    spent = usage(attempt, result)
    return {"task_id": attempt.parent.name, "attempt": attempt.name, "arm": arm["arm"],
        "policy": None, "library_version": None, "commit": arm.get("finch_commit"),
        "status": result["status"], "time": {"elapsed_seconds": result["elapsed_seconds"],
            "setup_seconds": None, "analysis_seconds": None, "model_seconds": spent["model_seconds"],
            "code_seconds": sum(r.get("duration_seconds", 0) for r in executions.values())},
        "tokens": spent, "code_runs": {"total": len(executions), "by_state": {
            s: sum(r["state"] == s for r in executions.values())
            for s in sorted({r["state"] for r in executions.values()})}},
        "tree": None, "questions": [], "not_applicable": ["research tree", "OceanX checkpoints"],
        "documents": documents_, "conversations": {"checkpoint_bytes": 0,
            "written_after_last_model_call": None, "history_files": int(conversations.is_file()),
            "history_bytes": conversations.stat().st_size if conversations.is_file() else 0},
        "disk": disk(attempt), "complete": not missing, "missing": missing,
        "limitations": "Conversation log completeness is not proven by presence. Killed/in-flight "
            "requests and router-internal retries may have unavailable usage."}


def claude_run_record(attempt: Path, arm: dict, result: dict) -> dict:
    """CLI evidence and whole-call usage, without inventing a tree or per-call/code ledger."""
    missing = []
    answer, events = attempt / 'answer.md', attempt / 'events.jsonl'
    if result.get('status') == 'completed' and (not answer.is_file() or not answer.read_text().strip()):
        missing.append('answer.md')
    if not events.is_file() or not events.stat().st_size:
        missing.append('CLI conversation events')
    spent = usage(attempt, result)
    if spent['input_tokens'] is None or spent['output_tokens'] is None:
        missing.append('whole-call token totals')
    if not (attempt / 'evidence_manifest.json').is_file():
        missing.append('evidence manifest')
    documents_ = [{'path': str(p.relative_to(attempt)), 'bytes': p.stat().st_size,
                   'kind': 'final report' if p.name == 'answer.md' else 'output'}
                  for p in evidence_files(attempt) if p.is_file()]
    return {'task_id': attempt.parent.name, 'attempt': attempt.name, 'arm': arm['arm'],
        'policy': None, 'library_version': None, 'commit': arm.get('commit'),
        'status': result['status'], 'time': {'elapsed_seconds': result.get('elapsed_seconds'),
            'setup_seconds': None, 'analysis_seconds': None, 'model_seconds': None, 'code_seconds': None},
        'tokens': spent, 'code_runs': {'total': None, 'by_state': {}}, 'tree': None, 'questions': [],
        'documents': documents_, 'conversations': {'checkpoint_bytes': 0,
            'written_after_last_model_call': None, 'history_files': int(events.is_file()),
            'history_bytes': events.stat().st_size if events.is_file() else 0},
        'disk': disk(attempt), 'complete': not missing, 'missing': missing,
        'not_applicable': ['research tree', 'OceanX checkpoints'],
        'limitations': 'CLI-reported whole-call tokens; model-call counts, failed-call counts and code '
            'execution times are unavailable, not zero. Event presence does not prove a complete transcript.'}


def millions(value) -> str:
    return "n/a" if value is None else f"{value / 1e6:.1f}M"


def gigabytes(value) -> str:
    return f"{value / 1e9:.1f} GB"


def record_page(record: dict) -> str:
    """The run record as a page: totals, then the research tree with what each question cost."""
    time, tokens, runs, size = record["time"], record["tokens"], record["code_runs"], record["disk"]
    kinds = [item["kind"] for item in record["documents"]]
    failed_runs = runs['total'] - runs['by_state'].get('succeeded', 0) if runs['total'] is not None else 'n/a'

    def minutes(seconds):
        return "n/a" if seconds is None else f"{seconds / 60:.0f} min"

    spent_time = (f"- Time: {minutes(time['elapsed_seconds'])} in total, {minutes(time['model_seconds'])} of model "
                  f"calls, {minutes(time['code_seconds'])} of code runs (agents work in parallel, so the parts can "
                  "exceed the total)")
    spent_tokens = (f"- Tokens: {millions(tokens['input_tokens'])} input ({millions(tokens['cached_input_tokens'])} "
                    f"from cache), {millions(tokens['output_tokens'])} output, {tokens['calls']} model calls "
                    f"({tokens['failed_calls']} failed)")
    released = size.get("scratch_released", 0)
    kept = (f"- Kept: {kinds.count('final report')} final report, {kinds.count('question report')} question "
            f"reports, {kinds.count('report version')} report versions, {kinds.count('conversation history')} "
            f"conversation histories, {gigabytes(size['total'])} on disk ({gigabytes(size['scratch'])} in scratch "
            "folders" + (f", {gigabytes(released)} scratch released after collection" if released else "") + ")")
    header = ("| Node | Question | Answered by | Status | Label | Attempts (without a report) | Minutes | "
              "Input tokens | Output tokens | Skills opened | Report |")
    causes = runs.get("failures") or {}
    why = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in causes.items() if count)
    lines = [f"# {record['task_id']}, arm {record['arm']}, {record['attempt']}: {record['status']}", "",
             spent_time, spent_tokens,
             f"- Code runs: {runs['total'] if runs['total'] is not None else 'n/a'} ({failed_runs} did not succeed"
             + (f": {why}" if why else "") + ")",
             kept, f"- Missing: {'; '.join(record['missing']) or 'nothing'}", "",
             header, "|---|---|---|---|---|---|---|---|---|---|---|"]
    for q in record["questions"]:
        question = (q["question"] or "").replace("|", "/")
        report = f"[report](<{q['report']}>)" if q["report"] else ""
        if q["report_versions"] > 1:
            report += f" ({q['report_versions']} versions)"
        lines.append(
            f"| {q['node']} | {question} | {q['expert'] or ''} | {q['status']} | {q['label'] or ''} | "
            f"{q['attempts']} ({q['attempts_without_report']}) | {q['minutes']:.0f} | {millions(q['input_tokens'])} | "
            f"{millions(q['output_tokens'])} | {', '.join(q['skills_read'])} | {report} |")
    return "\n".join(lines) + "\n"


def inventory(args) -> dict:
    """Write run_record.json and run_record.md into every attempt and report the incomplete ones."""
    records = []
    for arm_dir in args.runs:
        arm_dir = arm_dir.expanduser().resolve()
        arm = json.loads((arm_dir / "arm.json").read_text())
        for result in sorted(arm_dir.glob("*/attempt-*/result.json")):
            record = run_record(result.parent, arm)
            write_json(result.parent / "run_record.json", record)
            (result.parent / "run_record.md").write_text(record_page(record), encoding="utf-8")
            records.append({**record, "path": str(result.parent)})
    out = args.out.expanduser().resolve()
    write_json(out / "inventory.json", records)
    lines = ["# What each attempt cost and kept", "",
             "| Arm | Task | Status | Minutes | Input tokens (from cache) | Output tokens | Model calls (failed) | "
             + "Code runs (failed) | Questions answered | Markdown files | On disk | Missing |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        tokens, runs, tree = r["tokens"], r["code_runs"], r["tree"] or {}
        failed_runs = runs["total"] - runs["by_state"].get("succeeded", 0) if runs['total'] is not None else 'n/a'
        lines.append(
            f"| {r['arm']} | {r['task_id']} | {r['status']} | {(r['time']['elapsed_seconds'] or 0) / 60:.0f} | "
            f"{millions(tokens['input_tokens'])} ({millions(tokens['cached_input_tokens'])}) | "
            f"{millions(tokens['output_tokens'])} | {tokens['calls']} ({tokens['failed_calls']}) | "
            f"{runs['total']} ({failed_runs}) | {tree.get('questions_answered', 'n/a')} | {len(r['documents'])} | "
            f"{gigabytes(r['disk']['total'])} | {'; '.join(r['missing']) or 'nothing'} |")
    (out / "inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    incomplete = {r["path"]: r["missing"] for r in records if r["missing"]}
    return {"attempts": len(records), "complete": len(records) - len(incomplete), "incomplete": incomplete,
            "disk_gb": round(sum(r["disk"]["total"] for r in records) / 1e9, 1),
            "scratch_gb": round(sum(r["disk"]["scratch"] for r in records) / 1e9, 1),
            "scratch_released_gb": round(sum(
                r["disk"].get("scratch_released", 0) for r in records) / 1e9, 1),
            "report": str(out / "inventory.md")}


def library_check(args) -> dict:
    """Every attempt that ran with a frozen library must report its lessons and tools unchanged."""
    runs = args.runs.expanduser()
    records = sorted([*runs.rglob("arm_library.json"), *runs.rglob("arm_lessons.json")])
    problems = [str(record) for record in records if not json.loads(record.read_text()).get("unchanged")]
    return {"checked": len(records), "changed_or_unfinished": problems}


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
    p = sub.add_parser("process")
    p.add_argument("--runs", type=Path, nargs="+", required=True, help="Arm output folders (with arm.json)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--prereg", type=Path, help="Frozen pre-registration with process_comparisons")
    i = sub.add_parser("inventory")
    i.add_argument("--runs", type=Path, nargs="+", required=True, help="Arm output folders (with arm.json)")
    i.add_argument("--out", type=Path, required=True)
    lc = sub.add_parser("library-check", aliases=["lessons-check"])
    lc.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args(argv)
    handler = {"blind": blind, "validate": validate, "freeze": freeze, "summarize": summarize,
               "process": process, "inventory": inventory, "library-check": library_check,
               "lessons-check": library_check}[args.command]
    print(json.dumps(handler(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
