"""Post-task outcome records per research-tree node (improvement data only).

Computed once when the Coordinator finishes. Nothing here is shown to a model.

``cited_in_final`` deliberately ignores the rendered ``## Research Tree`` section,
which lists every node; a node counts as cited only if the final answer's prose
refers to its ID, one of its result bindings, or its report. Citation is a weak
signal (the Coordinator controls it); human labels remain the ground truth.
"""
from __future__ import annotations

import re

from oceanx.research.labels import apply_auto_labels
from oceanx.research.tree import kind, nodes
from oceanx.research.tree_view import TREE_SECTION




def _prose(final_report: str) -> str:
    return TREE_SECTION.sub("", final_report or "")


def _usage(record: dict) -> tuple[int, int]:
    usage = record.get("usage") or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def _executions_for(attempts: list[dict], executions: list[dict]) -> list[dict]:
    """Code runs by the attempt's Agent inside the attempt's time window.

    Agents on one root branch share a key (and kernel), so the window separates nodes.
    """
    runs = []
    for attempt in attempts:
        start, end = attempt.get("started_at") or "", attempt.get("ended_at") or "~"
        runs += [e for e in executions if e.get("agent_thread_id") == attempt["agent_key"]
                 and start <= (e.get("started_at") or "") <= end]
    return runs


def _tool_calls(executions: list[dict]) -> dict[str, int]:
    """Helper-function calls summed over code runs, by function name."""
    total: dict[str, int] = {}
    for execution in executions:
        for name, count in (execution.get("tool_calls") or {}).items():
            total[name] = total.get(name, 0) + int(count)
    return dict(sorted(total.items()))


def compute_outcomes(tree_doc: dict, events: list[dict], attempts: list[dict],
                     *, final_report: str, model_calls: list[dict],
                     code_executions: list[dict] = (), library: dict | None = None) -> dict[str, dict]:
    """``library`` says which lessons and tools the task ran with (see graphs.coordinator);
    it is kept on the first root, with the helper calls of the whole task."""
    found = nodes(tree_doc)
    prose = _prose(final_report)
    calls_by_attempt: dict[str, list[dict]] = {}
    for record in model_calls:
        if record.get("attempt_id"):
            calls_by_attempt.setdefault(record["attempt_id"], []).append(record)
    attempts_by_node: dict[str, list[dict]] = {}
    for attempt in attempts:
        attempts_by_node.setdefault(attempt["node_id"], []).append(attempt)
    delegations: dict[str, list[dict]] = {}
    for event in events:
        if event["type"] == "delegated":
            delegations.setdefault(event["node_id"], []).append(event["payload"])

    # The Coordinator answers the root itself, so its own model calls belong to the first root.
    coordinator_calls = [c for c in model_calls if c.get("role") == "coordinator"]
    root = next((n for n, node in found.items() if node.get("parent") is None), None)

    adopted: dict[str, int] = {}
    for node in found.values():
        for ref in (node.get("origin") or {}).get("refs", []):
            if node["origin"]["type"] == "expert-proposal":
                adopted[ref.partition("#")[0]] = adopted.get(ref.partition("#")[0], 0) + 1

    outcomes: dict[str, dict] = {}
    for node_id, node in found.items():
        node_attempts = attempts_by_node.get(node_id, [])
        attempt_ids = {a["attempt_id"] for a in node_attempts} | {
            d.get("attempt_id") for d in delegations.get(node_id, [])}
        calls = (coordinator_calls if node_id == root
                 else [c for a in attempt_ids for c in calls_by_attempt.get(a, [])])
        cited = bool(re.search(rf"(?<![A-Za-z0-9.]){re.escape(node_id)}(?![0-9A-Za-z]|\.\d)", prose)) \
            or any(f"[{a['agent_key']}/" in prose or a["report_path"] in prose for a in node_attempts)
        runs = _executions_for(node_attempts, list(code_executions))
        links = tree_doc["links"]
        outcomes[node_id] = {
            "kind": kind(node),
            "is_root": node.get("parent") is None,
            "final_status": node["status"],
            "verdict": node.get("verdict"),
            "attempts": len(node_attempts),
            "model_calls": len(calls),
            "input_tokens": sum(_usage(c)[0] for c in calls),
            "output_tokens": sum(_usage(c)[1] for c in calls),
            # Which skills these calls opened; shows whether a skill with lessons was read.
            "skills_read": sorted({name for c in calls for name in c.get("skills_read") or []}),
            "cited_in_final": cited,
            "spawned_children": sum(1 for n in found.values() if n.get("parent") == node_id),
            "follow_ups_proposed": len(((node.get("result") or {}).get("proposals")) or []),
            "follow_ups_adopted": adopted.get(node_id, 0),
            "reopened": any(e["type"] == "reopened" and e["node_id"] == node_id for e in events),
            "conflict_links": sum(1 for link in links if link["type"] == "conflicts"
                                  and node_id in (link["source"], link["target"])),
            "hypothesis_evidence": sum(1 for link in links if link["source"] == node_id
                                       and link["type"] in {"supports", "refutes"}
                                       and kind(found[link["target"]]) == "hypothesis"),
            "code_runs": len(runs),
            "code_seconds": round(sum(float(r.get("duration_seconds") or 0) for r in runs), 1),
            "code_failures": [str(r.get("error") or "")[:200] for r in runs
                              if r.get("state") not in {"succeeded", "running"}][:3],
            "tool_calls": _tool_calls(runs),
        }
    if root is not None and library is not None:
        # A code run of an attempt that returned no report belongs to no node, so the task's
        # calls are summed over every run, not over the nodes.
        outcomes[root]["library"] = {**library, "tool_calls": _tool_calls(list(code_executions))}
    return outcomes


def record_task_outcomes(tree, *, final_report: str, model_calls: list[dict],
                         code_executions: list[dict] = (), library: dict | None = None) -> dict[str, dict]:
    """Store outcomes and the automatic labels derived from them (see labels.py)."""
    outcomes = compute_outcomes(tree.document(), tree.events(), tree.attempts(),
                                final_report=final_report, model_calls=model_calls,
                                code_executions=code_executions, library=library)
    tree.store.write_outcomes(outcomes)
    apply_auto_labels(tree, outcomes)
    return outcomes


__all__ = ["compute_outcomes", "record_task_outcomes"]
