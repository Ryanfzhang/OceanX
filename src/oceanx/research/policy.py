"""Versioned research policies: how the Coordinator explores the research tree.

A policy is a bundled directory with ``policy.yaml`` and ``guidance.md``. Its version is
the name plus a content hash and is recorded on every tree event. A policy only sets
whether hypothesis nodes are enabled, the frontier mode, and guidance text for the
Coordinator. Learned Coordinator advice lives in lessons (lessons.py).

OceanX runs ``v2-nested``. ``OCEANX_RESEARCH_POLICY`` selects another bundled policy for an
experiment arm or a paired run; nothing else changes the policy.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from oceanx.research.tree import FRONTIER_MODES

DEFAULT_POLICY = "v2-nested"
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


@lru_cache(maxsize=16)
def _cached(name: str, stamp: float) -> ResearchPolicy:
    return load_policy(find_policy(name))


def active_policy() -> ResearchPolicy:
    name = os.environ.get(POLICY_ENV) or DEFAULT_POLICY
    directory = find_policy(name)
    return _cached(name, max(p.stat().st_mtime for p in directory.iterdir()))


__all__ = ["DEFAULT_POLICY", "POLICY_ENV", "ResearchPolicy", "active_policy",
           "available_policies", "find_policy", "load_policy", "validate_policy_document"]
