"""Labels (auto, judge, human), review set, judge agreement, code cost, bounded view,
frontier mode, the fixed policy, and the project's library as the desktop and the CLI use it."""
import json
import re
from types import SimpleNamespace

import pytest

from oceanx.research.labels import auto_label, judge_agreement, judge_labels, review_set
from oceanx.research.memory import task_key
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
             "duration_seconds": 4.0, "tool_calls": {"weighted_mean": 2}},
            {"agent_thread_id": "physics", "state": "failed", "started_at": "2026-09-30T01:20",
             "duration_seconds": 1.0, "error": "KeyError: 'thetao'", "tool_calls": {"weighted_mean": 1}},
            {"agent_thread_id": "physics", "state": "succeeded", "started_at": "2026-09-30T03:00",
             "tool_calls": {"rate_per_day": 1}}]
    outcomes = compute_outcomes(doc, [], attempts, final_report="", model_calls=[], code_executions=runs,
                                library={"lessons_shown": ["L001"], "lessons_cited": [], "tools_mounted": []})
    outcome = outcomes["B1.1"]
    assert (outcome["code_runs"], outcome["code_seconds"]) == (2, 5.0)
    assert outcome["code_failures"] == ["KeyError: 'thetao'"]
    assert outcome["tool_calls"] == {"weighted_mean": 3}  # the helper calls of its own code runs
    # The task's record counts every run, also one that belongs to no node.
    assert outcomes["B1"]["library"] == {"lessons_shown": ["L001"], "lessons_cited": [], "tools_mounted": [],
                                         "tool_calls": {"rate_per_day": 1, "weighted_mean": 3}}
    assert "library" not in compute_outcomes(doc, [], attempts, final_report="", model_calls=[])["B1"]


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


def test_the_policy_is_v2_nested_unless_an_experiment_selects_another(tmp_path, monkeypatch):
    monkeypatch.delenv("OCEANX_RESEARCH_POLICY", raising=False)
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    assert project.policy().name == "v2-nested"
    # A choice an older desktop left in the project folder no longer changes anything.
    (tmp_path / ".oceanx" / "research").mkdir(parents=True)
    (tmp_path / ".oceanx" / "research" / "active_policy").write_text("v1-hypotheses")
    assert project.policy().name == "v2-nested"
    monkeypatch.setenv("OCEANX_RESEARCH_POLICY", "v0-coordinator-bfs")
    assert project.policy().name == "v0-coordinator-bfs"  # an experiment arm
    monkeypatch.setenv("OCEANX_RESEARCH_POLICY", "v9-invented")
    with pytest.raises(ValueError):
        project.policy()


CODE = "def area_mean(field, lat):\n    weights = np.cos(np.deg2rad(lat))\n    return (field * weights).sum() / weights.sum()\n"
TOOL = ('def area_mean(field, weights, *, dims):\n    """Mean of a field over named dimensions with explicit '
        'weights, in the field\'s units."""\n    return (field * weights).sum(dims) / weights.sum(dims)\n')
TOOL_REPLY = ("### tool: area_mean\nreplaces: area_mean\nrationale: Repeated.\n"
              f"```python\n{TOOL}```\n```python\nassert ao.area_mean is not None\n```\n")


def finished_project(tmp_path, tasks=4):
    """A project whose tasks each ran one question and wrote the same small function."""
    project, stores = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx")), []
    for index in range(tasks):
        root = tmp_path / "tasks" / f"t{index}"
        tree = ResearchTree(root / "agents" / "coordinator" / "research_tree.json")
        tree.update([{"action": "add", "target": "ROOT", "question": f"Why is basin {index} warm?"},
                     {"action": "add", "target": "B1", "question": "Heat budget?", "status": "selected"}])
        tree.attach_result("B1.1", summary=SUMMARY, agent_key="p", report_path="/r", attempt_id="a")
        record_task_outcomes(
            tree, final_report="## Summary\nB1.1 decides it.", model_calls=[],
            code_executions=[{"agent_thread_id": "p", "state": "succeeded", "tool_calls": {"weighted_mean": 1}}],
            library={"lessons_shown": [], "lessons_cited": [],
                     "tools_mounted": [tool["name"] for tool in project.tools.mounted()]})
        code = root / "agents" / "physics" / ".runtime" / "executions" / "e1" / "code" / "analysis.py"
        code.parent.mkdir(parents=True)
        code.write_text(CODE)
        stores.append(tree.store.path)
    return project, stores


def test_a_tool_step_that_failed_is_tried_again_without_another_lessons_review(tmp_path, monkeypatch):
    """Server review of 2026-10-10: the lessons were made, the reply with the tools could not be
    read, and nothing would have asked for tools again before another task finished."""
    from oceanx.research import toolbook
    monkeypatch.setattr(toolbook, "run_tool_test", lambda module, test: None)
    project, stores = finished_project(tmp_path)
    prompts = []

    def llm(tool_reply):
        return lambda prompt: prompts.append(prompt) or ("{}" if "<skill name=" in prompt else tool_reply)

    broken = json.dumps({"tools": [{"name": "area_mean", "code": TOOL}]})[:-9]
    first = project.update(stores, llm=llm(broken))
    assert first["lessons"]["new_tasks"] == 4 and first["tools"]["created"] == []
    assert [(r["round"], r["reply"]) for r in first["tools"]["rejected"]] == [(1, broken), (1, broken)]
    asked = len(prompts)  # six skills, and the tools twice
    second = project.update(stores, llm=llm(TOOL_REPLY))
    assert second["lessons"]["new_tasks"] == 0 and second["lessons"]["skills_reviewed"] == 0
    assert second["tools"]["created"] == ["area_mean"] and second["tools"]["new_tasks"] == 4
    assert (asked, len(prompts)) == (8, 9) and "<skill name=" not in prompts[-1]


def test_the_periodic_update_counts_calls_and_lets_the_meta_agent_revise_the_library(tmp_path, monkeypatch):
    from oceanx.research import toolbook
    monkeypatch.setattr(toolbook, "run_tool_test", lambda module, test: None)  # the sandbox run
    project, stores = finished_project(tmp_path)
    keys = [task_key(store) for store in stores]
    assert project.version() is None and project.skills(research=True)  # nothing learned yet
    # Without a model: records and call counts only.
    result = project.update(stores)
    assert result["consolidation"]["digested"] == 4 and set(result) == {"consolidation", "tool_usage"}
    assert result["tool_usage"] == {"tasks_counted": 4, "removed": []}
    used = next(tool for tool in project.overview()["tools"] if tool["name"] == "weighted_mean")
    assert used["stats"] == {"tasks": 4, "tasks_called": 4, "calls": 4, "idle": 0}
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        skill = re.search(r'<skill name="([^"]+)">', prompt)
        if skill is None:  # the tool-writing prompt
            return TOOL_REPLY
        if skill.group(1) != "research-trajectory-planning":
            return "{}"
        return json.dumps({"add": [{"text": "Ask the heat budget before the eddies.",
                                    "applies_when": "Both are open.", "supporting": keys[:3],
                                    "rationale": "B1.1 decided every task."}]})

    reviewed = []
    result = project.update(stores, llm=llm, reviewer=lambda prompt: reviewed.append(prompt) or json.dumps(
        {"verdict": "accept", "reason": "Fine."}))
    assert result["lessons"]["changes"] == [{"lesson": "L001", "change": "added"}]
    assert result["tools"]["created"] == ["area_mean"] and len(reviewed) == 1
    assert len(prompts) == 7  # six skills with a lessons region, one tool-writing call
    # Both are in force for the next task, and the version names both.
    version = project.version()
    assert re.fullmatch(r"lessons@[0-9a-f]{12}\+tools@[0-9a-f]{12}", version)
    skills = project.skills(research=True)
    assert "(L001)" in skills["research-trajectory-planning"]
    assert "- `ao.area_mean(field, weights, *, dims)`: Mean of a field" in skills["xarray-array-ops"]
    assert "def area_mean(field, weights, *, dims)" in project.tools.module_source()
    script = "xarray-array-ops/scripts/oceanx_array_ops.py"
    assert set(skills) == {"xarray-array-ops", script, *project.lessons.regions()}
    assert all("oceanx:" not in text for text in skills.values())
    # The script the skill links to holds the learned function too, without the call counter.
    assert "def area_mean(field, weights, *, dims)" in skills[script] and "_oceanx_count_calls" not in skills[script]
    # A bounded request gets the tools but not the lessons, which come from research trees.
    bounded = project.skills(research=False)
    assert "(L001)" not in bounded["research-trajectory-planning"] and "ao.area_mean" in bounded["xarray-array-ops"]
    # Nothing finished since: the next update asks no model.
    quiet = project.update(stores, llm=lambda prompt: pytest.fail("the model must not be asked"))
    assert quiet["lessons"]["new_tasks"] == 0 and quiet["tools"]["new_tasks"] == 0

    overview = project.overview()
    assert overview["version"] == version and len(overview["skills"]) == 6 and len(overview["tools"]) == 9
    assert [change["tool"] for change in overview["tool_changes"]] == ["area_mean"]
    # The owner marks either kind right or wrong.
    project.mark("lesson", "L001", "wrong")
    project.mark("tool", "area_mean", "wrong")
    assert project.version() != version and project.lessons.active() == []
    assert "def area_mean(field, weights, *, dims)" not in project.tools.module_source()
    with pytest.raises(ValueError, match="kind must be lesson or tool"):
        project.mark("policy", "v2-nested", "right")


def test_library_protocol_requests():
    from pydantic import ValidationError

    from oceanx.protocol.v2.models import REQUEST_ADAPTER
    base = {"protocol_version": 2, "request_id": "req_1",
            "context": {"client_id": "c", "session_id": "s", "workspace_id": "ws"}}
    assert REQUEST_ADAPTER.validate_python(
        {**base, "type": "research.library.update", "payload": {}}).payload.review is False
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({**base, "type": "research.library.update", "payload": {"propose": True}})
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({**base, "type": "research.library.mark", "payload": {"kind": "tool"}})
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({**base, "type": "research.review.get", "payload": {}})
