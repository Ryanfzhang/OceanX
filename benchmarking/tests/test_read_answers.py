"""Reading the final answers of several arms against one list per question."""
import json

import read_answers

ANSWER = "## Summary\n" + "The upwelling is strongest in 1995 and the wind is excluded. " * 6


def arm_folder(root, arm, answers):
    folder = root / arm
    folder.mkdir(parents=True)
    (folder / "arm.json").write_text(json.dumps({"arm": arm}))
    for task_id, answer in answers.items():
        attempt = folder / task_id / "attempt-1"
        attempt.mkdir(parents=True)
        (attempt / "result.json").write_text("{}")
        (attempt / "query.json").write_text(json.dumps(
            {"id": task_id, "query": f"How strong is {task_id} in each year?"}))
        if answer is not None:
            (attempt / "answer.md").write_text(answer)
    return folder


def reader(calls, *, fail=()):
    """Lists two things per question; finds one gap and one strong conclusion in a "bare" answer."""
    def reply(prompt):
        if prompt.startswith("You prepare the list"):
            calls.append("asked")
            return json.dumps({"asked": ["the strength, for each year", "the main driver"]})
        calls.append("reading")
        if any(name in prompt for name in fail):
            return "no json"
        bare = "bare answer" in prompt
        return json.dumps({
            "asked": [{"item": 1, "status": "partly" if bare else "yes",
                       "missing": "No value per year." if bare else ""},
                      {"item": 2, "status": "yes", "missing": ""}],
            "overclaims": [{"claim": "The wind is excluded.", "why": "Not significant."}] if bare else [],
            "superseded": []})
    return reply


def test_arms_are_read_against_one_list_per_question_and_counted(tmp_path):
    plain = arm_folder(tmp_path / "runs", "OceanX", {"Q15": ANSWER + " bare answer", "Q20": ANSWER, "Q29": None})
    learned = arm_folder(tmp_path / "runs", "OceanX-L1", {"Q15": ANSWER, "Q20": ANSWER + " bare answer"})
    out, calls = tmp_path / "readings", []
    result = read_answers.read_runs([plain, learned], out, reader(calls), parallel=2)
    assert calls.count("asked") == 2 and calls.count("reading") == 4  # one list per question, not per arm
    assert result["arms"] == ["OceanX", "OceanX-L1"] and result["questions_read_in_every_arm"] == ["Q15", "Q20"]
    assert result["by_question"]["Q15"] == {
        "OceanX": {"asked": 2, "not_given": 1, "overclaims": 1, "superseded": 0},
        "OceanX-L1": {"asked": 2, "not_given": 0, "overclaims": 0, "superseded": 0}}
    assert result["totals"]["OceanX"] == result["totals"]["OceanX-L1"] == {
        "asked": 4, "not_given": 1, "overclaims": 1, "superseded": 0}
    assert result["skipped"] == [{"arm": "OceanX", "task_id": "Q29", "reason": "no question or no final answer"}]
    assert json.loads((out / "asked" / "Q15.json").read_text())["asked"][0] == "the strength, for each year"
    assert json.loads((out / "OceanX" / "Q15.json").read_text())["overclaims"][0]["claim"] == "The wind is excluded."
    page = (out / "readings.md").read_text()
    assert "| Q15 | 2 / 1 / 1 / 0 | 2 / 0 / 0 / 0 |" in page
    assert "| Total over the 2 questions read in every arm | 4 / 1 / 1 / 0 | 4 / 1 / 1 / 0 |" in page
    # Nothing is read twice, and an arm added later is read against the lists already kept.
    later = arm_folder(tmp_path / "runs", "OceanX-L1R", {"Q15": ANSWER})
    calls.clear()
    result = read_answers.read_runs([plain, learned, later], out, reader(calls))
    assert calls == ["reading"] and result["questions_read_in_every_arm"] == ["Q15"]
    assert result["by_question"]["Q20"].keys() == {"OceanX", "OceanX-L1"}


def test_a_reading_that_fails_is_reported_and_tried_again_next_time(tmp_path):
    plain = arm_folder(tmp_path / "runs", "OceanX", {"Q15": ANSWER + " unreadable", "Q20": ANSWER})
    out, calls = tmp_path / "readings", []
    result = read_answers.read_runs([plain], out, reader(calls, fail=("unreadable",)))
    assert result["failed"] == [{"arm": "OceanX", "task_id": "Q15", "reason": "The model returned no JSON object."}]
    assert list(result["by_question"]) == ["Q20"] and not (out / "OceanX" / "Q15.json").exists()
    assert "Failed:\n- Q15 (OceanX): The model returned no JSON object." in (out / "readings.md").read_text()
    calls.clear()
    assert read_answers.read_runs([plain], out, reader(calls))["failed"] == []
    assert calls == ["reading"]
