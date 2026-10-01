"""Labels (auto, judge, human), review set, judge agreement, code cost, bounded view,
frontier mode, stale lessons, project policy choice and review protocol requests."""
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from oceanx.research.labels import auto_label, judge_agreement, judge_labels, review_set
from oceanx.research.lessons import LessonBook
from oceanx.research.outcomes import compute_outcomes, record_task_outcomes
from oceanx.research.review import ProjectResearch
from oceanx.research.tree import ResearchTree, frontier
from oceanx.research.tree_view import render_full

SUMMARY = "Result: Flux explains onset.\nEvidence and limitations: One year.\nFurther analysis: None"


def tree_with_results(tmp_path, name="t"):
    tree = ResearchTree(tmp_path / name / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": "Why warm?"},
        {"action": "add", "target": "B1", "question": "Budget?", "status": "selected"},
        {"action": "add", "target": "B1", "question": "Eddies?", "status": "selected"},
        {"action": "add", "target": "B1.1", "question": "Deep follow-up?", "status": "selected"},
    ])
    for node, attempt in (("B1.1", "a1"), ("B1.2", "a2")):
        tree.attach_result(node, summary=SUMMARY, agent_key="physics", report_path=f"/{node}.md",
                           attempt_id=attempt, started_at="2026-09-30T01:00:00")
    tree.update([{"action": "set_status", "target": "B1.2", "status": "completed"}])
    return tree


def test_label_sources_rank_human_over_judge_over_auto(tmp_path):
    tree = tree_with_results(tmp_path)
    tree.label("B1.1", "misleading-or-wasteful", labeler="rules", source="auto")
    tree.label("B1.1", "informative-but-not-decisive", labeler="judge", source="judge")
    assert tree.store.labels()["B1.1"]["source"] == "judge"
    tree.label("B1.1", "decision-changing", labeler="owner")
    tree.label("B1.1", "misleading-or-wasteful", labeler="rules", source="auto")  # later auto
    effective = tree.store.labels()["B1.1"]
    assert (effective["label"], effective["source"]) == ("decision-changing", "human")
    assert set(tree.store.labels(sources=("auto",))) == {"B1.1"}


def test_auto_labels_follow_logged_outcomes(tmp_path):
    base = {"kind": "question", "attempts": 1}
    assert auto_label({**base, "cited_in_final": True, "spawned_children": 1}) == "decision-changing"
    assert auto_label({**base, "cited_in_final": True}) == "informative-but-not-decisive"
    assert auto_label({**base, "final_status": "closed"}) == "misleading-or-wasteful"
    assert auto_label({**base, "final_status": "selected"}) is None
    assert auto_label({"kind": "question", "attempts": 0, "cited_in_final": True}) is None
    # A node whose follow-ups were pursued moved the tree, wherever they were placed.
    assert auto_label({**base, "cited_in_final": True, "follow_ups_adopted": 1}) == "decision-changing"
    assert auto_label({**base, "final_status": "completed", "follow_ups_adopted": 2}) is None
    tree = tree_with_results(tmp_path)
    record_task_outcomes(tree, final_report="## Summary\nB1.1 explains it.", model_calls=[])
    labels = tree.store.labels(sources=("auto",))
    assert labels["B1.1"]["label"] == "decision-changing"  # cited and spawned B1.1.1
    assert labels["B1.2"]["label"] == "misleading-or-wasteful"  # completed, never cited


def test_the_root_is_never_labelled(tmp_path):
    tree = tree_with_results(tmp_path)
    tree.attach_result("B1", summary="Flux explains it.", agent_key="coordinator", report_path="/final.md")
    record_task_outcomes(tree, final_report="## Summary\nB1 is answered by B1.1.", model_calls=[])
    assert tree.store.outcomes()["B1"]["cited_in_final"] and "B1" not in tree.store.labels()
    judged = judge_labels(tree, lambda prompt: json.dumps(
        {"label": "decision-changing", "reason": "It is the answer."}), final_report="x")
    assert set(judged) == {"B1.1", "B1.2"}  # the root holds the answer; it is not a branch


def test_review_set_is_small_and_judge_disagreement_is_surfaced(tmp_path):
    tree = tree_with_results(tmp_path)
    record_task_outcomes(tree, final_report="## Summary\nnothing cited", model_calls=[])
    picked = {item["node_id"] for item in review_set(tree)}
    assert picked == {"B1.1", "B1.2"}  # both top-level branches
    judged = judge_labels(tree, lambda prompt: json.dumps(
        {"label": "decision-changing", "reason": "Budget decides it."}), final_report="x")
    assert set(judged) == {"B1.1", "B1.2"}
    item = next(i for i in review_set(tree) if i["node_id"] == "B1.2")
    assert (item["suggested"], item["suggested_source"]) == ("decision-changing", "judge")
    tree.label("B1.1", "decision-changing", labeler="owner")
    tree.label("B1.2", "misleading-or-wasteful", labeler="owner")
    agreement = judge_agreement([tree.store.path])
    assert (agreement["n"], agreement["agreement"]) == (2, 0.5)
    assert agreement["confusion_human_by_judge"]["misleading-or-wasteful"]["decision-changing"] == 1


def test_code_runs_are_attributed_to_the_attempt_window():
    doc = {"schema_version": "oceanx-research-tree/v4", "revision": 1, "links": [], "nodes": {
        "B1": {"id": "B1", "parent": None, "question": "Q", "why_it_matters": "", "relation": "independent",
               "dependencies": [], "origin": {"type": "c", "refs": []}, "status": "active", "result": None},
        "B1.1": {"id": "B1.1", "parent": "B1", "question": "q", "why_it_matters": "",
                 "relation": "dependency", "dependencies": [], "origin": {"type": "c", "refs": []},
                 "status": "completed", "result": None}}}
    attempts = [{"node_id": "B1.1", "attempt_id": "a", "agent_key": "physics",
                 "report_path": "/r", "started_at": "2026-09-30T01:00", "ended_at": "2026-09-30T02:00"}]
    runs = [{"agent_thread_id": "physics", "state": "succeeded", "started_at": "2026-09-30T01:10",
             "duration_seconds": 4.0},
            {"agent_thread_id": "physics", "state": "failed", "started_at": "2026-09-30T01:20",
             "duration_seconds": 1.0, "error": "KeyError: 'thetao'"},
            {"agent_thread_id": "physics", "state": "succeeded", "started_at": "2026-09-30T03:00"}]
    outcome = compute_outcomes(doc, [], attempts, final_report="", model_calls=[],
                               code_executions=runs)["B1.1"]
    assert (outcome["code_runs"], outcome["code_seconds"]) == (2, 5.0)
    assert outcome["code_failures"] == ["KeyError: 'thetao'"]


def test_view_is_bounded_but_full_view_lists_everything(tmp_path):
    tree = ResearchTree(tmp_path / "big" / "research_tree.json")
    tree.update([{"action": "add", "target": "ROOT", "question": "Root?"}] + [
        {"action": "add", "target": "B1", "question": f"Branch {i}?"} for i in range(30)])
    for i in range(1, 29):
        tree.update([{"action": "close", "target": f"B1.{i}", "reason": "not useful"}])
    doc = tree.document()
    text = render_full(doc, max_nodes=10)
    assert "B1.29" in text and "B1.30" in text  # live candidates always shown
    assert "finished nodes not shown" in text
    assert "not shown" not in render_full(doc, include_history=True)


def test_any_depth_frontier_lets_deep_follow_ups_run(tmp_path):
    tree = tree_with_results(tmp_path)  # B1.1 answered; its child B1.1.1 is selected
    tree.update([{"action": "add", "target": "B1", "question": "Sibling?", "status": "selected"}])
    doc = tree.document()
    assert "B1.1.1" not in frontier(doc)
    assert "B1.1.1" in frontier({**doc, "frontier_mode": "any_depth"})


def test_stale_lessons_return_to_the_owner(tmp_path):
    from oceanx.research.memory import ResearchMemory
    book = LessonBook(ResearchMemory(tmp_path / "research"))
    old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    book._save([{"id": "L001", "role": "coordinator", "text": "Test rivals first.",
                 "applies_when": "Two drivers.", "evidence": {"supporting": [], "counter": []},
                 "status": "active", "approved_by": "o", "approved_at": old}])
    [proposal] = book.review_stale()
    assert book.review_stale() == []  # not duplicated while pending
    book.decide(proposal["id"], approve=False, reviewer="owner")  # keep it
    assert book.active()[0]["reviewed_at"] and book.review_stale() == []


def test_project_policy_choice_is_a_file_the_owner_sets(tmp_path, monkeypatch):
    monkeypatch.delenv("OCEANX_RESEARCH_POLICY", raising=False)
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    assert project.policy().name == "v0-coordinator-bfs"
    project.activate_policy("v1-hypotheses")
    overview = project.policies()
    assert (overview["active"], overview["project_choice"]) == ("v1-hypotheses", "v1-hypotheses")
    assert {p["name"] for p in overview["available"]} == {
        "v0-coordinator-bfs", "v1-hypotheses", "v2-nested"}
    with pytest.raises(ValueError):
        project.activate_policy("v9-invented")
    monkeypatch.setenv("OCEANX_RESEARCH_POLICY", "v0-coordinator-bfs")
    assert project.policy().name == "v0-coordinator-bfs"  # the environment overrides


def test_review_protocol_requests():
    from pydantic import ValidationError

    from oceanx.protocol.v2.models import REQUEST_ADAPTER
    base = {"protocol_version": 2, "request_id": "req_1",
            "context": {"client_id": "c", "session_id": "s", "workspace_id": "ws"}}
    REQUEST_ADAPTER.validate_python({**base, "type": "research.labels.set", "payload": {
        "task_id": "t", "node_id": "B1.2", "label": "decision-changing"}})
    REQUEST_ADAPTER.validate_python({**base, "type": "research.policies.activate",
                                     "payload": {"name": "v1-hypotheses"}})
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({**base, "type": "research.policies.activate",
                                         "payload": {}})
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({**base, "type": "research.labels.set", "payload": {
            "task_id": "t", "node_id": "../B1", "label": "decision-changing"}})
