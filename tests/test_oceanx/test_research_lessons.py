"""Research memory cleanup, bounded digests, and the lessons the meta-agent keeps in the skills."""
import gzip
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from oceanx.research import lessons
from oceanx.research.lessons import LEARNED, MAX_WORDS, LessonBook, cited_lessons
from oceanx.research.memory import ResearchMemory, build_digest, run_measures, task_key
from oceanx.research.outcomes import record_task_outcomes
from oceanx.research.tree import ResearchTree

SUMMARY = "Result: Flux explains onset.\nEvidence and limitations: One year.\nFurther analysis: None"


def finished_task(root, name, *, finish=True):
    tree = ResearchTree(root / name / "agents" / "coordinator" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": f"Why is {name} warm?"},
        {"action": "add", "target": "B1", "question": "Heat budget?", "status": "selected"},
        {"action": "add", "target": "B1", "question": "Eddies?"},
    ])
    tree.attach_result("B1.1", summary=SUMMARY, agent_key="p", report_path="/r", attempt_id="a")
    if finish:
        record_task_outcomes(tree, final_report="## Summary\nB1.1 decides it.",
                             model_calls=[{"attempt_id": "a", "usage": {"input_tokens": 10}}])
        tree.label("B1.1", "decision-changing", labeler="owner")
    return tree


@pytest.fixture
def memory(tmp_path):
    return ResearchMemory(tmp_path / ".oceanx" / "research")


def test_digest_is_bounded_and_keeps_labelled_outcomes(tmp_path, memory):
    tree = finished_task(tmp_path, "t1")
    digest = build_digest(tree.store.path)
    assert digest["finished"] and digest["labels"]["B1.1"]["label"] == "decision-changing"
    assert digest["outcomes"]["B1.1"]["cited_in_final"] is True
    assert "attempts" not in digest and len(json.dumps(digest)) < 8000
    memory.digest(tree.store.path)
    assert len(list(memory.digests.glob("*.json"))) == 1


def test_consolidation_archives_only_old_finished_unprotected_stores(tmp_path, memory):
    old = finished_task(tmp_path, "old")
    protected = finished_task(tmp_path, "protected")
    unfinished = finished_task(tmp_path, "open", finish=False)
    fresh = finished_task(tmp_path, "fresh")
    past = time.time() - 60 * 86400
    for tree in (old, protected, unfinished):
        os.utime(tree.store.path, (past, past))
    result = memory.consolidate(
        [t.store.path for t in (old, protected, unfinished, fresh)],
        protected_keys={task_key(protected.store.path)})
    assert result["archived"] == 1 and result["digested"] == 4
    assert not old.store.path.exists() and protected.store.path.exists()
    assert unfinished.store.path.exists() and fresh.store.path.exists()
    archived = memory.archive / f"{task_key(old.store.path)}.sqlite3.gz"
    assert gzip.open(archived).read(16).startswith(b"SQLite format 3")
    assert ResearchTree(old.path).read()["roots"] == ["B1"]  # still readable from its export
    assert not memory.due()


def mined(memory, tmp_path, n=4):
    keys = [task_key(finished_task(tmp_path, f"t{i}").store.path) for i in range(n)]
    for i in range(n):
        memory.digest(tmp_path / f"t{i}" / "agents" / "coordinator" / "research_tree.sqlite3")
    return keys


def fake_llm(replies=None, prompts=None):
    """A meta model that answers each skill's review with the reply given for that skill."""
    def reply(prompt):
        if prompts is not None:
            prompts.append(prompt)
        skill = re.search(r'<skill name="([^"]+)">', prompt).group(1)
        return json.dumps((replies or {}).get(skill, {}))
    return reply


PLANNING, PHYSICS = "research-trajectory-planning", "ocean-physical-consistency-review"
DESIGN = "hypothesis-experiment-design"  # the skill with the smallest lessons region


def lesson(lesson_id, skill, text, supporting, *, counter=(), human=None, added_at="2026-01-01T00:00:00+00:00"):
    return {"id": lesson_id, "skill": skill, "role": "expert", "text": text, "applies_when": "Always.",
            "evidence": {"supporting": list(supporting), "counter": list(counter)}, "status": "active",
            "human": human, "added_by": "meta-agent", "added_at": added_at}


PROPOSING = ("Result: The residual dominates.\nEvidence and limitations: Daily fields only. Limits: "
             "the residual includes analysis increments.\nFurther analysis:\n"
             "1. Does the residual follow the surface layer? - separates flux from increments\n"
             "2. Would a second year repeat it? - needs data that is not here")


def decided_task(root, name):
    """A task whose Coordinator retried an attempt, adopted one proposal and declined a candidate."""
    tree = ResearchTree(root / name / "agents" / "coordinator" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": f"Why is {name} warm?"},
        {"action": "add", "target": "B1", "question": "Heat budget?", "status": "selected",
         "why_it_matters": "Ranks the mechanisms."},
        {"action": "add", "target": "B1", "question": "Eddies?"},
    ])
    for attempt in ("lost", "a"):  # the first delegation returns no report
        tree.record_delegation(SimpleNamespace(
            node_id="B1.1", delegation_id=f"d-{attempt}", attempt_id=attempt,
            binding="structured", subagent_type="ocean_process_expert"))
    tree.attach_result("B1.1", summary=PROPOSING, agent_key="p", report_path="/r", attempt_id="a",
                       expert_role="ocean_process_expert")
    tree.update([
        {"action": "add", "target": "B1.1", "question": "Surface layer?",
         "from_proposal": "B1.1#1", "status": "selected"},
        {"action": "decline", "target": "B1.2", "reason": "No velocity data."},
    ])
    record_task_outcomes(tree, final_report="## Summary\nB1.1 decides it.",
                         model_calls=[{"attempt_id": "a", "usage": {"input_tokens": 2_000_000}}])
    return tree


def test_digest_keeps_the_decision_history(tmp_path):
    digest = build_digest(decided_task(tmp_path, "t").store.path)
    budget = digest["outline"]["B1.1"]
    assert budget["origin"] == {"type": "coordinator", "refs": []}
    assert budget["expert"] == "ocean_process_expert"
    assert [run["end"] is not None for run in budget["attempts"]] == [False, True]  # lost, then reported
    assert budget["result"] == "The residual dominates."
    assert budget["limits"] == "Limits: the residual includes analysis increments."
    assert [p["adopted_as"] for p in budget["proposals"]] == ["B1.1.1", None]
    assert digest["outline"]["B1.1.1"]["origin"]["refs"] == ["B1.1#1"]
    declined = digest["outline"]["B1.2"]
    assert declined["close_reason"] == "No velocity data." and declined["attempts"] == []
    assert digest["started_at"] and digest["wall_minutes"] is not None


def test_run_measures_summarise_a_finished_tree(tmp_path):
    tree = decided_task(tmp_path, "t")
    tree.record_delegation(SimpleNamespace(
        node_id="B1.1.1", delegation_id="d-b", attempt_id="b", binding="structured",
        subagent_type="ocean_process_expert"))
    tree.attach_result("B1.1.1", summary=SUMMARY, agent_key="p", report_path="/r2", attempt_id="b")
    record_task_outcomes(tree, final_report="## Summary\nB1.1 decides it.", model_calls=[
        {"attempt_id": "a", "usage": {"input_tokens": 3_000_000}, "skills_read": [PHYSICS]},
        {"attempt_id": "b", "usage": {"input_tokens": 1_000_000}, "skills_read": []},
        {"role": "coordinator", "usage": {"input_tokens": 500_000}, "skills_read": [PLANNING]}])
    for node, label in (("B1.1", "decision-changing"), ("B1.1.1", "informative-but-not-decisive")):
        tree.label(node, label, labeler="model-judge", source="judge")
    digest = build_digest(tree.store.path)
    measures = run_measures(digest)
    assert measures["questions_run"] == 2 and measures["max_depth"] == 2
    assert measures["nondecisive_token_share"] == 0.25  # 1M of the 4M tokens spent by Experts
    assert measures["tokens"] == 4_500_000  # the Coordinator's own calls count on the root
    assert (measures["attempts"], measures["attempts_without_report"]) == (3, 1)
    assert (measures["followups_proposed"], measures["followups_adopted"]) == (2, 1)
    assert measures["last_decisive_minute"] is not None and measures["label_sources"] == {"judge": 2}
    # Whether the skills that hold lessons were opened, by the Coordinator and by the Experts.
    assert measures["coordinator_skills_read"] == [PLANNING]
    assert measures["questions_whose_expert_read_a_skill"] == 1
    assert measures["expert_skills_read"] == [PHYSICS]
    # A run recorded before skill reads were logged says so instead of reporting zero.
    for outcome in digest["outcomes"].values():
        del outcome["skills_read"]
    older = run_measures(digest)
    assert older["coordinator_skills_read"] is None
    assert older["questions_whose_expert_read_a_skill"] is None


def test_the_meta_agent_reads_each_skill_as_its_readers_get_it(tmp_path, memory):
    memory.digest(decided_task(tmp_path, "t").store.path)
    book = LessonBook(memory)
    tree_prompt, considered = book.review_prompt(PLANNING, memory.load_digests())
    analysis_prompt, _ = book.review_prompt(PHYSICS, memory.load_digests())
    assert considered == 1
    # It reads the whole skill it maintains, without the region markers, and what the region is for.
    assert f'<skill name="{PLANNING}">' in tree_prompt and "oceanx:" not in tree_prompt
    assert "## Scientific value\nA useful question addresses" in tree_prompt
    assert "This skill takes lessons about: which sub-questions and proposed follow-ups" in tree_prompt
    assert "It holds at most 4 lessons." in tree_prompt and "the Coordinator reads" in tree_prompt
    assert f'<skill name="{PHYSICS}">' in analysis_prompt and "an Expert reads" in analysis_prompt
    assert "A residual is not a measured forcing" in analysis_prompt  # so it is not proposed again
    assert "It holds at most 6 lessons." in analysis_prompt
    # The Coordinator's lessons come from decisions: who proposed a question, retries, dropped follow-ups.
    assert "policy v0-coordinator-bfs, run without lessons" in tree_prompt
    assert "- B1.1.1 | adopted from B1.1#1 |" in tree_prompt
    assert re.search(r"attempt 1 from min [\d.]+ returned no report; "
                     r"attempt 2 from min [\d.]+ reported at min [\d.]+ \| 2.0M tokens", tree_prompt)
    assert "follow-ups: 1 -> B1.1.1 | 2 dropped: Would a second year repeat it?" in tree_prompt
    assert re.search(r"- B1.2 \| added by the Coordinator \| created min [\d.]+ \| never run \| closed",
                     tree_prompt)
    assert "closed because: No velocity data." in tree_prompt and "limits:" not in tree_prompt
    # The Experts' lessons come from analyses: results and their limits, only for questions that ran.
    assert "- B1.1 | ocean_process_expert | 1 model calls | 1 of 2 attempts returned no report" in analysis_prompt
    assert "limits: Limits: the residual includes analysis increments." in analysis_prompt
    assert "follow-ups:" not in analysis_prompt and "- B1.2 |" not in analysis_prompt
    # Each prompt also names what its reader is told elsewhere.
    assert "# Research tree" in tree_prompt and "- xarray-array-ops:" in analysis_prompt


def test_only_skills_with_a_lessons_region_take_lessons():
    regions = LessonBook.regions()
    assert {skill: region.limit for skill, region in regions.items()} == {
        "claim-grounded-writing": 3, DESIGN: 3, "ocean-analysis-design": 6,
        "ocean-dataset-diagnosis": 4, PHYSICS: 6, PLANNING: 4}
    readers = {skill: LessonBook.reader(skill, region) for skill, region in regions.items()}
    assert readers.pop(PLANNING) == "coordinator" and set(readers.values()) == {"expert"}
    assert "xarray-array-ops" not in regions  # its region is for tools
    assert all(region.about for region in regions.values())


def test_a_review_applies_at_once_what_passes_the_rules(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book, prompts = LessonBook(memory), []
    good = {"text": "Drop eddy follow-ups without velocity data.",
            "applies_when": "No velocity fields are attached.", "supporting": keys[:3],
            "counter": [], "rationale": "B1.2 was never run in t0, t1 and t2."}
    result = book.review(fake_llm({
        PLANNING: {"add": [good, {**good, "text": "Another idea.", "supporting": keys[:2]},
                           {**good, "text": "A third idea."}]},  # more than a review may add
        PHYSICS: {"add": [{**good, "text": "word " * (MAX_WORDS + 1)},
                          {**good, "text": "Repeat what B1.2 did."}]},
        DESIGN: {"add": [{**good, "text": "Invented evidence.", "supporting": ["no1", "no2", "no3"]},
                         {**good, "text": "Contested.", "counter": keys[:3]}]}}, prompts))
    assert result["changes"] == [{"lesson": "L001", "change": "added"}]
    assert (result["skills_reviewed"], result["questions"], result["new_tasks"]) == (6, 4, 4)
    reasons = " | ".join(item["reason"] for item in result["rejected"])
    assert len(result["rejected"]) == 5 and reasons.count("different questions") == 2
    assert "Lesson text must be" in reasons and "node IDs belong in the rationale" in reasons
    assert "fewer questions than the support" in reasons
    # A reply that cannot be read changes nothing for its skill; the other skills are still reviewed.
    broken = LessonBook(ResearchMemory(memory.root.parent / "other"))
    for digest in memory.load_digests():
        atomic = broken.memory.digests / f"{digest['task_key']}.json"
        atomic.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(json.dumps(digest))
    answers = fake_llm({PLANNING: {"add": [good]}})
    partial = broken.review(lambda prompt: "no json here" if f'<skill name="{PHYSICS}">' in prompt else answers(prompt))
    assert partial["changes"] == [{"lesson": "L001", "change": "added"}] and partial["skills_reviewed"] == 6
    assert [r["skill"] for r in partial["rejected"] if "could not be read" in r["reason"]] == [PHYSICS]
    # The lesson is in force without anyone approving it, and the change is logged with its reason.
    [added] = book.active()
    assert (added["id"], added["skill"], added["role"], added["human"]) == ("L001", PLANNING, "coordinator", None)
    assert book.version().startswith("lessons@")
    [change] = book.changes()
    assert (change["change"], change["by"], change["reason"]) == ("added", "meta-agent", good["rationale"])
    # A later skill's review already sees it, and it cannot be added twice.
    assert good["text"] in book.review_prompt(PLANNING, memory.load_digests())[0]
    again = book.review(fake_llm({PLANNING: {"add": [good]}}), force=True)
    assert again["changes"] == [] and "Duplicate" in again["rejected"][0]["reason"]


def test_a_review_runs_only_when_a_task_finished_since_the_last_one(tmp_path, memory):
    mined(memory, tmp_path)
    book, prompts = LessonBook(memory), []
    assert book.review_due()
    assert book.review(fake_llm(prompts=prompts))["skills_reviewed"] == 6 and len(prompts) == 6
    assert not book.review_due() and book.review_due(now=datetime.now(UTC) + timedelta(days=1, minutes=1))
    quiet = book.review(fake_llm(prompts=prompts))
    assert (quiet["new_tasks"], quiet["skills_reviewed"]) == (0, 0) and len(prompts) == 6  # model not asked
    memory.digest(finished_task(tmp_path, "later").store.path)
    assert book.review(fake_llm(prompts=prompts))["new_tasks"] == 1 and len(prompts) == 12


def test_repeated_runs_of_one_question_cannot_support_a_lesson(tmp_path, memory):
    for run in ("r1", "r2", "r3"):
        memory.digest(finished_task(tmp_path / run, "bay").store.path)
    book, prompts = LessonBook(memory), []
    result = book.review(fake_llm(prompts=prompts))
    assert result["questions"] == 1 and result["skills_reviewed"] == 0 and prompts == []  # model not asked
    # A skill that already has a lesson is still reviewed, but three runs of one question add nothing.
    book._save([lesson("L001", PLANNING, "Test rivals first.", [])])
    keys = [d["task_key"] for d in memory.load_digests()]
    result = book.review(fake_llm({PLANNING: {"add": [{
        "text": "Check the baseline.", "applies_when": "Short records.", "supporting": keys}]}}, prompts),
        force=True)
    assert len(prompts) == 1 and result["changes"] == []
    assert "at least 3 different questions; these come from 1" in result["rejected"][0]["reason"]


def test_the_meta_agent_keeps_revises_or_retires_and_the_records_overrule_it(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    book._save([lesson("L001", PLANNING, "Test rivals first.", keys[:3]),
                lesson("L002", PLANNING, "Stop after two null results.", keys[:3]),
                lesson("L003", PLANNING, "Ask the budget question first.", keys[:3]),
                lesson("L004", PHYSICS, "Bound the residual.", keys[:2])])
    version = book.version()
    result = book.review(fake_llm({PLANNING: {"lessons": [
        {"id": "L001", "verdict": "revise", "text": "Test a rival mechanism before deepening one.",
         "applies_when": "Two drivers remain plausible.", "supporting": [keys[3]], "reason": "Too broad."},
        {"id": "L002", "verdict": "retire", "reason": "The skill already says it."},
        {"id": "L003", "verdict": "keep", "counter": keys[:3], "reason": "Seems fine."},
        {"id": "L004", "verdict": "retire", "reason": "Not a lesson of this skill."},
        {"id": "L999", "verdict": "retire"}]}}))
    assert result["changes"] == [{"lesson": "L001", "change": "revised"}, {"lesson": "L002", "change": "retired"},
                                 {"lesson": "L003", "change": "retired"}]
    by_id = {l["id"]: l for l in book.lessons()}
    assert by_id["L001"]["text"] == "Test a rival mechanism before deepening one."
    assert by_id["L001"]["evidence"]["supporting"] == keys  # evidence accumulates
    assert (by_id["L002"]["retired_by"], by_id["L002"]["retired_reason"]) == ("meta-agent", "The skill already says it.")
    # Kept by the model, but contradicted by as many questions as support it: retired by rule.
    assert by_id["L003"]["retired_by"] == "rule" and "3 questions against it, 3 for it" in by_id["L003"]["retired_reason"]
    assert by_id["L004"]["status"] == "active"  # a skill's review cannot touch another skill's lesson
    assert book.version() != version
    logged = [(c["lesson"], c["change"], c["by"]) for c in book.changes()]
    assert logged == [("L001", "revised", "meta-agent"), ("L002", "retired", "meta-agent"), ("L003", "retired", "rule")]
    assert book.changes()[0]["before"] == "Test rivals first."


def test_a_full_skill_only_takes_a_better_supported_lesson(tmp_path, memory):
    keys = mined(memory, tmp_path, n=5)
    book = LessonBook(memory)
    book._save([lesson("L001", DESIGN, "First.", keys[:3], added_at="2026-01-01T00:00:00+00:00"),
                lesson("L002", DESIGN, "Second.", keys[:4], added_at="2026-01-02T00:00:00+00:00"),
                lesson("L003", DESIGN, "Third.", keys[:3], added_at="2026-01-03T00:00:00+00:00", human="right")])
    new = {"applies_when": "A mechanism is claimed.", "rationale": "Seen across tasks."}
    result = book.review(fake_llm({DESIGN: {"add": [
        {**new, "text": "No better than the weakest.", "supporting": keys[:3]},
        {**new, "text": "Better supported.", "supporting": keys}]}}))
    assert result["changes"] == [{"lesson": "L001", "change": "retired"}, {"lesson": "L004", "change": "added"}]
    assert "already holds 3 lessons" in result["rejected"][0]["reason"]
    # The owner's lesson is listed first and is never the one replaced; then the best supported.
    assert [l["id"] for l in book.shown(DESIGN)] == ["L003", "L004", "L002"]
    retired = next(l for l in book.lessons() if l["id"] == "L001")
    assert retired["retired_reason"] == "replaced by the better supported L004"
    # Older data over the limit is cut back to the region's size at the next review.
    book._save([lesson(f"L{i:03d}", DESIGN, f"Lesson {i}.", keys[:i]) for i in range(1, 6)])
    cut = book.review(fake_llm(), force=True)
    assert [c["lesson"] for c in cut["changes"]] == ["L001", "L002"]
    assert [l["id"] for l in book.shown(DESIGN)] == ["L005", "L004", "L003"]


def test_the_owner_marks_a_lesson_right_or_wrong(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    book._save([lesson("L001", PLANNING, "Test rivals first.", keys[:3]),
                lesson("L002", PLANNING, "Stop after two null results.", keys[:3])])
    with pytest.raises(ValueError, match="right or wrong"):
        book.mark("L001", "maybe", reviewer="owner")
    with pytest.raises(ValueError, match="Unknown lesson"):
        book.mark("L404", "right", reviewer="owner")
    # Right: it stays whatever the meta-agent or the records say; only its evidence grows.
    book.mark("L001", "right", reviewer="owner")
    book.review(fake_llm({PLANNING: {"lessons": [
        {"id": "L001", "verdict": "retire", "counter": keys, "reason": "Contradicted."}]}}), force=True)
    kept = next(l for l in book.lessons() if l["id"] == "L001")
    assert (kept["status"], kept["human"], kept["evidence"]["counter"]) == ("active", "right", keys)
    assert "marked right by the owner" in book.review_prompt(PLANNING, memory.load_digests())[0]
    # Wrong: it leaves the skill at once and is not proposed again.
    book.mark("L002", "wrong", reviewer="owner")
    assert [l["id"] for l in book.active()] == ["L001"]
    prompt = book.review_prompt(PLANNING, memory.load_digests())[0]
    assert "# Lessons the owner marked wrong\n- Stop after two null results." in prompt
    again = book.review(fake_llm({PLANNING: {"add": [{
        "text": "Stop after two null results.", "applies_when": "Always.", "supporting": keys[:3]}]}}), force=True)
    assert again["changes"] == [] and "The owner marked this lesson wrong" in again["rejected"][0]["reason"]
    # Marking a retired lesson right brings it back.
    book.mark("L002", "right", reviewer="owner")
    restored = next(l for l in book.lessons() if l["id"] == "L002")
    assert restored["status"] == "active" and "retired_reason" not in restored
    assert [(c["lesson"], c["change"]) for c in book.changes()][-3:] == [
        ("L001", "marked right"), ("L002", "retired"), ("L002", "marked right")]


def test_prompt_budget_keeps_one_run_of_every_question_before_repeats(tmp_path, memory, monkeypatch):
    for folder, name in (("a", "gulf"), ("b", "bay"), ("c", "bay")):  # oldest first
        memory.digest(finished_task(tmp_path / folder, name).store.path)
    digests = memory.load_digests()
    sizes = [len(lessons._record(d, "coordinator")) for d in digests]
    monkeypatch.setattr(lessons, "MAX_PROMPT_CHARS", 2 * max(sizes) + 10)
    prompt, considered = LessonBook(memory).review_prompt(PLANNING, digests)
    assert considered == 2 and prompt.count("## Task") == 2
    assert "Why is gulf warm?" in prompt and prompt.count("Why is bay warm?") == 1


def test_old_digests_stay_readable_and_are_rebuilt_while_the_store_exists(tmp_path, memory):
    tree = finished_task(tmp_path, "t1")
    current = memory.digest(tree.store.path)
    path = memory.digests / f"{current['task_key']}.json"
    old = {**current, "schema": "oceanx-research-digest/v1", "outline": {
        node_id: {k: v for k, v in node.items() if k in {
            "parent", "kind", "status", "relation", "question", "why_it_matters", "result",
            "verdict", "close_reason"}} for node_id, node in current["outline"].items()}}
    path.write_text(json.dumps(old))
    [loaded] = memory.load_digests()
    assert loaded["schema"].endswith("/v1")
    assert "- B1.1 | added by the Coordinator" in LessonBook(memory).review_prompt(PLANNING, [loaded])[0]
    assert memory.consolidate([tree.store.path])["digested"] == 1
    assert memory.load_digests()[0]["schema"].endswith("/v2")


def test_lessons_are_written_only_into_the_region_their_skill_reserves(tmp_path, memory):
    pytest.importorskip("deepagents")
    from oceanx.native_skills import prepare_skill_library
    from oceanx.research.review import ProjectResearch
    from oceanx.skills import load_ocean_skill
    project = ProjectResearch(SimpleNamespace(root=memory.root.parent))
    book = project.lessons
    keys = mined(memory, tmp_path)
    book._save([lesson("L001", PLANNING, "Test a rival mechanism before deepening the leading one.", keys[:3]),
                lesson("L002", PLANNING, "Stop after two null results.", keys),
                lesson("L003", PHYSICS, "Bound the residual with a second estimator.", keys[:3])])

    def skill(role, name, *, research=True):
        library = prepare_skill_library(tmp_path / f"lib-{research}", role=role,
                                        revisions=project.skills(research=research))
        return (library / "skills" / name / "SKILL.md").read_text()

    packaged = load_ocean_skill(PLANNING)[0]
    before = packaged[:packaged.index("<!-- oceanx:lessons")]
    planning = skill("coordinator", PLANNING)
    # Every packaged line is kept; the lessons stand where the region is, best supported first.
    assert planning.startswith(before) and "oceanx:" not in planning
    assert planning[len(before):] == (
        f"{LEARNED}\n"
        "- Stop after two null results. Applies when: Always. (L002)\n"
        "- Test a rival mechanism before deepening the leading one. Applies when: Always. (L001)\n")
    physics = skill("ocean_process_expert", PHYSICS)
    assert (physics.index("The existence of additional possible checks") < physics.index("(L003)")
            < physics.index("## relevant_references"))
    # With no tool learned, the helper script an Expert can open is the packaged file, byte for byte.
    from oceanx.research.toolbook import packaged_source
    library = prepare_skill_library(tmp_path / "lib-True", role="ocean_process_expert",
                                    revisions=project.skills(research=True))
    assert (library / "skills/xarray-array-ops/scripts/oceanx_array_ops.py").read_text() == packaged_source()
    assert "(L001)" not in physics and "oceanx:" not in physics
    # A bounded (non-research) task gets the skills without lessons; the markers never reach a reader.
    plain = skill("coordinator", PLANNING, research=False)
    assert plain == before.rstrip() + "\n" and "oceanx:" not in plain
    assert plain == (prepare_skill_library(tmp_path / "none", role="coordinator") / "skills" / PLANNING
                     / "SKILL.md").read_text()
    assert load_ocean_skill(PLANNING)[0] == packaged  # the packaged file is never changed
    # The owner can read the skills as rendered, and the version names exactly what is shown.
    assert (book.skills_root / PLANNING / "SKILL.md").read_text() == planning
    version = book.version()
    assert project.version() == version  # no tool history yet
    book.mark("L001", "wrong", reviewer="owner")
    assert book.version() != version and "(L001)" not in skill("coordinator", PLANNING)
    book.mark("L002", "wrong", reviewer="owner")
    # Retiring its last lesson returns the skill to its packaged text.
    assert skill("coordinator", PLANNING) == plain and not (book.skills_root / PLANNING).exists()
    assert (book.skills_root / PHYSICS / "SKILL.md").is_file()


def test_a_task_records_the_lessons_it_was_shown_and_those_it_named(tmp_path, memory):
    assert cited_lessons(["L001", "L002", "L010"], ["Following L001, B1.2 was dropped.", "See XL002 and (L010)."]) == [
        "L001", "L010"]
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    book._save([lesson("L001", PLANNING, "Test rivals first.", keys[:3], counter=keys[3:])])
    tree = finished_task(tmp_path, "shown", finish=False)
    record_task_outcomes(tree, final_report="## Summary\nB1.1 decides it (L001).", model_calls=[],
                         library={"lessons_shown": ["L001"], "lessons_cited": ["L001"], "tools_mounted": []})
    digest = memory.digest(tree.store.path)
    assert (digest["lessons_shown"], digest["lessons_cited"]) == (["L001"], ["L001"])
    earlier = [d for d in memory.load_digests() if d["task_key"] != digest["task_key"]]
    assert len(earlier) == 4 and all(d["lessons_shown"] is None for d in earlier)  # recorded before this was logged
    overview = book.overview()
    [planning] = [s for s in overview["skills"] if s["name"] == PLANNING]
    assert (planning["limit"], planning["reader"]) == (4, "coordinator") and planning["about"]
    [shown] = planning["lessons"]
    assert (shown["shown"], shown["tasks_shown"], shown["tasks_cited"]) == (True, 1, 1)
    assert shown["evidence_tasks"]["counter"][0]["question"] == "Why is t3 warm?"
    assert "- L001: supported by 3 questions, contradicted by 1; shown in 1 tasks, cited in 1" in (
        book.review_prompt(PLANNING, memory.load_digests())[0])
    assert overview["limits"] == {"max_words": 40, "max_condition_words": 25, "min_support": 3}
    assert len(overview["skills"]) == 6 and overview["retired"] == []


def test_protocol_accepts_library_requests_and_rejects_bad_ones():
    from pydantic import ValidationError

    from oceanx.protocol.v2.models import REQUEST_ADAPTER
    context = {"client_id": "c", "session_id": "s", "workspace_id": "ws"}
    base = {"protocol_version": 2, "request_id": "req_1", "context": context}
    marked = REQUEST_ADAPTER.validate_python({**base, "type": "research.library.mark", "payload": {
        "kind": "lesson", "id": "L001", "verdict": "wrong"}})
    assert (marked.payload.kind, marked.payload.verdict) == ("lesson", "wrong")
    REQUEST_ADAPTER.validate_python({**base, "type": "research.library.mark", "payload": {
        "kind": "tool", "id": "weighted_mean", "verdict": "right"}})
    for payload in ({"kind": "lesson", "id": "../../etc", "verdict": "right"},
                    {"kind": "policy", "id": "L001", "verdict": "right"},
                    {"kind": "lesson", "id": "L001", "verdict": "approve"}):
        with pytest.raises(ValidationError):
            REQUEST_ADAPTER.validate_python({**base, "type": "research.library.mark", "payload": payload})
    assert REQUEST_ADAPTER.validate_python(
        {**base, "type": "research.library.get", "payload": {}}).type == "research.library.get"
    assert REQUEST_ADAPTER.validate_python(
        {**base, "type": "research.library.update", "payload": {"review": True}}).payload.review is True
    for retired in ("research.lessons.list", "research.lessons.decide", "research.policies.activate",
                    "research.labels.set"):
        with pytest.raises(ValidationError):
            REQUEST_ADAPTER.validate_python({**base, "type": retired, "payload": {}})
