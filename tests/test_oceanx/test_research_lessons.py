"""Research memory cleanup, bounded digests and human-approved lessons."""
import gzip
import json
import os
import re
import time
from types import SimpleNamespace

import pytest

from oceanx.research import lessons
from oceanx.research.lessons import MAX_WORDS, LessonBook
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


def fake_llm(**by_role):
    """A meta model that answers each role's prompt with the proposals given for that role."""
    def reply(prompt):
        role = "coordinator" if '<skill name="research-trajectory-planning"' in prompt else "expert"
        return json.dumps({"proposals": by_role.get(role, [])})
    return reply


PLANNING, PHYSICS = "research-trajectory-planning", "ocean-physical-consistency-review"


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


def test_the_meta_agent_reads_the_skills_it_writes_into_and_each_roles_records(tmp_path, memory):
    memory.digest(decided_task(tmp_path, "t").store.path)
    book = LessonBook(memory)
    tree_prompt, considered = book.mining_prompt("coordinator", memory.load_digests())
    analysis_prompt, _ = book.mining_prompt("expert", memory.load_digests())
    assert considered == 1
    # It reads the full text of the skills it may write into, and only those of the role.
    assert f'<skill name="{PLANNING}" read_by="coordinator">' in tree_prompt
    assert "## Scientific value\nA useful question addresses" in tree_prompt
    assert PHYSICS not in tree_prompt
    assert f'<skill name="{PHYSICS}" read_by="ocean_process_expert">' in analysis_prompt
    assert "A residual is not a measured forcing" in analysis_prompt  # so it is not proposed again
    assert PLANNING not in analysis_prompt
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


def test_a_lesson_names_the_skill_and_section_it_is_written_into(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    digests = {d["task_key"]: d for d in memory.load_digests()}
    lesson = {"role": "expert", "topic": "method", "skill": PHYSICS,
              "text": "Bound the residual with a second estimator.",
              "applies_when": "Unclosed budgets.", "supporting": keys[:3]}
    assert book.validate_candidate({**lesson, "section": "heat budgets"}, digests)["section"] == "Heat budgets"
    assert book.validate_candidate(lesson, digests)["section"] == "Method assumptions"  # opened for its topic
    for change, problem in (({"skill": PLANNING}, "skill must be one of ocean-physical"),
                            ({"skill": "xarray-array-ops"}, "skill must be one of"),
                            ({"section": "Heat budget closure"}, f"is not a section of {PHYSICS}"),
                            ({"topic": "adopt"}, "topic must be one of definition")):
        with pytest.raises(ValueError, match=problem):
            book.validate_candidate({**lesson, **change}, digests)


def test_mining_validates_every_proposal(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    good = {"kind": "add", "topic": "adopt", "skill": PLANNING,
            "text": "Drop eddy follow-ups without velocity data.",
            "applies_when": "No velocity fields are attached.", "supporting": keys[:3],
            "counter": [], "rationale": "B1.2 was never run in t0, t1 and t2."}
    weak = {**good, "text": "Another idea.", "supporting": keys[:2]}
    invented = {**good, "text": "Invented evidence.", "supporting": ["nope1", "nope2", "nope3"]}
    analysis = {**good, "topic": "check", "skill": PHYSICS}
    result = book.mine(fake_llm(
        coordinator=[good, weak, invented],
        expert=[{**good, "text": "Check units."},  # a Coordinator topic and skill
                {**analysis, "text": "word " * (MAX_WORDS + 1)},
                {**analysis, "text": "Test a second baseline."}]))
    assert [(p["role"], p["skill"], p["section"], p["text"]) for p in result["created"]] == [
        ("coordinator", PLANNING, "Adopting follow-ups", good["text"]),
        ("expert", PHYSICS, "Checks", "Test a second baseline.")]
    reasons = " | ".join(item["reason"] for item in result["rejected"])
    assert len(result["rejected"]) == 4 and reasons.count("different questions") == 2
    assert "topic must be one of definition" in reasons and "Lesson text must be" in reasons
    assert book.active() == [] and book.version() is None  # nothing applied yet
    assert book.revised_skills() == {}  # and nothing written into a skill
    # A proposal awaiting review is shown to the meta-agent and cannot be proposed again.
    assert good["text"] in book.mining_prompt("coordinator", memory.load_digests())[0]
    again = book.mine(fake_llm(coordinator=[good]))
    assert again["created"] == [] and "Duplicate" in again["rejected"][0]["reason"]


def test_repeated_runs_of_one_question_cannot_support_a_lesson(tmp_path, memory):
    for run in ("r1", "r2", "r3"):
        memory.digest(finished_task(tmp_path / run, "bay").store.path)
    book, prompts = LessonBook(memory), []
    result = book.mine(lambda prompt: prompts.append(prompt) or "{}")
    assert result["questions"] == 1 and result["created"] == [] and prompts == []  # model not asked
    digests = {d["task_key"]: d for d in memory.load_digests()}
    with pytest.raises(ValueError, match="at least 3 different questions; these come from 1"):
        book.validate_candidate({"role": "expert", "topic": "check", "skill": PHYSICS,
                                 "text": "Check the baseline.", "applies_when": "Short records.",
                                 "supporting": list(digests)}, digests)


def test_prompt_budget_keeps_one_run_of_every_question_before_repeats(tmp_path, memory, monkeypatch):
    for folder, name in (("a", "gulf"), ("b", "bay"), ("c", "bay")):  # oldest first
        memory.digest(finished_task(tmp_path / folder, name).store.path)
    digests = memory.load_digests()
    sizes = [len(lessons._record(d, "coordinator")) for d in digests]
    monkeypatch.setattr(lessons, "MAX_PROMPT_CHARS", 2 * max(sizes) + 10)
    prompt, considered = LessonBook(memory).mining_prompt("coordinator", digests)
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
    assert "- B1.1 | added by the Coordinator" in LessonBook(memory).mining_prompt("coordinator", [loaded])[0]
    assert memory.consolidate([tree.store.path])["digested"] == 1
    assert memory.load_digests()[0]["schema"].endswith("/v2")


def test_approved_lessons_are_written_into_the_skills_each_role_already_reads(tmp_path, memory):
    pytest.importorskip("deepagents")
    from oceanx.native_skills import prepare_skill_library
    from oceanx.skills import load_ocean_skill
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    book.mine(fake_llm(
        coordinator=[{"kind": "add", "topic": "order", "skill": PLANNING,
                      "text": "Test a rival mechanism before deepening one.",
                      "applies_when": "Two drivers remain plausible.", "supporting": keys[:3]}],
        expert=[{"kind": "add", "topic": "method", "skill": PHYSICS, "section": "Heat budgets",
                 "text": "Bound the residual with a second estimator.",
                 "applies_when": "Unclosed budgets.", "supporting": keys[:3]}]))
    tree_proposal, analysis_proposal = book.pending()
    assert (tree_proposal["skill"], tree_proposal["section"]) == (PLANNING, "Order of questions")
    with pytest.raises(ValueError):
        book.decide(tree_proposal["id"], approve=True, reviewer="", text=None)
    book.decide(tree_proposal["id"], approve=True, reviewer="owner",
                text="Test a rival mechanism before deepening the leading one.")
    [lesson] = book.active("coordinator")
    assert lesson["edited"] and lesson["approved_by"] == "owner"
    assert (lesson["skill"], lesson["section"]) == (PLANNING, "Order of questions")
    book.decide(analysis_proposal["id"], approve=True, reviewer="owner")

    def skill(role, name, revisions):
        library = prepare_skill_library(tmp_path / "lib", role=role, revisions=revisions)
        return (library / "skills" / name / "SKILL.md").read_text()

    packaged = load_ocean_skill(PLANNING)[0]
    planning = skill("coordinator", PLANNING, book.revised_skills())
    # The packaged text is kept, and the lesson opens a section named after its topic.
    assert planning.startswith(packaged.rstrip()) and "## Order of questions" not in packaged
    assert "## Order of questions\n\nLearned from past OceanX tasks" in planning
    assert planning.rstrip().endswith(
        "- Test a rival mechanism before deepening the leading one. Applies when: Two drivers "
        "remain plausible. (L001; seen in 3 tasks, 0 counterexamples.)")
    # A lesson for an existing section is written at the end of that section.
    physics = skill("ocean_process_expert", PHYSICS, book.revised_skills())
    assert (physics.index("## Heat budgets") < physics.index("Bound the residual with a second")
            < physics.index("## Transport and advection"))
    # Without lessons a task gets the packaged skill, and the packaged file is never changed.
    assert skill("coordinator", PLANNING, None) == packaged == load_ocean_skill(PLANNING)[0]
    # The owner can read the revised skills; the meta-agent reads them too, lesson ids included.
    assert (book.skills_root / PLANNING / "SKILL.md").read_text() == planning
    assert "(L001; seen in 3 tasks" in book.mining_prompt("coordinator", memory.load_digests())[0]

    version = book.version()
    with pytest.raises(ValueError):
        book.decide(tree_proposal["id"], approve=False, reviewer="owner")  # already decided
    book.mine(fake_llm(coordinator=[{"kind": "retire", "lesson_id": lesson["id"],
                                     "counter": keys[3:], "rationale": "Contradicted."}]))
    [retire] = book.pending()
    overview = book.overview()
    assert overview["pending"][0]["evidence_tasks"]["counter"][0]["question"].startswith("Why is")
    book.decide(retire["id"], approve=True, reviewer="owner")
    assert [l["role"] for l in book.active()] == ["expert"] and book.version() != version
    # Retiring its last lesson returns the skill to its packaged text.
    assert list(book.revised_skills()) == [PHYSICS] and not (book.skills_root / PLANNING).exists()


def test_protocol_accepts_lesson_requests_and_rejects_bad_ids():
    from pydantic import ValidationError

    from oceanx.protocol.v2.models import REQUEST_ADAPTER
    context = {"client_id": "c", "session_id": "s", "workspace_id": "ws"}
    base = {"protocol_version": 2, "request_id": "req_1", "context": context}
    decided = REQUEST_ADAPTER.validate_python({**base, "type": "research.lessons.decide", "payload": {
        "proposal_id": "lp_0123456789ab", "decision": "approve", "text": "Edited."}})
    assert decided.payload.text == "Edited."
    with pytest.raises(ValidationError):
        REQUEST_ADAPTER.validate_python({**base, "type": "research.lessons.decide", "payload": {
            "proposal_id": "../../etc", "decision": "approve"}})
    listed = REQUEST_ADAPTER.validate_python({**base, "type": "research.lessons.list", "payload": {}})
    assert listed.type == "research.lessons.list"
