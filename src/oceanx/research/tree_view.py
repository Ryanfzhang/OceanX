"""Compact text rendering of the research tree for the Coordinator.

The stored tree keeps every field; the model sees one line per decision-relevant
node. Completed questions keep Result, a one-line decision limit (compressed
"Evidence and limitations") and Further analysis, because those decide whether a
node can be closed or needs a follow-up.
"""
from __future__ import annotations

import re

from oceanx.research.tree import (
    _blocked,
    _depth,
    _descendants,
    frontier,
    kind,
    nodes,
    summary_field,
)

TERMINAL = {"completed", "closed", "failed"}
MAX_VIEW_NODES = 40
TREE_SECTION = re.compile(r"(?ims)^##[ \t]+Research Tree[ \t]*$.*?(?=^##[ \t]+|\Z)")


def _field(summary: str, label: str) -> str:
    return re.sub(r"\s+", " ", summary_field(summary, label)).strip()


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def result_fields(summary: str) -> tuple[str, str, str]:
    result = _field(summary, "Result") or re.sub(r"\s+", " ", summary or "").strip()
    limit = _first_sentence(_field(summary, "Evidence and limitations"))
    further = _field(summary, "Further analysis")
    return _clip(result, 320), _clip(limit, 160), _clip(further, 200)


def node_line(tree: dict, node_id: str, *, live: set[str] = frozenset(), indent: bool = True) -> str:
    found = nodes(tree)
    node = found[node_id]
    pad = "  " * _depth(tree, node_id) if indent else ""
    if kind(node) == "hypothesis":
        evidence = {"supports": [], "refutes": [], "inconclusive": []}
        for link in tree["links"]:
            if link["target"] == node_id and link["type"] in evidence:
                evidence[link["type"]].append(link["source"])
        parts = [f"{pad}{node_id} (hypothesis, {node['verdict']}) {node['question']}"]
        parts += [f"{name}: {','.join(ids)}" for name, ids in evidence.items() if ids]
        if node["status"] == "closed":
            parts.append(f"closed: {node.get('close_reason') or ''}")
        return " | ".join(parts)
    line = f"{pad}{node_id} [{node['status']}] {node['question']}"
    if node_id in live and node.get("why_it_matters"):
        line += f" — why: {_clip(node['why_it_matters'], 200)}"
    if node.get("dependencies"):
        line += f" | deps: {','.join(node['dependencies'])}"
    if node.get("relation") == "alternative":
        line += " | alternative"
    if node["status"] in {"closed", "failed"} and node.get("close_reason"):
        line += f" | reason: {_clip(node['close_reason'], 200)}"
    if node.get("result"):
        result, limit, further = result_fields(node["result"].get("summary", ""))
        line += f"\n{pad}  → Result: {result}"
        if limit:
            line += f"\n{pad}  → Limit: {limit}"
        proposals = node["result"].get("proposals") or []
        if proposals:
            line += f"\n{pad}  → Proposed follow-ups (add with from_proposal to pursue): " + "; ".join(
                f"{node_id}#{i} {_clip(q, 160)}" for i, q in enumerate(proposals, 1))
        elif further:
            line += f"\n{pad}  → Further: {further}"
    return line


def _folded(tree: dict, node_id: str) -> bool:
    """A finished question whose whole subtree is finished collapses to one line."""
    found = tree["nodes"]
    node = found[node_id]
    if node.get("parent") is None or kind(node) == "hypothesis":
        return False
    return all(found[n]["status"] in TERMINAL or kind(found[n]) == "hypothesis"
               for n in {node_id} | _descendants(tree, node_id))


def _live(tree: dict) -> set[str]:
    found = nodes(tree)
    return {k for k, v in found.items()
            if v["status"] in {"candidate", "selected"} and not _blocked(tree, k)}


def _summary_lines(tree: dict) -> list[str]:
    found = nodes(tree)
    live = _live(tree)
    lines = [f"frontier: {', '.join(frontier(tree)) or 'none'}",
             f"live candidates: {', '.join(sorted(k for k in live if found[k]['status'] == 'candidate')) or 'none'}"]
    return lines


def render_full(tree: dict, *, include_history: bool = False,
                max_nodes: int = MAX_VIEW_NODES) -> str:
    """The Coordinator's tree view, bounded to ``max_nodes`` lines of nodes.

    Live questions, hypotheses and their ancestors always appear; beyond the budget,
    finished branches are counted instead of listed (``include_history`` lists all).
    """
    found = nodes(tree)
    live = _live(tree)
    order: list[str] = []
    for root in sorted(k for k, v in found.items() if v.get("parent") is None):
        stack = [root]
        while stack:
            current = stack.pop()
            order.append(current)
            if include_history or current == root or not _folded(tree, current):
                stack.extend(sorted((k for k, v in found.items() if v.get("parent") == current),
                                    reverse=True))
    shown = set(order)
    if not include_history and len(order) > max_nodes:
        keep = {n for n in order if n in live or kind(found[n]) == "hypothesis"
                or found[n].get("parent") is None}
        for node_id in list(keep):
            while found[node_id].get("parent"):
                node_id = found[node_id]["parent"]
                keep.add(node_id)
        shown = keep | set([n for n in order if n not in keep][:max(0, max_nodes - len(keep))])
    lines = [f"research tree revision {tree['revision']}"]
    for node_id in order:
        if node_id not in shown:
            continue
        node = found[node_id]
        if not include_history and node.get("parent") and _folded(tree, node_id):
            conclusion = (" → " + result_fields(node["result"]["summary"])[0] if node.get("result")
                          else " → " + _clip(node["close_reason"], 200) if node.get("close_reason")
                          else "")
            lines.append(f"{'  ' * _depth(tree, node_id)}{node_id} [{node['status']}, folded] "
                         f"{node['question']}{conclusion}")
        else:
            lines.append(node_line(tree, node_id, live=live))
    hidden = len(order) - len(shown & set(order))
    if hidden:
        lines.append(f"+{hidden} finished nodes not shown (view=full lists every node)")
    lines.extend(_summary_lines(tree))
    return "\n".join(lines)


def render_results(tree: dict) -> str:
    """Every returned node's complete Result and Evidence and limitations, in tree order.

    The tree view clips them to 320 characters and one sentence, which hides a correction made late in a
    long Summary: in Q08 of the 40-call batch the final answer kept a number a later node had corrected.
    A node that corrects an earlier one replaces its value.
    """
    found = nodes(tree)
    returned = sorted((key for key in found if found[key].get("result")),
                      key=lambda key: [int(part) for part in re.findall(r"\d+", key)])
    lines = [f"research tree revision {tree['revision']}: complete results of {len(returned)} returned nodes"]
    for node_id in returned:
        summary = found[node_id]["result"].get("summary", "")
        result = _field(summary, "Result") or re.sub(r"\s+", " ", summary).strip()
        lines += ["", f"{node_id} {found[node_id]['question']}", f"  Result: {result}",
                  f"  Evidence and limitations: {_field(summary, 'Evidence and limitations')}"]
    return "\n".join(lines)


def render_delta(tree: dict, changed: list[str], *, created: list[str] = ()) -> str:
    found = nodes(tree)
    live = _live(tree)
    lines = [f"research tree revision {tree['revision']}"]
    if created:
        lines.append("created: " + ", ".join(created))
    shown = [c for c in dict.fromkeys(changed) if c in found]
    if shown:
        lines.append("changed:")
        lines.extend(node_line(tree, c, live=live, indent=False) for c in shown)
    hypotheses = {k for k, v in found.items() if kind(v) == "hypothesis" and v["status"] != "closed"}
    rest = sorted((live | hypotheses | set(frontier(tree))) - set(shown))
    if rest:
        lines.append("live nodes:")
        lines.extend(node_line(tree, c, live=live, indent=False) for c in rest)
    lines.extend(_summary_lines(tree))
    return "\n".join(lines)


__all__ = ["TREE_SECTION", "node_line", "render_delta", "render_full", "render_results", "result_fields"]
