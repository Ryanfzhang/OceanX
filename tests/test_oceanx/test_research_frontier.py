"""The research tree derives scientific readiness without scheduling agents."""

from oceanx.research.tree import ResearchTree


def _attach(tree, key):
    tree.attach_result(
        key,
        summary="Evidence supports a partial answer; alternatives remain.",
        agent_key=f"agent-{key.lower()}",
        report_path=f"/agents/{key.lower()}/report.md",
    )


def test_frontier_is_breadth_first_and_result_driven(tmp_path):
    tree = ResearchTree(tmp_path / "analysis" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?", "status": "selected"},
        {"action": "add", "target": "B1", "question": "Transport?", "status": "selected"},
        {"action": "add", "target": "B1.1", "question": "Why shallow?", "status": "selected"},
        {"action": "add", "target": "B1.1.1", "question": "What changes at depth?",
         "status": "selected"},
        {"action": "add", "target": "B1.2", "question": "Which pathway?", "status": "selected"},
    ])
    assert tree.update([])["frontier"] == ["B1.1", "B1.2"]
    _attach(tree, "B1.1")
    assert tree.update([])["frontier"] == ["B1.2"]
    _attach(tree, "B1.2")
    assert tree.update([])["frontier"] == ["B1.1.1", "B1.2.1"]
    _attach(tree, "B1.1.1")
    assert tree.update([])["frontier"] == ["B1.2.1"]
    _attach(tree, "B1.2.1")
    assert tree.update([])["frontier"] == ["B1.1.1.1"]


def test_candidates_are_visible_but_never_executable_until_selected(tmp_path):
    tree = ResearchTree(tmp_path / "analysis" / "research_tree.json")
    result = tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Heating?"},
        {"action": "add", "target": "B1", "question": "Transport?"},
        {"action": "add", "target": "B1", "question": "Mixing?"},
    ])["projection"]
    assert result["candidates"] == ["B1.1", "B1.2", "B1.3"]
    assert result["frontier"] == []

    tree.update([
        {"action": "set_status", "target": "B1.1", "status": "selected"},
        {"action": "set_status", "target": "B1.3", "status": "selected"},
    ])
    projection = tree.update([])
    assert projection["candidates"] == ["B1.2"]
    assert projection["selected"] == ["B1.1", "B1.3"]
    assert projection["frontier"] == ["B1.1", "B1.3"]


def test_selected_but_dependency_blocked_nodes_remain_visible(tmp_path):
    tree = ResearchTree(tmp_path / "analysis" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Characterize it",
         "status": "selected"},
        {"action": "add", "target": "B1.1", "question": "Explain it",
         "status": "selected"},
    ])
    view = tree.update([])
    assert view["selected"] == ["B1.1", "B1.1.1"]
    assert view["frontier"] == ["B1.1"]
    assert {node["id"] for node in view["nodes"]} >= {"B1", "B1.1", "B1.1.1"}


def test_result_can_expand_depth_and_ancestor_breadth_before_selection(tmp_path):
    tree = ResearchTree(tmp_path / "analysis" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains warming?"},
        {"action": "add", "target": "B1", "question": "Characterize the anomaly",
         "status": "selected"},
    ])
    _attach(tree, "B1.1")
    result = tree.update([
        {"action": "add", "target": "B1.1", "question": "Why is it surface confined?",
         "origin_type": "new_evidence", "origin_refs": ["B1.1"]},
        {"action": "add", "target": "B1", "question": "Is transport important?",
         "relation": "alternative", "origin_type": "new_evidence", "origin_refs": ["B1.1"]},
        {"action": "add", "target": "B1", "question": "Does freshwater stratify it?",
         "relation": "alternative", "origin_type": "new_evidence", "origin_refs": ["B1.1"]},
    ])["projection"]
    assert result["candidates"] == ["B1.1.1", "B1.2", "B1.3"]
    assert result["frontier"] == []

    tree.update([{"action": "set_status", "target": "B1.2", "status": "selected"}])
    assert tree.update([])["frontier"] == ["B1.2"]


def test_tree_has_no_agent_lifecycle_api(tmp_path):
    tree = ResearchTree(tmp_path / "analysis" / "research_tree.json")
    for name in ("owner", "mark_executed", "require_question"):
        assert not hasattr(tree, name)
