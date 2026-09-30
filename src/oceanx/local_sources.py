"""Resolve neutral local file/directory artifacts mounted into a Task."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from oceanx.artifacts.models import ArtifactRef
from oceanx.backend.store import RequestStore
from oceanx.storage import is_safe_cross_platform_relative_path


class LocalSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedLocalSource:
    path: Path
    kind: str
    format: str


def resolve_local_source(
    *, store: RequestStore, workspace_id: str, ref: ArtifactRef
) -> ResolvedLocalSource:
    artifact = store.get_artifact(workspace_id=workspace_id, ref=ref)
    if (
        artifact is None
        or artifact.artifact_type != "project_context"
        or artifact.schema_version != "ocean-local-source/v1"
    ):
        raise LocalSourceError("Artifact is not a local Task source")
    raw = artifact.content.get("source_path")
    if not isinstance(raw, str):
        relative = artifact.content.get("source_relative_path")
        workspace = store.workspace_snapshot(workspace_id)
        if not isinstance(relative, str) or not workspace.path:
            raise LocalSourceError("Local source has no resolvable path")
        if not is_safe_cross_platform_relative_path(relative):
            raise LocalSourceError("Local source path is unsafe")
        raw = str(Path(workspace.path).joinpath(*PurePosixPath(relative).parts))
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or candidate.is_symlink():
        raise LocalSourceError("Local source path is invalid")
    try:
        path = candidate.resolve(strict=True)
    except OSError as exc:
        raise LocalSourceError("Local source is unavailable") from exc
    kind = str(artifact.content.get("source_kind", ""))
    if kind == "file" and not path.is_file():
        raise LocalSourceError("Local source is not a file")
    if kind == "directory" and not path.is_dir():
        raise LocalSourceError("Local source is not a directory")
    if kind not in {"file", "directory"}:
        raise LocalSourceError("Local source kind is invalid")
    return ResolvedLocalSource(
        path=path,
        kind=kind,
        format=str(artifact.content.get("format") or path.suffix.lstrip(".") or kind),
    )


__all__ = ["LocalSourceError", "ResolvedLocalSource", "resolve_local_source"]
