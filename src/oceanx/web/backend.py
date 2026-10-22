"""Web-only lifetime policy, inheriting the existing backend and cache operations."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

from oceanx.backend.host import OceanBackendHost
from oceanx.cache_cleanup import CacheCleanupResult, TaskCacheCleaner
from oceanx.research.app import protocol

_LOG = logging.getLogger(__name__)


def positive_setting(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if not 0 < value < float("inf"):
        raise ValueError(f"{name} must be finite and positive")
    return value


class WebTaskCacheCleaner(TaskCacheCleaner):
    """Shorter web retention; use Desktop's protected-path and deletion methods."""

    def __init__(self, *, active_hours=24.0, archived_hours=6.0, **kwargs):
        super().__init__(**kwargs)
        if not all(0 < value < float("inf") for value in (active_hours, archived_hours)):
            raise ValueError("Cache retention must be finite and positive")
        self.active_retention = timedelta(hours=active_hours)
        self.archived_retention = timedelta(hours=archived_hours)

    def candidates(self, *, now=None):
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return self.store.list_cache_cleanup_candidates(
            active_before=(current - self.active_retention).isoformat(),
            archived_before=(current - self.archived_retention).isoformat(),
        )

    def clean_task(self, task_id, *, now=None):
        # These are the same busy/managed-directory guards as TaskCacheCleaner;
        # only the retention window is specialized. No timestamps are rewritten.
        current = (now or datetime.now(UTC)).astimezone(UTC)
        task = self.store.get_research_task(task_id)
        if task is None or task.active_request_id is not None:
            return CacheCleanupResult(task_id, 0, 0)
        retention = self.archived_retention if task.status == "archived" else self.active_retention
        if current - datetime.fromisoformat(task.updated_at).astimezone(UTC) < retention:
            return CacheCleanupResult(task_id, 0, 0)
        if any(w.state in {"planning", "working"} for w in self.store.list_task_workflows(task_id)):
            return CacheCleanupResult(task_id, 0, 0)
        if any(r.task_id == task_id for r in self.store.list_running_code_executions()):
            return CacheCleanupResult(task_id, 0, 0)
        task_root = self.task_workspaces.ensure_task_root(task_id).resolve()
        agents = task_root / "agents"
        if agents.is_symlink() or not agents.is_dir():
            return CacheCleanupResult(task_id, 0, 0)
        protected = self._published_paths(task, task_root)
        count = released = 0
        for agent in agents.iterdir():
            if agent.is_symlink() or not agent.is_dir():
                continue
            marker = agent / ".runtime/cache-policy-v1.json"
            if marker.is_symlink() or not marker.is_file():
                continue
            try:
                policy = json.loads(marker.read_text())
            except (OSError, ValueError):
                continue
            if policy.get("schema_version") != "ocean-task-cache/v1":
                continue
            roots = [agent / "scratch", agent / ".runtime/temporary"]
            if policy.get("outputs_managed") is True:
                roots.append(agent / "outputs")
            for root in roots:
                removed, size = self._prune_files(root, protected)
                count += removed
                released += size
        if count:
            with (task_root / "cache-cleanup.jsonl").open("a") as stream:
                stream.write(json.dumps({"at": current.isoformat(), "task_id": task_id,
                                         "file_count": count, "bytes_released": released}) + "\n")
        return CacheCleanupResult(task_id, count, released)


class WebBackendHost(OceanBackendHost):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_cleaner = WebTaskCacheCleaner(
            store=self.store, task_workspaces=self.task_workspace_projector,
            active_hours=positive_setting("OCEAN_WEB_CACHE_HOURS", 24),
            archived_hours=positive_setting("OCEAN_WEB_ARCHIVED_CACHE_HOURS", 6),
        )
        self.web_sweep_seconds = positive_setting("OCEAN_WEB_SWEEP_SECONDS", 3600)

    async def _maintain_cache(self):
        while not self._cache_maintenance_stop.is_set():
            try:
                for candidate in await asyncio.to_thread(self.cache_cleaner.candidates):
                    current = self.store.get_research_task(candidate.task_id)
                    if current is None or current.active_request_id is not None:
                        continue
                    # Match the original maintenance path: release idle kernels
                    # before pruning the task's managed intermediate files.
                    agents = self.task_workspace_projector.ensure_task_root(candidate.task_id) / "agents"
                    for key in tuple(self.expert_code_execution.kernels.kernels):
                        if Path(key).is_relative_to(agents):
                            await self.expert_code_execution.kernels.close(key)
                    await asyncio.to_thread(self.cache_cleaner.clean_task, candidate.task_id)
            except Exception:  # noqa: BLE001 - a failed sweep must not stop the backend
                _LOG.exception("Web task cache maintenance failed")
            try:
                await asyncio.wait_for(self._cache_maintenance_stop.wait(), self.web_sweep_seconds)
            except TimeoutError:
                pass


@asynccontextmanager
async def lifespan(app):
    from oceanx.research import services

    services._active_host = WebBackendHost(
        Path(os.environ["OCEAN_STATE_DIRECTORY"]), write_frame=lambda _: None,
    )
    services._active_host.start_cache_maintenance()
    try:
        yield
    finally:
        await services._active_host.close()
        services._active_host = None


# Reuse the native token/loopback-checked protocol, graphs and authorization.
app = Starlette(lifespan=lifespan, routes=[WebSocketRoute("/ocean/protocol", protocol)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not os.environ.get("OCEAN_SERVER_TOKEN") or not os.environ.get("OCEAN_DESKTOP_TOKEN"):
        raise RuntimeError("Web backend requires its private local-launch tokens")
    root = args.state.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["OCEAN_STATE_DIRECTORY"] = str(root)
    os.environ["OCEAN_CLIENT_KIND"] = "desktop"
    os.environ["BG_JOB_TIMEOUT_SECS"] = "inf"
    os.chdir(root)
    from langgraph_api.cli import run_server

    run_server(host="127.0.0.1", port=args.port, reload=False, open_browser=False,
               n_jobs_per_worker=64, allow_blocking=True, disable_persistence=False,
               graphs={"coordinator": "oceanx.research.graphs:coordinator"},
               http={"app": "oceanx.web.backend:app"},
               auth={"path": "oceanx.research.auth:auth"})


if __name__ == "__main__":
    main()
