"""Atomic execution evidence manifests; not an Expert recovery or scheduling service."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_FINGERPRINT_TRANSIENT_KEYS = frozenset(
    {
        "execution_id",
        "duration_seconds",
        "logs",
        "output_root",
        "input_manifest",
        "code_path",
        "work_root",
        "attempt_number",
        "attempt_limit",
        "output_bytes",
        "ended_at",
        "fingerprint",
    }
)


def execution_result_fingerprint(payload: dict[str, Any]) -> str:
    """Return the stable scientific fingerprint shared by write and recovery paths."""

    stable = {
        key: value
        for key, value in payload.items()
        if key not in _FINGERPRINT_TRANSIENT_KEYS
    }
    return hashlib.sha256(
        json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def write_execution_result_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish the manifest that proves one execution reached settlement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
