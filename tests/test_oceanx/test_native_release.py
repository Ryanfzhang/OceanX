"""Breaking release: fresh state, one current figure format, no journal conversion."""

import sqlite3

import pytest

from oceanx.backend.store import RequestStore, RequestStoreError
from oceanx.expert_deliverables import ExpertDeliverableError, hydrate_scientific_manifest
from oceanx.storage import OceanPaths


@pytest.mark.parametrize("version", [9, 35, 46, 47])
def test_legacy_database_is_rejected_without_migration_or_data_loss(tmp_path, version):
    database = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER)")
        connection.execute("INSERT INTO schema_migrations VALUES (?)", (version,))
        connection.execute("CREATE TABLE old_results (answer TEXT)")
        connection.execute("INSERT INTO old_results VALUES ('original answer')")
    before = database.read_bytes()
    with pytest.raises(RequestStoreError, match="Unsupported legacy database"):
        RequestStore(database)
    assert database.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_native_database_reopens_and_preserves_current_tasks(tmp_path):
    database = tmp_path / "native.sqlite3"
    store = RequestStore(database)
    store.create_research_task(workspace_id="ws", task_id="task_native", title="New research")
    store.close()
    store = RequestStore(database)
    try:
        assert store.get_research_task("task_native").title == "New research"
        assert store._connection.execute("SELECT version FROM storage_contract").fetchone()[0] == "oceanx-agent-server/v3"
        assert store._connection.execute("SELECT name FROM sqlite_master WHERE name = 'schema_migrations'").fetchone() is None
    finally:
        store.close()


def test_project_does_not_open_old_state_directory(tmp_path):
    old = tmp_path / ".oceanmind"
    old.mkdir()
    (old / "workspace.sqlite3").write_bytes(b"old database left untouched")
    paths = OceanPaths.for_project(tmp_path)
    assert paths.root == tmp_path / ".oceanx"
    assert (old / "workspace.sqlite3").read_bytes() == b"old database left untouched"


def test_retired_builders_and_tree_tools_are_not_available():
    from oceanx import scientific_view, tools
    assert not hasattr(scientific_view, "ScientificMap")
    assert not hasattr(scientific_view, "publish_report")
    assert not hasattr(tools, "OceanExplorationTool")
    assert not hasattr(tools, "OceanExpertTestsTool")


@pytest.mark.parametrize("schema", ["ocean-scientific-view/v1", "ocean-scientific-figure/v2", "ocean-scientific-figure/v3"])
def test_old_figure_manifest_is_not_upgraded(schema, tmp_path):
    with pytest.raises(ExpertDeliverableError, match="incompatible"):
        hydrate_scientific_manifest({"schema_version": schema}, tmp_path / "absent.nc")


def test_legacy_handoff_aliases_are_not_accepted():
    from oceanx.team.models import CoordinatorResult
    assert "work_order_id" not in CoordinatorResult.model_json_schema()["properties"]
    with pytest.raises(ValueError, match="deliverable_refs"):
        CoordinatorResult(answer_markdown="Old answer", deliverable_refs=[])
