#!/usr/bin/env python3
"""Benchmark evaluation: blind the run outputs, validate Codex score files, compare arms.

    blind      copy each attempt's answer, reports, figures, small outputs and code into a folder named
               by a random ID, so the judge cannot see the arm; the ID-to-arm map is written separately
    validate   check score files against the task rubrics (criteria, levels 0 to 4), and the files of
               the two criteria of paper verification that are judged beside the rubric
    rubric-check  check frozen rubrics before judging: every reference value and tolerance filled, nothing
               else changed from the repository's draft, the hash of the reference outputs still right
    freeze     hash-lock a pre-registration file before any test run
    summarize  join scores with the map, apply the pre-registered comparisons, write report.md
    indicators the six indicators per task type and arm, whose mean is the score (ASPECT_SCORES.md):
               a table and a chart
    process    measure how each attempt's research tree went (needs OceanX importable), compare arms
               on the pre-registered process metric, write process.md
    inventory  write run_record.json and run_record.md into every attempt (time, tokens, code runs, what
               each question of the tree cost, every .md file, disk use) and check that nothing needed
               for a later evaluation is missing

Nothing here runs an agent, a model or the agents' code.
"""
from __future__ import annotations

import argparse
import copy
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
# An executed notebook is mostly embedded images. A larger one is copied without them, long outputs cut.
MAX_NOTEBOOK, LONG_OUTPUT = 300 * 1024**2, 20_000
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


def fits(path: Path, kinds: set, limit: int, left_out: list | None) -> bool:
    """Whether a file of one of these kinds is small enough to copy; a larger one is noted as left out."""
    suffix, size = path.suffix.lower(), path.stat().st_size
    if suffix not in kinds:
        return False
    if size <= (MAX_NOTEBOOK if suffix == ".ipynb" else limit):
        return True
    if left_out is not None:
        left_out.append(path)
    return False


def evidence_files(attempt: Path, left_out: list | None = None):
    """Answer, Agent reports, published outputs and small code/tables; never state, logs or the tree.

    An attempt without a final answer delivered whatever it kept. For OceanX and Finch that is already
    below (the Experts' reports, the notebook, the outputs); for Claude Code it is also the messages the
    agent wrote on the way. A file of a kind that is copied but too large for it is added to `left_out`.
    """
    answer = attempt / "answer.md"
    yield answer
    if not (answer.is_file() and answer.read_text(encoding="utf-8", errors="replace").strip()):
        yield attempt / "partial_answer.md"
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
            if fits(path, TEXT, MAX_TEXT, left_out) or fits(path, IMAGES | {".nc", ".pdf"}, MAX_OUTPUT, left_out):
                yield path
    tasks_root = attempt / "workspace" / "OceanX Tasks"
    for path in sorted(tasks_root.rglob("*")) if tasks_root.is_dir() else []:
        if not path.is_file() or path.is_symlink() or path.name in NEVER_COPY:
            continue
        parts = set(path.relative_to(tasks_root).parts)
        if ".runtime" in parts or "kernel" in parts:
            continue
        if ("outputs" in parts and fits(path, IMAGES | {".nc"}, MAX_OUTPUT, left_out)
                or fits(path, TEXT, MAX_TEXT, left_out)):
            yield path


def slim_notebook(path: Path) -> str | None:
    """An executed notebook without its images and other binary outputs, and with long text outputs cut.
    The figures themselves are among the published outputs. None when the file cannot be read as one."""
    def cut(text):
        text = "".join(text) if isinstance(text, list) else text
        if isinstance(text, str) and len(text) > LONG_OUTPUT:
            return text[:LONG_OUTPUT] + "\n[the rest of this output is cut in the copy for the judge]\n"
        return text

    try:
        notebook = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        for cell in notebook["cells"]:
            for output in cell.get("outputs") or []:
                data = output.get("data")
                if isinstance(data, dict):
                    removed = [kind for kind in data if not kind.startswith("text/")]
                    if "text/html" in data and "text/plain" in data:
                        removed.append("text/html")  # the same table twice
                    for kind in removed:
                        del data[kind]
                    for kind in data:
                        data[kind] = cut(data[kind])
                    if removed:
                        data["text/plain"] = (f"[{', '.join(removed)} removed in the copy for the judge]\n"
                                              + (cut(data.get("text/plain")) or ""))
                for key in ("text", "traceback"):
                    if key in output:
                        output[key] = cut(output[key])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return json.dumps(notebook, ensure_ascii=False, indent=1)


def blind(args) -> dict:
    out = args.out.expanduser().resolve()
    mapping_path = args.map.expanduser().resolve()
    if mapping_path.is_relative_to(out):
        raise SystemExit("ERROR: keep the blind map outside the folder the judge reads")
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    seen = {entry["attempt"] for entry in mapping.values()}
    created = slimmed = incomplete = 0
    for arm_dir in args.runs:
        arm_dir = arm_dir.expanduser().resolve()
        arm = json.loads((arm_dir / "arm.json").read_text())
        for task_id, attempt in latest_attempts(arm_dir):
            if str(attempt) in seen:
                continue
            blind_id = "b" + secrets.token_hex(6)
            target = out / blind_id
            target.mkdir(parents=True)
            total, left_out = 0, []
            for source in evidence_files(attempt, left_out):
                if not source.is_file():
                    continue
                size, text = source.stat().st_size, None
                if source.suffix.lower() == ".ipynb" and size > MAX_TEXT:
                    text = slim_notebook(source)
                    if text is None or len(text.encode("utf-8")) > MAX_OUTPUT:
                        left_out.append(source)
                        continue
                    size, slimmed = len(text.encode("utf-8")), slimmed + 1
                if total + size > MAX_TOTAL:
                    left_out.append(source)
                    continue
                total += size
                destination = target / "evidence" / source.relative_to(attempt)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix.lower() in TEXT:
                    # Absolute run paths contain the arm folder name; replace them.
                    text = source.read_text(encoding="utf-8", errors="replace") if text is None else text
                    destination.write_text(text.replace(str(arm_dir), "<RUN>"), encoding="utf-8")
                else:
                    shutil.copyfile(source, destination)
            if left_out:
                # The judge must be able to tell a file that was too large to copy from one that is missing.
                incomplete += 1
                write_json(target / "left_out.json", {
                    "note": "Files of the attempt that exist but were too large to copy. What they hold cannot "
                            "be credited, and they are not missing.",
                    "files": [{"path": str(path.relative_to(attempt)), "bytes": path.stat().st_size}
                              for path in left_out]})
            result = json.loads((attempt / "result.json").read_text())
            query = json.loads((attempt / "query.json").read_text())["query"]
            write_json(target / "task.json", {"blind_id": blind_id, "task_id": task_id, "query": query,
                                              "status": result.get("status")})
            # What an attempt cost (time, tokens) is not part of the results; `inventory` records it per attempt.
            mapping[blind_id] = {"task_id": task_id, "arm": arm["arm"], "policy": arm.get("policy"),
                                 "library_version": library_version(arm),
                                 "arm_dir": str(arm_dir), "attempt": str(attempt), "status": result.get("status")}
            created += 1
    write_json(mapping_path, mapping)
    return {"created": created, "total": len(mapping), "blind_folder": str(out), "map": str(mapping_path),
            "notebooks_copied_without_images": slimmed, "folders_with_files_left_out": incomplete}


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
# Criteria of paper verification that no rubric holds: the judge scores them beside the rubric, in a file
# of their own (CODEX_JUDGE.md, "Added criteria of paper verification"). Letter and indicator.
ADDED_CRITERIA = {"S": "Robustness", "A": "Rigor"}


def level_errors(given: dict) -> list[str]:
    errors = []
    for cid, item in given.items():
        level = item.get("score")
        if isinstance(level, bool) or not isinstance(level, (int, float)) or level not in [n / 2 for n in range(9)]:
            errors.append(f"{cid}: score must be a level from 0 to 4 in steps of 0.5")
        if not str(item.get("evidence", "")).strip():
            errors.append(f"{cid}: evidence is required")
    return errors


def validate_score(score: dict) -> list[str]:
    """Problems of one score file. The score itself is not in it: evaluate.py computes it from the
    levels (ASPECT_SCORES.md), so a `total` that an older file carries is not read."""
    errors = []
    try:
        ref = rubric(score["task_id"])
    except (KeyError, FileNotFoundError):
        return ["unknown task_id"]
    wanted = {c["id"] for c in ref["criteria"]}
    given = {c.get("id"): c for c in score.get("criteria", [])}
    if set(given) != wanted:
        errors.append(f"criteria ids {sorted(given)} != rubric {sorted(wanted)}")
    errors += level_errors(given)
    # Every score file, also that of an attempt without a final answer, judged on what it kept.
    if score.get("rubric_status") != "frozen":
        errors.append("rubric was not frozen when judged (references and tolerances must be frozen first)")
    for key in ("blind_id", "judge"):
        if not score.get(key):
            errors.append(f"missing {key}")
    if not isinstance(score.get("delivered"), bool):
        errors.append("delivered must be true or false")
    return errors


def validate_added(added: dict, score: dict | None) -> list[str]:
    """Problems of one file of added criteria, against the score file of the same attempt."""
    if score is None:
        return ["no valid score file with this blind_id"]
    try:
        kind = rubric(score["task_id"])["type"]
    except (KeyError, FileNotFoundError):
        return ["unknown task_id"]
    if kind != "paper_reproduction":
        return ["only paper verification has added criteria"]
    errors = []
    if added.get("task_id") != score["task_id"]:
        errors.append(f"task_id {added.get('task_id')} != {score['task_id']} of the score file")
    wanted = {f"{score['task_id']}-{letter}" for letter in ADDED_CRITERIA}
    given = {c.get("id"): c for c in added.get("criteria", [])}
    if set(given) != wanted:
        errors.append(f"criteria ids {sorted(map(str, given))} != {sorted(wanted)}")
    errors += level_errors(given)
    if not added.get("judge"):
        errors.append("missing judge")
    return errors


def validate(args) -> dict:
    report, scores = {}, {}
    for path in sorted(args.scores.glob("*.json")):
        score = json.loads(path.read_text())
        report[path.name] = validate_score(score)
        if not report[path.name]:
            scores[score["blind_id"]] = score
    result = {"files": len(report), "invalid": {k: v for k, v in report.items() if v}}
    if args.added:
        checked = {}
        for path in sorted(args.added.glob("*.json")):
            added = json.loads(path.read_text())
            checked[path.name] = (added.get("blind_id"), validate_added(added, scores.get(added.get("blind_id"))))
        paper = {blind_id for blind_id, score in scores.items()
                 if rubric(score["task_id"])["type"] == "paper_reproduction"}
        result["added"] = {"files": len(checked),
                           "invalid": {name: errors for name, (_, errors) in checked.items() if errors},
                           "paper_attempts_without": sorted(paper - {blind_id for blind_id, _ in checked.values()})}
    return result


def read_scores(folder: Path) -> dict:
    """The score files of a folder by blind ID; every one must be valid."""
    scores = {}
    for path in sorted(folder.glob("*.json")):
        score = json.loads(path.read_text())
        if validate_score(score):
            raise SystemExit(f"ERROR: invalid score file {path.name}; run validate first")
        scores[score["blind_id"]] = score
    return scores


def read_added(folder: Path | None, scores: dict) -> dict:
    """The files of added criteria of a folder by blind ID; every one must be valid."""
    added = {}
    for path in sorted(folder.glob("*.json")) if folder else ():
        doc = json.loads(path.read_text())
        if validate_added(doc, scores.get(doc.get("blind_id"))):
            raise SystemExit(f"ERROR: invalid file of added criteria {path.name}; run validate first")
        added[doc["blind_id"]] = doc
    return added


# ------------------------------------------------------------------------------------------ frozen rubrics
PLACEHOLDER = "to freeze before judging"
CAUSE_VERDICTS = ("supported", "partly supported", "not supported")


def outputs_sha256(folder: Path) -> str | None:
    """One hash of a task's reference outputs: every file's path and content, in path order."""
    files = sorted(path for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else []
    if not files:
        return None
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _items(doc: dict, group: str) -> list:
    return doc.get("answer_key", {}).get("items", []) if group == "answer_key" else doc.get(group, [])


def places_to_freeze(draft: dict):
    """Where a draft rubric waits for a reference: the expected value and the tolerance of each finding
    and answer-key item, and the expected verdict of each candidate cause."""
    for group in ("criteria", "answer_key", "candidate_causes"):
        for index, item in enumerate(_items(draft, group)):
            for key in ("expected", "tolerance"):
                if PLACEHOLDER in str(item.get(key, "")):
                    yield group, index, key


def rubric_problems(path: Path, references: Path) -> tuple[list[str], str | None]:
    """What keeps one frozen rubric from being judged with, and the hash of its reference outputs."""
    task = path.stem
    try:
        frozen, draft = json.loads(path.read_text(encoding="utf-8")), rubric(task)
    except ValueError:
        return ["not valid JSON"], None
    except FileNotFoundError:
        return [f"no task {task} in the repository"], None
    if not isinstance(frozen, dict):
        return ["not a rubric"], None
    problems = []
    plain_draft, plain_frozen = copy.deepcopy(draft), copy.deepcopy(frozen)
    for group, index, key in places_to_freeze(draft):
        source = _items(plain_draft, group)[index]
        name = f"{source.get('id')} {key}"
        try:
            item = _items(plain_frozen, group)[index]
            value = item[key]
        except (IndexError, KeyError, TypeError, AttributeError):
            problems.append(f"{name}: missing")
            continue
        if not isinstance(value, str) or not value.strip() or PLACEHOLDER in value:
            problems.append(f"{name}: not filled")
        elif group == "candidate_causes" and value not in CAUSE_VERDICTS:
            problems.append(f"{name}: must be one of {', '.join(CAUSE_VERDICTS)}")
        elif (group, key) == ("criteria", "expected") and not value.startswith(tuple(draft["verdict_labels"])):
            problems.append(f"{name}: must begin with a verdict ({'; '.join(draft['verdict_labels'])})")
        item[key] = source[key] = None
    # Everything else is the repository's, untouched: criteria, weights, anchors, probes, gates.
    for doc in (plain_draft, plain_frozen):
        doc["status"] = doc["frozen"] = None
    changed = sorted(key for key in set(plain_draft) | set(plain_frozen) if plain_frozen.get(key) != plain_draft.get(key))
    if changed:
        problems.append("differs from the repository's rubric outside the places to freeze: " + ", ".join(changed))
    if draft["query_sha256"] != hashlib.sha256(task_info(task)["query"].encode()).hexdigest():
        problems.append("the question's text changed after the rubric was written")
    if frozen.get("status") != "frozen":
        problems.append('status is not "frozen"')
    stamp = frozen.get("frozen") if isinstance(frozen.get("frozen"), dict) else {}
    if not all(stamp.get(key) for key in ("references_sha256", "tolerances_frozen_at", "frozen_by")):
        problems.append("frozen.references_sha256, tolerances_frozen_at and frozen_by must be set")
    work = references / task
    for name in ("spec.md", "compute.py"):
        if not (work / name).is_file():
            problems.append(f"references/{task}/{name} is missing")
    digest = outputs_sha256(work / "outputs")
    if digest is None:
        problems.append(f"references/{task}/outputs has no files")
    elif stamp.get("references_sha256") != digest:
        problems.append(f"references_sha256 is not the hash of references/{task}/outputs (now {digest})")
    return problems, digest


def rubric_check(args) -> dict:
    """Frozen rubrics that are ready to judge with, and what is wrong with the others."""
    folder = args.rubrics.expanduser()
    found = {path.stem: path for path in sorted(folder.glob("*.json"))}
    tasks = args.tasks or sorted(found)
    report = {"ready": [], "not_ready": {}, "references_sha256": {}}
    for task in tasks:
        if task not in found:
            report["not_ready"][task] = ["no frozen rubric file"]
            continue
        problems, digest = rubric_problems(found[task], args.references.expanduser())
        report["references_sha256"][task] = digest
        if problems:
            report["not_ready"][task] = problems
        else:
            report["ready"].append(task)
    return report


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
    scores = read_scores(args.scores)
    added = read_added(args.added, scores)
    failed_score = float(prereg.get("failed_attempt_score", 0))
    rows = []
    for blind_id, entry in mapping.items():
        score = scores.get(blind_id)
        if score is None and entry["status"] == "completed":
            raise SystemExit(f"ERROR: completed attempt {blind_id} has no score")
        ref = rubric(entry["task_id"])
        # A judged attempt scores the mean of its six indicators (ASPECT_SCORES.md). An attempt without
        # a final answer has a score file when it kept executed work to judge (CODEX_JUDGE.md, "Attempts
        # that end without a final answer"); otherwise it scores as failed.
        total = whole_mean(indicator_scores(ref, score, added.get(blind_id)).values()) if score else failed_score
        if total is None:
            raise SystemExit(f"ERROR: attempt {blind_id} ({entry['task_id']}) has an indicator that is not judged "
                             "yet; `evaluate.py indicators` names it")
        rows.append({**entry, "blind_id": blind_id, "total": total, "scored": score is not None,
                     "type": ref["type"]})
    by = {}
    for row in rows:
        by.setdefault((row["arm"], row["task_id"]), []).append(row)
    cell = {key: {"score": statistics.fmean(r["total"] for r in group),
                  "failures": sum(r["status"] != "completed" for r in group),
                  "failures_scored": sum(r["status"] != "completed" and r["scored"] for r in group),
                  "n": len(group)}
            for key, group in by.items()}
    arms = sorted({arm for arm, _ in cell})
    per_arm = {arm: {"mean_score": statistics.fmean(v["score"] for (a, _), v in cell.items() if a == arm),
                     "failures": sum(v["failures"] for (a, _), v in cell.items() if a == arm),
                     "failures_scored": sum(v["failures_scored"] for (a, _), v in cell.items() if a == arm)}
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
        comparison = {"name": spec["name"], "treatment": treat, "control": control, "tasks": len(tasks),
                      "mean_diff": statistics.fmean(diffs), "ci_low": low, "ci_high": high,
                      "wins": sum(d > 0 for d in diffs), "losses": sum(d < 0 for d in diffs),
                      "by_type": breakdown(diffs, tasks, "type"), "by_data": breakdown(diffs, tasks, "data_access")}
        comparison["decision"] = decide(spec["rule"], comparison)
        comparisons.append(comparison)
    summary = {"experiment": prereg["experiment"], "arms": per_arm, "comparisons": comparisons,
               "cells": {f"{a}|{t}": v for (a, t), v in sorted(cell.items())}}
    out = args.out.expanduser().resolve()
    write_json(out / "summary.json", summary)
    lines = [f"# {prereg['experiment']}", "",
             "| Arm | Mean score | Attempts not completed (judged on what they kept) |",
             "|---|---|---|"]
    lines += [f"| {a} | {v['mean_score']:.1f} | {v['failures']} ({v['failures_scored']}) |"
              for a, v in per_arm.items()]
    lines += ["", "| Comparison | Tasks | Mean diff | 95% CI | Wins/losses | Decision |",
              "|---|---|---|---|---|---|"]
    for c in comparisons:
        if c.get("decision") is None:
            lines.append(f"| {c['name']} | 0 | | | | no paired tasks |")
            continue
        lines.append(f"| {c['name']} ({c['treatment']} vs {c['control']}) | {c['tasks']} | {c['mean_diff']:+.1f} | "
                     f"[{c['ci_low']:+.1f}, {c['ci_high']:+.1f}] | {c['wins']}/{c['losses']} | "
                     f"{'meets rule' if c['decision'] else 'does not meet rule'} |")
    for c in comparisons:
        for field in ("by_type", "by_data"):
            if c.get(field):
                parts = ", ".join(f"{k} {v['mean_diff']:+.1f} ({v['tasks']} tasks)" for k, v in c[field].items())
                lines.append(f"\n{c['name']}, mean difference {field.replace('_', ' ')}: {parts}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out / "report.md"), "comparisons": [(c["name"], c.get("decision")) for c in comparisons]}


# ------------------------------------------------------------------------------------------ indicators
# The six indicators of each task type in the order of the chart's axes (ASPECT_SCORES.md): English and
# Chinese name, then the question the indicator answers, in both languages.
INDICATORS = {
    "open_problem": (
        ("Framing", "问题拆解", "Is the question turned into testable hypotheses?", "问题拆成可检验的假设了吗"),
        ("Correctness", "正确性", "Do the key results agree with the reference?", "关键结果与参考答案一致吗"),
        ("Depth", "深度", "Is the mechanism tested in the data?", "机制用数据检验了吗"),
        ("Breadth", "广度", "Are related processes and published work connected?", "联系了相关过程和已有研究吗"),
        ("Robustness", "稳健性", "Does the conclusion hold under other choices?", "换一种设定结论还成立吗"),
        ("Rigor", "严谨性", "Are the data handled right and the limits stated?", "数据用得对、边界说得清吗"),
    ),
    "paper_reproduction": (
        ("Finding tests", "命题检验", "Is each finding tested properly?", "每个命题都认真检验了吗"),
        ("Right verdicts", "判定正确", "Do the verdicts agree with the reference?", "判定与参考答案一致吗"),
        ("Method fidelity", "方法忠实", "Are the paper's definitions and methods followed?", "按论文的定义和方法做了吗"),
        ("Differences explained", "差异归因", "Are the differences from the paper explained?", "与论文的差别解释了吗"),
        ("Robustness", "稳健性", "Do the verdicts hold under other choices?", "换一种设定判定还成立吗"),
        ("Rigor", "严谨性", "Are the data handled right and fit for the findings?", "数据用得对、适合检验吗"),
    ),
}
TYPE_NAMES = {"open_problem": ("Open problems", "开放题"),
              "paper_reproduction": ("Paper verification", "论文验证题")}


def whole_mean(values) -> float | None:
    """The mean of the values; None while one of them is missing."""
    values = list(values)
    return None if None in values else statistics.fmean(values)


def indicator_scores(ref: dict, score: dict | None, added: dict | None = None) -> dict:
    """The six indicators of one attempt, each 0-100: the judge's level of the criteria the indicator
    names, as a share of the top level. The six count the same, and the attempt's score is their mean.

    None where the judge has not recorded what the indicator needs. An attempt without a score file
    (nothing was executed) counts 0 in each.
    """
    names = [indicator[0] for indicator in INDICATORS[ref["type"]]]
    if score is None:
        return dict.fromkeys(names, 0.0)
    level = {c["id"].rsplit("-", 1)[-1]: c["score"] for c in score["criteria"]}
    if ref["type"] == "open_problem":
        levels = (level["F"], level["Q"], level["M"], level["B"], level["R"], (level["A"] + level["I"]) / 2)
        return {name: 25.0 * value for name, value in zip(names, levels)}
    # Paper verification: the findings by their weights in the rubric, the share of verdicts that agree
    # with the reference, method, differences, and the two criteria judged beside the rubric.
    weight = {c["id"].rsplit("-", 1)[-1]: c["weight"] for c in ref["criteria"] if c.get("kind") == "claim"}
    agrees = {str(entry.get("id")).rsplit("-", 1)[-1]: entry.get("matches_reference")
              for entry in score.get("findings") or []}
    verdicts = [agrees.get(finding) for finding in weight]
    beside = {c["id"].rsplit("-", 1)[-1]: c["score"] for c in (added or {}).get("criteria", [])}
    values = {"Finding tests": 25.0 * sum(weight[k] * level[k] for k in weight) / sum(weight.values()),
              "Right verdicts": (100.0 * sum(verdicts) / len(verdicts)
                                 if all(isinstance(verdict, bool) for verdict in verdicts) else None),
              "Method fidelity": 25.0 * level["M"], "Differences explained": 25.0 * level["D"],
              **{indicator: 25.0 * beside[letter] if letter in beside else None
                 for letter, indicator in ADDED_CRITERIA.items()}}
    return {name: values[name] for name in names}


def indicators(args) -> dict:
    mapping = json.loads(args.map.read_text())
    scores = read_scores(args.scores)
    added = read_added(args.added, scores)
    arms = args.arms or sorted({entry["arm"] for entry in mapping.values()})
    unknown = set(arms) - {entry["arm"] for entry in mapping.values()}
    if unknown:
        raise SystemExit(f"ERROR: no attempt of arm {sorted(unknown)} in the map")
    attempts, not_judged, unscored, status_differs = [], {}, [], []
    for blind_id, entry in mapping.items():
        if entry["arm"] not in arms:
            continue
        score = scores.get(blind_id)
        if score is None and entry["status"] == "completed":
            raise SystemExit(f"ERROR: completed attempt {blind_id} has no score")
        ref = rubric(entry["task_id"])
        values = indicator_scores(ref, score, added.get(blind_id))
        waiting = [name for name, value in values.items() if value is None]
        if waiting:
            not_judged[blind_id] = waiting
        if score is None:
            unscored.append(blind_id)
        elif score["delivered"] and entry["status"] != "completed":
            status_differs.append(blind_id)  # delivered although the runner did not record a completed run
        attempts.append({"blind_id": blind_id, "arm": entry["arm"], "task_id": entry["task_id"],
                         "type": ref["type"], "status": entry["status"], "scored": score is not None,
                         "delivered": bool(score and score["delivered"]),
                         "indicators": values, "score": whole_mean(values.values())})
    summary, beside = {}, {}
    for kind, listed in INDICATORS.items():
        for arm in arms:
            rows = [a for a in attempts if a["type"] == kind and a["arm"] == arm]
            if not rows:
                continue
            by_task = {}
            for row in rows:
                by_task.setdefault(row["task_id"], []).append(row)
            # Repeats of a question are averaged first, then the questions of the type. The six means
            # then make up the arm's mean score as the six indicators make up an attempt's score.
            means = {name: whole_mean(whole_mean(row["indicators"][name] for row in group)
                                      for group in by_task.values()) for name, *_ in listed}
            summary.setdefault(kind, {})[arm] = {"indicators": means, "score": whole_mean(means.values())}
            beside.setdefault(kind, {})[arm] = {
                "questions": len(by_task), "attempts": len(rows),
                "not_completed": sum(row["status"] != "completed" for row in rows),
                "without_score_file": sum(not row["scored"] for row in rows),
                "not_delivered": sum(not row["delivered"] for row in rows)}
    out = args.out.expanduser().resolve()
    no_chart = indicator_chart(summary, beside, arms, out)
    write_json(out / "indicators.json", {
        "definition": "benchmarking/evaluation/ASPECT_SCORES.md", "arms": arms, "summary": summary,
        "beside": beside, "attempts": attempts, "not_judged": not_judged, "without_score_file": unscored,
        "delivered_with_other_status": status_differs, "chart": no_chart or "six-indicators.png"})

    def shown(value):
        return "" if value is None else f"{value:.1f}"

    lines = ["# Six indicators per task type", "",
             ("Defined in `benchmarking/evaluation/ASPECT_SCORES.md`. Each indicator is 0-100: the judge's level "
              "of the criteria it names. The six count the same, and the score is their mean."), ""]
    for kind, listed in INDICATORS.items():
        if kind not in summary:
            continue
        present = [arm for arm in arms if arm in summary[kind]]
        lines += [f"## {TYPE_NAMES[kind][0]} ({TYPE_NAMES[kind][1]})", "",
                  "| Indicator | The question it answers | " + " | ".join(present) + " |",
                  "|---|---|" + "---|" * len(present)]
        lines += [f"| {name} ({chinese}) | {question} | "
                  + " | ".join(shown(summary[kind][arm]["indicators"][name]) for arm in present) + " |"
                  for name, chinese, question, _ in listed]
        totals = [shown(summary[kind][arm]["score"]) for arm in present]
        lines += ["| **Score (mean of the six)** | | " + " | ".join(f"**{total}**" if total else "" for total in totals) + " |",
                  "", "Beside the scores (not part of them):", "",
                  "| | " + " | ".join(present) + " |", "|---|" + "---|" * len(present)]
        for key, label in (("questions", "Questions"), ("attempts", "Attempts judged"),
                           ("not_completed", "Judged attempts not completed"),
                           ("without_score_file", "Attempts without a score file (count 0)"),
                           ("not_delivered", "Attempts that did not deliver")):
            lines.append(f"| {label} | " + " | ".join(str(beside[kind][arm][key]) for arm in present) + " |")
        lines.append("")
    if no_chart:
        lines += [f"No chart: {no_chart}.", ""]
    else:
        lines += ["![six indicators](six-indicators.png)", ""]
    if not_judged:
        lines += ["## Not judged yet", "",
                  ("An indicator stays empty, and the score with it, until the judge has recorded what it needs "
                   "(`CODEX_JUDGE.md`)."), ""]
        lines += [f"- `{blind_id}`: {', '.join(waiting)}" for blind_id, waiting in not_judged.items()]
        lines.append("")
    if status_differs:
        lines += [("Recorded as delivered although the status is not `completed` (the judge's notes say why): ")
                  + ", ".join(f"`{b}`" for b in status_differs) + ".", ""]
    (out / "indicators.md").write_text("\n".join(lines), encoding="utf-8")

    def rounded(value):
        return None if value is None else round(value, 1)

    return {"report": str(out / "indicators.md"), "chart": None if no_chart else str(out / "six-indicators.png"),
            "no_chart": no_chart, "not_judged": sum(len(v) for v in not_judged.values()),
            "scores": {kind: {arm: rounded(of_arm["score"]) for arm, of_arm in by_arm.items()}
                       for kind, by_arm in summary.items()},
            "indicators": {kind: {arm: {name: rounded(value) for name, value in of_arm["indicators"].items()}
                                  for arm, of_arm in by_arm.items()} for kind, by_arm in summary.items()}}


# Categorical slots 1 to 3 of a palette checked for colour-vision deficiency with every pair side by side;
# overlapping polygons stay apart for three series at most, so a chart shows three arms at most.
CHART_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a")
CHART_MARKERS = ("o", "^", "s")
CHART_SURFACE, CHART_INK, CHART_INK_2, CHART_MUTED, CHART_GRID, CHART_RIM = (
    "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7")
CJK_FONTS = ("PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
             "WenQuanYi Micro Hei", "Microsoft YaHei", "SimHei", "Arial Unicode MS")


def indicator_chart(summary: dict, beside: dict, arms: list[str], out: Path) -> str | None:
    """One six-axis chart per task type with the arms overlaid, as PNG and SVG. Returns why there is
    no chart, or None. Every axis carries the indicator's name and the question it answers, and each
    arm's score stands under the title. The values of the axes are in the table of indicators.md."""
    if len(arms) > len(CHART_COLOURS):
        return "more than three arms; name the three to draw with --arms"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.lines import Line2D
        from matplotlib.patheffects import withStroke
    except ImportError:
        return "matplotlib is not installed"
    import math
    import textwrap
    kinds = [kind for kind in INDICATORS if kind in summary]
    if not kinds:
        return "no judged attempt"
    # Chinese names and questions where the machine has a font for them.
    cjk = next((name for name in CJK_FONTS if name in {font.name for font in font_manager.fontManager.ttflist}), None)
    with plt.rc_context({"font.family": "sans-serif", "axes.unicode_minus": False,
                         "font.sans-serif": [*([cjk] if cjk else []), "DejaVu Sans"]}):
        fig, panels = plt.subplots(1, len(kinds), figsize=(7.6 * len(kinds), 7.8), squeeze=False,
                                   facecolor=CHART_SURFACE)
        for ax, kind in zip(panels[0], kinds):
            listed = INDICATORS[kind]
            present = [arm for arm in arms if arm in summary[kind]]
            angles = [2 * math.pi * index / len(listed) for index in range(len(listed))]
            closed = [*angles, angles[0]]
            between = math.pi / len(listed)  # the scale is written between two axes, clear of the marks on them
            for radius in (20, 40, 60, 80, 100):
                ax.plot([radius * math.sin(a) for a in closed], [radius * math.cos(a) for a in closed],
                        color=CHART_RIM if radius == 100 else CHART_GRID, linewidth=0.8, zorder=1)
                edge = radius * math.cos(between)
                ax.text(edge * math.sin(between) + 2, edge * math.cos(between) + 2, str(radius), fontsize=7.5,
                        color=CHART_MUTED, ha="left", va="bottom", zorder=6,
                        path_effects=[withStroke(linewidth=2.2, foreground=CHART_SURFACE)])
            for angle in angles:
                ax.plot([0, 100 * math.sin(angle)], [0, 100 * math.cos(angle)], color=CHART_GRID, linewidth=0.8,
                        zorder=1)
            # The first arm is drawn last, so it lies on top.
            for colour, marker, arm in reversed(list(zip(CHART_COLOURS, CHART_MARKERS, arms))):
                if arm not in summary[kind]:
                    continue
                values = [summary[kind][arm]["indicators"][name] for name, *_ in listed]
                points = [None if value is None else (value * math.sin(angle), value * math.cos(angle))
                          for value, angle in zip(values, angles)]
                if None not in points:
                    ax.fill(*zip(*points), color=colour, alpha=0.10, zorder=3)
                # An indicator that is not judged yet leaves a gap in the outline.
                for here, there in zip(points, [*points[1:], points[0]]):
                    if here and there:
                        ax.plot(*zip(here, there), color=colour, linewidth=2, solid_capstyle="round", zorder=4)
                known = [point for point in points if point]
                if known:
                    ax.plot(*zip(*known), linestyle="none", marker=marker, markersize=8, color=colour,
                            markeredgecolor=CHART_SURFACE, markeredgewidth=1.5, zorder=5)
            for angle, (name, chinese, question, asks) in zip(angles, listed):
                side, up = math.sin(angle), math.cos(angle)
                title, text = (chinese, asks) if cjk else (name, textwrap.fill(question, 24))
                if any(summary[kind][arm]["indicators"][name] is None for arm in present):
                    title, text = (f"{title}（待评）", text) if cjk else (title, f"{text}\n(not judged yet)")
                align = "center" if abs(side) < 0.3 else "left" if side > 0 else "right"
                x, y, rows = 112 * side, 108 * up, text.count("\n") + 1
                # Over the chart both lines stand above the axis, under it below; beside it the name sits
                # above the end of the axis and the question below.
                name_y, name_va, text_y, text_va = ((y + 4 + 9 * rows, "bottom", y + 4, "bottom") if up > 0.9 else
                                                    (y - 4, "top", y - 16, "top") if up < -0.9 else
                                                    (y + 1.5, "bottom", y - 1.5, "top"))
                ax.text(x, name_y, title, fontsize=13, color=CHART_INK, ha=align, va=name_va)
                ax.text(x, text_y, text, fontsize=9, color=CHART_INK_2, ha=align, va=text_va, linespacing=1.3)
            questions = max(beside[kind][arm]["questions"] for arm in present)
            ax.set_title(f"{TYPE_NAMES[kind][1]}（{questions} 题）" if cjk
                         else f"{TYPE_NAMES[kind][0]} ({questions} questions)", fontsize=14.5, color=CHART_INK, pad=28)
            waiting = "待评" if cjk else "not judged yet"
            marks = " · ".join(f"{arm} " + (waiting if summary[kind][arm]["score"] is None
                                           else format(summary[kind][arm]["score"], ".1f")) for arm in present)
            ax.text(0.5, 1.0, ("总分（六项平均）  " if cjk else "Score (mean of the six)  ") + marks,
                    transform=ax.transAxes, ha="center", va="bottom", fontsize=10.5, color=CHART_INK_2)
            ax.set_xlim(-198, 198)
            ax.set_ylim(-152, 152)
            ax.set_aspect("equal")
            ax.axis("off")
        handles = [Line2D([0], [0], color=colour, linewidth=2, marker=marker, markersize=8,
                          markeredgecolor=CHART_SURFACE, markeredgewidth=1.5, label=arm)
                   for colour, marker, arm in zip(CHART_COLOURS, CHART_MARKERS, arms)]
        fig.legend(handles=handles, loc="lower center", ncol=len(arms), frameon=False, fontsize=11.5,
                   labelcolor=CHART_INK, bbox_to_anchor=(0.5, 0.06), handlelength=2.6, columnspacing=2.4)
        note = ("每个轴 0–100，是裁判给这一项的等级；六项同等重要，平均就是总分（ASPECT_SCORES.md）。各轴数值见 indicators.md。"
                if cjk else "Each axis 0-100: the judge's level of that indicator. The six count the same and "
                            "their mean is the score (ASPECT_SCORES.md). The values are in indicators.md.")
        fig.text(0.5, 0.025, note, ha="center", va="center", fontsize=8.5, color=CHART_INK_2)
        fig.subplots_adjust(left=0.02, right=0.98, top=0.87, bottom=0.12, wspace=0.04)
        out.mkdir(parents=True, exist_ok=True)
        fig.savefig(out / "six-indicators.png", dpi=200, facecolor=CHART_SURFACE)
        fig.savefig(out / "six-indicators.svg", facecolor=CHART_SURFACE)
        plt.close(fig)
    return None


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
    v.add_argument("--added", type=Path,
                   help="Folder of the criteria of paper verification judged beside the rubric, one <blind_id>.json each")
    f = sub.add_parser("freeze")
    f.add_argument("--prereg", type=Path, required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--prereg", type=Path, required=True)
    s.add_argument("--map", type=Path, required=True)
    s.add_argument("--scores", type=Path, required=True)
    s.add_argument("--added", type=Path,
                   help="Folder of the criteria of paper verification judged beside the rubric, one <blind_id>.json each")
    s.add_argument("--out", type=Path, required=True)
    x = sub.add_parser("indicators")
    x.add_argument("--map", type=Path, required=True)
    x.add_argument("--scores", type=Path, required=True)
    x.add_argument("--added", type=Path,
                   help="Folder of the criteria of paper verification judged beside the rubric, one <blind_id>.json each")
    x.add_argument("--out", type=Path, required=True)
    x.add_argument("--arms", nargs="+", help="Arms to show, in this order; by default every arm of the map")
    p = sub.add_parser("process")
    p.add_argument("--runs", type=Path, nargs="+", required=True, help="Arm output folders (with arm.json)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--prereg", type=Path, help="Frozen pre-registration with process_comparisons")
    i = sub.add_parser("inventory")
    i.add_argument("--runs", type=Path, nargs="+", required=True, help="Arm output folders (with arm.json)")
    i.add_argument("--out", type=Path, required=True)
    lc = sub.add_parser("library-check", aliases=["lessons-check"])
    lc.add_argument("--runs", type=Path, required=True)
    rc = sub.add_parser("rubric-check")
    rc.add_argument("--rubrics", type=Path, required=True, help="Folder of frozen rubrics, one <task>.json each")
    rc.add_argument("--references", type=Path, required=True,
                    help="Folder of reference work: <task>/spec.md, compute.py and outputs/")
    rc.add_argument("--tasks", nargs="+", help="Tasks that must be frozen; by default every rubric file found")
    args = parser.parse_args(argv)
    handler = {"blind": blind, "validate": validate, "freeze": freeze, "summarize": summarize,
               "indicators": indicators, "process": process, "inventory": inventory,
               "library-check": library_check, "lessons-check": library_check,
               "rubric-check": rubric_check}[args.command]
    result = handler(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Not ready to judge with, or an indicator that the judge has still to score.
    return 1 if (args.command == "rubric-check" and result["not_ready"]
                 or args.command == "indicators" and result["not_judged"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
