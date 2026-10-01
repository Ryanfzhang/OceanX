"""Blinding, score validation and the paired summary; no models or agents."""
import json

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
    (arm_dir / "arm.json").write_text(json.dumps({"arm": arm, "policy": policy, "lessons": None}))
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
    assert set(policy["by_type"]) == {"paper_reproduction", "open_problem"}
    assert policy["by_data"]["public"]["tasks"] == 2 and policy["by_data"]["private"]["tasks"] == 2
    assert summary["arms"]["A"]["failures"] == 1  # Q01 failed in both arms and scored 0
    assert "meets rule" in (eval_root / "report" / "report.md").read_text()
    prereg.write_text(prereg.read_text() + "# edited\n")
    with pytest.raises(SystemExit):  # changed after freezing
        evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping), "--scores", str(scores),
                       "--out", str(eval_root / "report2")])


def test_lessons_check(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "arm_lessons.json").write_text(json.dumps({"unchanged": True}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "arm_lessons.json").write_text(json.dumps({"sha256_before": "x"}))
    report = evaluate.lessons_check(type("A", (), {"runs": tmp_path})())
    assert report["checked"] == 2 and report["changed_or_unfinished"] == [str(tmp_path / "b" / "arm_lessons.json")]


def make_tree(attempt, task, *, side_tokens, planning_opened):
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
         "skills_read": ["research-trajectory-planning"] if planning_opened else []}])
    tree.label("B1.1", "decision-changing", labeler="model-judge", source="judge")
    tree.label("B1.2", "informative-but-not-decisive", labeler="model-judge", source="judge")


def test_process_measures_compare_arms_on_the_research_tree(tmp_path):
    runs = []
    for repeat, control_side in ((1, 3_000_000), (2, 2_000_000)):
        for arm, side in (("B", control_side), ("C1", 1_000_000)):
            arm_dir = make_arm(tmp_path / f"r{repeat}", arm, "v2-nested", {"Q07": 2, "Q17": 2, "Q25": None})
            for task in ("Q07", "Q17"):
                make_tree(arm_dir / task / "attempt-1", task, side_tokens=side, planning_opened=arm == "C1")
            runs.append(arm_dir)
    prereg = tmp_path / "preregistration.yaml"
    prereg.write_text("experiment: unit\nbootstrap: {resamples: 200, seed: 1}\ncomparisons: []\n"
                      "process_comparisons:\n  - {name: lessons-L1-process, metric: nondecisive_token_share, "
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
    [comparison] = result["comparisons"]
    assert comparison["tasks"] == 2 and comparison["decision"] is True
    assert comparison["mean_diff"] == pytest.approx(0.5 - (0.75 + 2 / 3) / 2)
    assert comparison["control_repeat_noise"] == pytest.approx(0.75 - 2 / 3)
    assert "meets rule" in (out / "process.md").read_text()
    # Without a pre-registration the measures are still reported; nothing is decided.
    evaluate.main(["process", "--runs", str(runs[0]), "--out", str(tmp_path / "plain")])
    assert json.loads((tmp_path / "plain" / "process.json").read_text())["comparisons"] == []
