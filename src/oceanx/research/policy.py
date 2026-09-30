"""Versioned research policies: the human-authored experiment arms for how the tree is explored.

A policy is a bundled directory with ``policy.yaml`` and ``guidance.md``. Its version is
the name plus a content hash and is recorded on every tree event. A policy only sets
whether hypothesis nodes are enabled, the frontier mode, and guidance text for the
Coordinator. Learned Coordinator advice lives in approved lessons (lessons.py).

Selection: ``OCEANX_RESEARCH_POLICY`` (experiments, paired runs) > the project's choice
in the desktop (``.oceanx/research/active_policy``) > ``v0-coordinator-bfs``.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from oceanx.research.tree import FRONTIER_MODES

DEFAULT_POLICY = "v0-coordinator-bfs"
POLICY_ENV = "OCEANX_RESEARCH_POLICY"
BUNDLED_POLICIES = Path(__file__).resolve().parents[1] / "resources" / "policies"
POLICY_KEYS = {"name", "description", "hypotheses", "frontier"}


@dataclass(frozen=True)
class ResearchPolicy:
    name: str
    version: str
    description: str
    hypotheses: bool
    frontier_mode: str
    guidance: str


def validate_policy_document(data: dict) -> None:
    unknown = set(data) - POLICY_KEYS
    if unknown:
        raise ValueError(f"Unknown policy fields: {sorted(unknown)}.")
    if data.get("frontier", "shallowest") not in FRONTIER_MODES:
        raise ValueError("frontier must be shallowest or any_depth.")


def load_policy(directory: Path) -> ResearchPolicy:
    data = yaml.safe_load((directory / "policy.yaml").read_text(encoding="utf-8")) or {}
    validate_policy_document(data)
    guidance_path = directory / "guidance.md"
    guidance = guidance_path.read_text(encoding="utf-8") if guidance_path.exists() else ""
    digest = hashlib.sha256((directory / "policy.yaml").read_bytes() + b"\0" + guidance.encode())
    name = str(data.get("name") or directory.name)
    return ResearchPolicy(
        name=name, version=f"policy/{name}@{digest.hexdigest()[:12]}",
        description=str(data.get("description") or ""),
        hypotheses=bool(data.get("hypotheses", False)),
        frontier_mode=str(data.get("frontier") or "shallowest"), guidance=guidance.strip())


def available_policies() -> list[ResearchPolicy]:
    return [load_policy(p.parent) for p in sorted(BUNDLED_POLICIES.glob("*/policy.yaml"))]


def find_policy(name: str) -> Path:
    candidate = BUNDLED_POLICIES / name
    if not (candidate / "policy.yaml").is_file():
        raise ValueError(f"Unknown research policy: {name}.")
    return candidate


def project_choice(research_root: Path | None) -> str | None:
    """The policy the owner activated for this project in the desktop, if any."""
    path = Path(research_root) / "active_policy" if research_root else None
    return (path.read_text(encoding="utf-8").strip() or None) if path and path.is_file() else None


@lru_cache(maxsize=16)
def _cached(name: str, stamp: float) -> ResearchPolicy:
    return load_policy(find_policy(name))


def active_policy(research_root: Path | None = None) -> ResearchPolicy:
    name = os.environ.get(POLICY_ENV) or project_choice(research_root) or DEFAULT_POLICY
    directory = find_policy(name)
    return _cached(name, max(p.stat().st_mtime for p in directory.iterdir()))


__all__ = ["DEFAULT_POLICY", "POLICY_ENV", "ResearchPolicy", "active_policy",
           "available_policies", "find_policy", "load_policy", "project_choice",
           "validate_policy_document"]
