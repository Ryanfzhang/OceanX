"""Source-path validation and immutable viewer grants for the browser adapter."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

MAX_RESOURCE_BYTES = 25 * 1024 * 1024
SAFE_MIME_TYPES = frozenset({
    "application/json", "application/x-netcdf", "application/octet-stream", "application/pdf",
    "application/x-ipynb+json", "image/jpeg", "image/png", "image/svg+xml", "image/webp",
    "text/csv", "text/markdown", "text/plain", "text/tab-separated-values", "text/x-python",
})


class PathNotAllowed(ValueError):
    pass


def source_path(raw: str, roots: tuple[Path, ...]) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts or candidate.is_symlink():
        raise PathNotAllowed("path_not_allowed")
    # Refuse disallowed prefixes before stat/resolve: this is not a file-existence API.
    if not any(candidate.is_relative_to(root) for root in roots):
        raise PathNotAllowed("path_not_allowed")
    try:
        real = candidate.resolve(strict=True)
        if not any(real.is_relative_to(root.resolve()) for root in roots):
            raise PathNotAllowed("path_not_allowed")
        if not real.is_file() and not real.is_dir():
            raise PathNotAllowed("not_a_source")
        return real
    except OSError as exc:
        raise PathNotAllowed("source_unavailable") from exc


@dataclass(frozen=True)
class GrantedResource:
    path: Path
    uri: str
    size: int
    digest: str
    mime: str
    expires: float


class ResourceGrants:
    def __init__(self, workspace: Path, state: Path):
        self.workspace = workspace.resolve()
        self.artifacts = (state / "artifacts").resolve()
        self.grants: dict[str, GrantedResource] = {}

    def resolve(self, uri: str) -> Path:
        parts = urlsplit(uri)
        if parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError("invalid_resource")
        if parts.scheme == "file" and not parts.netloc:
            candidate = Path(unquote(parts.path))
            root = self.workspace
        elif parts.scheme == "ocean" and parts.netloc == "artifacts":
            relative = Path(unquote(parts.path).lstrip("/"))
            if ".." in relative.parts:
                raise ValueError("invalid_resource")
            candidate = self.artifacts / relative
            root = self.artifacts
        else:
            raise ValueError("invalid_resource")
        real = candidate.resolve(strict=True)
        if not real.is_relative_to(root) or candidate.is_symlink() or not real.is_file():
            raise ValueError("invalid_resource")
        return real

    def capture(self, result: dict) -> None:
        uri = result.pop("resource_uri", None)
        token = result.get("resource_token")
        if not isinstance(token, str):
            return
        try:
            size = result.get("size_bytes")
            digest = result.get("sha256")
            mime = result.get("mime_type")
            if (not re.fullmatch(r"res_[A-Za-z0-9]+", token)
                    or not isinstance(uri, str) or type(size) is not int
                    or size < 0
                    or (size > MAX_RESOURCE_BYTES
                        and not (mime == "text/csv" and result.get("purpose") == "result_file"))
                    or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or mime not in SAFE_MIME_TYPES):
                raise ValueError("invalid_resource")
            path = self.resolve(uri)
            with path.open("rb") as stream:
                actual_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if path.stat().st_size != size or actual_digest != digest:
                raise ValueError("resource_changed")
            now = time.monotonic()
            self.grants = {k: v for k, v in self.grants.items() if v.expires > now}
            if len(self.grants) >= 512:
                self.grants.pop(next(iter(self.grants)))
            self.grants[token] = GrantedResource(path, uri, size, digest, mime, now + 600)
        except (OSError, ValueError):
            result.pop("resource_token", None)

    def open(self, token: str) -> tuple[BinaryIO, GrantedResource]:
        """Verify the file in chunks and return the same descriptor for streaming."""
        grant = self.grants.get(token)
        if grant is None or grant.expires <= time.monotonic():
            raise ValueError("resource_expired")
        path = self.resolve(grant.uri)
        if path != grant.path or path.stat().st_size != grant.size:
            raise ValueError("resource_changed")
        stream = path.open("rb")
        try:
            if hashlib.file_digest(stream, "sha256").hexdigest() != grant.digest:
                raise ValueError("resource_changed")
            stream.seek(0)
            return stream, grant
        except BaseException:
            stream.close()
            raise
