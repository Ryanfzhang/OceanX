"""Expire task-owned intermediate files without touching published evidence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from oceanx.backend.store import RequestStore, ResearchTaskRecord
from oceanx.figure_delivery import static_figure_files, static_figures
from oceanx.task_results import TaskResultRecord
from oceanx.task_workspace import TaskWorkspaceProjector

ACTIVE_CACHE_RETENTION = timedelta(days=7)
ARCHIVED_CACHE_RETENTION = timedelta(days=1)
_RUNNING_WORKFLOWS = frozenset({"planning", "working"})


@dataclass(frozen=True)
class CacheCleanupResult:
    task_id: str
    file_count: int
    bytes_released: int


class TaskCacheCleaner:
    """Only remove files in managed scratch and unreferenced managed outputs."""

    def __init__(
        self, *, store: RequestStore, task_workspaces: TaskWorkspaceProjector,
    ) -> None:
        self.store = store
        self.task_workspaces = task_workspaces

    def candidates(self, *, now: datetime | None = None) -> tuple[ResearchTaskRecord, ...]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return self.store.list_cache_cleanup_candidates(
            active_before=(current - ACTIVE_CACHE_RETENTION).isoformat(),
            archived_before=(current - ARCHIVED_CACHE_RETENTION).isoformat(),
        )

    def clean_task(
        self, task_id: str, *, now: datetime | None = None,
    ) -> CacheCleanupResult:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        task = self.store.get_research_task(task_id)
        if task is None or task.active_request_id is not None:
            return CacheCleanupResult(task_id, 0, 0)
        retention = (
            ARCHIVED_CACHE_RETENTION if task.status == "archived" else ACTIVE_CACHE_RETENTION
        )
        if current - datetime.fromisoformat(task.updated_at).astimezone(UTC) < retention:
            return CacheCleanupResult(task_id, 0, 0)
        if any(
            workflow.state in _RUNNING_WORKFLOWS
            for workflow in self.store.list_task_workflows(task_id)
        ):
            return CacheCleanupResult(task_id, 0, 0)
        if any(record.task_id == task_id for record in self.store.list_running_code_executions()):
            return CacheCleanupResult(task_id, 0, 0)

        task_root = self.task_workspaces.ensure_task_root(task_id).resolve()
        agents = task_root / "agents"
        if agents.is_symlink() or not agents.is_dir():
            return CacheCleanupResult(task_id, 0, 0)
        protected = self._published_paths(task, task_root)
        count = total_bytes = 0
        for agent in agents.iterdir():
            if agent.is_symlink() or not agent.is_dir():
                continue
            marker = agent / ".runtime" / "cache-policy-v1.json"
            if marker.is_symlink() or not marker.is_file():
                continue
            try:
                policy = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if policy.get("schema_version") != "ocean-task-cache/v1":
                continue
            for cache_root in (agent / "scratch", agent / ".runtime" / "temporary"):
                removed, released = self._prune_files(cache_root, protected)
                count += removed
                total_bytes += released
            if policy.get("outputs_managed") is True:
                removed, released = self._prune_files(agent / "outputs", protected)
                count += removed
                total_bytes += released
        if count:
            audit = task_root / "cache-cleanup.jsonl"
            with audit.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "at": current.isoformat(), "task_id": task_id,
                    "file_count": count, "bytes_released": total_bytes,
                }) + "\n")
        return CacheCleanupResult(task_id, count, total_bytes)

    def _published_paths(
        self, task: ResearchTaskRecord, task_root: Path,
    ) -> frozenset[Path]:
        protected: set[Path] = set()

        def add(root: Path, name: object) -> None:
            if not isinstance(name, str) or not name:
                return
            relative = PurePosixPath(name)
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                return
            candidate = (root / Path(*relative.parts)).resolve()
            if candidate.is_relative_to(root):
                protected.add(candidate)

        for record in self.store.list_task_code_executions(
            workspace_id=task.workspace_id, task_id=task.task_id,
        ):
            result = record.result
            if not isinstance(result, dict) or not isinstance(result.get("work_root"), str):
                continue
            output_root = (Path(result["work_root"]) / "outputs").resolve()
            if not output_root.is_relative_to(task_root / "agents"):
                continue
            events = result.get("discovered_results")
            if not isinstance(events, (list, tuple)):
                continue
            for event in events:
                if not isinstance(event, dict):
                    continue
                for field in ("data_output", "preview_output", "report_output", "dataset_output"):
                    add(output_root, event.get(field))
                attachments = event.get("attachment_outputs")
                for name in attachments if isinstance(attachments, (list, tuple)) else ():
                    add(output_root, name)

        # Read only small delivery manifests. TaskResultStore.list() also hashes
        # every published NetCDF, which is inappropriate for routine cleanup.
        result_root = task_root / "results"
        if result_root.is_symlink():
            raise ValueError("Task result directory is not a managed directory")
        for manifest in result_root.glob("*/v*/manifest.json") if result_root.is_dir() else ():
            try:
                record = TaskResultRecord.model_validate_json(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                # Never infer that a corrupt manifest means its files are unbound.
                raise ValueError(f"Cannot verify published result: {manifest}") from exc
            if record.ref.task_id != task.task_id:
                continue
            add(task_root, record.content.get("output_path"))
            files = record.content.get("workspace_files")
            if isinstance(files, dict):
                for name in files.values():
                    add(task_root, name)
        if static_figures():
            # In a static-delivery run the delivered figures are the images under outputs.
            protected.update(path.resolve() for _, path in static_figure_files(task_root))
        return frozenset(protected)

    @staticmethod
    def _prune_files(root: Path, protected: frozenset[Path]) -> tuple[int, int]:
        if root.is_symlink() or not root.is_dir():
            return 0, 0
        count = total_bytes = 0
        for directory, _, files in os.walk(root, topdown=False, followlinks=False):
            parent = Path(directory)
            for name in files:
                path = parent / name
                if path.is_symlink() or not path.is_file() or path.resolve() in protected:
                    continue
                metadata = path.stat()
                # Removing one name does not release blocks when another hardlink
                # (for example a copied result) still points to the same inode.
                size = metadata.st_size if metadata.st_nlink == 1 else 0
                path.unlink()
                count += 1
                total_bytes += size
            if parent != root and not parent.is_symlink():
                try:
                    parent.rmdir()
                except OSError:
                    pass
        return count, total_bytes
