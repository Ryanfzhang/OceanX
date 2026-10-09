"""The independent reading of a final answer: one list per question, bounded readings, failed
calls, and what the meta-agent and the periodic update do with it."""
import json
import time
from types import SimpleNamespace

import pytest

from oceanx.research import referee
from oceanx.research.lessons import LessonBook
from oceanx.research.memory import ResearchMemory, task_key
from oceanx.research.outcomes import record_task_outcomes
from oceanx.research.referee import Referee, question_key, read_answer, reading_lines
from oceanx.research.review import ProjectResearch
from oceanx.research.tree import ResearchTree

SUMMARY = "Result: Flux explains onset.\nEvidence and limitations: One year.\nFurther analysis: None"
ANSWER = "## Summary\n" + "The upwelling is strongest in 1995 and the wind is excluded. " * 6


def finished_task(root, name, *, question=None, answer=ANSWER, finish=True):
    tree = ResearchTree(root / name / "agents" / "coordinator" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": question or f"How strong is {name} in each year?"},
        {"action": "add", "target": "B1", "question": "Index?", "status": "selected"},
    ])
    tree.attach_result("B1.1", summary=SUMMARY, agent_key="p", report_path="/r", attempt_id="a")
    if finish:
        record_task_outcomes(tree, final_report=answer or "", model_calls=[])
    if answer is not None:
        tree.path.with_name("report.md").write_text(answer, encoding="utf-8")
    return tree


@pytest.fixture
def memory(tmp_path):
    return ResearchMemory(tmp_path / ".oceanx" / "research")


READING = {"asked": [{"item": 1, "status": "partly", "missing": "Only the strongest year has a value."},
                     {"item": 2, "status": "yes", "missing": ""}],
           "overclaims": [{"claim": "The wind is excluded.", "why": "The test is not significant."}],
           "superseded": []}


def reader(asked=("the strength, for each year", "the main driver"), reading=READING, calls=None):
    """A model that lists what a question asks for, then reads an answer against the list."""
    def reply(prompt):
        listing = prompt.startswith("You prepare the list")
        if calls is not None:
            calls.append("asked" if listing else "reading")
        return json.dumps({"asked": list(asked)} if listing else reading)
    return reply


def test_a_finished_task_is_read_once_and_the_reading_is_kept(tmp_path, memory):
    tree = finished_task(tmp_path, "t1")
    memory.digest(tree.store.path)
    book, calls = Referee(memory), []
    result = book.read_new([tree.store.path], memory.load_digests(), reader(calls=calls))
    assert result == {"read": 1, "without_answer": 0, "failed": [], "left_for_later": 0}
    reading = book.readings()[task_key(tree.store.path)]
    assert reading["asked"] == [
        {"item": "the strength, for each year", "status": "partly",
         "missing": "Only the strongest year has a value."},
        {"item": "the main driver", "status": "yes", "missing": ""}]
    assert reading["overclaims"] == [{"claim": "The wind is excluded.", "why": "The test is not significant."}]
    assert reading["answer_chars"] == len(ANSWER) and reading["superseded"] == []
    assert calls == ["asked", "reading"]
    assert book.read_new([tree.store.path], memory.load_digests(), reader(calls=calls))["read"] == 0
    assert calls == ["asked", "reading"]  # nothing is read twice


def test_the_reader_sees_only_the_question_the_list_and_the_answer(tmp_path, memory):
    tree = finished_task(tmp_path, "t1", question="How strong is the upwelling in each year?")
    memory.digest(tree.store.path)
    prompts = []
    Referee(memory).read_new([tree.store.path], memory.load_digests(),
                             lambda prompt: prompts.append(prompt) or reader()(prompt))
    listing, reading = prompts
    assert "How strong is the upwelling in each year?" in listing and ANSWER.strip() not in listing
    assert "1. the strength, for each year\n2. the main driver" in reading and ANSWER.strip() in reading
    assert "Flux explains onset" not in reading  # no Expert result, only the final answer


def test_every_run_of_a_question_is_read_against_the_same_list(tmp_path, memory):
    question = "How strong is the upwelling in each year?"
    trees = [finished_task(tmp_path, name, question=question) for name in ("a", "b")]
    trees.append(finished_task(tmp_path, "c"))
    for tree in trees:
        memory.digest(tree.store.path)
    calls = []
    result = Referee(memory).read_new([t.store.path for t in trees], memory.load_digests(), reader(calls=calls))
    assert result["read"] == 3 and calls.count("asked") == 2 and calls.count("reading") == 3
    assert question_key("How strong  is the Upwelling, in each year") == question_key(question)


def test_a_task_without_a_final_answer_or_still_running_is_not_read(tmp_path, memory, monkeypatch):
    silent = finished_task(tmp_path, "silent", answer=None)
    running = finished_task(tmp_path, "running", finish=False)
    kept = finished_task(tmp_path, "kept")
    for tree in (silent, running, kept):
        memory.digest(tree.store.path)
    book, stores = Referee(memory), [t.store.path for t in (silent, running, kept)]
    result = book.read_new(stores, memory.load_digests(), reader())
    assert result == {"read": 1, "without_answer": 1, "failed": [], "left_for_later": 0}
    assert set(book.readings()) == {task_key(kept.store.path)}
    # One update reads a bounded number of tasks; the others wait for the next.
    more = [finished_task(tmp_path, name) for name in ("m1", "m2", "m3")]
    for tree in more:
        memory.digest(tree.store.path)
    monkeypatch.setattr(referee, "MAX_NEW_PER_UPDATE", 2)
    result = book.read_new([t.store.path for t in more], memory.load_digests(), reader())
    assert (result["read"], result["left_for_later"]) == (2, 1)


def test_a_call_that_fails_is_tried_twice_and_the_task_is_left_for_the_next_update(tmp_path, memory, monkeypatch):
    tree = finished_task(tmp_path, "t1")
    memory.digest(tree.store.path)
    replies = iter([RuntimeError("network"), json.dumps({"asked": ["the strength"]}),
                    "no json here", "still none"])

    def flaky(prompt):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    book = Referee(memory)
    result = book.read_new([tree.store.path], memory.load_digests(), flaky)
    assert result["read"] == 0 and result["failed"] == [
        {"task_key": task_key(tree.store.path), "reason": "The model returned no JSON object."}]
    assert book.readings() == {}
    # The list of the question was made and is kept; the next update reads the answer against it.
    calls = []
    assert book.read_new([tree.store.path], memory.load_digests(), reader(calls=calls))["read"] == 1
    assert calls == ["reading"]
    assert [entry["item"] for entry in book.readings()[task_key(tree.store.path)]["asked"]] == ["the strength"]

    monkeypatch.setattr(referee, "CALL_SECONDS", 0.05)
    slow = finished_task(tmp_path, "slow")
    memory.digest(slow.store.path)
    started = time.monotonic()
    result = book.read_new([slow.store.path], memory.load_digests(), lambda prompt: time.sleep(5) or "{}")
    assert result["failed"][0]["reason"] == "no reply within 0.05 s" and time.monotonic() - started < 2


def test_a_reading_keeps_only_what_was_asked_and_stays_bounded():
    reply = {"asked": [{"item": "2", "status": "no", "missing": "x " * 400}, {"item": 9, "status": "no"},
                       {"item": 1, "status": "maybe"}, "junk"],
             "overclaims": [{"claim": "", "why": "no claim"}, *({"claim": f"c{i}", "why": "w"} for i in range(12))],
             "superseded": [{"stale": "222 d", "corrected": "177 d"}, "junk"]}
    reading = read_answer("Q?", ["first", "second"], "answer", lambda prompt: json.dumps(reply))
    assert reading["asked"][0] == {"item": "first", "status": "unread", "missing": ""}
    assert reading["asked"][1]["status"] == "no" and len(reading["asked"][1]["missing"]) == 200
    assert [entry["claim"] for entry in reading["overclaims"]] == [f"c{i}" for i in range(referee.MAX_FINDINGS)]
    assert reading["superseded"] == [{"stale": "222 d", "corrected": "177 d"}]
    with pytest.raises(ValueError, match="judged none"):
        read_answer("Q?", ["first"], "answer", lambda prompt: json.dumps({"asked": [{"item": 3, "status": "no"}]}))
    lines = reading_lines({"asked": [{"item": f"item {i}", "status": "no", "missing": "m"} for i in range(9)],
                           "overclaims": [], "superseded": [{"stale": "222 d", "corrected": "177 d"}]})
    assert lines[0] == ("Independent reading of the final answer: of 9 things the question asks for, 9 "
                        "missing or partial; conclusions stronger than their support: 0; superseded numbers "
                        "still used: 1.")
    assert lines[1].count("(no: m)") == referee.SHOWN_ASKED and lines[1].endswith("| and 3 more")
    assert lines[2] == '  superseded but still used: "222 d", corrected to "177 d"'


def test_the_meta_agent_reads_the_reading_with_the_task_record(tmp_path, memory):
    read, unread = finished_task(tmp_path, "t1"), finished_task(tmp_path, "t2")
    for tree in (read, unread):
        memory.digest(tree.store.path)
    Referee(memory).read_new([read.store.path], memory.load_digests(), reader())
    for skill in ("research-trajectory-planning", "claim-grounded-writing"):
        prompt, fitted = LessonBook(memory).review_prompt(skill, memory.load_digests())
        assert fitted == 2
        assert prompt.count("Independent reading of the final answer: of 2 things the question asks "
                            "for, 1 missing or partial") == 1
        assert ("  not given: the strength, for each year (partly: Only the strongest year has a value.)"
                in prompt)
        assert '  stronger than its support: "The wind is excluded.": The test is not significant.' in prompt
        assert "About one such finding in three is wrong" in prompt
        assert "the same kind of gap left in the final answers of several tasks" in prompt
    regions = LessonBook.regions()
    assert "what the question asked for that the final answer did not give" in regions[
        "research-trajectory-planning"].about
    assert "claims stated more strongly than their evidence" in regions["claim-grounded-writing"].about


def test_the_periodic_update_reads_final_answers_before_the_review(tmp_path):
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    stores = [finished_task(tmp_path, f"t{i}").store.path for i in range(3)]
    assert "referee" not in project.update(stores)  # no model, nothing is read
    assert project.referee.readings() == {}
    seen = []

    def llm(prompt):
        seen.append(prompt)
        if "<skill name=" in prompt:
            return "{}"
        return reader()(prompt)

    result = project.update(stores, llm=llm)
    assert result["referee"] == {"read": 3, "without_answer": 0, "failed": [], "left_for_later": 0}
    first_review = next(i for i, prompt in enumerate(seen) if "<skill name=" in prompt)
    assert first_review == 6  # three lists and three readings, then the skills
    assert all("Independent reading of the final answer" in prompt for prompt in seen[first_review:])
    assert len(project.referee.readings()) == 3
