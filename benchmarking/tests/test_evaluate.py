"""Blinding, score validation and the paired summary; no models or agents."""
import json
import os
import sqlite3
from contextlib import closing

import evaluate
import pytest


def make_arm(root, arm, policy, scores_by_task):
    arm_dir = root / f"arm-{arm}"
    for task in scores_by_task:
        attempt = arm_dir / task / "attempt-1"
        workspace = attempt / "workspace" / "OceanX Tasks" / f"{task}--abc"
        (workspace / "agents" / "coordinator").mkdir(parents=True)
        (workspace / "agents" / "coordinator" / "research_tree.json").write_text('{"frontier_mode": "any_depth"}')
        report = workspace / "agents" / "ocean-process-1" / "reports" / "B1.1" / "report.md"
        report.parent.mkdir(parents=True)
        report.write_text(f"Result: see {arm_dir}/{task}/attempt-1/workspace/x.nc")
        figure = workspace / "agents" / "ocean-process-1" / "outputs" / "map.preview.png"
        figure.parent.mkdir(parents=True)
        figure.write_bytes(b"png")
        (attempt / "answer.md").write_text("## Summary\nanswer")
        (attempt / "query.json").write_text(json.dumps({"query": evaluate.json.loads(
            (evaluate.TASKS / task / "task_info.json").read_text())["query"]}))
        status = "completed" if scores_by_task[task] is not None else "failed"
        (attempt / "result.json").write_text(json.dumps({"status": status, "elapsed_seconds": 3600,
            "coordinator_usage": {"input_tokens": 1000, "output_tokens": 100}}))
    (arm_dir / "arm.json").write_text(json.dumps({"arm": arm, "policy": policy, "library": None}))
    return arm_dir


def score_file(blind_id, task, level):
    criteria = evaluate.rubric(task)["criteria"]
    return {"blind_id": blind_id, "task_id": task, "status": "completed", "rubric_version": "3.0",
            "rubric_status": "frozen", "references_sha256": "x" * 64, "judge": {"name": "codex"},
            "delivered": True,
            "criteria": [{"id": c["id"], "score": level, "evidence": "evidence/answer.md"} for c in criteria],
            # Paper verification: every finding has a verdict that agrees with the reference.
            "findings": [{"id": c["id"], "agent_verdict": "reproduced", "matches_reference": True}
                         for c in criteria if c.get("kind") == "claim"]}


def added_file(blind_id, task, level):
    """The two criteria of paper verification that are judged beside the rubric: one level, or one per letter."""
    levels = level if isinstance(level, dict) else dict.fromkeys(evaluate.ADDED_CRITERIA, level)
    return {"blind_id": blind_id, "task_id": task, "judge": {"name": "codex"},
            "criteria": [{"id": f"{task}-{letter}", "score": levels[letter], "evidence": "evidence/answer.md"}
                         for letter in evaluate.ADDED_CRITERIA]}


def write_scores(eval_root, mapping, level_of):
    """Score files for the attempts that `level_of(entry)` gives a level, and the added files of the paper tasks."""
    scores, added = eval_root / "scores", eval_root / "added"
    scores.mkdir()
    added.mkdir()
    for blind_id, entry in json.loads(mapping.read_text()).items():
        level, task = level_of(entry), entry["task_id"]
        if level is None:
            continue
        (scores / f"{blind_id}.json").write_text(json.dumps({**score_file(blind_id, task, level), "status": entry["status"]}))
        if evaluate.rubric(task)["type"] == "paper_reproduction":
            (added / f"{blind_id}.json").write_text(json.dumps(added_file(blind_id, task, level)))
    return scores, added


def test_blind_hides_the_arm_and_the_tree(tmp_path):
    runs = [make_arm(tmp_path / "runs", "A", "v0-coordinator-bfs", {"Q01": 2}),
            make_arm(tmp_path / "runs", "B", "v2-nested", {"Q01": 3})]
    out, mapping = tmp_path / "eval" / "blind", tmp_path / "eval" / "blind_map.json"
    result = evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(out), "--map", str(mapping)])
    assert result == 0
    entries = json.loads(mapping.read_text())
    assert sorted(e["arm"] for e in entries.values()) == ["A", "B"]
    for blind_id in entries:
        folder = out / blind_id
        assert json.loads((folder / "task.json").read_text()).keys() == {"blind_id", "task_id", "query", "status"}
        assert not list(folder.rglob("research_tree.json"))
        assert list(folder.rglob("map.preview.png"))
        text = next(folder.rglob("report.md")).read_text()
        assert "arm-A" not in text and "arm-B" not in text and "<RUN>" in text
    # Re-running adds nothing and the map may not sit inside the judged folder.
    evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(out), "--map", str(mapping)])
    assert len(json.loads(mapping.read_text())) == 2
    with pytest.raises(SystemExit):
        evaluate.main(["blind", "--runs", str(runs[0]), "--out", str(out), "--map", str(out / "map.json")])


def test_blind_keeps_a_large_notebook_and_names_what_it_leaves_out(tmp_path, monkeypatch):
    """An executed notebook is mostly images; the judge needs its code and numbers, and must be able to
    tell a file that was too large to copy from one the agent never wrote."""
    arm_dir = make_arm(tmp_path / "runs", "C", None, {"Q07": 2})
    attempt = arm_dir / "Q07" / "attempt-1"
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "markdown", "source": "# Analysis"},
        {"cell_type": "code", "execution_count": 1, "source": "plot(field)", "outputs": [
            {"output_type": "display_data", "metadata": {},
             "data": {"image/png": "A" * 6000, "text/plain": "<Figure size 640x480>"}},
            {"output_type": "execute_result", "execution_count": 1, "metadata": {},
             "data": {"text/html": "<table>" + "<td>1</td>" * 400 + "</table>", "text/plain": "mean 1.25"}},
            {"output_type": "stream", "name": "stdout", "text": [f"row {n} {arm_dir}\n" for n in range(400)]}]}]}
    (attempt / "workspace" / "analysis.ipynb").write_text(json.dumps(notebook))
    (attempt / "outputs").mkdir()
    (attempt / "outputs" / "table.csv").write_text("a,b\n" + "1,2\n" * 3000)
    (attempt / "outputs" / "small.csv").write_text("a,b\n1,2\n")
    (attempt / "evidence_manifest.json").write_text(json.dumps(
        {"files": ["workspace/analysis.ipynb", "outputs/table.csv", "outputs/small.csv", "outputs/never_written.csv"]}))
    monkeypatch.setattr(evaluate, "MAX_TEXT", 4000)
    monkeypatch.setattr(evaluate, "LONG_OUTPUT", 300)
    out, mapping = tmp_path / "eval" / "blind", tmp_path / "eval" / "blind_map.json"
    result = evaluate.blind(type("Args", (), {"runs": [arm_dir], "out": out, "map": mapping})())
    assert (result["notebooks_copied_without_images"], result["folders_with_files_left_out"]) == (1, 1)
    [folder] = [path for path in out.iterdir()]
    text = (folder / "evidence" / "workspace" / "analysis.ipynb").read_text()
    figure, table, printed = json.loads(text)["cells"][1]["outputs"]
    assert set(figure["data"]) == {"text/plain"} and "image/png removed" in figure["data"]["text/plain"]
    assert "<Figure size 640x480>" in figure["data"]["text/plain"]
    assert set(table["data"]) == {"text/plain"} and table["data"]["text/plain"].endswith("mean 1.25")
    assert printed["text"].startswith("row 0 <RUN>") and "is cut in the copy" in printed["text"]
    assert len(text) < 4000 and "arm-C" not in text and json.loads(text)["cells"][1]["source"] == "plot(field)"
    # The table that was too large is named with its size; the one never written is not, so it reads as missing.
    left = json.loads((folder / "left_out.json").read_text())["files"]
    assert left == [{"path": "outputs/table.csv", "bytes": 12004}]
    assert (folder / "evidence" / "outputs" / "small.csv").is_file()
    # Without anything too large there is no such file.
    monkeypatch.setattr(evaluate, "MAX_TEXT", 2 * 1024**2)
    other = evaluate.blind(type("Args", (), {"runs": [arm_dir], "out": tmp_path / "b2", "map": tmp_path / "m2.json"})())
    assert (other["notebooks_copied_without_images"], other["folders_with_files_left_out"]) == (0, 0)
    [whole] = [path for path in (tmp_path / "b2").iterdir()]
    assert not (whole / "left_out.json").exists()
    assert "image/png" in json.loads((whole / "evidence" / "workspace" / "analysis.ipynb").read_text())["cells"][1]["outputs"][0]["data"]


def test_validate_catches_bad_scores():
    good = score_file("b1", "Q17", 3)
    assert evaluate.validate_score(good) == []
    assert evaluate.validate_score({**good, "total": 50}) == []  # the score is computed; an older file's total is not read
    assert evaluate.validate_score({**good, "rubric_status": "draft"})
    # An attempt without a final answer, judged on what it kept, needs the frozen rubric like any other.
    assert evaluate.validate_score({**good, "status": "failed", "rubric_status": "draft"})
    assert evaluate.validate_score({**good, "status": "failed"}) == []
    missing = json.loads(json.dumps(good))
    missing["criteria"][0]["evidence"] = ""
    assert evaluate.validate_score(missing)
    wrong = json.loads(json.dumps(good))
    wrong["criteria"][0]["score"] = 5
    assert evaluate.validate_score(wrong)
    # Half levels are allowed, nothing finer, and nothing that is not a number.
    half = judged_file("b1", "Q17", {"F": 2.5, "A": 0.5, "Q": 3, "M": 3.5, "R": 4, "B": 0, "I": 1.5})
    assert evaluate.validate_score(half) == []
    for bad in (2.25, 4.5, -0.5, "3", True, None):
        wrong["criteria"][0]["score"] = bad
        assert any("steps of 0.5" in error for error in evaluate.validate_score(wrong)), bad
    # Whether the attempt delivered is recorded in every score file.
    assert evaluate.validate_score({key: value for key, value in good.items() if key != "delivered"})
    assert evaluate.validate_score({**good, "delivered": "yes"})
    assert evaluate.validate_score({**good, "delivered": False}) == []


def test_validate_checks_the_criteria_judged_beside_the_rubric():
    """Robustness and data handling of paper verification: two levels in a file beside the score file."""
    paper, beside = score_file("b2", "Q09", 3), added_file("b2", "Q09", {"S": 2.5, "A": 4})
    assert evaluate.validate_added(beside, paper) == []
    assert evaluate.validate_added(beside, None) == ["no valid score file with this blind_id"]
    assert evaluate.validate_added(added_file("b1", "Q17", 3), score_file("b1", "Q17", 3)) == [
        "only paper verification has added criteria"]
    assert any("task_id" in error for error in evaluate.validate_added({**beside, "task_id": "Q08"}, paper))
    assert any("criteria ids" in error for error in evaluate.validate_added({**beside, "criteria": beside["criteria"][:1]}, paper))
    assert any("steps of 0.5" in error for error in evaluate.validate_added(added_file("b2", "Q09", 5), paper))
    unsupported = json.loads(json.dumps(beside))
    unsupported["criteria"][1]["evidence"] = " "
    assert evaluate.validate_added(unsupported, paper) == ["Q09-A: evidence is required"]
    assert evaluate.validate_added({key: value for key, value in beside.items() if key != "judge"}, paper) == ["missing judge"]


def test_freeze_summarize_and_decisions(tmp_path):
    tasks = {"Q07": 2, "Q17": 2, "Q25": 2, "Q01": None}
    better = {"Q07": 4, "Q17": 3, "Q25": 3, "Q01": None}
    runs = [make_arm(tmp_path / "runs", "A", "v0-coordinator-bfs", tasks),
            make_arm(tmp_path / "runs", "B", "v2-nested", better)]
    eval_root = tmp_path / "eval"
    mapping = eval_root / "blind_map.json"
    evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(eval_root / "blind"), "--map", str(mapping)])
    scores, added = write_scores(eval_root, mapping, lambda entry: (better if entry["arm"] == "B" else tasks)[entry["task_id"]])
    prereg = eval_root / "preregistration.yaml"
    prereg.write_text("experiment: unit\nfailed_attempt_score: 0\nbootstrap: {resamples: 200, seed: 1}\n"
                      "comparisons:\n  - name: policy\n    treatment: B\n    control: A\n"
                      "    rule: {type: superior, margin: 0}\n")
    judged = ["--map", str(mapping), "--scores", str(scores), "--added", str(added)]
    with pytest.raises(SystemExit):  # not frozen yet
        evaluate.main(["summarize", "--prereg", str(prereg), *judged, "--out", str(eval_root / "report")])
    evaluate.main(["freeze", "--prereg", str(prereg)])
    with pytest.raises(SystemExit, match="not judged yet"):  # the paper task lacks its two added criteria
        evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                       "--out", str(eval_root / "report")])
    evaluate.main(["summarize", "--prereg", str(prereg), *judged, "--out", str(eval_root / "report")])
    summary = json.loads((eval_root / "report" / "summary.json").read_text())
    policy = summary["comparisons"][0]
    assert policy["tasks"] == 4 and policy["mean_diff"] > 0 and policy["decision"] is True
    # A score is the mean of six indicators that count the same. Open problem: every level 2 gives 50.
    # Paper task: five indicators at 50 and every verdict in agreement with the reference.
    assert summary["cells"]["A|Q17"]["score"] == 50 and summary["cells"]["B|Q17"]["score"] == 75
    assert summary["cells"]["A|Q07"]["score"] == pytest.approx((5 * 50 + 100) / 6) and summary["cells"]["B|Q07"]["score"] == 100
    # What the arms cost is not part of the results: no tokens, no time, in the summary or in the report.
    report = (eval_root / "report" / "report.md").read_text()
    assert not {"tokens", "elapsed_hours"} & set(summary["arms"]["A"]) and "tokens" not in summary["cells"]["A|Q17"]
    assert not {"token_reduction", "time_reduction"} & set(policy)
    assert "Tokens" not in report and "Hours" not in report and "cut" not in report
    with pytest.raises(ValueError, match="unknown rule type"):  # the rule that weighed a score against tokens is gone
        evaluate.decide({"type": "noninferior_and_better_or_cheaper", "margin": -2, "token_reduction": 0.15}, policy)
    assert set(policy["by_type"]) == {"paper_reproduction", "open_problem"}
    assert policy["by_data"]["public"]["tasks"] == 2 and policy["by_data"]["private"]["tasks"] == 2
    assert summary["arms"]["A"]["failures"] == 1  # Q01 failed in both arms and scored 0
    assert "meets rule" in (eval_root / "report" / "report.md").read_text()
    prereg.write_text(prereg.read_text() + "# edited\n")
    with pytest.raises(SystemExit):  # changed after freezing
        evaluate.main(["summarize", "--prereg", str(prereg), *judged, "--out", str(eval_root / "report2")])


def test_library_check(tmp_path, capsys):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "arm_library.json").write_text(json.dumps({"unchanged": True}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "arm_library.json").write_text(json.dumps({"sha256_before": {"lessons.json": "x"}}))
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "arm_lessons.json").write_text(json.dumps({"unchanged": True}))  # an older run
    report = evaluate.library_check(type("A", (), {"runs": tmp_path})())
    assert report["checked"] == 3 and report["changed_or_unfinished"] == [str(tmp_path / "b" / "arm_library.json")]
    assert evaluate.main(["library-check", "--runs", str(tmp_path)]) == 0
    assert evaluate.main(["lessons-check", "--runs", str(tmp_path)]) == 0  # the earlier name still works
    assert capsys.readouterr().out.count('"checked": 3') == 2


def make_tree(attempt, task, *, side_tokens, planning_opened, library=None, executions=()):
    """A finished research tree with one decisive question and one side question."""
    from oceanx.research.outcomes import record_task_outcomes
    from oceanx.research.tree import ResearchTree
    path = attempt / "workspace" / "OceanX Tasks" / f"{task}--abc" / "agents" / "coordinator" / "research_tree.json"
    path.unlink()  # the placeholder written by make_arm
    tree = ResearchTree(path)
    tree.update([{"action": "add", "target": "ROOT", "question": "Why?"},
                 {"action": "add", "target": "B1", "question": "Decisive?", "status": "selected"},
                 {"action": "add", "target": "B1", "question": "Side question?", "status": "selected"}])
    summary = "Result: x.\nEvidence and limitations: y.\nFurther analysis: None"
    for node, attempt_id in (("B1.1", "a"), ("B1.2", "b")):
        tree.attach_result(node, summary=summary, agent_key="p", report_path=f"/{node}.md", attempt_id=attempt_id)
    record_task_outcomes(tree, final_report="## Summary\nB1.1 decides it.", model_calls=[
        {"attempt_id": "a", "usage": {"input_tokens": 1_000_000}, "skills_read": ["ocean-analysis-design"]},
        {"attempt_id": "b", "usage": {"input_tokens": side_tokens}, "skills_read": []},
        {"role": "coordinator", "usage": {"input_tokens": 100_000},
         "skills_read": ["research-trajectory-planning"] if planning_opened else []}],
        code_executions=list(executions), library=library)
    tree.label("B1.1", "decision-changing", labeler="model-judge", source="judge")
    tree.label("B1.2", "informative-but-not-decisive", labeler="model-judge", source="judge")


def test_process_measures_compare_arms_on_the_research_tree(tmp_path):
    runs = []
    for repeat, control_side in ((1, 3_000_000), (2, 2_000_000)):
        for arm, side in (("B", control_side), ("C1", 1_000_000)):
            arm_dir = make_arm(tmp_path / f"r{repeat}", arm, "v2-nested", {"Q07": 2, "Q17": 2, "Q25": None})
            for task in ("Q07", "Q17"):
                attempt = arm_dir / task / "attempt-1"
                if arm == "C1":  # ran with a library: one lesson shown and named, one helper called twice
                    make_tree(attempt, task, side_tokens=side, planning_opened=True,
                              executions=[{"agent_thread_id": "p", "state": "succeeded",
                                           "tool_calls": {"weighted_mean": 2}}],
                              library={"lessons_shown": ["L001"], "lessons_cited": ["L001"],
                                       "tools_mounted": ["weighted_mean"]})
                    make_state(attempt, [], code=[("succeeded", 1.0)] * 3 + [("failed", 1.0)])
                else:
                    make_tree(attempt, task, side_tokens=side, planning_opened=False)
                    make_state(attempt, [], code=[("succeeded", 1.0), ("failed", 1.0)])
            runs.append(arm_dir)
    prereg = tmp_path / "preregistration.yaml"
    prereg.write_text("experiment: unit\nbootstrap: {resamples: 200, seed: 1}\ncomparisons: []\n"
                      "process_comparisons:\n  - {name: lessons-L1-process, metric: nondecisive_token_share, "
                      "treatment: C1, control: B, rule: {type: lower, margin: 0}}\n"
                      "  - {name: library-L1-code, metric: code_failure_share, "
                      "treatment: C1, control: B, rule: {type: lower, margin: 0}}\n")
    evaluate.main(["freeze", "--prereg", str(prereg)])
    out = tmp_path / "report"
    assert evaluate.main(["process", "--runs", *map(str, runs), "--out", str(out), "--prereg", str(prereg)]) == 0
    result = json.loads((out / "process.json").read_text())
    control, treated = result["arms"]["B"], result["arms"]["C1"]
    # Q25 failed without a tree: it is counted as an attempt and left out of the measures.
    assert (control["attempts"], control["finished_trees"]) == (6, 4)
    assert control["nondecisive_token_share"] == pytest.approx((0.75 + 2 / 3) / 2)
    assert treated["nondecisive_token_share"] == pytest.approx(0.5)
    assert control["repeat_noise"]["nondecisive_token_share"] == pytest.approx(0.75 - 2 / 3)
    assert (control["planning_skill_opened"], treated["planning_skill_opened"]) == (0.0, 1.0)
    assert treated["questions_reading_an_analysis_skill"] == 0.5 and treated["rule_only_labels"] == 0
    # What the library is meant to change. Arm B recorded no library, so it reports no count, not zero.
    assert (control["code_failure_share"], treated["code_failure_share"]) == (0.5, 0.25)
    assert (control["helper_calls"], treated["helper_calls"]) == (None, 2)
    assert (control["lessons_cited"], treated["lessons_cited"]) == (None, 1)
    comparison, code = result["comparisons"]
    assert (code["metric"], code["mean_diff"], code["decision"]) == ("code_failure_share", -0.25, True)
    assert comparison["tasks"] == 2 and comparison["decision"] is True
    assert comparison["mean_diff"] == pytest.approx(0.5 - (0.75 + 2 / 3) / 2)
    assert comparison["control_repeat_noise"] == pytest.approx(0.75 - 2 / 3)
    assert "meets rule" in (out / "process.md").read_text()
    # Without a pre-registration the measures are still reported; nothing is decided.
    evaluate.main(["process", "--runs", str(runs[0]), "--out", str(tmp_path / "plain")])
    assert json.loads((tmp_path / "plain" / "process.json").read_text())["comparisons"] == []


def make_state(attempt, calls, code=()):
    """The parts of an attempt's own state that the evaluation reads: call ledger, code runs, conversations."""
    state = attempt / "state"
    (state / ".langgraph_api").mkdir(parents=True)
    (state / ".langgraph_api" / ".langgraph_checkpoint.1.pckl").write_bytes(b"conversation" * 100)
    with closing(sqlite3.connect(state / "workspace.sqlite3")) as db:
        db.execute("CREATE TABLE model_call_observations (call_id TEXT PRIMARY KEY, request_id TEXT, "
                   "thread_id TEXT NOT NULL, record_json TEXT NOT NULL)")
        db.execute("CREATE TABLE code_executions (execution_id TEXT PRIMARY KEY, state TEXT NOT NULL, result_json TEXT)")
        db.executemany("INSERT INTO model_call_observations VALUES (?,?,?,?)",
                       [(str(i), "request", "thread", json.dumps(call)) for i, call in enumerate(calls)])
        db.executemany("INSERT INTO code_executions VALUES (?,?,?)",
                       [(str(i), state_, json.dumps({"duration_seconds": seconds}))
                        for i, (state_, seconds) in enumerate(code)])
        db.commit()


CALLS = [
    {"role": "coordinator", "state": "completed", "duration_seconds": 2.0,
     "usage": {"input_tokens": 1000, "output_tokens": 50, "input_token_details": {"cache_read": 800}}},
    {"role": "ocean_process_expert", "node_id": "B1.2", "attempt_id": "first", "state": "failed",
     "duration_seconds": 1.0, "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-01T00:06:00+00:00"},
    {"role": "ocean_process_expert", "node_id": "B1.2", "attempt_id": "b", "state": "completed", "duration_seconds": 3.5,
     "usage": {"input_tokens": 9000, "output_tokens": 500}, "skills_read": ["ocean-analysis-design"],
     "started_at": "2026-01-01T00:10:00+00:00", "ended_at": "2026-01-01T00:13:30+00:00"},
]


def test_tokens_come_from_the_call_ledger_not_the_end_of_run_report(tmp_path):
    arm_dir = make_arm(tmp_path / "runs", "B", "v2-nested", {"Q07": 2, "Q17": 2})
    attempt = arm_dir / "Q07" / "attempt-1"
    # Like real runs, this one reported zero tokens when it ended. The ledger has every call.
    result = {**json.loads((attempt / "result.json").read_text()),
              "coordinator_usage": {"input_tokens": 0, "output_tokens": 0}}
    (attempt / "result.json").write_text(json.dumps(result))
    make_state(attempt, CALLS)
    spent = evaluate.usage(attempt, result)
    assert spent["source"] == "ledger"
    assert (spent["input_tokens"], spent["cached_input_tokens"], spent["output_tokens"]) == (10000, 800, 550)
    assert (spent["calls"], spent["failed_calls"], spent["model_seconds"]) == (3, 1, 6.5)
    assert spent["by_role"]["ocean_process_expert"] == {"calls": 2, "input_tokens": 9000, "output_tokens": 500}
    # Without a state folder the end-of-run report is all there is.
    other = arm_dir / "Q17" / "attempt-1"
    reported = evaluate.usage(other, json.loads((other / "result.json").read_text()))
    assert (reported["source"], reported["input_tokens"], reported["output_tokens"]) == ("result.json", 1000, 100)
    # The blind map that the results are computed from holds none of this: what an attempt cost is its own record.
    mapping = tmp_path / "eval" / "blind_map.json"
    evaluate.main(["blind", "--runs", str(arm_dir), "--out", str(tmp_path / "eval" / "blind"), "--map", str(mapping)])
    for entry in json.loads(mapping.read_text()).values():
        assert not {"tokens", "usage", "elapsed_seconds"} & set(entry)


def test_inventory_records_what_each_attempt_cost_and_kept(tmp_path):
    arm_dir = make_arm(tmp_path / "runs", "C1", "v2-nested", {"Q07": 2, "Q17": 2, "Q25": None})
    attempt = arm_dir / "Q07" / "attempt-1"
    make_tree(attempt, "Q07", side_tokens=1_000_000, planning_opened=True)
    make_state(attempt, CALLS, code=[("succeeded", 4.0), ("failed", 1.5)])
    task = attempt / "workspace" / "OceanX Tasks" / "Q07--abc"
    agent = "agents/ocean-process-1"
    for relative, body in (("agents/coordinator/report.md", "## Summary\nFinal."),
                           (f"{agent}/reports/B1.2/report.md", "## Summary\nSide."),
                           (f"{agent}/.runtime/report-history/B1.1/a.md", "## Summary\nEarlier."),
                           (f"{agent}/.runtime/context/conversation_history/session_1.md", "## Summarized at ..."),
                           (f"{agent}/.runtime/skills/x/skills/xarray-array-ops/SKILL.md", "skill"),
                           (f"{agent}/scratch/field.npy", "x" * 2000)):
        (task / relative).parent.mkdir(parents=True, exist_ok=True)
        (task / relative).write_text(body)
    out = tmp_path / "report"
    assert evaluate.main(["inventory", "--runs", str(arm_dir), "--out", str(out)]) == 0
    records = {r["task_id"]: r for r in json.loads((out / "inventory.json").read_text())}
    full = records["Q07"]
    assert full["complete"] and full["missing"] == [] and full["arm"] == "C1"
    assert full == {**json.loads((attempt / "run_record.json").read_text()), "path": str(attempt)}
    assert full["time"] == {"elapsed_seconds": 3600, "setup_seconds": None, "analysis_seconds": None,
                            "model_seconds": 6.5, "code_seconds": 5.5}
    assert (full["tokens"]["input_tokens"], full["tokens"]["output_tokens"]) == (10000, 550)
    assert full["code_runs"] == {"total": 2, "by_state": {"failed": 1, "succeeded": 1}, "failures": {
        "kernel_start": 0, "time_limit": 0, "read_only": 0, "cancelled": 0, "code": 1}}
    assert full["tree"]["finished"] and full["tree"]["questions_answered"] == 2
    # Every Markdown file of the run is listed by kind; the agents' copies of skills are not.
    kinds = sorted((d["kind"], d["node"]) for d in full["documents"])
    assert kinds == [("conversation history", None), ("final report", None), ("question report", "B1.1"),
                     ("question report", "B1.2"), ("report version", "B1.1")]
    assert full["conversations"] == {"checkpoint_bytes": 1200, "written_after_last_model_call": True,
                                     "history_files": 1, "history_bytes": 20}
    assert full["disk"]["scratch"] == 2000 and full["disk"]["total"] > 2000
    assert full["disk"]["scratch_released"] == 0
    # Each question of the tree carries its own cost; the Coordinator's calls are on the root.
    root, decisive, side = full["questions"]
    assert (root["node"], root["expert"], root["model_calls"], root["input_tokens"]) == ("B1", "coordinator", 1, 1000)
    assert (decisive["label"], decisive["model_calls"], decisive["report_versions"]) == ("decision-changing", 0, 1)
    assert (side["node"], side["model_calls"], side["input_tokens"], side["output_tokens"]) == ("B1.2", 2, 9000, 500)
    # Time on a question counts the attempt that returned no report: 6 minutes, then 3.5.
    assert side["minutes"] == 9.5
    assert side["skills_read"] == ["ocean-analysis-design"]
    assert side["report"] == f"workspace/OceanX Tasks/Q07--abc/{agent}/reports/B1.2/report.md"
    assert sum(q["input_tokens"] for q in full["questions"]) == full["tokens"]["input_tokens"]
    page = (attempt / "run_record.md").read_text()
    assert "# Q07, arm C1, attempt-1: completed" in page and "- Missing: nothing" in page
    assert f"| ocean-analysis-design | [report](<{side['report']}>) |" in page
    # An attempt without its state, tree and reports says exactly what a later evaluation would lack.
    assert not records["Q17"]["complete"] and records["Q17"]["questions"] == []
    assert records["Q17"]["missing"] == ["final report", "model-call ledger", "research tree",
                                         "agent conversations"]
    assert records["Q25"]["status"] == "failed" and "research tree" in records["Q25"]["missing"]
    table = (out / "inventory.md").read_text()
    assert "| C1 | Q07 | completed | 60 | 0.0M (0.0M) | 0.0M | 3 (1) | 2 (1) | 2 | 5 | 0.0 GB | nothing |" in table
    # Conversations are written when the Agent Server stops. A server killed before that leaves checkpoints
    # older than its last model call, or files of a few bytes.
    checkpoint = attempt / "state" / ".langgraph_api" / ".langgraph_checkpoint.1.pckl"
    os.utime(checkpoint, (0, 0))
    assert evaluate.run_record(attempt, {"arm": "C1"})["missing"] == ["end of agent conversations"]
    checkpoint.write_bytes(b"\x80\x02}q\x00.")
    assert evaluate.run_record(attempt, {"arm": "C1"})["missing"] == ["agent conversations"]


def test_code_failure_descriptions_do_not_assign_fault():
    description = evaluate.code_failures.__doc__
    assert "environment's fault" not in description
    assert "not the code's" not in description
    assert "protecting another node's files" in description
    assert "slow computation" in description


def test_run_disclosures_cover_delivery_requests_budgets_and_search():
    text = (evaluate.TASKS.parent / "EVALUATION.md").read_text()
    assert text.count("## Run settings and comparison limits") == 1  # listed once, with the evaluation
    section = text.split("## Run settings and comparison limits", 1)[1].split("\n## ", 1)[0]
    assert "OCEANX_FIGURE_DELIVERY=static" in section
    assert "not exposed" in section
    assert "extra provider request" in section and "compaction" in section and "ledger" in section
    assert "75%" in section and "changes Coordinator behavior" in section
    assert "Finch-local has no literature-search agent" in section
    assert "Claude Code's search depends on its configured tools" in section
    assert "OceanX consults Search Expert on demand" in section


def test_code_failures_classify_observed_failures_without_assigning_fault():
    # What the server run of 2026-10-03 needed counting by hand.
    code = [
        ("succeeded", {}),
        ("failed", {"error": "Kernel died before replying to kernel_info. Kernel output:\nbwrap: execvp"}),
        ("timed_out", {"limit_trigger": "wall_time"}),
        ("failed", {"stderr": "OSError: [Errno 30] Read-only file system: '/task/agents/x/outputs/a.nc'"}),
        ("cancelled", {}),
        ("failed", {"stderr": "ValueError: operands could not be broadcast together"}),
        ("running", {}),
    ]
    assert evaluate.code_failures(code) == {
        "kernel_start": 1, "time_limit": 1, "read_only": 1, "cancelled": 1, "code": 1}
    page = evaluate.record_page({
        "task_id": "Q01", "arm": "B", "attempt": "attempt-1", "status": "completed",
        "time": {"elapsed_seconds": 60, "model_seconds": 30, "code_seconds": 10},
        "tokens": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "calls": 0,
                   "failed_calls": 0},
        "code_runs": {"total": 7, "by_state": {"succeeded": 1}, "failures": evaluate.code_failures(code)},
        "disk": {"total": 0, "scratch": 0, "scratch_released": 0},
        "documents": [], "missing": [], "questions": []})
    assert ("Code runs: 7 (6 did not succeed: 1 kernel start, 1 time limit, 1 read only, "
            "1 cancelled, 1 code)") in page


@pytest.mark.parametrize("status, released", [("cleaned", 5_400_000_000), ("partial", 5_400_000_000),
                                              ("retained", 0)])
def test_inventory_accounts_for_scratch_released_by_collection(tmp_path, status, released):
    attempt = tmp_path / "Q01/attempt-1"
    attempt.mkdir(parents=True)
    (attempt / "kept.txt").write_bytes(b"kept")
    (attempt / "scratch_cleanup.json").write_text(json.dumps({
        "status": status, "bytes_released": 5_400_000_000,
    }))

    size = evaluate.disk(attempt)

    assert size["scratch"] == 0
    assert size["scratch_released"] == released
    assert size["total"] < 5_400_000_000


def test_an_attempt_without_a_final_answer_is_scored_on_what_it_kept(tmp_path):
    """OceanX's Q27 of the three-method batch: nine Expert reports, an error, and a score of 0."""
    runs = [make_arm(tmp_path / "runs", "A", "v2-nested", {"Q07": 2, "Q17": 2, "Q25": None}),
            make_arm(tmp_path / "runs", "B", "v2-nested", {"Q07": 2, "Q17": 2, "Q25": None})]
    for arm_dir in runs:  # Q17 ended on an error in both arms; only arm A kept executed work the judge scored
        result = arm_dir / "Q17" / "attempt-1" / "result.json"
        result.write_text(json.dumps({**json.loads(result.read_text()), "status": "failed"}))
        (arm_dir / "Q17" / "attempt-1" / "answer.md").write_text("")
    eval_root = tmp_path / "eval"
    mapping = eval_root / "blind_map.json"
    evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(eval_root / "blind"), "--map", str(mapping)])
    entries = json.loads(mapping.read_text())
    for blind_id, entry in entries.items():
        # What the failed attempt kept reached the judge: the Expert's report and its figure.
        if entry["task_id"] == "Q17":
            assert list((eval_root / "blind" / blind_id).rglob("report.md"))
            assert list((eval_root / "blind" / blind_id).rglob("map.preview.png"))
    scores, added = write_scores(eval_root, mapping, lambda entry: 2 if (
        entry["status"] == "completed" or (entry["task_id"], entry["arm"]) == ("Q17", "A")) else None)
    prereg = eval_root / "preregistration.yaml"
    prereg.write_text("experiment: unit\nfailed_attempt_score: 0\nbootstrap: {resamples: 200, seed: 1}\n"
                      "comparisons:\n  - name: kept\n    treatment: A\n    control: B\n"
                      "    rule: {type: superior, margin: 0}\n")
    evaluate.main(["freeze", "--prereg", str(prereg)])
    assert evaluate.main(["validate", "--scores", str(scores), "--added", str(added)]) == 0
    evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                   "--added", str(added), "--out", str(eval_root / "report")])
    summary = json.loads((eval_root / "report" / "summary.json").read_text())
    assert summary["cells"]["A|Q17"]["score"] == 50 and summary["cells"]["B|Q17"]["score"] == 0
    assert summary["arms"]["A"]["failures"] == 2 and summary["arms"]["A"]["failures_scored"] == 1
    assert summary["arms"]["B"]["failures"] == 2 and summary["arms"]["B"]["failures_scored"] == 0
    report = (eval_root / "report" / "report.md").read_text()
    assert "Attempts not completed (judged on what they kept)" in report and "| 2 (1) |" in report


def test_the_messages_of_an_attempt_without_a_final_answer_reach_the_judge(tmp_path):
    """Claude Code writes its narrative to partial_answer.md; without an answer it is what was delivered."""
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / "partial_answer.md").write_text("Loaded 2011-2015; the mixed layer deepens to 58 m in January.")
    assert [p.name for p in evaluate.evidence_files(attempt) if p.is_file()] == ["partial_answer.md"]
    (attempt / "answer.md").write_text("   \n")  # an empty answer is no answer
    assert [p.name for p in evaluate.evidence_files(attempt) if p.is_file()] == ["answer.md", "partial_answer.md"]
    (attempt / "answer.md").write_text("# Final report")
    # With a final answer the judge reads that, as before.
    assert [p.name for p in evaluate.evidence_files(attempt) if p.is_file()] == ["answer.md"]


# --- frozen rubrics ------------------------------------------------------------------------------
def frozen_copy(task, root, change=None):
    """A rubric as the reference work leaves it: the repository's draft with every waiting place
    filled, beside the folder of that work. `change` damages the copy before it is written."""
    draft = evaluate.rubric(task)
    doc = json.loads(json.dumps(draft))
    for group, index, key in evaluate.places_to_freeze(draft):
        item = evaluate._items(doc, group)[index]
        if group == "candidate_causes":
            item[key] = "partly supported"
        elif (group, key) == ("criteria", "expected"):
            item[key] = "partly reproduced: low-stratification layer at 60-240 m in the reanalysis eddy core"
        elif key == "expected":
            item[key] = "0.42 days per decade (0.31 to 0.55 across the three baselines)"
        else:  # the suggested tolerance, made final
            item[key] = item[key].split("suggested: ", 1)[1].rstrip(")") if "suggested: " in item[key] else "+/-10%"
    work = root / "references" / task
    (work / "outputs").mkdir(parents=True, exist_ok=True)
    (work / "spec.md").write_text("definitions, written before anything was computed")
    (work / "compute.py").write_text("print('reference')")
    (work / "outputs" / "values.json").write_text(json.dumps({"task": task, "items": []}))
    doc["status"] = "frozen"
    doc["frozen"] = {"references_sha256": evaluate.outputs_sha256(work / "outputs"),
                     "tolerances_frozen_at": "2026-10-09", "frozen_by": "Codex"}
    if change:
        change(doc)
    path = root / "rubrics" / f"{task}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(doc))
    return doc


def rubric_check(root, capsys, *tasks):
    code = evaluate.main(["rubric-check", "--rubrics", str(root / "rubrics"),
                          "--references", str(root / "references"), *(["--tasks", *tasks] if tasks else [])])
    return code, json.loads(capsys.readouterr().out)


def test_filled_rubrics_with_their_reference_work_are_ready_to_judge(tmp_path, capsys):
    # A paper task, one with a finding that cannot be tested, an open problem, a disagreement question.
    frozen = {task: frozen_copy(task, tmp_path) for task in ("Q08", "Q10", "Q25", "Q27")}
    code, report = rubric_check(tmp_path, capsys)
    assert code == 0 and report["ready"] == ["Q08", "Q10", "Q25", "Q27"] and report["not_ready"] == {}
    assert report["references_sha256"] == {task: doc["frozen"]["references_sha256"] for task, doc in frozen.items()}
    # The finding that cannot be tested keeps the repository's "n/a": nothing waited to be filled there.
    k4 = next(c for c in frozen["Q10"]["criteria"] if c["id"] == "Q10-K4")
    assert (k4["expected"], k4["tolerance"]) == ("n/a", "n/a")


def criterion(doc, cid):
    return next(c for c in doc["criteria"] if c["id"] == cid)


RUBRIC_DAMAGE = [
    ("Q08", lambda d: criterion(d, "Q08-K1").update(expected=evaluate.rubric("Q08")["criteria"][0]["expected"]),
     "Q08-K1 expected: not filled"),
    ("Q08", lambda d: criterion(d, "Q08-K2").update(tolerance=" "), "Q08-K2 tolerance: not filled"),
    ("Q08", lambda d: criterion(d, "Q08-K1").update(expected="low-stratification layer at 60-240 m"),
     "Q08-K1 expected: must begin with a verdict"),
    ("Q08", lambda d: criterion(d, "Q08-K1").pop("tolerance"), "Q08-K1 tolerance: missing"),
    ("Q08", lambda d: criterion(d, "Q08-K1").update(weight=20), "outside the places to freeze: criteria"),
    ("Q08", lambda d: criterion(d, "Q08-M")["anchors"].update({"4": "any method at all"}),
     "outside the places to freeze: criteria"),
    ("Q10", lambda d: criterion(d, "Q10-K4").update(expected="reproduced"), "outside the places to freeze: criteria"),
    ("Q27", lambda d: d["depth_probes"].pop(), "outside the places to freeze: depth_probes"),
    ("Q27", lambda d: d["candidate_causes"][0].update(expected="mostly supported"),
     "Q27-H1 expected: must be one of supported, partly supported, not supported"),
    ("Q27", lambda d: d["answer_key"]["items"].pop(), "Q27-A2 expected: missing"),
    ("Q27", lambda d: d.update(gates=[]), "outside the places to freeze: gates"),
    ("Q25", lambda d: d.update(status="draft"), 'status is not "frozen"'),
    ("Q25", lambda d: d["frozen"].update(frozen_by=""), "frozen_by must be set"),
    ("Q25", lambda d: d["frozen"].update(references_sha256="0" * 64), "references_sha256 is not the hash"),
    ("Q25", lambda d: d.update(query_sha256="0" * 64), "outside the places to freeze: query_sha256"),
]


@pytest.mark.parametrize("task, damage, said", RUBRIC_DAMAGE)
def test_rubric_check_names_what_is_wrong_with_a_rubric(tmp_path, capsys, task, damage, said):
    frozen_copy(task, tmp_path, damage)
    frozen_copy("Q24", tmp_path)  # a sound one beside it stays ready
    code, report = rubric_check(tmp_path, capsys)
    assert code == 1 and report["ready"] == ["Q24"] and list(report["not_ready"]) == [task]
    assert any(said in problem for problem in report["not_ready"][task]), report["not_ready"][task]


def test_rubric_check_follows_the_reference_work_and_the_files_present(tmp_path, capsys):
    frozen_copy("Q08", tmp_path)
    work = tmp_path / "references" / "Q08"
    # The outputs changed after the rubric was frozen.
    (work / "outputs" / "values.json").write_text('{"items": ["recomputed"]}')
    code, report = rubric_check(tmp_path, capsys)
    assert code == 1 and "references_sha256 is not the hash of references/Q08/outputs" in report["not_ready"]["Q08"][0]
    assert report["references_sha256"]["Q08"] == evaluate.outputs_sha256(work / "outputs")  # what it is now
    (work / "outputs" / "values.json").unlink()
    (work / "spec.md").unlink()
    _, report = rubric_check(tmp_path, capsys)
    assert report["not_ready"]["Q08"] == ["references/Q08/spec.md is missing", "references/Q08/outputs has no files"]
    # A draft copied as it is, a file that is not JSON, a task that does not exist, a task with no file.
    (tmp_path / "rubrics" / "Q09.json").write_text(json.dumps(evaluate.rubric("Q09")))
    (tmp_path / "rubrics" / "Q07.json").write_text("{")
    (tmp_path / "rubrics" / "Q99.json").write_text("{}")
    code, report = rubric_check(tmp_path, capsys, "Q07", "Q09", "Q15", "Q99")
    assert code == 1 and report["ready"] == []
    assert report["not_ready"]["Q07"] == ["not valid JSON"]
    assert report["not_ready"]["Q15"] == ["no frozen rubric file"]
    assert report["not_ready"]["Q99"] == ["no task Q99 in the repository"]
    waiting = [p for p in report["not_ready"]["Q09"] if p.endswith(": not filled")]
    assert len(waiting) == json.dumps(evaluate.rubric("Q09")).count(evaluate.PLACEHOLDER) == 10
    assert 'status is not "frozen"' in report["not_ready"]["Q09"]


def test_the_reference_hash_covers_file_names_and_contents(tmp_path):
    assert evaluate.outputs_sha256(tmp_path / "absent") is None and evaluate.outputs_sha256(tmp_path) is None
    (tmp_path / "tables").mkdir()
    (tmp_path / "values.json").write_text("1")
    (tmp_path / "tables" / "a.csv").write_text("x")
    first = evaluate.outputs_sha256(tmp_path)
    assert len(first) == 64 and evaluate.outputs_sha256(tmp_path) == first
    (tmp_path / "values.json").write_text("2")
    changed = evaluate.outputs_sha256(tmp_path)
    (tmp_path / "values.json").write_text("1")
    (tmp_path / "tables" / "a.csv").rename(tmp_path / "tables" / "b.csv")
    renamed = evaluate.outputs_sha256(tmp_path)
    (tmp_path / "tables" / "b.csv").rename(tmp_path / "tables" / "a.csv")
    (tmp_path / "extra.txt").write_text("")
    added = evaluate.outputs_sha256(tmp_path)
    assert len({first, changed, renamed, added}) == 4
    (tmp_path / "extra.txt").unlink()
    assert evaluate.outputs_sha256(tmp_path) == first


def test_every_draft_rubric_waits_only_in_the_places_the_check_knows(tmp_path):
    """215 places in the 30 rubrics, and no placeholder anywhere else in a rubric."""
    total = 0
    for path in sorted(evaluate.TASKS.glob("Q*/evaluator/rubric.json")):
        places = list(evaluate.places_to_freeze(json.loads(path.read_text())))
        assert len(places) == path.read_text().count(evaluate.PLACEHOLDER), path
        total += len(places)
    assert total == 215


def test_rubric_check_notices_a_question_reworded_after_its_rubric(tmp_path, capsys, monkeypatch):
    frozen_copy("Q25", tmp_path)
    assert rubric_check(tmp_path, capsys)[0] == 0
    reworded = {**evaluate.task_info("Q25"), "query": evaluate.task_info("Q25")["query"] + " Also map it."}
    monkeypatch.setattr(evaluate, "task_info", lambda task: reworded)
    code, report = rubric_check(tmp_path, capsys)
    assert code == 1 and report["not_ready"]["Q25"] == ["the question's text changed after the rubric was written"]


def judged_file(blind_id, task, levels, **fields):
    """A score file with one level per criterion letter."""
    criteria = evaluate.rubric(task)["criteria"]
    return {**score_file(blind_id, task, 0), **fields,
            "criteria": [{"id": c["id"], "score": levels[c["id"].rsplit("-", 1)[-1]], "evidence": "evidence/answer.md"}
                         for c in criteria]}


OPEN_LEVELS = {"F": 4, "A": 2, "Q": 3, "M": 2, "R": 4, "B": 1, "I": 4}
PAPER_LEVELS = {"K1": 4, "K2": 3, "K3": 2, "K4": 1, "K5": 0, "M": 2, "D": 4, "R": 3}


def test_the_six_indicators_are_the_judges_levels_and_their_mean_is_the_score():
    """ASPECT_SCORES.md: six indicators that count the same, each one plain number."""
    checkable = evaluate.rubric("Q21")
    # Nothing but the levels enters: not the delivery, not the counts the judge records beside them.
    score = judged_file("b1", "Q21", OPEN_LEVELS, delivered=False,
                        answer_key=[{"id": "Q21-A1", "result": "fail"}], probes={"depth_addressed": [], "breadth_addressed": []})
    values = evaluate.indicator_scores(checkable, score)
    assert values == {"Framing": 100, "Correctness": 75, "Depth": 50, "Breadth": 25, "Robustness": 100,
                      "Rigor": 75}  # rigor: data handling (A) and insight (I) together
    assert evaluate.whole_mean(values.values()) == pytest.approx(425 / 6)

    paper = evaluate.rubric("Q09")  # findings K1, K2 (20 points each), K3 to K5 (10 each); M, D, R
    findings = [{"id": f"Q09-K{n}", "agent_verdict": "reproduced", "matches_reference": n <= 2} for n in range(1, 6)]
    score, beside = judged_file("b3", "Q09", PAPER_LEVELS, findings=findings), added_file("b3", "Q09", {"S": 3, "A": 1.5})
    values = evaluate.indicator_scores(paper, score, beside)
    assert values == {"Finding tests": pytest.approx(25 * 170 / 70),  # the findings by their weights in the rubric
                      "Right verdicts": 40, "Method fidelity": 50, "Differences explained": 100,
                      "Robustness": 75, "Rigor": 37.5}
    # The report criterion of the rubric enters no indicator.
    assert evaluate.indicator_scores(paper, judged_file("b3", "Q09", {**PAPER_LEVELS, "R": 0}, findings=findings), beside) == values

    # An indicator stays empty, and the score with it, until the judge has recorded what it needs.
    waiting = evaluate.indicator_scores(paper, score)
    assert (waiting["Robustness"], waiting["Rigor"], waiting["Method fidelity"]) == (None, None, 50)
    assert evaluate.whole_mean(waiting.values()) is None
    unfinished = judged_file("b3", "Q09", PAPER_LEVELS, findings=[*findings[:4], {"id": "Q09-K5", "agent_verdict": "missing"}])
    assert evaluate.indicator_scores(paper, unfinished, beside)["Right verdicts"] is None

    # An attempt without a score file counts 0 in every indicator.
    assert evaluate.indicator_scores(paper, None) == dict.fromkeys(values, 0)
    assert evaluate.indicator_scores(checkable, None)["Framing"] == 0


def test_indicators_average_questions_and_repeats_per_arm(tmp_path):
    runs = [make_arm(tmp_path / "r1", "A", "v2-nested", {"Q21": 2, "Q20": 2, "Q09": 2}),
            make_arm(tmp_path / "r2", "A", "v2-nested", {"Q21": 2}),  # a repeat of one question
            make_arm(tmp_path / "r1", "B", "v2-nested", {"Q21": None, "Q09": 2})]  # Q21 failed, nothing executed
    # Arm B's paper task ended with a whole report, but its runner recorded another status.
    relabelled = runs[2] / "Q09" / "attempt-1" / "result.json"
    relabelled.write_text(json.dumps({**json.loads(relabelled.read_text()), "status": "needs_interaction"}))
    eval_root = tmp_path / "eval"
    mapping, scores, added, out = (eval_root / name for name in ("blind_map.json", "scores", "added", "indicators"))
    evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(eval_root / "blind"), "--map", str(mapping)])
    scores.mkdir()
    added.mkdir()
    findings = [{"id": f"Q09-K{n}", "agent_verdict": "reproduced", "matches_reference": n <= 2} for n in range(1, 6)]
    for blind_id, entry in json.loads(mapping.read_text()).items():
        task, repeat = entry["task_id"], "r2" in entry["arm_dir"]
        if entry["status"] == "failed":
            continue
        if task == "Q09":
            score = judged_file(blind_id, task, PAPER_LEVELS, findings=findings)
            (added / f"{blind_id}.json").write_text(json.dumps(added_file(blind_id, task, {"S": 3, "A": 1.5})))
        else:
            score = judged_file(blind_id, task, {**OPEN_LEVELS, "F": 0 if repeat else 4}, delivered=not repeat)
        (scores / f"{blind_id}.json").write_text(json.dumps(score))
    judged = ["--map", str(mapping), "--scores", str(scores), "--added", str(added), "--out", str(out)]
    assert evaluate.main(["indicators", *judged, "--arms", "B", "A"]) == 0
    result = json.loads((out / "indicators.json").read_text())
    assert result["arms"] == ["B", "A"] and result["not_judged"] == {} and len(result["without_score_file"]) == 1
    a, b = result["summary"]["open_problem"]["A"], result["summary"]["open_problem"]["B"]
    # Arm A: the two runs of Q21 are averaged first (framing 100 and 0), then with Q20.
    assert a["indicators"] == {"Framing": 75, "Correctness": 75, "Depth": 50, "Breadth": 25, "Robustness": 100, "Rigor": 75}
    # The six means make up the arm's score as the six indicators make up an attempt's score.
    assert a["score"] == pytest.approx(400 / 6)
    assert a["score"] == pytest.approx(evaluate.statistics.fmean([(425 / 6 + 325 / 6) / 2, 425 / 6]))
    # Arm B: its only open problem was not scored and counts 0 everywhere.
    assert b == {"indicators": dict.fromkeys(a["indicators"], 0), "score": 0}
    beside = result["beside"]["open_problem"]
    assert (beside["A"]["questions"], beside["A"]["attempts"], beside["A"]["not_delivered"]) == (2, 3, 1)
    assert not {"hours", "tokens"} & set(beside["A"]) and not {"tokens", "elapsed_seconds"} & set(result["attempts"][0])
    assert (beside["B"]["without_score_file"], beside["B"]["not_completed"], beside["B"]["not_delivered"]) == (1, 1, 1)
    paper = result["summary"]["paper_reproduction"]
    assert paper["A"] == paper["B"] and paper["A"]["score"] == pytest.approx((25 * 170 / 70 + 40 + 50 + 100 + 75 + 37.5) / 6)
    # Delivery is the judge's record for the attempt it judged, whatever status the runner wrote.
    [flagged] = result["delivered_with_other_status"]
    assert json.loads(mapping.read_text())[flagged]["task_id"] == "Q09" and result["beside"]["paper_reproduction"]["B"]["not_completed"] == 1
    report = (out / "indicators.md").read_text()
    assert "| Framing (问题拆解) | Is the question turned into testable hypotheses? | 0.0 | 75.0 |" in report
    assert "| **Score (mean of the six)** | | **0.0** | **66.7** |" in report and "## Paper verification (论文验证题)" in report
    assert "Hours" not in report and "Tokens" not in report  # time and tokens are not reported with the results
    import importlib.util
    drawn = importlib.util.find_spec("matplotlib")
    if drawn:
        assert (out / "six-indicators.png").stat().st_size > 10_000 and (out / "six-indicators.svg").is_file()
    # Three arms at most are drawn; the table does not depend on the chart.
    assert "three" in evaluate.indicator_chart(result["summary"], result["beside"], ["A", "B", "C", "D"], out)
    with pytest.raises(SystemExit):
        evaluate.main(["indicators", *judged, "--arms", "Z"])
    # A paper attempt whose two added criteria are not judged yet: named, no score, and the exit status says so.
    (added / f"{flagged}.json").unlink()
    assert evaluate.main(["indicators", *judged]) == 1
    result = json.loads((out / "indicators.json").read_text())
    assert result["not_judged"] == {flagged: ["Robustness", "Rigor"]}
    waiting = result["summary"]["paper_reproduction"]["B"]
    assert waiting["score"] is None and waiting["indicators"]["Rigor"] is None and waiting["indicators"]["Right verdicts"] == 40
    assert result["summary"]["paper_reproduction"]["A"]["score"] is not None
    report = (out / "indicators.md").read_text()
    assert "## Not judged yet" in report
    assert "| Rigor (严谨性) | Are the data handled right and fit for the findings? | 37.5 |  |" in report  # empty, not 0
    if drawn:  # the chart is still drawn, with a gap where the indicator is missing
        assert (out / "six-indicators.png").stat().st_size > 10_000
    checked = evaluate.validate(evaluate.argparse.Namespace(scores=scores, added=added))
    assert checked["invalid"] == {} and checked["added"] == {"files": 1, "invalid": {}, "paper_attempts_without": [flagged]}
    # A file of added criteria that is not valid stops the command; it is not read as far as it goes.
    (added / f"{flagged}.json").write_text(json.dumps(added_file(flagged, "Q09", 5)))
    with pytest.raises(SystemExit, match="invalid file of added criteria"):
        evaluate.main(["indicators", *judged])
