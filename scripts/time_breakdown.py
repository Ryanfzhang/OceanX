"""Where did the time go in one `ocean run` attempt?

Usage: python scripts/time_breakdown.py <run-output-dir>   (the directory given to --output)

Reads only local records the run already keeps: result.json (setup vs analysis wall time) and
state/workspace.sqlite3 (model-call observations, code executions, request records). Prints a
timeline and a breakdown of analysis time into model calls, code execution and everything else.
Parallel intervals are merged, so the parts add up to wall time rather than double counting.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _t(value: str | None) -> float | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None


def _union(intervals: list[tuple[float, float]]) -> float:
    total, end = 0.0, float("-inf")
    for start, stop in sorted(intervals):
        if stop <= end:
            continue
        total += stop - max(start, end)
        end = stop
    return total


def _attempt(root: Path) -> Path:
    if (root / "result.json").exists():
        return root
    found = sorted(root.glob("*/attempt-*/result.json"))
    if not found:
        raise SystemExit(f"No result.json under {root}")
    return found[-1].parent


def main(root: Path) -> None:
    run = _attempt(root)
    result = json.loads((run / "result.json").read_text())
    db = sqlite3.connect(run / "state" / "workspace.sqlite3")
    calls = [json.loads(r[0]) for r in db.execute("SELECT record_json FROM model_call_observations")]
    code = [dict(zip(("state", "request", "result", "started", "ended", "agent"), r)) for r in db.execute(
        "SELECT state, request_json, result_json, started_at, ended_at, agent_thread_id FROM code_executions")]
    submit = db.execute("SELECT created_at, updated_at FROM request_records "
                        "WHERE request_type='session.submit' ORDER BY created_at LIMIT 1").fetchone()

    t0 = _t(submit[0]) if submit else min(_t(c["started_at"]) for c in calls)
    t_end = _t(submit[1]) if submit else max(_t(c.get("ended_at") or c["started_at"]) for c in calls)

    rows, model_iv, code_iv = [], [], []
    for c in calls:
        start, end = _t(c["started_at"]), _t(c.get("ended_at"))
        if end is None:
            continue
        model_iv.append((start, end))
        usage = c.get("usage") or {}
        who = c["role"] + (f" ({c['agent_run_id'][:18]})" if c.get("agent_run_id") else "")
        rows.append((start, end, "model", who,
                     f"in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')} "
                     f"tools={c.get('tool_calls', 0)} first_chunk={c.get('first_chunk_seconds', 0):.1f}s"
                     + (" SUMMARY" if c.get("kind") == "summary" else "")
                     + ("" if c.get("state") == "completed" else f" {c.get('state')}")))
    for e in code:
        start, end = _t(e["started"]), _t(e["ended"])
        if end is None:
            continue
        code_iv.append((start, end))
        error = (json.loads(e["result"] or "{}").get("error") or "")[:60]
        rows.append((start, end, "code", e["agent"][:30], f"{e['state']} {error}".strip()))

    print(f"Run: {run}\nStatus: {result.get('status')}   total wall {result.get('elapsed_seconds')} s  "
          f"(setup {result.get('setup_seconds', '?')} s, analysis {result.get('analysis_seconds', '?')} s)\n")
    print(f"{'start':>7} {'dur':>7}  kind   who / detail")
    for start, end, kind, who, detail in sorted(rows):
        print(f"{start - t0:7.1f} {end - start:7.1f}  {kind:<6} {who}  {detail}")

    wall = t_end - t0
    model_t, code_t = _union(model_iv), _union(code_iv)
    both = _union(model_iv + code_iv)
    by_role: dict[str, list] = {}
    for c in calls:
        by_role.setdefault(c["role"], []).append(c)
    print(f"\nAnalysis request wall: {wall:.1f} s")
    print(f"  model calls (merged): {model_t:6.1f} s  {100 * model_t / wall:4.0f}%")
    print(f"  code execution:       {code_t:6.1f} s  {100 * code_t / wall:4.0f}%")
    print(f"  everything else:      {wall - both:6.1f} s  {100 * (wall - both) / wall:4.0f}%  "
          "(tool I/O, sandbox/kernel start, graph and receipt handling, waiting)")
    for role, items in by_role.items():
        usage = [c.get("usage") or {} for c in items]
        print(f"  {role:<28} {len(items):3d} calls  "
              f"in {sum(u.get('input_tokens') or 0 for u in usage):>8,}  "
              f"out {sum(u.get('output_tokens') or 0 for u in usage):>6,}  "
              f"summed {sum(c.get('duration_seconds') or 0 for c in items):6.1f} s")
    failed = sum(e["state"] != "succeeded" for e in code)
    print(f"  code runs: {len(code)} ({failed} not succeeded)")

    gaps, last = [], t0
    for start, end, *_ in sorted(rows):
        if start - last > 3:
            gaps.append((last - t0, start - last))
        last = max(last, end)
    if t_end - last > 3:
        gaps.append((last - t0, t_end - last))
    if gaps:
        print("\nIdle gaps > 3 s (no model call or code running):")
        for at, length in gaps:
            print(f"  at {at:7.1f} s for {length:5.1f} s")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
