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
            "criteria": [{"id": c["id"], "score": level, "evidence": "evidence/answer.md"} for c in criteria],
            "total": sum(c["weight"] * level / 4 for c in criteria)}


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


def test_validate_catches_bad_scores():
    good = score_file("b1", "Q17", 3)
    assert evaluate.validate_score(good) == []
    assert evaluate.validate_score({**good, "total": 50})
    assert evaluate.validate_score({**good, "rubric_status": "draft"})
    missing = json.loads(json.dumps(good))
    missing["criteria"][0]["evidence"] = ""
    assert evaluate.validate_score(missing)
    wrong = json.loads(json.dumps(good))
    wrong["criteria"][0]["score"] = 5
    assert evaluate.validate_score(wrong)


def test_freeze_summarize_and_decisions(tmp_path):
    tasks = {"Q07": 2, "Q17": 2, "Q25": 2, "Q01": None}
    better = {"Q07": 4, "Q17": 3, "Q25": 3, "Q01": None}
    runs = [make_arm(tmp_path / "runs", "A", "v0-coordinator-bfs", tasks),
            make_arm(tmp_path / "runs", "B", "v2-nested", better)]
    eval_root = tmp_path / "eval"
    mapping = eval_root / "blind_map.json"
    evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(eval_root / "blind"), "--map", str(mapping)])
    scores = eval_root / "scores"
    scores.mkdir()
    for blind_id, entry in json.loads(mapping.read_text()).items():
        level = (better if entry["arm"] == "B" else tasks)[entry["task_id"]]
        if level is not None:
            (scores / f"{blind_id}.json").write_text(json.dumps(score_file(blind_id, entry["task_id"], level)))
    prereg = eval_root / "preregistration.yaml"
    prereg.write_text("experiment: unit\nfailed_attempt_score: 0\nbootstrap: {resamples: 200, seed: 1}\n"
                      "comparisons:\n  - name: policy\n    treatment: B\n    control: A\n"
                      "    rule: {type: noninferior_and_better_or_cheaper, margin: -2, token_reduction: 0.15}\n")
    with pytest.raises(SystemExit):  # not frozen yet
        evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                       "--out", str(eval_root / "report")])
    evaluate.main(["freeze", "--prereg", str(prereg)])
    evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                   "--out", str(eval_root / "report")])
    summary = json.loads((eval_root / "report" / "summary.json").read_text())
    policy = summary["comparisons"][0]
    assert policy["tasks"] == 4 and policy["mean_diff"] > 0 and policy["decision"] is True
    assert policy["token_reduction"] == 0 and policy["time_reduction"] == 0  # both arms cost the same here
    assert set(policy["by_type"]) == {"paper_reproduction", "open_problem"}
    assert policy["by_data"]["public"]["tasks"] == 2 and policy["by_data"]["private"]["tasks"] == 2
    assert summary["arms"]["A"]["failures"] == 1  # Q01 failed in both arms and scored 0
    assert "meets rule" in (eval_root / "report" / "report.md").read_text()
    prereg.write_text(prereg.read_text() + "# edited\n")
    with pytest.raises(SystemExit):  # changed after freezing
        evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                       "--out", str(eval_root / "report2")])


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
    mapping = tmp_path / "eval" / "blind_map.json"
    evaluate.main(["blind", "--runs", str(arm_dir), "--out", str(tmp_path / "eval" / "blind"), "--map", str(mapping)])
    tokens = {entry["task_id"]: (entry["tokens"], entry["usage"]["source"])
              for entry in json.loads(mapping.read_text()).values()}
    # Without a state folder the end-of-run report is all there is.
    assert tokens == {"Q07": (10550, "ledger"), "Q17": (1100, "result.json")}


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
    assert full["code_runs"] == {"total": 2, "by_state": {"failed": 1, "succeeded": 1}}
    assert full["tree"]["finished"] and full["tree"]["questions_answered"] == 2
    # Every Markdown file of the run is listed by kind; the agents' copies of skills are not.
    kinds = sorted((d["kind"], d["node"]) for d in full["documents"])
    assert kinds == [("conversation history", None), ("final report", None), ("question report", "B1.1"),
                     ("question report", "B1.2"), ("report version", "B1.1")]
    assert full["conversations"] == {"checkpoint_bytes": 1200, "written_after_last_model_call": True,
                                     "history_files": 1, "history_bytes": 20}
    assert full["disk"]["scratch"] == 2000 and full["disk"]["total"] > 2000
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
