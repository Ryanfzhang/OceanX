"""A file-backed scientific decision tree.

The tree records what is worth asking, why, and what the resulting report says.
It deliberately does not mirror DeepAgents task state, transcripts, methods, or
review logs.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from oceanx.research.tree_store import (
    POLICY_V0,
    NodeAttempt,
    TreeEvent,
    TreeStore,
    atomic_write_text,
    events_for_changes,
)

SCHEMA = "oceanx-research-tree/v4"
# v3 trees are read and upgraded in memory (v4 only adds optional hypothesis nodes).
READABLE_SCHEMAS = {"oceanx-research-tree/v3", SCHEMA}
STATUSES = {"active", "candidate", "selected", "completed", "closed", "failed"}
# Accepted only while loading trees written before selection became explicit.
LEGACY_STATUSES = {"ready", "running"}
RELATIONS = {"independent", "dependency", "alternative", "extension"}
LINK_TYPES = {"supports", "conflicts", "depends_on", "related", "refutes", "inconclusive"}
# Question -> hypothesis evidence. ``supports`` keeps its v3 meaning between questions.
EVIDENCE_LINKS = {"supports", "refutes", "inconclusive"}
KINDS = {"question", "hypothesis"}
VERDICTS = {"supported", "refuted", "unresolved"}


def kind(node: dict) -> str:
    """Nodes written before v4 are questions."""
    return node.get("kind") or "question"


def empty_tree() -> dict:
    return {"schema_version": SCHEMA, "revision": 0, "nodes": {}, "links": []}


def nodes(tree: dict) -> dict[str, dict]:
    """Validate the durable public shape and return its node dictionary."""
    if not isinstance(tree, dict) or tree.get("schema_version") not in READABLE_SCHEMAS:
        raise ValueError("Research tree has an unsupported schema.")
    found = tree.get("nodes")
    links = tree.get("links")
    if not isinstance(found, dict) or not isinstance(links, list):
        raise ValueError("Research tree requires nodes and links.")
    for node_id, node in found.items():
        if not isinstance(node_id, str) or not node_id.strip() or not isinstance(node, dict):
            raise ValueError("Research node IDs and values are invalid.")
        if node.get("id") != node_id:
            raise ValueError(f"Research node {node_id} has a mismatched ID.")
        if not isinstance(node.get("question"), str) or not node["question"].strip():
            raise ValueError(f"Research node {node_id} needs a question.")
        if not isinstance(node.get("why_it_matters"), str):
            raise ValueError(f"Research node {node_id} needs why_it_matters text.")
        parent = node.get("parent")
        if parent is not None and parent not in found:
            raise ValueError(f"Research node {node_id} has an unknown parent.")
        if node.get("status") not in STATUSES | LEGACY_STATUSES:
            raise ValueError(f"Research node {node_id} has an invalid status.")
        if node.get("relation") not in RELATIONS:
            raise ValueError(f"Research node {node_id} has an invalid relation.")
        if kind(node) not in KINDS:
            raise ValueError(f"Research node {node_id} has an invalid kind.")
        if kind(node) == "hypothesis":
            if node.get("verdict") not in VERDICTS:
                raise ValueError(f"Hypothesis {node_id} has an invalid verdict.")
            if node.get("result") is not None or parent is None:
                raise ValueError(f"Hypothesis {node_id} must be a non-delegated child claim.")
        dependencies = node.get("dependencies")
        if not isinstance(dependencies, list) or any(item not in found for item in dependencies):
            raise ValueError(f"Research node {node_id} has invalid dependencies.")
        origin = node.get("origin")
        if (not isinstance(origin, dict) or not isinstance(origin.get("type"), str)
                or not isinstance(origin.get("refs"), list)):
            raise ValueError(f"Research node {node_id} has invalid origin metadata.")
        result = node.get("result")
        if result is not None:
            if not isinstance(result, dict) or not isinstance(result.get("summary"), str):
                raise ValueError(f"Research node {node_id} has an invalid result.")
            if not isinstance(result.get("agent_key"), str):
                raise ValueError(f"Research node {node_id} has an invalid Agent key.")
            if not isinstance(result.get("report_path"), str) or not result["report_path"]:
                raise ValueError(f"Research node {node_id} has an invalid report path.")
    for link in links:
        if (not isinstance(link, dict) or link.get("source") not in found
                or link.get("target") not in found or link.get("type") not in LINK_TYPES):
            raise ValueError("Research tree contains an invalid cross-link.")
        target_is_hypothesis = kind(found[link["target"]]) == "hypothesis"
        if link["type"] in {"refutes", "inconclusive"} and not target_is_hypothesis:
            raise ValueError("refutes/inconclusive links must point at a hypothesis.")
        if target_is_hypothesis and link["type"] in EVIDENCE_LINKS and (
                kind(found[link["source"]]) != "question"):
            raise ValueError("Hypothesis evidence must come from a question node.")
    return found


def _children(tree: dict, node_id: str) -> list[str]:
    return [key for key, value in tree["nodes"].items() if value.get("parent") == node_id]


def _depth(tree: dict, node_id: str) -> int:
    depth, current, seen = 0, tree["nodes"][node_id], set()
    while current.get("parent") is not None:
        parent = current["parent"]
        if parent in seen:
            raise ValueError("Research tree contains a parent cycle.")
        seen.add(parent)
        current = tree["nodes"][parent]
        depth += 1
    return depth


def _blocked(tree: dict, node_id: str) -> bool:
    current = tree["nodes"][node_id]
    while current.get("parent") is not None:
        current = tree["nodes"][current["parent"]]
        if current["status"] in {"closed", "failed"}:
            return True
    return False


def _is_root_anchor(node: dict) -> bool:
    """Return whether a node is a top-level research-question container."""
    return node.get("parent") is None


def _dependency_satisfied(found: dict[str, dict], node_id: str) -> bool:
    """A live root anchors research; ordinary dependencies need delivered evidence."""
    node = found[node_id]
    return node.get("result") is not None or node["status"] == "completed" or (
        _is_root_anchor(node) and node["status"] == "active"
    )


FRONTIER_MODES = {"shallowest", "any_depth"}
MAX_PROPOSALS = 3
SUMMARY_LABELS = ("Result", "Evidence and limitations", "Further analysis")


def _label(pattern: str) -> str:
    """A Summary label at a line start, plain or emphasized, then ':' or '.' ("**Result.**")."""
    return rf"^[ \t]*[*_]{{0,2}}(?:{pattern})[*_]{{0,2}}[ \t]*[:.][*_]{{0,2}}"


_NEXT_LABEL = _label("|".join(map(re.escape, SUMMARY_LABELS)))


def summary_field(summary: str, label: str) -> str:
    """One field of an Expert's ## Summary; the single parser for all three labels."""
    match = re.search(rf"(?ims){_label(re.escape(label))}(.*?)(?={_NEXT_LABEL}|\Z)", summary or "")
    return match.group(1).strip() if match else ""


# An item number at a line start, or mid-line just after a sentence or clause ends
# ("... this year. 2. Can ...").
_ITEM_NUMBER = re.compile(r"(?:^[ \t]*|(?<=[.;:,?!)]\s))\(?(\d{1,2})[.)](?=\s)", re.MULTILINE)


def proposals_from_summary(summary: str) -> list[str]:
    """An Expert's proposed follow-up sub-questions: the numbered items of Further analysis.

    They are saved on the node's result and become nodes only when the Coordinator
    adds one with ``from_proposal`` (e.g. ``B1.2#1``); unadopted proposals simply lapse.
    Items are numbered ``1.``, ``1)`` or ``(1)``, one per line or run together on one
    line. An item may wrap onto following lines; it ends at the next item or a blank line.
    """
    text = summary_field(summary, "Further analysis")
    starts = []
    for match in _ITEM_NUMBER.finditer(text):
        if int(match.group(1)) == len(starts) + 1:  # 1, 2, 3 in order; other numbers are text
            starts.append(match)
    items = []
    for i, start in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        items.append(re.split(r"\n[ \t]*\n", text[start.end():end], maxsplit=1)[0])
    return [" ".join(item.split()) for item in items if item.strip()][:MAX_PROPOSALS]


def frontier(tree: dict) -> list[str]:
    """Return executable selected questions.

    Candidate nodes preserve the Coordinator's scientific idea space.  Only an
    explicit Select decision (``status=selected``) makes a node executable. The
    policy's ``frontier_mode`` (recorded on the tree) decides whether only the
    shallowest executable depth runs (breadth-first, the default) or every
    executable selected question does, so a deep follow-up need not wait.
    """
    found = nodes(tree)
    eligible = []
    for node_id, node in found.items():
        if (node["status"] != "selected" or node.get("result") is not None
                or kind(node) == "hypothesis" or _blocked(tree, node_id)):
            continue
        if _is_root_anchor(node):
            continue
        parent = node.get("parent")
        if parent is not None and not _dependency_satisfied(found, parent):
            continue
        if any(not _dependency_satisfied(found, dependency)
               for dependency in node["dependencies"]):
            continue
        eligible.append((_depth(tree, node_id), node_id))
    if tree.get("frontier_mode") == "any_depth":
        return [node_id for _, node_id in sorted(eligible)]
    shallowest = min((depth for depth, _ in eligible), default=None)
    return [node_id for depth, node_id in eligible if depth == shallowest]


def _next_id(tree: dict, parent_id: str) -> str:
    existing = set(tree["nodes"])
    if parent_id == "ROOT":
        index = 1
        while f"B{index}" in existing:
            index += 1
        return f"B{index}"
    index = 1
    while f"{parent_id}.{index}" in existing:
        index += 1
    return f"{parent_id}.{index}"


def _waits_for(found: dict[str, dict], node_id: str, other: str) -> bool:
    """Whether node_id already waits, directly or through its dependencies, for other."""
    pending, seen = [node_id], set()
    while pending:
        current = pending.pop()
        if current == other:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(found[current]["dependencies"])
    return False


def _proposal_ids(found: dict[str, dict]) -> str:
    return ", ".join(f"{key}#{number}" for key, item in found.items() for number in
                     range(1, len((item.get("result") or {}).get("proposals") or []) + 1)) or "none"


def _descendants(tree: dict, node_id: str) -> set[str]:
    result: set[str] = set()
    pending = _children(tree, node_id)
    while pending:
        child = pending.pop()
        if child in result:
            continue
        result.add(child)
        pending.extend(_children(tree, child))
    return result


def apply_changes(tree: dict, changes: list[dict]) -> tuple[dict, list[str], list[str]]:
    """Apply semantic edits to a copy; no model-generated code is evaluated."""
    result = json.loads(json.dumps(tree, ensure_ascii=False))
    found = result["nodes"]
    created: list[str] = []
    changed: list[str] = []
    for change in changes:
        action = change["action"]
        target = change["target"]
        if action == "add":
            question = str(change.get("question") or "").strip()
            if not question:
                raise ValueError("add needs a question.")
            if target != "ROOT" and target not in found:
                raise ValueError(f"Unknown parent node: {target}.")
            node_id = _next_id(result, target)
            parent = None if target == "ROOT" else target
            relation = str(change.get("relation") or ("independent" if parent is None else "dependency"))
            if relation not in RELATIONS:
                raise ValueError(f"Unknown node relation: {relation}.")
            dependencies = list(dict.fromkeys(change.get("dependencies") or []))
            if any(item not in found for item in dependencies):
                raise ValueError("add references an unknown dependency.")
            origin_refs = [str(item) for item in change.get("origin_refs") or [] if str(item).strip()]
            if change.get("from_proposal"):
                source, _, index = str(change["from_proposal"]).partition("#")
                offered = ((found.get(source) or {}).get("result") or {}).get("proposals") or []
                if not index.isdigit() or not 1 <= int(index) <= len(offered):
                    raise ValueError(f"Unknown Expert proposal: {change['from_proposal']}. "
                                     f"Valid proposal IDs: {_proposal_ids(found)}.")
                change = {**change, "origin_type": "expert-proposal",
                          "origin_refs": [change["from_proposal"]]}
                origin_refs = change["origin_refs"]
            elif (str(change.get("origin_type") or "").lower().replace("_", "-")
                  == "expert-proposal"):
                # Adoption is counted from from_proposal, so a free-text origin would go unrecorded.
                raise ValueError(
                    "Add a question that pursues an Expert proposal with from_proposal (e.g. "
                    f"B1.2#1). Valid proposal IDs: {_proposal_ids(found)}.")
            node_kind = str(change.get("kind") or "question")
            if node_kind not in KINDS:
                raise ValueError(f"Unknown node kind: {node_kind}.")
            if node_kind == "hypothesis":
                if parent is None:
                    raise ValueError("A hypothesis belongs under the question it would explain.")
                if kind(found[parent]) != "question":
                    raise ValueError("A hypothesis must be placed under a question.")
                status = "active"
            else:
                status = str(change.get("status") or ("active" if parent is None else "candidate"))
            if parent is None and status != "active":
                raise ValueError("A root research question must start as active.")
            found[node_id] = {
                "id": node_id,
                "parent": parent,
                "question": question,
                "why_it_matters": str(change.get("why_it_matters") or "").strip(),
                "relation": relation,
                "origin": {"type": str(change.get("origin_type") or "coordinator"),
                           "refs": origin_refs},
                "dependencies": dependencies,
                "status": status,
                "branch_key": str(change.get("branch_key") or (parent or node_id)),
                "expert_role": (str(change["expert_role"]) if change.get("expert_role") else None),
                "result": None,
                "close_reason": None,
            }
            if node_kind == "hypothesis":
                found[node_id]["kind"] = "hypothesis"
                found[node_id]["verdict"] = "unresolved"
            elif parent is not None and found[node_id]["status"] not in {"candidate", "selected"}:
                raise ValueError("A new subquestion must start as candidate or selected.")
            created.append(node_id)
            changed.append(node_id)
        elif action == "revise":
            if target not in found:
                raise ValueError(f"Unknown research node: {target}.")
            for key in ("question", "why_it_matters", "expert_role"):
                if key in change and change[key] is not None:
                    value = str(change[key]).strip()
                    if key == "question" and not value:
                        raise ValueError("revise question cannot be empty.")
                    found[target][key] = value or None
            changed.append(target)
        elif action == "set_status":
            if target not in found:
                raise ValueError(f"Unknown research node: {target}.")
            status = str(change.get("status") or "")
            if status not in {"candidate", "selected", "completed", "failed"}:
                raise ValueError("set_status accepts candidate, selected, completed or failed.")
            if kind(found[target]) == "hypothesis":
                raise ValueError("A hypothesis is a claim: use set_verdict or close, not set_status.")
            if _is_root_anchor(found[target]) and status in {"candidate", "selected", "completed"}:
                raise ValueError("The root is an active question anchor, not an assignment.")
            if status == "selected" and _blocked(result, target):
                raise ValueError("A question below a closed or failed branch cannot be selected.")
            if status == "completed" and found[target].get("result") is None:
                raise ValueError("A scientific question cannot be completed before a report is attached.")
            found[target]["status"] = status
            if status != "failed":
                found[target]["close_reason"] = None
            elif change.get("reason"):
                found[target]["close_reason"] = str(change["reason"]).strip()
            changed.append(target)
        elif action == "close":
            if target not in found:
                raise ValueError(f"Unknown research node: {target}.")
            reason = str(change.get("reason") or "").strip()
            if not reason:
                raise ValueError("close needs a scientific reason.")
            found[target]["status"] = "closed"
            found[target]["close_reason"] = reason
            changed.append(target)
        elif action == "reopen":
            if target not in found:
                raise ValueError(f"Unknown research node: {target}.")
            found[target]["status"] = (
                "active" if _is_root_anchor(found[target]) or kind(found[target]) == "hypothesis"
                else "candidate"
            )
            found[target]["close_reason"] = None
            changed.append(target)
        elif action == "set_verdict":
            if target not in found or kind(found[target]) != "hypothesis":
                raise ValueError("set_verdict needs an existing hypothesis node.")
            verdict = str(change.get("verdict") or "")
            if verdict not in VERDICTS:
                raise ValueError("set_verdict accepts supported, refuted or unresolved.")
            if not str(change.get("reason") or "").strip():
                raise ValueError("set_verdict needs the evidence-based reason.")
            found[target]["verdict"] = verdict
            changed.append(target)
        elif action == "decline":
            if target not in found or kind(found[target]) != "question":
                raise ValueError("decline needs an existing question node.")
            if found[target]["status"] != "candidate":
                raise ValueError("Only a candidate question can be declined.")
            reason = str(change.get("reason") or "").strip()
            if not reason:
                raise ValueError("decline needs the reason for not exploring now.")
            # A declined candidate stops returning as a live candidate; reopen revives it.
            found[target]["status"] = "closed"
            found[target]["close_reason"] = reason
            changed.append(target)
        elif action == "link":
            other = str(change.get("other") or "")
            link_type = str(change.get("link_type") or "related")
            if target not in found or other not in found or target == other:
                raise ValueError("link needs two different existing nodes.")
            if link_type not in LINK_TYPES:
                raise ValueError(f"Unknown link type: {link_type}.")
            if (link_type == "depends_on" and kind(found[other]) == "question"
                    and other not in found[target]["dependencies"]):
                # dependencies is what the frontier reads: the target now waits for other's result.
                if _waits_for(found, other, target):
                    raise ValueError(f"{target} depends_on {other} would create a dependency cycle.")
                found[target]["dependencies"].append(other)
            link = {"source": target, "target": other, "type": link_type,
                    "note": str(change.get("reason") or "").strip()}
            if link not in result["links"]:
                result["links"].append(link)
            changed.extend((target, other))
        elif action == "prune":
            if target not in found:
                raise ValueError(f"Unknown research node: {target}.")
            removed = _descendants(result, target) | {target}
            for node_id in removed:
                found.pop(node_id, None)
            result["links"] = [link for link in result["links"]
                               if link["source"] not in removed and link["target"] not in removed]
            changed.append(target)
        else:
            raise ValueError(f"Unknown tree action: {action}.")
    result["revision"] = int(result.get("revision", 0)) + (1 if changes else 0)
    nodes(result)
    for node_id in result["nodes"]:
        _depth(result, node_id)
    return result, created, list(dict.fromkeys(changed))


def projection(
    tree: dict, *, focus: list[str] | None = None, include_history: bool = False
) -> dict:
    """Return a compact decision view instead of the entire persisted document."""
    found = nodes(tree)
    frontier_nodes = frontier(tree)
    roots = [node_id for node_id, node in found.items() if node["parent"] is None]
    candidate_nodes = [node_id for node_id, node in found.items()
                       if node["status"] == "candidate" and kind(node) == "question"
                       and not _blocked(tree, node_id)]
    hypothesis_nodes = [node_id for node_id, node in found.items()
                        if kind(node) == "hypothesis" and node["status"] != "closed"]
    selected_nodes = [node_id for node_id, node in found.items()
                      if node["status"] == "selected" and not _blocked(tree, node_id)]
    visible = (
        set(found) if include_history else
        set(roots) | set(candidate_nodes) | set(selected_nodes)
        | set(frontier_nodes) | set(hypothesis_nodes) | set(focus or [])
    )
    for node_id in list(visible):
        current = found.get(node_id)
        if current is None:
            continue
        if current.get("parent"):
            parent = current["parent"]
            visible.add(parent)
            visible.update(_children(tree, parent))
        visible.update(current.get("dependencies", []))
    for link in tree["links"]:
        if link["source"] in visible or link["target"] in visible:
            visible.update((link["source"], link["target"]))
    compact = []
    for node_id in sorted(visible, key=lambda key: (_depth(tree, key), key)):
        node = found[node_id]
        item = {key: node.get(key) for key in (
            "id", "parent", "question", "why_it_matters", "relation", "origin",
            "dependencies", "branch_key", "expert_role", "close_reason")}
        item["status"] = node["status"]
        if kind(node) == "hypothesis":
            item["kind"] = "hypothesis"
            item["verdict"] = node["verdict"]
        if node.get("result"):
            item["result"] = node["result"]
        compact.append(item)
    view = {
        "schema_version": SCHEMA,
        "revision": tree["revision"],
        "roots": roots,
        "candidates": candidate_nodes,
        "selected": selected_nodes,
        "frontier": frontier_nodes,
        "nodes": compact,
        "links": [link for link in tree["links"]
                  if link["source"] in visible or link["target"] in visible],
        "counts": {status: sum(node["status"] == status for node in found.values())
                   for status in sorted(STATUSES)},
    }
    if hypothesis_nodes:
        view["hypotheses"] = hypothesis_nodes
    return view


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


class ResearchTree:
    """Task research tree: SQLite-canonical, with a derived JSON export.

    The public methods and the model-visible projection are unchanged. Each
    mutation also records decision events and delegation attempts in the same
    SQLite transaction (see ``tree_store``); those records are never returned
    to the model.
    """

    def __init__(self, path: Path, *, policy=None, policy_version: str | None = None):
        self.path = path
        self.store = TreeStore(path.with_suffix(".sqlite3"))
        self.policy = policy
        self.policy_version = policy_version or (policy.version if policy else POLICY_V0)

    def _read(self) -> dict:
        tree = self.store.load()
        if tree is None:
            # First open of a task created before the store existed: adopt its
            # JSON once; the next mutation makes SQLite canonical.
            tree = (json.loads(self.path.read_text(encoding="utf-8"))
                    if self.path.exists() else empty_tree())
        nodes(tree)
        tree["schema_version"] = SCHEMA  # v3 -> v4 is additive
        tree["frontier_mode"] = getattr(self.policy, "frontier_mode", "shallowest")
        # v3 originally treated top-level research questions as executable
        # candidates.  They are now durable question anchors: Expert work
        # starts at their selected subquestions.  Normalize in memory so live
        # tasks created before this correction remain usable; the next update
        # persists the normalized state atomically.
        for node in tree["nodes"].values():
            if _is_root_anchor(node) and node["status"] in {
                "candidate", "ready", "running"
            }:
                node["status"] = "active"
            elif not _is_root_anchor(node) and node["status"] in {"ready", "running"}:
                node["status"] = "selected"
        return tree

    def _save(self, tree: dict, *, events=(), attempts=()) -> None:
        self.store.commit(tree, events=list(events), attempts=list(attempts),
                          policy_version=self.policy_version)
        atomic_write_text(self.path, json.dumps(tree, ensure_ascii=False, indent=2))

    def _mutate(self, changes: list[dict]) -> tuple[dict, dict, list[str], list[str]]:
        """Apply one decision batch and log it; caller holds the lock."""
        before = self._read()
        if not changes:
            return before, before, [], []
        if self.policy is not None and not self.policy.hypotheses and any(
                c.get("kind") == "hypothesis" or c["action"] == "set_verdict" for c in changes):
            raise ValueError("Hypothesis nodes are not enabled by the active research policy.")
        after, created, changed = apply_changes(before, changes)
        self._save(after, events=events_for_changes(changes, created))
        return before, after, created, changed

    def read(self, *, include_history: bool = False) -> dict:
        with _locked(self.path):
            return projection(self._read(), include_history=include_history)

    def update(self, changes: list[dict], *, include_history: bool = False) -> dict:
        """Atomically apply one Coordinator decision batch."""
        with _locked(self.path):
            _, after, created, changed = self._mutate(changes)
            if not changes:
                return projection(after, include_history=include_history)
            return {
                "created": created,
                "projection": projection(
                    after, focus=changed, include_history=include_history
                ),
            }

    def attach_result(
        self, node_id: str, *, summary: str, agent_key: str, report_path: str,
        delegation_id: str | None = None, attempt_id: str | None = None,
        expert_role: str | None = None, output_refs: tuple[str, ...] = (),
        started_at: str | None = None,
    ) -> dict:
        """Attach an Expert delivery without making a scientific progress decision.

        The node keeps its latest result for the Coordinator view; every delivery
        is also appended as a separate attempt, so reruns are never lost.
        """
        summary = summary.strip()
        agent_key = agent_key.strip()
        report_path = report_path.strip()
        if not summary:
            raise ValueError("attach_result requires the report Summary.")
        if not agent_key:
            raise ValueError("attach_result requires the responsible Agent key.")
        if not report_path:
            raise ValueError("attach_result requires the report path.")
        with _locked(self.path):
            tree = self._read()
            found = nodes(tree)
            if node_id not in found:
                raise ValueError(f"Unknown research node: {node_id}.")
            if kind(found[node_id]) == "hypothesis":
                raise ValueError("A hypothesis cannot receive an Expert report.")
            proposals = proposals_from_summary(summary)
            found[node_id]["result"] = {
                "summary": summary, "agent_key": agent_key, "report_path": report_path,
                **({"proposals": proposals} if proposals else {}),
            }
            tree["revision"] = int(tree.get("revision", 0)) + 1
            attempt = NodeAttempt(
                node_id=node_id, agent_key=agent_key, summary=summary,
                report_path=report_path, delegation_id=delegation_id,
                expert_role=expert_role, output_refs=tuple(output_refs),
                started_at=started_at,
                **({"attempt_id": attempt_id} if attempt_id else {}),
            )
            self._save(tree, attempts=[attempt], events=[TreeEvent(
                "attempt_returned", node_id, None,
                {"attempt_id": attempt.attempt_id, "delegation_id": delegation_id})])
            return {
                "created": [],
                "projection": projection(tree, focus=[node_id]),
            }

    def view_text(self, changes: list[dict], *, full: bool = False,
                  last_seen_revision: int | None = None) -> tuple[str, int]:
        """Compact text view: delta after an edit, full view on request or revision gap."""
        from oceanx.research.tree_view import render_delta, render_full  # noqa: PLC0415
        with _locked(self.path):
            before, after, created, changed = self._mutate(changes)
            gap = last_seen_revision is None or last_seen_revision != before.get("revision")
            if full or gap or not changes:
                text = render_full(after, include_history=full)
            else:
                text = render_delta(after, changed, created=created)
            return text, int(after.get("revision", 0))

    def label(self, node_id: str, label: str, *, labeler: str, note: str | None = None,
              source: str = "human") -> None:
        with _locked(self.path):
            if node_id not in self._read()["nodes"]:
                raise ValueError(f"Unknown research node: {node_id}.")
            self.store.add_label(node_id, label, labeler=labeler, note=note, source=source)

    def document(self) -> dict:
        with _locked(self.path):
            return self._read()

    def has_node(self, node_id: str) -> bool:
        with _locked(self.path):
            return node_id in self._read()["nodes"]

    def record_delegation(self, delegation) -> None:
        """Log a Coordinator delegation; the tree document itself is unchanged."""
        with _locked(self.path):
            tree = self._read()
            if delegation.node_id not in tree["nodes"]:
                raise ValueError(f"Unknown research node: {delegation.node_id}.")
            on_frontier = delegation.node_id in frontier(tree)
            self.store.append_events([TreeEvent("delegated", delegation.node_id, None, {
                "delegation_id": delegation.delegation_id,
                "attempt_id": delegation.attempt_id,
                "binding": delegation.binding,
                "subagent_type": delegation.subagent_type,
                "on_frontier": on_frontier,
                "status": tree["nodes"][delegation.node_id]["status"],
            })], revision=int(tree.get("revision", 0)), policy_version=self.policy_version)

    def attempts(self, node_id: str | None = None) -> list[dict]:
        return self.store.attempts(node_id)

    def events(self, node_id: str | None = None) -> list[dict]:
        return self.store.events(node_id)


__all__ = ["ResearchTree", "apply_changes", "empty_tree", "frontier", "nodes", "projection"]
