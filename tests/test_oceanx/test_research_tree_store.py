"""Phase 1: SQLite-canonical research tree with an improvement log.

These tests pin two properties: the Coordinator-visible behaviour is unchanged, and
every decision and delivery is recorded atomically for later policy analysis.
"""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from oceanx.research.tree import ResearchTree, projection
from oceanx.research.tree_store import POLICY_V0, TreeStore


@pytest.fixture
def tree(tmp_path):
    return ResearchTree(tmp_path / "coordinator" / "research_tree.json")


def _seed(tree):
    return tree.update([
        {"action": "add", "target": "ROOT", "question": "What sustains the warm anomaly?"},
        {"action": "add", "target": "B1", "question": "Surface heat flux share?",
         "status": "selected"},
        {"action": "add", "target": "B1", "question": "Eddy advection share?"},
    ])


def test_store_is_canonical_and_json_is_an_identical_export(tree):
    _seed(tree)
    stored = tree.store.load()
    exported = json.loads(tree.path.read_text())
    assert stored == exported
    assert tree.store.path.name == "research_tree.sqlite3"


def test_decision_batch_is_logged_with_node_ids_reasons_and_policy(tree):
    _seed(tree)
    tree.update([
        {"action": "set_status", "target": "B1.2", "status": "selected"},
        {"action": "close", "target": "B1.2", "reason": "No eddy-resolving velocity data."},
    ])
    events = tree.events()
    assert [(e["type"], e["node_id"]) for e in events] == [
        ("created", "B1"), ("created", "B1.1"), ("selected", "B1.1"), ("created", "B1.2"),
        ("selected", "B1.2"), ("closed", "B1.2"),
    ]
    assert events[-1]["reason"] == "No eddy-resolving velocity data."
    assert events[1]["payload"]["parent"] == "B1"
    assert {e["policy_version"] for e in events} == {POLICY_V0}
    assert events[-1]["revision"] == tree.store.load()["revision"]


def test_every_delivery_is_kept_as_an_attempt_while_node_shows_latest(tree):
    _seed(tree)
    tree.attach_result("B1.1", summary="Result: flux dominates onset.", agent_key="physics-a",
                       report_path="/r/a.md", delegation_id="d1", expert_role="ocean_process_expert",
                       output_refs=("physics-a/budget",))
    tree.attach_result("B1.1", summary="Result: flux dominates; residual 20%.",
                       agent_key="physics-b", report_path="/r/b.md", delegation_id="d2")
    attempts = tree.attempts("B1.1")
    assert [a["agent_key"] for a in attempts] == ["physics-a", "physics-b"]
    assert attempts[0]["output_refs"] == ["physics-a/budget"]
    assert attempts[0]["delegation_id"] == "d1"
    assert attempts[0]["attempt_id"] != attempts[1]["attempt_id"]
    node = tree.store.load()["nodes"]["B1.1"]
    assert node["result"]["agent_key"] == "physics-b"
    assert node["status"] == "selected"  # delivery never decides scientific progress
    assert [e["type"] for e in tree.events("B1.1")][-2:] == ["attempt_returned"] * 2


def test_model_visible_projection_is_unchanged_by_logging(tree):
    _seed(tree)
    tree.attach_result("B1.1", summary="Result: x.", agent_key="a", report_path="/r.md")
    view = tree.read(include_history=True)
    assert view == projection(json.loads(tree.path.read_text()), include_history=True)
    text = json.dumps(view)
    for hidden in ("attempt_id", "delegation_id", "policy_version", "tree_events"):
        assert hidden not in text


def test_failed_commit_leaves_tree_and_log_unchanged(tree, monkeypatch):
    _seed(tree)
    before_doc = tree.store.load()
    before_json = tree.path.read_text()
    before_events = len(tree.events())

    import oceanx.research.tree as tree_module
    from oceanx.research.tree_store import TreeEvent

    # The tree row is written first; an unserializable event payload then fails
    # inside the same transaction, which must roll the tree row back too.
    monkeypatch.setattr(tree_module, "events_for_changes",
                        lambda changes, created: [TreeEvent("selected", "B1.2", None,
                                                            {"bad": object()})])
    with pytest.raises(TypeError):
        tree.update([{"action": "set_status", "target": "B1.2", "status": "selected"}])
    assert tree.store.load() == before_doc
    assert tree.path.read_text() == before_json
    assert len(tree.events()) == before_events


def test_legacy_json_task_is_adopted_then_sqlite_becomes_canonical(tmp_path):
    path = tmp_path / "research_tree.json"
    legacy = ResearchTree(tmp_path / "scratch" / "research_tree.json")
    _seed(legacy)
    path.write_text(legacy.path.read_text())
    tree = ResearchTree(path)
    assert not tree.store.path.exists()
    assert tree.read()["candidates"] == ["B1.2"]
    tree.update([{"action": "set_status", "target": "B1.2", "status": "selected"}])
    assert tree.store.path.exists()
    assert tree.store.load()["nodes"]["B1.2"]["status"] == "selected"
    assert [e["type"] for e in tree.events()] == ["selected"]


def test_concurrent_batches_keep_revision_and_log_consistent(tree):
    _seed(tree)
    base = tree.store.load()["revision"]

    def add(index):
        tree.update([{"action": "add", "target": "B1", "question": f"Alternative {index}?"}])

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(add, range(12)))
    doc = tree.store.load()
    assert doc["revision"] == base + 12
    created = [e for e in tree.events() if e["type"] == "created"]
    assert [e["payload"].get("at_creation") for e in tree.events() if e["type"] == "selected"] == [True]
    assert len(created) == 3 + 12
    assert len({e["node_id"] for e in created}) == len(created)
    assert json.loads(tree.path.read_text()) == doc


def test_store_rejects_unknown_schema(tmp_path):
    store = TreeStore(tmp_path / "t.sqlite3")
    store.commit({"schema_version": "x", "revision": 0, "nodes": {}, "links": []})
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE store_meta SET value = 'other/v9' WHERE key = 'schema'")
    with pytest.raises(ValueError):
        store.load()
