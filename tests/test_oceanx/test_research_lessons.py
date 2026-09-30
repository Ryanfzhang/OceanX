"""Research memory cleanup, bounded digests and human-approved lessons."""
import gzip
import json
import os
import time

import pytest

from oceanx.research.lessons import MAX_WORDS, LessonBook
from oceanx.research.memory import ResearchMemory, build_digest, task_key
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


def fake_llm(proposals):
    return lambda prompt: json.dumps({"proposals": proposals})


def test_mining_validates_every_proposal(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    good = {"kind": "add", "role": "coordinator", "text": "Close eddy branches without velocity data.",
            "applies_when": "No velocity fields are attached.", "supporting": keys[:3],
            "counter": [], "rationale": "Repeated waste."}
    weak = {**good, "text": "Another idea.", "supporting": keys[:2]}
    invented = {**good, "text": "Invented evidence.", "supporting": ["nope1", "nope2", "nope3"]}
    long = {**good, "text": "word " * (MAX_WORDS + 1)}
    result = book.mine(fake_llm([good, weak, invented, long, good]))
    assert [p["text"] for p in result["created"]] == [good["text"]]
    assert len(result["rejected"]) == 4  # weak, invented, too long, duplicate
    assert book.active() == [] and book.version() is None  # nothing applied yet


def test_approved_coordinator_lessons_join_its_guidance(tmp_path, memory):
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    book.mine(fake_llm([{"kind": "add", "role": "coordinator",
                         "text": "Test a rival mechanism before deepening one.",
                         "applies_when": "Two drivers remain plausible.",
                         "supporting": keys[:3], "counter": []}]))
    [proposal] = book.pending()
    with pytest.raises(ValueError):
        book.decide(proposal["id"], approve=True, reviewer="", text=None)
    book.decide(proposal["id"], approve=True, reviewer="owner",
                text="Test a rival mechanism before deepening the leading one.")
    [lesson] = book.active("coordinator")
    assert lesson["edited"] and lesson["approved_by"] == "owner"
    assert "rival mechanism" in book.coordinator_guidance()
    assert not (book.skills_root / "method-lessons").exists()  # no Expert lesson yet
    version = book.version()
    with pytest.raises(ValueError):
        book.decide(proposal["id"], approve=False, reviewer="owner")  # already decided
    book.mine(fake_llm([{"kind": "retire", "lesson_id": lesson["id"],
                         "counter": keys[3:], "rationale": "Contradicted."}]))
    [retire] = book.pending()
    overview = book.overview()
    assert overview["pending"][0]["evidence_tasks"]["counter"][0]["question"].startswith("Why is")
    book.decide(retire["id"], approve=True, reviewer="owner")
    assert book.active() == [] and book.version() is None and version
    assert book.coordinator_guidance() == ""


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


def test_expert_lessons_enter_the_expert_skill_library_only(tmp_path, memory):
    pytest.importorskip("deepagents")
    from oceanx.native_skills import prepare_skill_library
    keys = mined(memory, tmp_path)
    book = LessonBook(memory)
    book.mine(fake_llm([{"kind": "add", "role": "expert", "text": "Check units before budgets.",
                         "applies_when": "Heat budget questions.", "supporting": keys[:3]}]))
    book.decide(book.pending()[0]["id"], approve=True, reviewer="owner")
    expert = prepare_skill_library(tmp_path / "lib", role="ocean_process_expert",
                                   extra_skill_dirs=(book.skills_root,))
    coordinator = prepare_skill_library(tmp_path / "lib", role="coordinator",
                                        extra_skill_dirs=(book.skills_root,))
    assert (expert / "skills" / "method-lessons" / "SKILL.md").is_file()
    assert not (coordinator / "skills" / "method-lessons").exists()
