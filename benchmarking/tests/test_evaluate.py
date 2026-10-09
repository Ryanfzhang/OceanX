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
    # An attempt without a final answer, judged on what it kept, needs the frozen rubric like any other.
    assert evaluate.validate_score({**good, "status": "failed", "rubric_status": "draft"})
    assert evaluate.validate_score({**good, "status": "failed"}) == []
    missing = json.loads(json.dumps(good))
    missing["criteria"][0]["evidence"] = ""
    assert evaluate.validate_score(missing)
    wrong = json.loads(json.dumps(good))
    wrong["criteria"][0]["score"] = 5
    assert evaluate.validate_score(wrong)
    # Whether the attempt delivered is recorded in every score file.
    assert evaluate.validate_score({key: value for key, value in good.items() if key != "delivered"})
    assert evaluate.validate_score({**good, "delivered": "yes"})
    assert evaluate.validate_score({**good, "delivered": False}) == []


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
    scores = eval_root / "scores"
    scores.mkdir()
    for blind_id, entry in entries.items():
        # What the failed attempt kept reached the judge: the Expert's report and its figure.
        if entry["task_id"] == "Q17":
            assert list((eval_root / "blind" / blind_id).rglob("report.md"))
            assert list((eval_root / "blind" / blind_id).rglob("map.preview.png"))
        if entry["status"] == "completed" or (entry["task_id"], entry["arm"]) == ("Q17", "A"):
            (scores / f"{blind_id}.json").write_text(json.dumps(
                {**score_file(blind_id, entry["task_id"], 2), "status": entry["status"]}))
    prereg = eval_root / "preregistration.yaml"
    prereg.write_text("experiment: unit\nfailed_attempt_score: 0\nbootstrap: {resamples: 200, seed: 1}\n"
                      "comparisons:\n  - name: kept\n    treatment: A\n    control: B\n"
                      "    rule: {type: superior, margin: 0}\n")
    evaluate.main(["freeze", "--prereg", str(prereg)])
    assert evaluate.main(["validate", "--scores", str(scores)]) == 0
    evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                   "--out", str(eval_root / "report")])
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
    """A score file with one level per criterion letter and the counts the indicators read."""
    criteria = evaluate.rubric(task)["criteria"]
    given = {c["id"]: levels[c["id"].rsplit("-", 1)[-1]] for c in criteria}
    return {**score_file(blind_id, task, 0), **fields,
            "criteria": [{"id": cid, "score": level, "evidence": "evidence/answer.md"} for cid, level in given.items()],
            "total": sum(c["weight"] * given[c["id"]] / 4 for c in criteria)}


OPEN_LEVELS = {"F": 4, "A": 2, "Q": 3, "M": 2, "R": 4, "B": 1, "I": 4}
PAPER_LEVELS = {"K1": 4, "K2": 3, "K3": 2, "K4": 1, "K5": 0, "M": 2, "D": 4, "R": 3}


def test_indicator_parts_follow_the_definition():
    """ASPECT_SCORES.md: judged parts divide the rubric total; counts and delivery stand beside them."""
    checkable = evaluate.rubric("Q21")  # answer key A1, A2 used by Q; three depth probes, two breadth probes
    score = judged_file("b1", "Q21", OPEN_LEVELS, delivered=False,
                        answer_key=[{"id": "Q21-A1", "result": "pass"}, {"id": "Q21-A2", "result": "fail"},
                                    {"id": "Q21-A3", "result": "pass"}],  # A3 belongs to M and is not counted
                        probes={"depth_addressed": [1, 3], "breadth_addressed": [2]})
    parts, holes = evaluate.indicator_parts(checkable, score)
    assert holes == []
    assert parts["Framing"] == {"judged": 100, "counted": None, "run": None, "combined": 100}
    assert parts["Correctness"] == {"judged": 75, "counted": 50, "run": None, "combined": 68.75}
    assert parts["Depth"]["counted"] == pytest.approx(200 / 3)
    assert parts["Depth"]["combined"] == pytest.approx(0.75 * 50 + 0.25 * 200 / 3)
    assert parts["Breadth"] == {"judged": 25, "counted": 50, "run": None, "combined": 31.25}
    assert parts["Robustness"] == {"judged": 100, "counted": None, "run": 0.0, "combined": 75.0}
    assert parts["Rigor"]["combined"] == 75  # A and I together
    points = {"Framing": 10, "Correctness": 20, "Depth": 20, "Breadth": 15, "Robustness": 15, "Rigor": 20}
    assert sum(parts[name]["judged"] * weight / 100 for name, weight in points.items()) == pytest.approx(score["total"])

    disagreement = evaluate.rubric("Q20")  # two depth probes and four candidate causes
    causes = [{"id": f"Q20-H{n}", "tested": n != 4} for n in (1, 2, 3, 4)]
    score = judged_file("b2", "Q20", OPEN_LEVELS, causes=causes, probes={"depth_addressed": [1], "breadth_addressed": []},
                        answer_key=[{"id": "Q20-A1", "result": "partial"}, {"id": "Q20-A2", "result": "not_reported"}])
    parts, holes = evaluate.indicator_parts(disagreement, score)
    assert holes == [] and parts["Depth"]["counted"] == (50 + 75) / 2  # probes and causes count alike
    assert parts["Correctness"]["counted"] == 25 and parts["Breadth"]["counted"] == 0
    assert parts["Robustness"]["combined"] == 100  # judged 100 and the attempt delivered

    paper = evaluate.rubric("Q09")  # findings K1, K2 (20 points each), K3 to K5 (10 each); M, D, R
    findings = [{"id": f"Q09-K{n}", "agent_verdict": "missing" if n == 5 else "reproduced",
                 "matches_reference": n <= 2, "evidence_ok": n <= 3} for n in range(1, 6)]
    score = judged_file("b3", "Q09", PAPER_LEVELS, findings=findings)
    parts, holes = evaluate.indicator_parts(paper, score)
    assert holes == []
    assert parts["Finding tests"]["judged"] == pytest.approx(100 * 55 / 70) and parts["Finding tests"]["counted"] == 80
    assert parts["Right verdicts"]["judged"] == pytest.approx(100 * 30 / 70) and parts["Right verdicts"]["counted"] == 40
    assert parts["Right verdicts"]["combined"] == pytest.approx(0.75 * 100 * 30 / 70 + 10)
    assert parts["Method fidelity"]["combined"] == 50 and parts["Differences explained"]["combined"] == 100
    assert parts["Traceability"] == {"judged": 75, "counted": 60, "run": None, "combined": 71.25}
    assert parts["Robustness"] == {"judged": None, "counted": None, "run": 100.0, "combined": 100.0}
    points = {"Finding tests": 35, "Right verdicts": 35, "Method fidelity": 10, "Differences explained": 10,
              "Traceability": 10}
    assert sum(parts[name]["judged"] * weight / 100 for name, weight in points.items()) == pytest.approx(score["total"])

    # An attempt without a score file counts 0 in every part; nothing is reported as left out.
    parts, holes = evaluate.indicator_parts(checkable, None)
    assert holes == [] and {name: value["combined"] for name, value in parts.items()} == dict.fromkeys(parts, 0)
    assert parts["Correctness"]["counted"] == 0 and parts["Framing"]["counted"] is None

    # A score file that leaves counts out: each counts as not met and is named.
    bare = judged_file("b4", "Q20", OPEN_LEVELS, causes=causes[:2], probes={"depth_addressed": [1, 9]})
    parts, holes = evaluate.indicator_parts(disagreement, bare)
    assert parts["Correctness"]["counted"] == 0 and parts["Depth"]["counted"] == (50 + 50) / 2
    assert holes == ["probes: depth_addressed must list numbers from 1 to 2",
                     "causes: Q20-H3 has no usable tested", "causes: Q20-H4 has no usable tested",
                     "answer_key: Q20-A1 has no usable result", "answer_key: Q20-A2 has no usable result",
                     "probes: breadth_addressed must list numbers from 1 to 1"]


def test_indicators_average_questions_and_repeats_per_arm(tmp_path):
    runs = [make_arm(tmp_path / "r1", "A", "v2-nested", {"Q21": 2, "Q20": 2, "Q09": 2}),
            make_arm(tmp_path / "r2", "A", "v2-nested", {"Q21": 2}),  # a repeat of one question
            make_arm(tmp_path / "r1", "B", "v2-nested", {"Q21": None, "Q09": 2})]  # Q21 failed, nothing executed
    # Arm B's paper task ended with a whole report, but its runner recorded another status.
    relabelled = runs[2] / "Q09" / "attempt-1" / "result.json"
    relabelled.write_text(json.dumps({**json.loads(relabelled.read_text()), "status": "needs_interaction"}))
    eval_root = tmp_path / "eval"
    mapping, scores, out = eval_root / "blind_map.json", eval_root / "scores", eval_root / "indicators"
    evaluate.main(["blind", "--runs", *map(str, runs), "--out", str(eval_root / "blind"), "--map", str(mapping)])
    scores.mkdir()
    counts = {"Q21": {"answer_key": [{"id": "Q21-A1", "result": "pass"}, {"id": "Q21-A2", "result": "pass"}],
                      "probes": {"depth_addressed": [1, 2, 3], "breadth_addressed": [1, 2]}},
              "Q20": {"answer_key": [{"id": "Q20-A1", "result": "pass"}, {"id": "Q20-A2", "result": "pass"}],
                      "probes": {"depth_addressed": [1, 2], "breadth_addressed": [1]},
                      "causes": [{"id": f"Q20-H{n}", "tested": True} for n in (1, 2, 3, 4)]},
              "Q09": {"findings": [{"id": f"Q09-K{n}", "agent_verdict": "reproduced", "matches_reference": True,
                                    "evidence_ok": True} for n in range(1, 6)]}}
    for blind_id, entry in json.loads(mapping.read_text()).items():
        task, repeat = entry["task_id"], "r2" in entry["arm_dir"]
        if entry["status"] == "failed":
            continue
        levels = PAPER_LEVELS if task == "Q09" else {**OPEN_LEVELS, "F": 0 if repeat else 4}
        (scores / f"{blind_id}.json").write_text(json.dumps(judged_file(
            blind_id, task, levels, **counts[task], delivered=not repeat)))
    assert evaluate.main(["indicators", "--map", str(mapping), "--scores", str(scores), "--out", str(out),
                          "--arms", "B", "A"]) == 0
    result = json.loads((out / "indicators.json").read_text())
    assert result["arms"] == ["B", "A"] and result["holes"] == {} and len(result["without_score_file"]) == 1
    a, b = result["summary"]["open_problem"]["A"], result["summary"]["open_problem"]["B"]
    # Arm A: the two runs of Q21 are averaged first (framing 100 and 0, delivery 100 and 0), then with Q20.
    assert a["Framing"]["combined"] == pytest.approx((50 + 100) / 2)
    assert a["Robustness"]["run"] == pytest.approx((50 + 100) / 2)
    assert a["Robustness"]["combined"] == pytest.approx(0.75 * 100 + 0.25 * 75)
    assert a["Correctness"] == {"judged": 75, "counted": 100, "run": None, "combined": 81.25}
    # Arm B: its only open problem was not scored and counts 0 everywhere.
    assert {name: parts["combined"] for name, parts in b.items()} == dict.fromkeys(b, 0)
    beside = result["beside"]["open_problem"]
    assert (beside["A"]["questions"], beside["A"]["attempts"], beside["A"]["not_delivered"]) == (2, 3, 1)
    assert (beside["B"]["without_score_file"], beside["B"]["not_completed"], beside["B"]["not_delivered"]) == (1, 1, 1)
    # Delivery is the judge's record for the attempt it judged, whatever status the runner wrote.
    assert result["summary"]["paper_reproduction"]["B"]["Robustness"]["combined"] == 100
    [flagged] = result["delivered_with_other_status"]
    assert json.loads(mapping.read_text())[flagged]["task_id"] == "Q09" and result["beside"]["paper_reproduction"]["B"]["not_completed"] == 1
    report = (out / "indicators.md").read_text()
    assert "| Framing (问题拆解) | 0.0 | 75.0 |" in report and "## Paper verification (论文验证题)" in report
    import importlib.util
    if importlib.util.find_spec("matplotlib"):
        assert (out / "six-indicators.png").stat().st_size > 10_000 and (out / "six-indicators.svg").is_file()
    # Three arms at most are drawn; the table does not depend on the chart.
    assert "three" in evaluate.indicator_chart(result["summary"], result["beside"], ["A", "B", "C", "D"], out)
    with pytest.raises(SystemExit):
        evaluate.main(["indicators", "--map", str(mapping), "--scores", str(scores), "--out", str(out), "--arms", "Z"])
    # A count the judge left out is reported, and the command says so by its exit status.
    blind_id = next(path.stem for path in scores.glob("*.json") if json.loads(path.read_text())["task_id"] == "Q20")
    score = json.loads((scores / f"{blind_id}.json").read_text())
    del score["probes"]
    (scores / f"{blind_id}.json").write_text(json.dumps(score))
    assert evaluate.main(["indicators", "--map", str(mapping), "--scores", str(scores), "--out", str(out)]) == 1
    assert list(json.loads((out / "indicators.json").read_text())["holes"]) == [blind_id]
    assert "Entries the score files leave out" in (out / "indicators.md").read_text()
