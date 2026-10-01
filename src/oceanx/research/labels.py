"""Node labels without asking the owner to rate every sub-question.

Three sources, in increasing trust (tree_store.LABEL_SOURCES):

* ``auto``  — rules over the task log (below), written when a task finishes;
* ``judge`` — a model from another family answers a leave-one-out question
  ("would the conclusion change without this branch?");
* ``human`` — the owner, asked only about a small review set (top-level branches,
  cited nodes, and nodes where auto and judge disagree).

Lesson mining uses the effective label (human > judge > auto). Whether the judge
can stand in for the owner is measured by ``judge_agreement`` on human-labelled
nodes. Policy acceptance uses no node labels at all (one A/B judgement per case).
"""
from __future__ import annotations

from collections.abc import Callable

from oceanx.research.llm import parse_json_object
from oceanx.research.tree import kind
from oceanx.research.tree_store import LABELS, TreeStore

JUDGE_PROMPT = """\
An ocean-science research agent explored several sub-questions and wrote a final answer.
Would the final scientific conclusion be materially different if this sub-question had
never been explored? Reply with JSON only: {{"label": "decision-changing" |
"informative-but-not-decisive" | "misleading-or-wasteful", "reason": "<one sentence>"}}.

Research question: {root}
Final answer summary: {final}
Sub-question: {question}
Its result: {result}
"""


def auto_label(outcome: dict) -> str | None:
    """Rules over logged outcomes; ``None`` when the log is not informative."""
    if outcome.get("kind") != "question" or not outcome.get("attempts") or outcome.get("is_root"):
        return None  # the root holds the final answer, not a branch that could be left out
    # An adopted follow-up moved the tree even when it was placed elsewhere than under this node.
    moved = (outcome.get("hypothesis_evidence") or outcome.get("reopened")
             or outcome.get("conflict_links") or outcome.get("spawned_children")
             or outcome.get("follow_ups_adopted"))
    if outcome.get("cited_in_final"):
        return "decision-changing" if moved else "informative-but-not-decisive"
    if not moved and outcome.get("final_status") in {"closed", "failed", "completed"}:
        return "misleading-or-wasteful"
    return None


def apply_auto_labels(tree, outcomes: dict[str, dict]) -> dict[str, str]:
    labels = {n: label for n, o in outcomes.items() if (label := auto_label(o))}
    for node_id, label in labels.items():
        tree.store.add_label(node_id, label, labeler="log-rules", source="auto")
    return labels


def review_set(tree, *, closed_sample: int = 2) -> list[dict]:
    """The few nodes worth a human look: top-level branches, cited nodes, disagreements."""
    document = tree.document()
    outcomes = tree.store.outcomes()
    by_source = {source: tree.store.labels(sources=(source,)) for source in ("auto", "judge")}
    effective, human = tree.store.labels(), tree.store.labels(sources=("human",))
    picked: list[str] = []
    for node_id, node in sorted(document["nodes"].items()):
        outcome = outcomes.get(node_id, {})
        if kind(node) != "question" or not outcome.get("attempts") or node.get("parent") is None:
            continue
        auto, judge = (by_source[s].get(node_id, {}).get("label") for s in ("auto", "judge"))
        top_level = document["nodes"][node["parent"]].get("parent") is None
        if top_level or outcome.get("cited_in_final") or (auto and judge and auto != judge):
            picked.append(node_id)
    closed = [n for n, node in sorted(document["nodes"].items())
              if node["status"] in {"closed", "failed"} and n not in picked
              and outcomes.get(n, {}).get("attempts")]
    picked += closed[:closed_sample]
    return [{"node_id": n, "question": document["nodes"][n]["question"],
             "status": document["nodes"][n]["status"],
             "result": ((document["nodes"][n].get("result") or {}).get("summary") or "")[:400],
             "suggested": effective.get(n, {}).get("label"),
             "suggested_source": effective.get(n, {}).get("source"),
             "human": human.get(n, {}).get("label")} for n in picked]


def judge_labels(tree, llm: Callable[[str], str], *, final_report: str) -> dict[str, str]:
    """Leave-one-out judgement for executed nodes without a human label."""
    document, human = tree.document(), tree.store.labels(sources=("human",))
    root = next((n for n in document["nodes"].values() if n.get("parent") is None), {})
    judged: dict[str, str] = {}
    for node_id, outcome in tree.store.outcomes().items():
        node = document["nodes"].get(node_id)
        if (node is None or node.get("parent") is None or node_id in human
                or not outcome.get("attempts")):
            continue
        reply = parse_json_object(llm(JUDGE_PROMPT.format(
            root=root.get("question", ""), final=final_report[:1500],
            question=node["question"], result=((node.get("result") or {}).get("summary") or "")[:800])))
        label = reply.get("label")
        try:
            tree.store.add_label(node_id, label, labeler="model-judge", source="judge",
                                 note=str(reply.get("reason") or "")[:300])
        except ValueError:
            continue  # an invalid label from the judge is simply ignored
        judged[node_id] = label
    return judged


def judge_agreement(store_paths) -> dict:
    """How often the model judge matches the owner, on nodes both labelled (RQ4)."""
    pairs = []
    for path in store_paths:
        store = TreeStore(path)
        human, judge = store.labels(sources=("human",)), store.labels(sources=("judge",))
        pairs += [(human[n]["label"], judge[n]["label"]) for n in human.keys() & judge.keys()]
    confusion = {h: {j: sum(p == (h, j) for p in pairs) for j in LABELS} for h in LABELS}
    return {"n": len(pairs), "agreement": sum(h == j for h, j in pairs) / len(pairs) if pairs else None,
            "confusion_human_by_judge": confusion}


__all__ = ["apply_auto_labels", "auto_label", "judge_agreement", "judge_labels", "review_set"]
