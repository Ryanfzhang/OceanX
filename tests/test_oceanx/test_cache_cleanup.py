"""Task cache expiry must never remove active work or published evidence."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from oceanx.backend.store import RequestStore
from oceanx.cache_cleanup import TaskCacheCleaner
from oceanx.native_backend import OceanSandbox
from oceanx.task_results import TaskResultRecord, TaskResultRef
from oceanx.task_workspace import TaskWorkspaceProjector


class _Store:
    def __init__(self, task, executions=(), workflows=(), running=()):
        self.task = task
        self.executions = executions
        self.workflows = workflows
        self.running = running

    def get_research_task(self, task_id):
        return self.task if task_id == self.task.task_id else None

    def list_task_workflows(self, task_id):
        assert task_id == self.task.task_id
        return self.workflows

    def list_running_code_executions(self):
        return self.running

    def list_task_code_executions(self, *, workspace_id, task_id):
        assert (workspace_id, task_id) == (self.task.workspace_id, self.task.task_id)
        return self.executions

    def list_cache_cleanup_candidates(self, *, active_before, archived_before):
        if self.task.active_request_id is not None:
            return ()
        cutoff = archived_before if self.task.status == "archived" else active_before
        return (self.task,) if self.task.updated_at <= cutoff else ()


class _Projector:
    def __init__(self, root):
        self.root = root

    def ensure_task_root(self, task_id):
        assert task_id == "task"
        return self.root


def _task(now, *, days_old=8, status="active", active_request_id=None):
    return SimpleNamespace(
        task_id="task", workspace_id="workspace", status=status,
        active_request_id=active_request_id,
        updated_at=(now - timedelta(days=days_old)).isoformat(),
    )


def _managed_agent(root, *, outputs_managed=True):
    agent = root / "agents" / "ocean"
    (agent / ".runtime").mkdir(parents=True)
    (agent / "outputs").mkdir()
    (agent / "scratch").mkdir()
    (agent / ".runtime" / "cache-policy-v1.json").write_text(json.dumps({
        "schema_version": "ocean-task-cache/v1", "outputs_managed": outputs_managed,
    }), encoding="utf-8")
    return agent


def test_expired_cache_prunes_intermediates_but_keeps_published_figure(tmp_path):
    now = datetime(2026, 9, 24, tzinfo=UTC)
    agent = _managed_agent(tmp_path)
    (agent / "scratch" / "calculation.nc").write_bytes(b"scratch")
    (agent / ".runtime" / "temporary").mkdir()
    (agent / ".runtime" / "temporary" / "preview-buffer.nc").write_bytes(b"temporary")
    (agent / "outputs" / "unpublished.nc").write_bytes(b"orphan")
    (agent / "outputs" / "figure.nc").write_bytes(b"published")
    (agent / "outputs" / "figure.preview.png").write_bytes(b"preview")
    execution = SimpleNamespace(
        result={"work_root": str(agent), "discovered_results": [{
            "schema_version": "ocean-result-event/v1", "kind": "interactive_view",
            "data_output": "figure.nc", "preview_output": "figure.preview.png",
        }]},
    )
    cleaner = TaskCacheCleaner(
        store=_Store(_task(now), executions=(execution,)),
        task_workspaces=_Projector(tmp_path),
    )

    assert [item.task_id for item in cleaner.candidates(now=now)] == ["task"]
    result = cleaner.clean_task("task", now=now)

    assert (result.file_count, result.bytes_released) == (3, len(b"scratchorphantemporary"))
    assert not (agent / "scratch" / "calculation.nc").exists()
    assert not (agent / "outputs" / "unpublished.nc").exists()
    assert not (agent / ".runtime" / "temporary" / "preview-buffer.nc").exists()
    assert (agent / "outputs" / "figure.nc").read_bytes() == b"published"
    assert (agent / "outputs" / "figure.preview.png").read_bytes() == b"preview"
    assert json.loads((tmp_path / "cache-cleanup.jsonl").read_text().splitlines()[0])[
        "file_count"
    ] == 3


def test_cleanup_skips_active_recent_and_running_work(tmp_path):
    now = datetime(2026, 9, 24, tzinfo=UTC)
    agent = _managed_agent(tmp_path)
    scratch = agent / "scratch" / "data.nc"
    scratch.write_bytes(b"keep")
    cases = (
        (_task(now, active_request_id="request"), (), ()),
        (_task(now, days_old=2), (), ()),
        (_task(now), (SimpleNamespace(state="working"),), ()),
        (_task(now), (), (SimpleNamespace(task_id="task"),)),
    )
    for task, workflows, running in cases:
        cleaner = TaskCacheCleaner(
            store=_Store(task, workflows=workflows, running=running),
            task_workspaces=_Projector(tmp_path),
        )
        assert cleaner.clean_task("task", now=now).file_count == 0
        assert scratch.read_bytes() == b"keep"


def test_archived_retention_and_legacy_outputs(tmp_path):
    now = datetime(2026, 9, 24, tzinfo=UTC)
    agent = _managed_agent(tmp_path, outputs_managed=False)
    (agent / "scratch" / "cache.nc").write_bytes(b"scratch")
    legacy = agent / "outputs" / "old.nc"
    legacy.write_bytes(b"legacy")
    store = _Store(_task(now, days_old=0.5, status="archived"))
    cleaner = TaskCacheCleaner(
        store=store, task_workspaces=_Projector(tmp_path),
    )
    assert cleaner.clean_task("task", now=now).file_count == 0
    store.task = _task(now, days_old=2, status="archived")
    assert cleaner.clean_task("task", now=now).file_count == 1
    assert legacy.read_bytes() == b"legacy"


def test_result_manifest_path_is_protected(tmp_path):
    now = datetime(2026, 9, 24, tzinfo=UTC)
    agent = _managed_agent(tmp_path)
    figure = agent / "outputs" / "manifest-bound.nc"
    figure.write_bytes(b"keep")
    manifest = tmp_path / "results" / "figure" / "v1" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(TaskResultRecord(
        ref=TaskResultRef(task_id="task", result_id="figure"),
        workspace_id="workspace", kind="report", title="Bound figure",
        created_at=now.isoformat(),
        content={"output_path": figure.relative_to(tmp_path).as_posix()},
    ).model_dump_json(), encoding="utf-8")
    cleaner = TaskCacheCleaner(
        store=_Store(_task(now)), task_workspaces=_Projector(tmp_path),
    )
    assert cleaner.clean_task("task", now=now).file_count == 0
    assert figure.read_bytes() == b"keep"


def test_native_shell_defaults_to_scratch_not_outputs(tmp_path):
    sandbox = OceanSandbox(service=SimpleNamespace(), work_root=tmp_path, read_roots=lambda: ())
    assert sandbox.cwd == tmp_path.resolve() / "scratch"
    assert sandbox.outputs == tmp_path.resolve() / "outputs"
    assert sandbox.cwd.is_dir() and sandbox.outputs.is_dir()


def test_agent_session_marks_only_new_outputs_as_managed(tmp_path):
    projector = TaskWorkspaceProjector.__new__(TaskWorkspaceProjector)
    projector._lock = threading.RLock()
    projector.ensure_task_root = lambda _task_id: tmp_path

    new_agent = projector.expert_session_root("task", "new")
    new_policy = json.loads((new_agent / ".runtime" / "cache-policy-v1.json").read_text())
    assert new_policy["outputs_managed"] is True
    assert (new_agent / "scratch").is_dir()

    old_outputs = tmp_path / "agents" / "old" / "outputs"
    old_outputs.mkdir(parents=True)
    (old_outputs / "existing.nc").write_bytes(b"old")
    old_agent = projector.expert_session_root("task", "old")
    old_policy = json.loads((old_agent / ".runtime" / "cache-policy-v1.json").read_text())
    assert old_policy["outputs_managed"] is False


def test_store_candidate_query_respects_status_and_active_request(tmp_path):
    now = datetime(2026, 9, 24, tzinfo=UTC)
    store = RequestStore(tmp_path / "state.sqlite3")
    try:
        for task_id in ("old_active", "old_archived", "recent", "in_progress"):
            store.create_research_task(workspace_id="workspace", title=task_id, task_id=task_id)
        old = (now - timedelta(days=8)).isoformat()
        archived = (now - timedelta(days=2)).isoformat()
        store._connection.execute(
            "UPDATE research_tasks SET updated_at=? WHERE task_id IN ('old_active', 'in_progress')",
            (old,),
        )
        store._connection.execute(
            "UPDATE research_tasks SET status='archived', updated_at=? WHERE task_id='old_archived'",
            (archived,),
        )
        store._connection.execute(
            "UPDATE research_tasks SET active_request_id='request' WHERE task_id='in_progress'"
        )
        candidates = store.list_cache_cleanup_candidates(
            active_before=(now - timedelta(days=7)).isoformat(),
            archived_before=(now - timedelta(days=1)).isoformat(),
        )
        assert {task.task_id for task in candidates} == {"old_active", "old_archived"}
    finally:
        store.close()


def test_corrupt_result_manifest_prevents_cleanup(tmp_path):
    now = datetime(2026, 9, 24, tzinfo=UTC)
    agent = _managed_agent(tmp_path)
    scratch = agent / "scratch" / "calculation.nc"
    scratch.write_bytes(b"keep")
    manifest = tmp_path / "results" / "figure" / "v1" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{broken", encoding="utf-8")
    cleaner = TaskCacheCleaner(
        store=_Store(_task(now)), task_workspaces=_Projector(tmp_path),
    )
    try:
        cleaner.clean_task("task", now=now)
    except ValueError as exc:
        assert "Cannot verify published result" in str(exc)
    else:
        raise AssertionError("Corrupt published manifest must stop cache cleanup")
    assert scratch.read_bytes() == b"keep"
