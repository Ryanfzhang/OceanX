"""The independent reading of a final answer: one list per question, bounded readings, the
reader's notes as a reviewer, a critic's outline, a reviewer's own notes, failed calls, and what
the meta-agent and the periodic update do with them."""
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


NOTES = [{"aspect": "depth", "text": "A ranking of the candidate drivers on one annual index.", "general": True},
         {"aspect": "results", "text": "The strength at the second cape.", "general": False},
         {"aspect": "breadth", "text": "The yearly values set against published indices.", "general": True}]


POINTS = [{"point": "Rank every candidate driver on the same annual index", "status": "no",
           "missing": "Each driver is tested alone."},
          {"point": "Give the strength for every year in one table", "status": "yes", "missing": "It is all there."},
          {"point": "Set the yearly values beside a published index", "status": "partly",
           "missing": "Two of five years."}]


def reader(asked=("the strength, for each year", "the main driver"), reading=READING, calls=None,
           notes=NOTES, points=POINTS):
    """A model that lists what a question asks for, reads an answer against the list, reviews
    it: what a complete answer would also hold (``notes=None``: a reply without notes), and
    compares it with a critic's outline (``points=None``: a reply that judges no point)."""
    def reply(prompt):
        kind = ("asked" if prompt.startswith("You prepare the list")
                else "review" if prompt.startswith("You review a research answer")
                else "outline" if prompt.startswith("You compare a research answer") else "reading")
        if calls is not None:
            calls.append(kind)
        return json.dumps({"asked": {"asked": list(asked)}, "reading": reading,
                           "review": {} if notes is None else {"notes": notes},
                           "outline": {"points": points or []}}[kind])
    return reply


def test_a_finished_task_is_read_once_and_the_reading_is_kept(tmp_path, memory):
    tree = finished_task(tmp_path, "t1")
    memory.digest(tree.store.path)
    book, calls = Referee(memory), []
    result = book.read_new([tree.store.path], memory.load_digests(), reader(calls=calls))
    assert result == {"read": 1, "completed": 0, "compared": 0, "without_answer": 0, "failed": [], "left_for_later": 0}
    reading = book.readings()[task_key(tree.store.path)]
    assert reading["asked"] == [
        {"item": "the strength, for each year", "status": "partly",
         "missing": "Only the strongest year has a value."},
        {"item": "the main driver", "status": "yes", "missing": ""}]
    assert reading["overclaims"] == [{"claim": "The wind is excluded.", "why": "The test is not significant."}]
    assert reading["answer_chars"] == len(ANSWER) and reading["superseded"] == []
    assert reading["expected"] == NOTES and list(referee.ASPECTS) == [
        "framing", "results", "depth", "breadth", "robustness", "rigor"]
    assert calls == ["asked", "reading", "review"]
    assert book.read_new([tree.store.path], memory.load_digests(), reader(calls=calls))["read"] == 0
    assert calls == ["asked", "reading", "review"]  # nothing is read twice


def test_the_reader_sees_only_the_question_the_list_and_the_answer(tmp_path, memory):
    tree = finished_task(tmp_path, "t1", question="How strong is the upwelling in each year?")
    memory.digest(tree.store.path)
    prompts = []
    Referee(memory).read_new([tree.store.path], memory.load_digests(),
                             lambda prompt: prompts.append(prompt) or reader()(prompt))
    listing, reading, review = prompts
    assert "How strong is the upwelling in each year?" in listing and ANSWER.strip() not in listing
    assert "1. the strength, for each year\n2. the main driver" in reading and ANSWER.strip() in reading
    assert "Flux explains onset" not in reading  # no Expert result, only the final answer
    # The third call reviews the answer, with nothing but the question beside it: what a complete
    # answer to such a question would also hold, not whether this one "does" each aspect.
    assert "How strong is the upwelling in each year?" in review and ANSWER.strip() in review
    assert all(f"{name}: {question}" in review for name, question in referee.ASPECTS.items())
    assert "Flux explains onset" not in review and "the main driver" not in review
    assert "what a complete answer to a question of this kind holds" in review and "at most 10 notes" in review


def test_every_run_of_a_question_is_read_against_the_same_list(tmp_path, memory):
    question = "How strong is the upwelling in each year?"
    trees = [finished_task(tmp_path, name, question=question) for name in ("a", "b")]
    trees.append(finished_task(tmp_path, "c"))
    for tree in trees:
        memory.digest(tree.store.path)
    calls = []
    result = Referee(memory).read_new([t.store.path for t in trees], memory.load_digests(), reader(calls=calls))
    assert result["read"] == 3 and calls.count("asked") == 2
    assert calls.count("reading") == calls.count("review") == 3
    assert question_key("How strong  is the Upwelling, in each year") == question_key(question)


def test_a_task_without_a_final_answer_or_still_running_is_not_read(tmp_path, memory, monkeypatch):
    silent = finished_task(tmp_path, "silent", answer=None)
    running = finished_task(tmp_path, "running", finish=False)
    kept = finished_task(tmp_path, "kept")
    for tree in (silent, running, kept):
        memory.digest(tree.store.path)
    book, stores = Referee(memory), [t.store.path for t in (silent, running, kept)]
    result = book.read_new(stores, memory.load_digests(), reader())
    assert result == {"read": 1, "completed": 0, "compared": 0, "without_answer": 1, "failed": [], "left_for_later": 0}
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
    assert calls == ["reading", "review"]
    assert [entry["item"] for entry in book.readings()[task_key(tree.store.path)]["asked"]] == ["the strength"]

    monkeypatch.setattr(referee, "CALL_SECONDS", 0.05)
    slow = finished_task(tmp_path, "slow")
    memory.digest(slow.store.path)
    started = time.monotonic()
    result = book.read_new([slow.store.path], memory.load_digests(), lambda prompt: time.sleep(5) or "{}")
    assert result["failed"][0]["reason"] == "no reply within 0.05 s" and time.monotonic() - started < 2


def test_the_reader_also_reviews_the_answer_and_older_readings_are_completed(tmp_path, memory):
    """The third part of a reading: notes on what a complete answer would also hold. A reading
    made before it existed is completed by one call, and a third call that fails costs only
    itself."""
    tree = finished_task(tmp_path, "t1")
    memory.digest(tree.store.path)
    book, key = Referee(memory), task_key(tree.store.path)
    stores, digests = [tree.store.path], memory.load_digests()
    # The reviewer's reply holds no notes at all: the first two parts are kept anyway.
    partial = book.read_new(stores, digests, reader(notes=None))
    assert partial["read"] == 0 and partial["failed"] == [
        {"task_key": key, "reason": "The reviewer returned no list of notes."}]
    kept = book.readings()[key]
    assert "expected" not in kept and kept["overclaims"] and len(reading_lines(kept)) == 3
    # The next update makes the third call only.
    calls = []
    result = book.read_new(stores, digests, reader(calls=calls))
    assert result == {"read": 0, "completed": 1, "compared": 0, "without_answer": 0, "failed": [], "left_for_later": 0}
    assert calls == ["review"]
    completed = book.readings()[key]
    assert completed["expected"] == NOTES and completed["read_at"] == kept["read_at"]
    assert reading_lines(completed)[-3:] == [
        "  the same reader as a reviewer of such answers (3 notes):",
        ("    expected of answers to such questions: depth: A ranking of the candidate drivers on one "
         "annual index. | breadth: The yearly values set against published indices."),
        "    particular to this question: results: The strength at the second cape."]
    assert book.read_new(stores, digests, reader(calls=calls))["completed"] == 0 and calls == ["review"]
    # A note the model wrote badly is dropped, a long one is cut, and at most OWN_NOTES are kept.
    wordy = [{"aspect": "depth", "text": "word " * 200, "general": True},
             {"aspect": "style", "text": "No such aspect.", "general": True},
             {"aspect": "rigor", "text": "Whether it is general is not said."}, "junk",
             *({"aspect": "rigor", "text": f"Note {n}.", "general": False} for n in range(20))]
    read = referee.read_expected("Q?", "answer", lambda prompt: json.dumps({"notes": wordy}))
    assert len(read) == referee.OWN_NOTES - 3 and len(read[0]["text"]) == referee.MAX_NOTE_CHARS
    assert referee.read_expected("Q?", "answer", lambda prompt: json.dumps({"notes": []})) == []  # nothing missed
    with pytest.raises(ValueError, match="None of the reviewer's notes"):
        referee.read_expected("Q?", "answer", lambda prompt: json.dumps({"notes": wordy[1:4]}))
    assert len(reading_lines({**kept, "expected": []})) == 3
    # An old reading whose answer is no longer kept is left as it is and not asked for again.
    gone = finished_task(tmp_path, "gone")
    memory.digest(gone.store.path)
    book.read_new([gone.store.path], memory.load_digests(), reader(notes=None))
    gone.path.with_name("report.md").unlink()
    result = book.read_new([gone.store.path], memory.load_digests(), reader(calls=calls))
    assert (result["without_answer"], result["completed"]) == (1, 0) and calls == ["review"]
    left = book.readings()[task_key(gone.store.path)]
    assert left["expected"] == [] and left["answer_gone"] is True
    assert book.read_new([gone.store.path], memory.load_digests(), reader(calls=calls))["without_answer"] == 0


def test_a_reviewer_who_knows_the_field_adds_notes_and_the_next_review_learns_from_them(tmp_path):
    """Notes by the owner or someone the owner asked (reviews.py): kept per task, shown in the
    task's record above the system's own, and a reason to review the lessons again."""
    from typer.testing import CliRunner

    from oceanx.research.cli import research_app
    from oceanx.research.reviews import Reviews
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    stores = [finished_task(tmp_path, f"t{i}").store.path for i in range(3)]
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return "{}" if "<skill name=" in prompt else reader()(prompt)

    assert project.update(stores, llm=llm)["lessons"]["new_tasks"] == 3
    assert project.update(stores, llm=llm)["lessons"]["new_tasks"] == 0
    key = task_key(stores[0])
    notes = [{"aspect": "depth", "text": "A ranking of  every candidate driver on one annual index.",
              "general": True},
             {"aspect": "results", "text": "The heat content of the upper 100 m beside the surface index.",
              "general": False}]
    kept = project.reviews.record(key, {"notes": notes}, reviewer="  the owner ")
    assert kept["reviewer"] == "the owner" and kept["notes"][0]["text"] == (
        "A ranking of every candidate driver on one annual index.")
    assert Reviews(project.memory).all() == {key: kept}
    # The task is new again for the lesson review, once.
    prompts.clear()
    again = project.update(stores, llm=llm)["lessons"]
    assert (again["new_tasks"], again["tasks_left"], again["skills_reviewed"]) == (1, 0, 6)
    record = prompts[0].split("# Records")[1]
    assert record.index(f"## Task {key}") < record.index("## Task ", record.index(f"## Task {key}") + 1)  # first
    assert ("Reviewer's notes on the final answer (2, by the owner):\n"
            "  expected of answers to such questions: depth: A ranking of every candidate driver on one annual "
            "index.\n  particular to this question: results: The heat content of the upper 100 m beside the "
            "surface index.") in record
    assert record.count("Reviewer's notes on the final answer") == 1  # the other tasks have none
    assert "Weigh it above the independent reading" in prompts[0] and "what a reviewer found missing" in prompts[0]
    assert project.update(stores, llm=llm)["lessons"]["new_tasks"] == 0
    # A later review of the same task replaces the earlier one and is read in its turn.
    project.reviews.record(key, notes[:1], reviewer="a colleague")
    assert project.update(stores, llm=llm)["lessons"]["new_tasks"] == 1
    # What cannot be kept is refused with the reason.
    for bad, problem in (([], "needs a list of notes"), ([{**notes[0], "aspect": "style"}], "needs an aspect"),
                         ([{**notes[0], "text": "x" * 401}], "1-400 characters"),
                         ([{"aspect": "depth", "text": "No word on whether it is general."}], "true or false"),
                         (notes * 9, "at most 16 notes")):
        with pytest.raises(ValueError, match=problem):
            project.reviews.record(key, bad, reviewer="the owner")
    with pytest.raises(ValueError, match="No finished task has this key"):
        project.reviews.record("0" * 16, notes, reviewer="the owner")
    with pytest.raises(ValueError, match="names its reviewer"):
        project.reviews.record(key, notes, reviewer=" ")
    # The command a reviewer uses.
    file = tmp_path / "notes.json"
    file.write_text(json.dumps({"notes": notes}))
    other = task_key(stores[1])
    done = CliRunner().invoke(research_app, ["review", "--project", str(tmp_path), "--task", other,
                                             "--notes", str(file), "--reviewer", "codex"])
    assert done.exit_code == 0 and done.output.strip() == f"kept 2 notes on {other}"
    assert Reviews(project.memory).all()[other]["reviewer"] == "codex"
    file.write_text("not json")
    refused = CliRunner().invoke(research_app, ["review", "--project", str(tmp_path), "--task", other,
                                                "--notes", str(file), "--reviewer", "codex"])
    assert refused.exit_code != 0


OUTLINE = ("Give the strength for every year in one table. Rank every candidate driver on the same annual index.\n"
           "Then set the yearly values beside a published index.")
OUTLINE_LINE = "A critic's outline of what should be done for this question and how to investigate it"


def test_a_critic_says_what_should_be_done_and_every_answer_to_the_question_is_compared_with_it(tmp_path):
    """A critic's outline (reviews.py): a few sentences on what should be done for a question and
    how to investigate it, by a person or a stronger model. The meta-agent compares every answer
    to that question with it, and the lesson review reads what the answers did not do."""
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    # A question is usually longer than the 240 characters a digest keeps of it, and two questions
    # can begin alike. An outline belongs to the whole text, as a reading does.
    opening = "How strong is the upwelling in each year? " + "Use the daily and the monthly fields supplied. " * 6
    question = opening + "Say which driver explains the strongest year."
    trees = [finished_task(tmp_path, name, question=question) for name in ("a", "b")]
    trees.append(finished_task(tmp_path, "twin", question=opening + "Say how deep it reaches."))
    trees += [finished_task(tmp_path, name) for name in ("c", "d")]
    stores = [tree.store.path for tree in trees]
    first, second, twin, other, gone = (task_key(store) for store in stores)
    calls, prompts = [], []

    def llm(prompt):
        prompts.append(prompt)
        return "{}" if "<skill name=" in prompt else reader(calls=calls)(prompt)

    # Nobody gave an outline: nothing is compared, and no call is made for it.
    assert project.update(stores, llm=llm)["referee"]["compared"] == 0 and "outline" not in calls
    assert "against_outline" not in project.referee.readings()[first]
    kept_of = {d["task_key"]: d["question"] for d in project.memory.load_digests()}
    assert kept_of[first] == kept_of[twin] != question and len(kept_of[first]) == 240
    kept = project.reviews.record_outline(first, "  " + OUTLINE.replace("\n", "   \n  ") + "\n\n", critic=" codex ")
    assert (kept["critic"], kept["question"], kept["text"]) == ("codex", question, OUTLINE)
    assert project.reviews.outlines() == {question_key(question): kept} and project.reviews.all() == {}
    # The next update compares both answers to that question with it, one call each, and the
    # lessons are reviewed again for those two tasks.
    calls.clear()
    prompts.clear()
    result = project.update(stores, llm=llm)
    assert result["referee"] == {"read": 0, "completed": 0, "compared": 2, "without_answer": 0, "failed": [],
                                 "left_for_later": 0}
    assert calls == ["outline", "outline"]
    compare = prompts[0]
    assert question in compare and OUTLINE in compare and ANSWER.strip() in compare
    assert "Flux explains onset" not in compare and "the main driver" not in compare  # no tree, no other list
    assert "what should be done for this question and how to investigate it" in " ".join(compare.split())
    reading = project.referee.readings()[first]
    assert reading["against_outline"] == {
        "noted_at": kept["noted_at"], "by": "codex", "text": OUTLINE,
        "points": [POINTS[0], {**POINTS[1], "missing": ""}, POINTS[2]]}
    assert reading["expected"] == NOTES
    assert not any("against_outline" in project.referee.readings()[key] for key in (twin, other, gone))
    lessons = result["lessons"]
    assert (lessons["new_tasks"], lessons["tasks_left"], lessons["skills_reviewed"]) == (2, 0, 6)
    review = next(prompt for prompt in prompts if "<skill name=" in prompt)
    records = review.split("# Records")[1]
    shown = (f"{OUTLINE_LINE} (by codex): Give the strength for every year in one table. Rank every candidate "
             "driver on the same annual index. Then set the yearly values beside a published index.\n"
             "  compared with the final answer: 2 of 3 points missing or partial.\n"
             "  not done: Rank every candidate driver on the same annual index (no: Each driver is tested alone.) | "
             "Set the yearly values beside a published index (partly: Two of five years.)\n")
    assert records.count(shown) == 2 == records.count(OUTLINE_LINE)  # both tasks on the question, no other
    assert records.index(OUTLINE_LINE) < records.index(f"## Task {other}")  # the tasks compared anew come first
    assert "weigh it above every kind of note" in review
    assert "what a critic's outline says should have been done" in review
    # Nothing is compared or reviewed twice.
    calls.clear()
    again = project.update(stores, llm=llm)
    assert (again["referee"]["compared"], again["lessons"]["new_tasks"], calls) == (0, 0, [])
    # A later task on the question is read and compared with the same outline.
    stores.append(finished_task(tmp_path, "later", question=question).store.path)
    later = project.update(stores, llm=llm)
    assert calls == ["reading", "review", "outline"]
    assert (later["referee"]["read"], later["referee"]["compared"], later["lessons"]["new_tasks"]) == (1, 1, 1)
    # A new outline for the question replaces the old one, and its three answers are compared again.
    calls.clear()
    project.reviews.record_outline(second, "Rank the drivers first.", critic="the owner")
    replaced = project.update(stores, llm=llm)
    assert calls == ["outline"] * 3 and replaced["referee"]["compared"] == 3
    assert replaced["lessons"]["new_tasks"] == 3
    assert [r["against_outline"]["by"] for r in project.referee.readings().values()
            if "against_outline" in r] == ["the owner"] * 3
    # A reply that judges no point fails that answer only: the rest of its reading stays, and the
    # next update asks again.
    project.reviews.record_outline(other, OUTLINE, critic="codex")
    failed = project.update(stores, llm=lambda prompt: (
        "{}" if "<skill name=" in prompt else reader(points=None)(prompt)))["referee"]
    assert failed["failed"] == [{"task_key": other, "reason": "The reader judged no point of the critic's outline."}]
    assert (failed["compared"], "against_outline" in project.referee.readings()[other]) == (0, False)
    assert project.update(stores, llm=llm)["referee"]["compared"] == 1
    # An answer that is no longer kept cannot be compared: its reading stays and is left alone.
    trees[4].path.with_name("report.md").unlink()
    project.reviews.record_outline(gone, OUTLINE, critic="codex")
    calls.clear()
    lost = project.update(stores, llm=llm)
    assert (lost["referee"]["without_answer"], lost["referee"]["compared"], lost["lessons"]["new_tasks"]) == (1, 0, 0)
    left = project.referee.readings()[gone]
    assert left["answer_gone"] is True and "against_outline" not in left and left["expected"] == NOTES
    assert calls == [] and project.update(stores, llm=llm)["referee"]["without_answer"] == 0


def test_an_outline_is_brief_plain_language_and_only_the_points_the_reader_judged_are_kept(tmp_path):
    from typer.testing import CliRunner

    from oceanx.research.cli import research_app
    from oceanx.research.reviews import MAX_OUTLINE_CHARS
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    store = finished_task(tmp_path, "t1").store.path
    project.update([store])
    key = task_key(store)
    for bad in ("", "  \n ", "x" * (MAX_OUTLINE_CHARS + 1)):
        with pytest.raises(ValueError, match=f"1-{MAX_OUTLINE_CHARS} characters of plain language"):
            project.reviews.record_outline(key, bad, critic="codex")
    with pytest.raises(ValueError, match="No finished task has this key"):
        project.reviews.record_outline("0" * 16, OUTLINE, critic="codex")
    with pytest.raises(ValueError, match="An outline names its critic"):
        project.reviews.record_outline(key, OUTLINE, critic=" ")
    assert project.reviews.outlines() == {}
    # The question in full comes from the task's own record. Once that is gone it comes from an
    # earlier reading, and with neither the outline is refused: a digest keeps only its beginning.
    long_question = "How deep does it reach? " + "Use every field that is supplied. " * 9
    read_store, unread_store = (finished_task(tmp_path, name, question=long_question + name).store.path
                                for name in ("read", "unread"))
    project.update([read_store], llm=lambda prompt: "{}" if "<skill name=" in prompt else reader()(prompt))
    project.update([read_store, unread_store])
    read_store.unlink()
    unread_store.unlink()
    kept = project.reviews.record_outline(task_key(read_store), OUTLINE, critic="codex")
    assert kept["question"] == long_question + "read" and len(kept["question"]) > 240
    assert kept["question_key"] == project.referee.readings()[task_key(read_store)]["question_key"]
    with pytest.raises(ValueError, match="no longer on record in full"):
        project.reviews.record_outline(task_key(unread_store), OUTLINE, critic="codex")
    (project.reviews.root / "outlines" / f"{kept['question_key']}.json").unlink()
    # The reader's reply: a point without a verdict is dropped, a long text is cut, and at most
    # MAX_POINTS are kept. A reply without a judged point is a failed call.
    wordy = [{"point": "word " * 100, "status": "no", "missing": "x " * 400}, {"point": "", "status": "no"},
             {"point": "No verdict.", "status": "maybe"}, "junk",
             *({"point": f"Point {n}.", "status": "yes", "missing": "ignored"} for n in range(20))]
    points = referee.read_against("Q?", OUTLINE, "answer", lambda prompt: json.dumps({"points": wordy}))
    assert len(points) == referee.MAX_POINTS and len(points[0]["point"]) == 200 == len(points[0]["missing"])
    assert points[1] == {"point": "Point 0.", "status": "yes", "missing": ""}
    for empty in ({"points": wordy[1:4]}, {"points": "none"}, {}):
        with pytest.raises(ValueError, match="judged no point of the critic's outline"):
            referee.read_against("Q?", OUTLINE, "answer", lambda prompt, reply=empty: json.dumps(reply))
    # What a record shows: the outline, the count, and only the points not done.
    assert referee.outline_lines({"against_outline": {"by": "", "text": "Do  it\nall.", "points": [points[1]]}}) == [
        f"{OUTLINE_LINE} (by a critic): Do it all.",
        "  compared with the final answer: 0 of 1 points missing or partial."]
    bare = {"by": "codex", "text": "Do it.", "points": [{"point": "Do it", "status": "no", "missing": ""}]}
    assert referee.outline_lines({"against_outline": bare})[1:] == [
        "  compared with the final answer: 1 of 1 points missing or partial.", "  not done: Do it (no)"]
    assert referee.outline_lines({}) == [] == referee.outline_lines({"against_outline": {"points": []}})
    # The command a critic uses.
    file = tmp_path / "outline.txt"
    file.write_text(OUTLINE + "\n", encoding="utf-8")
    command = ["outline", "--project", str(tmp_path), "--task", key, "--text", str(file), "--critic", "codex"]
    done = CliRunner().invoke(research_app, command)
    assert done.exit_code == 0 and done.output.strip() == (
        f"kept codex's outline ({len(OUTLINE)} characters) for the question of {key}")
    assert next(iter(project.reviews.outlines().values()))["text"] == OUTLINE
    file.write_text("x" * (MAX_OUTLINE_CHARS + 1), encoding="utf-8")
    assert CliRunner().invoke(research_app, command).exit_code != 0


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
        assert ("  the same reader as a reviewer of such answers (3 notes):\n    expected of answers to such "
                "questions: depth: A ranking of the candidate drivers on one annual index.") in prompt
        assert "this reader does not know the\nfield as a specialist does" in prompt
        assert "About one such finding in three is wrong" in prompt
        assert "the same kind of gap left in the final answers of several tasks" in prompt
        # Both skills are the Coordinator's: it plans the tree and writes the final answer.
        assert "Judge the whole tree by its final answer" in prompt and "Propose at most 4 new lessons" in prompt
    regions = LessonBook.regions()
    assert "which sub-questions a stronger final answer would have needed" in regions[
        "research-trajectory-planning"].about
    assert "what the final answer must contain" in regions["claim-grounded-writing"].about
    assert {LessonBook.reader(skill, regions[skill]) for skill in (
        "research-trajectory-planning", "claim-grounded-writing")} == {"coordinator"}


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
    assert result["referee"] == {"read": 3, "completed": 0, "compared": 0, "without_answer": 0, "failed": [],
                                 "left_for_later": 0}
    first_review = next(i for i, prompt in enumerate(seen) if "<skill name=" in prompt)
    assert first_review == 9  # per task its list, its reading and what it lacked; then the skills
    assert all("Independent reading of the final answer" in prompt for prompt in seen[first_review:])
    assert len(project.referee.readings()) == 3
