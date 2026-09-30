"""Bounded research-policy loop: policies, hypotheses, Expert proposals, the compact
view, structured delegation, outcomes, frozen acceptance and paired-run evaluation.
Graph-level integration (DeepAgents/Agent Server) is exercised by the integration tests.
"""
import asyncio
import json
import shutil

import pytest
import yaml

from oceanx.research import acceptance
from oceanx.research.delegation import (
    StructuredDelegationMiddleware, current_delegation, resolve_delegation)
from oceanx.research.outcomes import record_task_outcomes
from oceanx.research.paired_runs import evaluate_pairs
from oceanx.research.policy import (
    BUNDLED_POLICIES, find_policy, load_policy, validate_policy_document)
from oceanx.research.tree import (
    ResearchTree, apply_changes, empty_tree, frontier, proposals_from_summary)
from oceanx.research.tree_tools import research_tree_tool
from oceanx.research.tree_view import render_delta, render_full

SUMMARY = ("Result: Surface heat flux explains onset.\nEvidence and limitations: One year only; "
           "budget residual 20%. Eddy terms unresolved.\nFurther analysis: Test eddy advection.")
PROPOSING = ("Result: Flux closes 80% of the budget.\nEvidence and limitations: One year only.\n"
             "Further analysis:\n1. Do eddies converge heat in Aug-Sep? — the residual.\n"
             "2. Is the mixed-layer depth biased? — it scales the budget.\n"
             "3. Does 2019 repeat the pattern? — one year is thin.\n4. Extra item.")


def policy(name):
    return load_policy(find_policy(name))


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    path = tmp_path / "acceptance.yaml"
    data = yaml.safe_load((BUNDLED_POLICIES.parent / "evals" /
                           "research_policy_acceptance.yaml").read_text())
    data["held_out_tasks"]["queries_file"] = "held_out.jsonl"
    data["rq1"]["min_pairs"] = 2
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setenv(acceptance.ACCEPTANCE_ENV, str(path))
    acceptance.freeze(path, owner="tester")
    return path


def mechanism_tree(tmp_path, name="v1-hypotheses"):
    tree = ResearchTree(tmp_path / "t" / "research_tree.json", policy=policy(name))
    tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains the warm anomaly?"},
        {"action": "add", "target": "B1", "kind": "hypothesis", "question": "Surface heat flux."},
        {"action": "add", "target": "B1", "kind": "hypothesis", "question": "Eddy advection."},
        {"action": "add", "target": "B1", "question": "Does the heat budget close with flux alone?"},
        {"action": "add", "target": "B1", "question": "Do eddies converge heat in Aug-Sep?",
         "relation": "alternative"},
    ])
    return tree


# --- policies ---------------------------------------------------------------

def test_bundled_policies_load_with_content_versions():
    v0, v1 = policy("v0-coordinator-bfs"), policy("v1-hypotheses")
    assert v0.version.startswith("policy/v0-coordinator-bfs@")
    assert (v0.hypotheses, v0.frontier_mode, v0.guidance) == (False, "shallowest", "")
    assert v1.hypotheses and v1.guidance


def test_policy_boundary_rejects_unknown_fields_and_values():
    with pytest.raises(ValueError):
        validate_policy_document({"name": "x", "acceptance": {}})
    with pytest.raises(ValueError):
        validate_policy_document({"name": "x", "frontier": "random"})


def test_hypotheses_need_a_policy_that_enables_them(tmp_path):
    tree = ResearchTree(tmp_path / "research_tree.json", policy=policy("v0-coordinator-bfs"))
    tree.update([{"action": "add", "target": "ROOT", "question": "Q?"}])
    with pytest.raises(ValueError, match="not enabled"):
        tree.update([{"action": "add", "target": "B1", "kind": "hypothesis", "question": "H."}])
    assert "set_verdict" not in research_tree_tool(tree).description


def test_hypotheses_are_claims_never_frontier_or_reports(tmp_path):
    tree = mechanism_tree(tmp_path)
    doc = tree.document()
    assert doc["nodes"]["B1.1"]["kind"] == "hypothesis"
    assert doc["nodes"]["B1.1"]["verdict"] == "unresolved"
    with pytest.raises(ValueError):
        tree.update([{"action": "set_status", "target": "B1.1", "status": "selected"}])
    tree.update([{"action": "set_status", "target": "B1.3", "status": "selected"}])
    assert frontier(tree.document()) == ["B1.3"]
    with pytest.raises(ValueError):
        tree.attach_result("B1.1", summary="x", agent_key="a", report_path="/r")
    view = tree.read()
    assert view["hypotheses"] == ["B1.1", "B1.2"]
    assert "B1.1" not in view["candidates"]


def test_directed_evidence_and_verdict_history(tmp_path):
    tree = mechanism_tree(tmp_path)
    tree.update([
        {"action": "link", "target": "B1.3", "other": "B1.1", "link_type": "supports"},
        {"action": "link", "target": "B1.3", "other": "B1.2", "link_type": "refutes"},
    ])
    with pytest.raises(ValueError):  # refutes must point at a hypothesis
        tree.update([{"action": "link", "target": "B1.3", "other": "B1.4",
                      "link_type": "refutes"}])
    with pytest.raises(ValueError):  # evidence must come from a question
        tree.update([{"action": "link", "target": "B1.1", "other": "B1.2",
                      "link_type": "supports"}])
    with pytest.raises(ValueError):  # verdict needs a reason
        tree.update([{"action": "set_verdict", "target": "B1.1", "verdict": "supported"}])
    tree.update([{"action": "set_verdict", "target": "B1.1", "verdict": "supported",
                  "reason": "Budget closes within 20%."}])
    tree.update([{"action": "set_verdict", "target": "B1.1", "verdict": "unresolved",
                  "reason": "Residual too large."}])
    verdicts = [(e["payload"]["verdict"], e["reason"]) for e in tree.events("B1.1")
                if e["type"] == "verdict"]
    assert verdicts == [("supported", "Budget closes within 20%."),
                        ("unresolved", "Residual too large.")]


def test_decline_requires_reason_and_keeps_candidate(tmp_path):
    tree = mechanism_tree(tmp_path)
    with pytest.raises(ValueError):
        tree.update([{"action": "decline", "target": "B1.4"}])
    tree.update([{"action": "decline", "target": "B1.4", "reason": "No velocity data."}])
    assert tree.document()["nodes"]["B1.4"]["status"] == "candidate"
    assert tree.events("B1.4")[-1]["type"] == "declined"


def test_v3_tree_is_read_and_upgraded(tmp_path):
    doc = empty_tree()
    doc, _, _ = apply_changes(doc, [{"action": "add", "target": "ROOT", "question": "Q"}])
    doc["schema_version"] = "oceanx-research-tree/v3"
    path = tmp_path / "research_tree.json"
    path.write_text(json.dumps(doc))
    tree = ResearchTree(path)
    tree.update([{"action": "add", "target": "B1", "question": "Sub?"}])
    assert tree.document()["schema_version"] == "oceanx-research-tree/v4"


# --- Expert proposals ---------------------------------------------------------

def test_proposals_are_the_numbered_further_analysis_items():
    assert proposals_from_summary(PROPOSING) == [
        "Do eddies converge heat in Aug-Sep? — the residual.",
        "Is the mixed-layer depth biased? — it scales the budget.",
        "Does 2019 repeat the pattern? — one year is thin."]
    assert proposals_from_summary(SUMMARY) == []
    assert proposals_from_summary("Further analysis: None") == []


def test_proposals_become_nodes_only_when_the_coordinator_adopts_one(tmp_path):
    tree = mechanism_tree(tmp_path)
    tree.update([{"action": "set_status", "target": "B1.3", "status": "selected"}])
    tree.attach_result("B1.3", summary=PROPOSING, agent_key="a", report_path="/r.md")
    before = set(tree.document()["nodes"])
    assert len(tree.document()["nodes"]["B1.3"]["result"]["proposals"]) == 3
    assert "B1.3#1" in render_full(tree.document())
    for bad in ("B1.3#4", "B1.3#x", "B1.4#1"):
        with pytest.raises(ValueError, match="Unknown Expert proposal"):
            tree.update([{"action": "add", "target": "B1.3", "question": "Q?",
                          "from_proposal": bad}])
    assert set(tree.document()["nodes"]) == before
    tree.update([{"action": "add", "target": "B1.3", "from_proposal": "B1.3#2",
                  "question": "Is the mixed-layer depth biased?"}])
    node = tree.document()["nodes"]["B1.3.1"]
    assert node["origin"] == {"type": "expert-proposal", "refs": ["B1.3#2"]}
    created = [e for e in tree.events("B1.3.1") if e["type"] == "created"][0]
    assert created["payload"]["from_proposal"] == "B1.3#2"
    outcomes = record_task_outcomes(tree, final_report="## Summary\nx", model_calls=[])
    assert (outcomes["B1.3"]["follow_ups_proposed"], outcomes["B1.3"]["follow_ups_adopted"]) == (3, 1)


# --- compact view -----------------------------------------------------------

def test_compact_view_keeps_decision_limit_and_folds_finished_branches(tmp_path):
    tree = mechanism_tree(tmp_path)
    tree.update([{"action": "set_status", "target": "B1.3", "status": "selected"}])
    tree.attach_result("B1.3", summary=SUMMARY, agent_key="a", report_path="/r.md")
    text = render_full(tree.document())
    assert "→ Limit: One year only; budget residual 20%." in text
    assert "→ Further: Test eddy advection." in text
    assert "B1.1 (hypothesis, unresolved)" in text
    tree.update([{"action": "set_status", "target": "B1.3", "status": "completed"}])
    folded = render_full(tree.document())
    assert "B1.3 [completed, folded]" in folded and "→ Limit" not in folded
    assert "→ Limit" in render_full(tree.document(), include_history=True)


def test_tool_returns_delta_then_full_view_after_external_change(tmp_path):
    tree = mechanism_tree(tmp_path)
    tool = research_tree_tool(tree)
    first = asyncio.run(tool.coroutine(changes=[], view="decision"))
    assert first.startswith("research tree revision")
    change = tool.args_schema.model_fields["changes"].annotation.__args__[0]
    delta = asyncio.run(tool.coroutine(
        changes=[change(action="set_status", target="B1.3", status="selected")]))
    assert "changed:" in delta and "frontier: B1.3" in delta and "live nodes:" in delta
    tree.attach_result("B1.3", summary=SUMMARY, agent_key="a", report_path="/r.md")  # elsewhere
    after_gap = asyncio.run(tool.coroutine(
        changes=[change(action="set_status", target="B1.4", status="selected")]))
    assert "changed:" not in after_gap and "What sustains the warm anomaly?" in after_gap
    assert len(render_delta(tree.document(), ["B1.4"])) < len(json.dumps(tree.read()))


# --- structured delegation ---------------------------------------------------

class _Request:
    def __init__(self, tool_call=None, tools=None):
        self.tool_call, self.tools = tool_call, tools

    def override(self, **kwargs):
        return _Request(kwargs.get("tool_call", self.tool_call), kwargs.get("tools", self.tools))


def test_delegation_binding_explicit_inferred_unbound(tmp_path):
    tree = mechanism_tree(tmp_path)
    assert resolve_delegation({"node_id": "B1.3", "description": "x"}, tree).binding == "explicit"
    inferred = resolve_delegation({"description": "Question (B1.4): eddies?"}, tree)
    assert (inferred.node_id, inferred.binding) == ("B1.4", "inferred")
    assert resolve_delegation({"node_id": "B9", "description": "x"}, tree).binding == "unbound"
    assert resolve_delegation({"description": "no id"}, tree).node_id is None


def test_middleware_logs_delegation_strips_arg_and_exposes_binding(tmp_path):
    tree = mechanism_tree(tmp_path)
    tree.update([{"action": "set_status", "target": "B1.3", "status": "selected"}])
    middleware = StructuredDelegationMiddleware(tree)
    seen = {}

    def handler(request):
        seen["args"] = request.tool_call["args"]
        seen["delegation"] = current_delegation()
        return "receipt"

    call = {"name": "task", "id": "c1", "args": {"description": "Question: budget?",
                                                  "subagent_type": "ocean_process_expert",
                                                  "node_id": "B1.3"}}
    assert middleware.wrap_tool_call(_Request(call), handler) == "receipt"
    assert "node_id" not in seen["args"]
    assert seen["delegation"].node_id == "B1.3"
    assert current_delegation() is None  # reset after the call
    event = tree.events("B1.3")[-1]
    assert event["type"] == "delegated"
    assert event["payload"]["on_frontier"] is True
    assert event["payload"]["attempt_id"] == seen["delegation"].attempt_id
    other = {"name": "ls", "id": "c2", "args": {"path": "/"}}
    assert middleware.wrap_tool_call(_Request(other), lambda r: r.tool_call) == other


# --- outcomes ----------------------------------------------------------------

def test_outcomes_ignore_tree_section_and_attribute_tokens(tmp_path):
    tree = mechanism_tree(tmp_path)
    tree.update([{"action": "set_status", "target": "B1.3", "status": "selected"},
                 {"action": "set_status", "target": "B1.4", "status": "selected"}])
    tree.attach_result("B1.3", summary=SUMMARY, agent_key="physics-1", report_path="/r3.md",
                       attempt_id="a3")
    tree.attach_result("B1.4", summary=SUMMARY, agent_key="physics-2", report_path="/r4.md",
                       attempt_id="a4")
    final = ("## Summary\nHeat flux dominates [physics-1/budget].\n\n"
             "## Research Tree\n- B1.3 completed\n- B1.4 completed\n")
    calls = [{"attempt_id": "a3", "usage": {"input_tokens": 100, "output_tokens": 10}},
             {"attempt_id": "a4", "usage": {"input_tokens": 50, "output_tokens": 5}},
             {"attempt_id": None, "usage": {"input_tokens": 999}}]
    outcomes = record_task_outcomes(tree, final_report=final, model_calls=calls)
    assert outcomes["B1.3"]["cited_in_final"] is True
    assert outcomes["B1.4"]["cited_in_final"] is False  # only listed in the tree section
    assert (outcomes["B1.3"]["input_tokens"], outcomes["B1.3"]["model_calls"]) == (100, 1)
    assert tree.store.outcomes()["B1.4"]["output_tokens"] == 5


# --- acceptance --------------------------------------------------------------

def labelled_run(root, useful: str, waste: str):
    tree = mechanism_tree(root)
    tree.update([{"action": "set_status", "target": "B1.3", "status": "selected"},
                 {"action": "set_status", "target": "B1.4", "status": "selected"}])
    for node in ("B1.3", "B1.4"):
        tree.attach_result(node, summary=SUMMARY, agent_key=f"k{node}", report_path="/r")
    record_task_outcomes(tree, final_report="## Summary\nx", model_calls=[])
    tree.label(useful, "decision-changing", labeler="owner")
    tree.label(waste, "misleading-or-wasteful", labeler="owner")
    return tree


def test_acceptance_freeze_detects_tampering(tmp_path, monkeypatch):
    path = tmp_path / "a.yaml"
    shutil.copyfile(BUNDLED_POLICIES.parent / "evals" / "research_policy_acceptance.yaml", path)
    monkeypatch.setenv(acceptance.ACCEPTANCE_ENV, str(path))
    assert not acceptance.is_frozen(path)
    with pytest.raises(ValueError):  # queries_file still null
        acceptance.freeze(path, owner="o")
    path.write_text(path.read_text().replace("queries_file: null", "queries_file: h.jsonl"))
    acceptance.freeze(path, owner="o")
    assert acceptance.require_frozen(path)["rq1"]["min_pairs"] == 8
    path.write_text(path.read_text().replace("min_pairs: 8", "min_pairs: 1"))
    with pytest.raises(acceptance.AcceptanceNotFrozen):
        acceptance.require_frozen(path)


def test_paired_evaluation_applies_frozen_criteria(tmp_path, frozen):
    runs = []
    for case in ("c1", "c2"):
        for arm, useful, tokens in (("A", "B1.3", 9000), ("B", "B1.4", 3000)):
            directory = tmp_path / case / arm
            labelled_run(directory, useful=useful, waste="B1.4" if useful == "B1.3" else "B1.3")
            (directory / "result.json").write_text(json.dumps({
                "status": "completed", "elapsed_seconds": 10,
                "coordinator_usage": {"input_tokens": tokens, "output_tokens": 0}}))
            runs.append({"case": case, "arm": arm, "policy": arm, "status": "completed",
                         "directory": str(directory)})
    (tmp_path / "pairs.json").write_text(json.dumps(
        {"policy_a": "v0", "policy_b": "v1", "runs": runs}))
    quality = tmp_path / "q.jsonl"
    quality.write_text('{"case": "c1", "better": "B"}\n{"case": "c2", "better": "same"}\n')
    verdict = evaluate_pairs(tmp_path, quality_file=quality)
    assert verdict["token_reduction"] == pytest.approx(2 / 3)
    assert verdict["meets_frozen_criteria"] is True
    quality.write_text('{"case": "c1", "better": "A"}\n{"case": "c2", "better": "same"}\n')
    assert evaluate_pairs(tmp_path, quality_file=quality)["meets_frozen_criteria"] is False
