"""Task-scoped files exposed to the desktop.

Reports and supplementary files may use durable manifests. Interactive views
are only the self-describing NetCDF files explicitly declared by
``ScientificFigure.save()``. Ordinary NetCDF outputs remain data files and
never become UI results by directory scan.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from oceanx.task_workspace import TaskWorkspaceProjector


class TaskResultError(RuntimeError):
    """A task result cannot be written or read safely."""


class TaskResultRef(BaseModel):
    """Small identity passed between an Expert, Coordinator, and frontend."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    result_id: str
    version: int = 1

    @property
    def key(self) -> str:
        return f"{self.task_id}:{self.result_id}@v{self.version}"


class TaskResultFile(BaseModel):
    path: str
    mime_type: str
    size: int = Field(ge=0)
    sha256: str


class TaskResultRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: TaskResultRef
    workspace_id: str
    kind: Literal["interactive_view", "report", "file", "table"]
    title: str
    summary: str = ""
    created_at: str
    origin_request_id: str | None = None
    agent_run_id: str | None = None
    execution_id: str | None = None
    # Immutable execution outputs represented by this result. Keeping this
    # binding inside the atomically written manifest makes the TaskResult
    # self-describing without asking an Expert to repeat publication.
    execution_output_names: tuple[str, ...] = ()
    materialization_key: str | None = None
    source_refs: tuple[dict[str, Any], ...] = ()
    content: dict[str, Any] = Field(default_factory=dict)
    files: tuple[TaskResultFile, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["result_ref"] = payload.pop("ref")
        return payload


class TaskResultStore:
    """Write and list results inside the task that owns them."""

    def __init__(self, *, task_workspaces: TaskWorkspaceProjector) -> None:
        self.task_workspaces = task_workspaces
        self._lock = threading.RLock()
        self._view_cache: dict[tuple[str, int, int, str], TaskResultRecord] = {}

    def put(
        self,
        *,
        workspace_id: str,
        task_id: str,
        kind: Literal["interactive_view", "report", "file", "table"],
        title: str,
        summary: str = "",
        content: dict[str, Any] | None = None,
        files: dict[str, Path | bytes] | None = None,
        workspace_files: dict[str, Path] | None = None,
        source_refs: tuple[dict[str, Any], ...] = (),
        origin_request_id: str | None = None,
        agent_run_id: str | None = None,
        execution_id: str | None = None,
        execution_output_names: tuple[str, ...] = (),
        materialization_key: str | None = None,
    ) -> TaskResultRecord:
        """Create an immutable result manifest.

        ``files`` are accepted evidence and are linked/copied into the result
        directory. ``workspace_files`` are deliberately mutable user-facing
        files (currently the single supplementary notebook); only their path
        and creation-time checksum are recorded in the manifest.
        """
        with self._lock:
            existing = self.find_by_materialization_key(
                task_id=task_id,
                materialization_key=materialization_key,
            )
            if existing is not None:
                return existing

            result_id = self._result_id(
                task_id=task_id,
                kind=kind,
                title=title,
                execution_id=execution_id,
                materialization_key=materialization_key,
            )
            ref = TaskResultRef(task_id=task_id, result_id=result_id)
            result_root = self._result_root(ref)
            if result_root.exists():
                return self.get(ref)

            result_root.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(prefix=f".{result_id}-", dir=result_root.parent)
            )
            try:
                content_payload = dict(content or {})
                file_records: list[TaskResultFile] = []
                for relative_name, value in (files or {}).items():
                    safe_name = self._safe_relative_path(relative_name)
                    destination = staging / safe_name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(value, bytes):
                        destination.write_bytes(value)
                    else:
                        source = value.resolve(strict=True)
                        if not source.is_file() or source.is_symlink():
                            raise TaskResultError(
                                f"Result file is unavailable or unsafe: {value}"
                            )
                        # Published results are an immutable index over the
                        # Expert's already-saved file. A hard link keeps one
                        # physical scientific payload; atomic source replacement
                        # leaves the accepted inode unchanged. Cross-device
                        # stores fall back to a copy.
                        try:
                            os.link(source, destination)
                        except OSError:
                            shutil.copyfile(source, destination)
                    size = destination.stat().st_size
                    digest = hashlib.sha256()
                    with destination.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    mime_type = (
                        "application/x-ipynb+json"
                        if destination.suffix.lower() == ".ipynb"
                        else mimetypes.guess_type(destination.name)[0]
                        or "application/octet-stream"
                    )
                    file_records.append(
                        TaskResultFile(
                            path=safe_name.as_posix(),
                            mime_type=mime_type,
                            size=size,
                            sha256=digest.hexdigest(),
                        )
                    )

                workspace_file_locations: dict[str, str] = {}
                task_root = self.task_workspaces.ensure_task_root(task_id).resolve(strict=True)
                for relative_name, value in (workspace_files or {}).items():
                    safe_name = self._safe_relative_path(relative_name)
                    if any(item.path == safe_name.as_posix() for item in file_records):
                        raise TaskResultError(
                            f"Result file is declared twice: {safe_name.as_posix()}"
                        )
                    source = value.resolve(strict=True)
                    if source.is_symlink() or not source.is_file() or task_root not in source.parents:
                        raise TaskResultError(
                            f"Workspace result file is unavailable or unsafe: {value}"
                        )
                    workspace_relative = source.relative_to(task_root).as_posix()
                    digest = hashlib.sha256()
                    with source.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    mime_type = (
                        "application/x-ipynb+json"
                        if source.suffix.lower() == ".ipynb"
                        else mimetypes.guess_type(source.name)[0]
                        or "application/octet-stream"
                    )
                    file_records.append(
                        TaskResultFile(
                            path=safe_name.as_posix(),
                            mime_type=mime_type,
                            size=source.stat().st_size,
                            sha256=digest.hexdigest(),
                        )
                    )
                    workspace_file_locations[safe_name.as_posix()] = workspace_relative
                if workspace_file_locations:
                    content_payload["workspace_files"] = workspace_file_locations

                record = TaskResultRecord(
                    ref=ref,
                    workspace_id=workspace_id,
                    kind=kind,
                    title=title.strip() or kind.replace("_", " ").title(),
                    summary=summary.strip(),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    origin_request_id=origin_request_id,
                    agent_run_id=agent_run_id,
                    execution_id=execution_id,
                    execution_output_names=tuple(
                        dict.fromkeys(
                            self._safe_relative_path(name).as_posix()
                            for name in execution_output_names
                        )
                    ),
                    materialization_key=materialization_key,
                    source_refs=source_refs,
                    content=content_payload,
                    files=tuple(file_records),
                )
                self._write_json(staging / "manifest.json", record.model_dump(mode="json"))
                os.replace(staging, result_root)
                return record
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise

    def get(self, ref: TaskResultRef) -> TaskResultRecord:
        discovered = next(
            (item for item in self._agent_views(task_id=ref.task_id) if item.ref == ref),
            None,
        )
        if discovered is not None:
            return discovered
        manifest = self._result_root(ref) / "manifest.json"
        try:
            return TaskResultRecord.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TaskResultError(f"Task result is unavailable: {ref.key}") from exc

    def list(self, *, task_id: str) -> tuple[TaskResultRecord, ...]:
        root = self.task_workspaces.ensure_task_root(task_id) / "results"
        records: list[TaskResultRecord] = []
        if root.exists():
            for manifest in sorted(root.glob("*/v*/manifest.json")):
                try:
                    record = TaskResultRecord.model_validate_json(
                        manifest.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    continue
                if record.ref.task_id == task_id and record.kind != "interactive_view":
                    records.append(record)
        records.extend(self._agent_views(task_id=task_id))
        records.sort(key=lambda item: (item.created_at, item.ref.result_id))
        return tuple(records)

    def _agent_views(self, *, task_id: str) -> tuple[TaskResultRecord, ...]:
        task_root = self.task_workspaces.ensure_task_root(task_id).resolve(strict=True)
        task = self.task_workspaces.store.get_research_task(task_id)
        if task is None:
            return ()
        declarations: dict[
            tuple[str, str], tuple[Any, dict[str, Any], Path, Path, Path | None]
        ] = {}
        for execution in self.task_workspaces.store.list_task_code_executions(
            workspace_id=task.workspace_id,
            task_id=task_id,
        ):
            result = execution.result
            # ``ScientificFigure.save()`` is the delivery boundary. If later
            # code in the same execution fails, the already-declared figure
            # remains available as long as its event and bytes are valid.
            if execution.state == "running" or not isinstance(result, dict):
                continue
            work_root_name = result.get("work_root")
            events = result.get("discovered_results")
            if not isinstance(work_root_name, str) or not isinstance(events, list):
                continue
            try:
                output_root = (Path(work_root_name) / "outputs").resolve(strict=True)
                output_root.relative_to(task_root)
            except (OSError, ValueError):
                continue
            for event in events:
                if (
                    not isinstance(event, dict)
                    or event.get("schema_version") != "ocean-result-event/v1"
                    or event.get("kind") != "interactive_view"
                ):
                    continue
                output_name = event.get("data_output")
                if not isinstance(output_name, str):
                    continue
                try:
                    safe_output = self._safe_relative_path(output_name)
                    path = (output_root / safe_output).resolve(strict=True)
                    path.relative_to(output_root)
                    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".nc":
                        continue
                except (OSError, ValueError, TaskResultError):
                    continue
                preview_path: Path | None = None
                preview_name = event.get("preview_output")
                if isinstance(preview_name, str):
                    try:
                        candidate = (
                            output_root / self._safe_relative_path(preview_name)
                        ).resolve(strict=True)
                        candidate.relative_to(output_root)
                        if (
                            candidate.is_file()
                            and not candidate.is_symlink()
                            and candidate.suffix.lower() == ".png"
                        ):
                            preview_path = candidate
                    except (OSError, ValueError, TaskResultError):
                        pass
                # A later explicit save of the same Agent-owned result replaces
                # the earlier declaration and bytes as one atomic figure.
                declarations[(execution.agent_thread_id, output_name)] = (
                    execution,
                    event,
                    path,
                    output_root,
                    preview_path,
                )

        records: list[TaskResultRecord] = []
        for execution, event, path, output_root, preview_path in declarations.values():
            try:
                stat = path.stat()
                event_identity = json.dumps(event, sort_keys=True, ensure_ascii=True)
                key = (str(path), stat.st_mtime_ns, stat.st_size, event_identity)
                record = self._view_cache.get(key)
                if record is None:
                    record = self._agent_view_record(
                        task_id=task_id,
                        workspace_id=task.workspace_id,
                        task_root=task_root,
                        output_root=output_root,
                        agent_key=execution.agent_thread_id,
                        execution_id=execution.execution_id,
                        origin_request_id=(
                            str(execution.request["origin_request_id"])
                            if isinstance(execution.request, dict)
                            and execution.request.get("origin_request_id")
                            else None
                        ),
                        created_at=execution.ended_at,
                        event=event,
                        path=path,
                        preview=preview_path,
                    )
                    if record is not None:
                        self._view_cache[key] = record
                if record is not None:
                    records.append(record)
            except (OSError, ValueError, TypeError):
                continue
        return tuple(records)

    @staticmethod
    def _agent_view_record(
        *,
        task_id: str,
        workspace_id: str,
        task_root: Path,
        output_root: Path,
        agent_key: str,
        execution_id: str,
        origin_request_id: str | None,
        created_at: str | None,
        event: dict[str, Any],
        path: Path,
        preview: Path | None,
    ) -> TaskResultRecord | None:
        try:
            import xarray as xr

            source = xr.open_dataset(path, decode_cf=False, mask_and_scale=False)
        except Exception:
            return None
        try:
            if source.attrs.get("ocean_view_schema") != "ocean-view-netcdf/v1":
                return None
            stored_origin_request_id = source.attrs.get("ocean_origin_request_id")
            if (
                isinstance(stored_origin_request_id, str)
                and stored_origin_request_id.strip()
            ):
                origin_request_id = stored_origin_request_id
            raw = source.attrs.get("ocean_view")
            if not isinstance(raw, str):
                return None
            view = json.loads(raw)
            if not isinstance(view, dict) or view.get("schema_version") not in {
                "ocean-scientific-figure/v4",
                "ocean-interactive-spatial/v2",
            }:
                return None
        except (TypeError, ValueError):
            return None
        finally:
            source.close()

        relative = path.relative_to(task_root).as_posix()
        try:
            output_relative = path.relative_to(output_root)
        except ValueError:
            return None
        local_key = output_relative.with_suffix("").as_posix()
        result_key = f"{agent_key}/{local_key}"
        identity = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:32]

        def file_record(file_path: Path, logical_name: str, mime_type: str) -> TaskResultFile:
            digest = hashlib.sha256()
            with file_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return TaskResultFile(
                path=logical_name,
                mime_type=mime_type,
                size=file_path.stat().st_size,
                sha256=digest.hexdigest(),
            )

        files = [file_record(path, "data.nc", "application/x-netcdf")]
        workspace_files = {"data.nc": relative}
        if preview is not None:
            files.append(file_record(preview, "preview.png", "image/png"))
            workspace_files["preview.png"] = preview.relative_to(task_root).as_posix()

        title = next(
            (
                value.strip()
                for value in (event.get("title"), view.get("title"))
                if isinstance(value, str) and value.strip()
            ),
            "",
        )
        summary = next(
            (
                value.strip()
                for value in (event.get("summary"), view.get("caption"), view.get("subtitle"))
                if isinstance(value, str) and value.strip()
            ),
            "",
        )
        view_kind = view.get("view_kind") or view.get("plot_kind") or "interactive_view"
        features = view.get("features") if isinstance(view.get("features"), list) else []
        content: dict[str, Any] = {
            "agent_key": agent_key,
            "result_key": result_key,
            "output_path": relative,
            "view_kind": str(view_kind),
            "render_status": "interactive",
            "data_file": "data.nc",
            "dataset_file": "data.nc",
            "workspace_files": workspace_files,
            "features": features,
        }
        if len(files) > 1:
            content["preview_file"] = "preview.png"
        return TaskResultRecord(
            ref=TaskResultRef(task_id=task_id, result_id=f"view_{identity}"),
            workspace_id=workspace_id,
            kind="interactive_view",
            title=(title.strip() or local_key.replace("_", " ")),
            summary=summary,
            created_at=created_at
            or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            origin_request_id=origin_request_id,
            agent_run_id=agent_key,
            execution_id=execution_id,
            execution_output_names=(result_key, local_key, path.name, relative),
            content=content,
            files=tuple(files),
        )

    def list_payloads(self, *, task_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(item.as_payload() for item in self.list(task_id=task_id))

    def find_by_materialization_key(
        self,
        *,
        task_id: str,
        materialization_key: str | None,
    ) -> TaskResultRecord | None:
        if not materialization_key:
            return None
        for item in self.list(task_id=task_id):
            if item.materialization_key == materialization_key:
                return item
        return None

    def file_path(self, *, ref: TaskResultRef, relative_path: str) -> Path:
        safe = self._safe_relative_path(relative_path)
        record = self.get(ref)
        workspace_files = record.content.get("workspace_files")
        if isinstance(workspace_files, dict):
            workspace_relative = workspace_files.get(safe.as_posix())
            if isinstance(workspace_relative, str):
                workspace_safe = self._safe_relative_path(workspace_relative)
                task_root = self.task_workspaces.ensure_task_root(ref.task_id).resolve(
                    strict=True
                )
                candidate = (task_root / workspace_safe).resolve(strict=True)
                if task_root not in candidate.parents or not candidate.is_file():
                    raise TaskResultError("Task workspace result file is unavailable")
                return candidate
        candidate = (self._result_root(ref) / safe).resolve(strict=True)
        root = self._result_root(ref).resolve(strict=True)
        if root not in candidate.parents or not candidate.is_file():
            raise TaskResultError("Task result file is unavailable")
        return candidate

    def _result_root(self, ref: TaskResultRef) -> Path:
        task_root = self.task_workspaces.ensure_task_root(ref.task_id)
        return task_root / "results" / ref.result_id / f"v{ref.version:04d}"

    @staticmethod
    def _result_id(
        *,
        task_id: str,
        kind: str,
        title: str,
        execution_id: str | None,
        materialization_key: str | None,
    ) -> str:
        identity = materialization_key or "\x1f".join(
            (task_id, kind, title, execution_id or "")
        )
        return f"result_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"

    @staticmethod
    def _safe_relative_path(value: str) -> PurePosixPath:
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise TaskResultError(f"Unsafe task result path: {value}")
        return path

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
