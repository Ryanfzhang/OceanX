"""Paired live runs and frozen-criteria acceptance for research policies.

1. ``run_pairs`` runs every held-out case under policy A and policy B (order
   randomised per case), same data and model.
2. The owner compares the two final answers once per case ({case, better: A|B|same});
   no per-node labels are needed for acceptance.
3. ``evaluate_pairs`` applies the frozen criteria: B must not lose on quality, must
   stay within budget and failure limits, and must either win on quality or cut
   tokens by ``rq1.min_relative_improvement``. It reports; it never promotes.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path

from oceanx.research import acceptance
from oceanx.research.policy import POLICY_ENV, find_policy


async def run_pairs(queries_file: Path, output: Path, *, policy_a: str, policy_b: str,
                    seed: int = 0) -> list[dict]:
    from oceanx.batch import load_queries, run_case

    criteria = acceptance.require_frozen()
    find_policy(policy_a), find_policy(policy_b)  # fail early on unknown names
    cases = load_queries(queries_file)
    if len(cases) < int(criteria["rq1"]["min_pairs"]):
        raise ValueError("Fewer held-out cases than rq1.min_pairs in the frozen criteria.")
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(seed)
    manifest = {"queries_file": str(queries_file), "policy_a": policy_a, "policy_b": policy_b,
                "seed": seed, "acceptance_sha": acceptance.lock_record()["sha256"], "runs": []}
    previous = os.environ.get(POLICY_ENV)
    try:
        for case in cases:
            arms = [("A", policy_a), ("B", policy_b)]
            rng.shuffle(arms)
            for arm, policy in arms:
                os.environ[POLICY_ENV] = policy  # inherited by the backend subprocess
                directory = output / case.id / arm
                result = await run_case(case, directory)
                manifest["runs"].append({"case": case.id, "arm": arm, "policy": policy,
                                         "status": result.get("status"),
                                         "directory": str(directory)})
                (output / "pairs.json").write_text(json.dumps(manifest, indent=2))
    finally:
        if previous is None:
            os.environ.pop(POLICY_ENV, None)
        else:
            os.environ[POLICY_ENV] = previous
    return manifest["runs"]


def _arm_metrics(directory: Path) -> dict:
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    usages = [result.get("coordinator_usage") or {}]
    if isinstance(result.get("expert_usage"), dict):
        usages += list(result["expert_usage"].values())
    tokens = sum(int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
                 for u in usages if isinstance(u, dict))
    return {"status": result.get("status"), "elapsed_seconds": result.get("elapsed_seconds") or 0,
            "tokens": tokens}


def evaluate_pairs(output: Path, *, quality_file: Path) -> dict:
    """Apply the frozen criteria. ``quality_file``: JSONL of {case, better: A|B|same}."""
    criteria = acceptance.require_frozen()
    budgets, rq1 = criteria["budgets"], criteria["rq1"]
    manifest = json.loads((output / "pairs.json").read_text())
    by_case: dict[str, dict[str, dict]] = {}
    for run in manifest["runs"]:
        by_case.setdefault(run["case"], {})[run["arm"]] = _arm_metrics(Path(run["directory"]))
    pairs = {c: arms for c, arms in by_case.items() if {"A", "B"} <= set(arms)}
    quality = {item["case"]: item["better"] for item in
               (json.loads(line) for line in quality_file.read_text().splitlines() if line.strip())}
    b_runs = [arms["B"] for arms in pairs.values()]
    tokens = {arm: sum(arms[arm]["tokens"] for arms in pairs.values()) for arm in ("A", "B")}
    token_cut = (tokens["A"] - tokens["B"]) / tokens["A"] if tokens["A"] else None
    wins = sum(quality.get(c) == "B" for c in pairs)
    losses = sum(quality.get(c) == "A" for c in pairs)
    checks = {
        "enough_pairs": len(pairs) >= int(rq1["min_pairs"]),
        "every_pair_rated": all(c in quality for c in pairs),
        "no_quality_regressions": losses <= int(rq1["max_quality_regressions"]),
        "b_failure_rate_ok": bool(b_runs) and sum(r["status"] != "completed" for r in b_runs)
        / len(b_runs) <= budgets["max_failure_rate"],
        "b_within_budget": all(r["tokens"] <= budgets["max_tokens_per_task"]
                               and r["elapsed_seconds"] <= budgets["max_wall_seconds_per_task"]
                               for r in b_runs),
        "b_better_or_cheaper": wins > losses or (
            token_cut is not None and token_cut >= float(rq1["min_relative_improvement"])),
    }
    return {"policy_a": manifest["policy_a"], "policy_b": manifest["policy_b"],
            "pairs": len(pairs), "quality": {"B_better": wins, "A_better": losses},
            "tokens": tokens, "token_reduction": token_cut, "checks": checks,
            "meets_frozen_criteria": all(checks.values()), "per_case": pairs,
            "note": "Meeting the criteria permits, but does not perform, activation."}


def run_pairs_sync(*args, **kwargs):
    return asyncio.run(run_pairs(*args, **kwargs))


__all__ = ["evaluate_pairs", "run_pairs", "run_pairs_sync"]
