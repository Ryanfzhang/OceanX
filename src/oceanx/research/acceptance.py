"""Frozen acceptance criteria for research-policy changes.

The criteria live in ``resources/evals/research_policy_acceptance.yaml`` (or the path
in ``OCEANX_ACCEPTANCE_FILE``). Freezing writes ``<file>.lock`` with its SHA-256.
Paired-run acceptance calls :func:`require_frozen`, so the criteria cannot be
edited after freezing without it being detected. Nothing automated writes this file.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

ACCEPTANCE_ENV = "OCEANX_ACCEPTANCE_FILE"
BUNDLED = Path(__file__).resolve().parents[1] / "resources" / "evals" / \
    "research_policy_acceptance.yaml"


class AcceptanceNotFrozen(RuntimeError):
    pass


def acceptance_path() -> Path:
    return Path(os.environ.get(ACCEPTANCE_ENV) or BUNDLED).expanduser()


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path | None = None) -> dict:
    path = path or acceptance_path()
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_frozen(path: Path | None = None) -> bool:
    path = path or acceptance_path()
    lock = _lock_path(path)
    if not lock.is_file():
        return False
    record = json.loads(lock.read_text(encoding="utf-8"))
    return record.get("sha256") == _digest(path)


def require_frozen(path: Path | None = None) -> dict:
    path = path or acceptance_path()
    if not _lock_path(path).is_file():
        raise AcceptanceNotFrozen(
            f"{path.name} is not frozen; review it and run `ocean research freeze-acceptance`.")
    if not is_frozen(path):
        raise AcceptanceNotFrozen(f"{path.name} changed after freezing; re-review and re-freeze.")
    return load(path)


def validate(data: dict) -> None:
    for section in ("held_out_tasks", "budgets", "rq1"):
        if not isinstance(data.get(section), dict):
            raise ValueError(f"Acceptance file needs a {section} section.")
    if not data["held_out_tasks"].get("queries_file"):
        raise ValueError("held_out_tasks.queries_file must name the held-out query set.")
    if int(data["rq1"].get("min_pairs", 0)) < 2:
        raise ValueError("rq1.min_pairs must be at least 2.")


def freeze(path: Path | None = None, *, owner: str) -> dict:
    """Human action: validate and write the hash lock (the lock is what "frozen" means)."""
    path = path or acceptance_path()
    if not owner.strip():
        raise ValueError("Freezing needs the responsible owner.")
    data = load(path)
    validate(data)
    record = {"sha256": _digest(path), "frozen_at": datetime.now(UTC).isoformat(),
              "owner": owner.strip()}
    _lock_path(path).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def lock_record(path: Path | None = None) -> dict:
    path = path or acceptance_path()
    return json.loads(_lock_path(path).read_text(encoding="utf-8"))


__all__ = ["AcceptanceNotFrozen", "acceptance_path", "freeze",
           "is_frozen", "load", "lock_record", "require_frozen", "validate"]
