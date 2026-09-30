import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from oceanx.research.services import report_summary
from oceanx.research.tree import ResearchTree
from oceanx.research.tree_tools import research_tree_tool


@pytest.fixture
def tree(tmp_path):
    return ResearchTree(tmp_path / "analysis" / "research_tree.json")


def test_tree_stores_only_scientific_questions_and_evidence(tree):
    result = tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains the warming?"},
        {"action": "add", "target": "B1", "question": "Is warming surface-confined?"},
        {"action": "add", "target": "B1", "question": "What explains the deeper signal?"},
    ])
    assert result["created"] == ["B1", "B1.1", "B1.2"]
    assert result["projection"]["candidates"] == ["B1.1", "B1.2"]
    assert result["projection"]["frontier"] == []
    stored = json.loads(tree.path.read_text())
    assert stored["nodes"]["B1"]["status"] == "active"
    assert stored["nodes"]["B1.1"]["question"] == "Is warming surface-confined?"
    assert stored["nodes"]["B1.1"]["parent"] == "B1"
    serialized = tree.path.read_text()
    assert "task_id" not in serialized
    assert "executed" not in serialized
    assert "transcript" not in serialized


def test_result_attachment_reuses_summary_without_deciding_progress(tree, tmp_path):
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains the warming?"},
        {"action": "add", "target": "B1", "question": "Surface warming?", "status": "selected"},
        {"action": "add", "target": "B1.1", "question": "Transport contribution?",
         "status": "selected"},
        {"action": "add", "target": "B1", "question": "Mixing contribution?"},
    ])
    text = "# Structure\n\n## Summary\nShallow warming; transport unresolved.\n\n## Evidence\nLarge array"
    summary = report_summary(text)
    result = tree.attach_result(
        "B1.1", summary=summary, agent_key="ocean-process-a1b2",
        report_path="/agents/a/report.md",
    )
    assert result["created"] == []
    assert result["projection"]["frontier"] == ["B1.1.1"]
    stored = json.loads(tree.path.read_text())
    assert stored["nodes"]["B1.1"]["status"] == "selected"
    assert stored["nodes"]["B1.1"]["result"] == {
        "summary": summary, "agent_key": "ocean-process-a1b2",
        "report_path": "/agents/a/report.md"}
    assert "Large array" not in tree.path.read_text()
    tree.update([{"action": "set_status", "target": "B1.2", "status": "selected"}])
    assert tree.update([])["frontier"] == ["B1.2"]


@pytest.mark.parametrize("change", [
    {"action": "add", "target": "missing", "question": "new"},
    {"action": "add", "target": "ROOT", "question": ""},
    {"action": "revise", "target": "missing", "question": "new"},
    {"action": "prune", "target": "ROOT"},
    {"action": "invent", "target": "B1"},
])
def test_invalid_update_is_atomic(tree, change):
    tree.update([{"action": "add", "target": "ROOT", "question": "original"}])
    before = tree.read()
    with pytest.raises(ValueError):
        tree.update([change])
    assert tree.read() == before


def test_close_retains_questions_but_removes_branch_from_frontier(tree):
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?", "status": "selected"},
        {"action": "add", "target": "B1.1", "question": "Why shallow?", "status": "selected"},
        {"action": "add", "target": "B1", "question": "Transport?", "status": "selected"},
        {"action": "close", "target": "B1.1", "reason": "Evidence is already sufficient."},
    ])
    assert tree.update([])["frontier"] == ["B1.2"]
    assert "B1.1.1" in json.loads(tree.path.read_text())["nodes"]
    tree.update([{"action": "reopen", "target": "B1.1"}])
    tree.update([{"action": "set_status", "target": "B1.1", "status": "selected"}])
    assert tree.update([])["frontier"] == ["B1.1", "B1.2"]


def test_concurrent_edits_are_atomic(tree):
    def insert(i):
        ResearchTree(tree.path).update([{"action": "add", "target": "B1", "question": f"question {i}"}])
    tree.update([{"action": "add", "target": "ROOT", "question": "root question"}])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(insert, range(6)))
    assert len(json.loads(tree.path.read_text())["nodes"]) == 7


def test_model_tool_is_tree_only(tree):
    tool = research_tree_tool(tree)
    assert set(tool.args_schema.model_json_schema()["properties"]) == {"changes", "view"}
    result = asyncio.run(tool.coroutine(changes=[], view="decision"))
    assert result.startswith("research tree revision") and "frontier: none" in result
    assert "Never store methods" in tool.description
    assert "native task tool" in tool.description


def test_full_view_retains_completed_branches_for_final_report(tree):
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?", "status": "selected"},
    ])
    tree.attach_result(
        "B1.1", summary="Heating is insufficient.", agent_key="ocean-a",
        report_path="/agents/ocean-a/report.md",
    )
    tree.update([{"action": "set_status", "target": "B1.1", "status": "completed"}])

    assert [node["id"] for node in tree.read()["nodes"]] == ["B1"]
    full = tree.read(include_history=True)
    assert [node["id"] for node in full["nodes"]] == ["B1", "B1.1"]
    assert full["nodes"][1]["result"]["summary"] == "Heating is insufficient."


def test_only_coordinator_decision_can_complete_a_reported_question(tree):
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?", "status": "selected"},
    ])
    tree.attach_result(
        "B1.1", summary="Result: partial\nFurther analysis: test transport",
        agent_key="ocean-a", report_path="/agents/ocean-a/report.md",
    )
    stored = json.loads(tree.path.read_text())
    assert stored["nodes"]["B1.1"]["status"] == "selected"
    assert tree.read()["frontier"] == []

    tree.update([{"action": "set_status", "target": "B1.1", "status": "completed"}])
    assert json.loads(tree.path.read_text())["nodes"]["B1.1"]["status"] == "completed"


def test_question_cannot_complete_without_an_attached_report(tree):
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?", "status": "selected"},
    ])
    with pytest.raises(ValueError, match="before a report is attached"):
        tree.update([{"action": "set_status", "target": "B1.1", "status": "completed"}])


def test_legacy_ready_nodes_are_normalized_without_exposing_legacy_statuses(tree):
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?", "status": "selected"},
    ])
    stored = json.loads(tree.path.read_text())
    stored["nodes"]["B1"]["status"] = "candidate"
    stored["nodes"]["B1.1"]["status"] = "ready"
    tree.path.write_text(json.dumps(stored), encoding="utf-8")

    view = tree.read()
    statuses = {node["id"]: node["status"] for node in view["nodes"]}
    assert statuses == {"B1": "active", "B1.1": "selected"}
    assert view["frontier"] == ["B1.1"]
    assert "ready" not in view["counts"]
    assert "running" not in view["counts"]
