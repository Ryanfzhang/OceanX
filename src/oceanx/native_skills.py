"""Role-scoped, task-owned files consumed by DeepAgents' native SkillsMiddleware.

These are content-addressed bundled snapshots, not a second model-visible skill registry.
Discovery, reading and checkpointed metadata belong to DeepAgents.
"""
from __future__ import annotations

import os
import hashlib
import shutil
import tempfile
from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.permissions import FilesystemPermission

from oceanx.skills import (
    ocean_reference_root,
    ocean_skill_dirs,
    ocean_skill_metadata,
)


def _extra_skill_directories(roots, role: str) -> list[Path]:
    """Human-approved project skills (e.g. research lessons) scoped by frontmatter roles."""
    from oceanx.skills import _skill_frontmatter, _skill_roles

    found = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for directory in sorted(root.iterdir()):
            skill = directory / "SKILL.md"
            if directory.is_dir() and skill.is_file():
                roles = _skill_roles(_skill_frontmatter(skill.read_text(encoding="utf-8")))
                if role in roles:
                    found.append(directory)
    return found


def prepare_skill_library(root: Path, *, role: str, capabilities=(), extra_skill_dirs=()) -> Path:
    """Use the current bundled content, never a legacy snapshot or database overlay.

    Existing snapshots remain immutable for active readers. A changed bundle
    gets a new directory without deleting past research or altering its files.
    ``extra_skill_dirs`` adds human-approved project skills (research lessons);
    they are part of the content hash, so a lesson change selects a new snapshot.
    """
    allowed = {s.name for s in ocean_skill_metadata(role=role, capabilities=capabilities)}
    files = []
    for source in ocean_skill_dirs(capabilities=capabilities):
        for directory in sorted(source.iterdir()):
            if directory.name in allowed and directory.is_dir():
                files.extend((p, Path("skills") / directory.name / p.relative_to(directory))
                             for p in sorted(directory.rglob("*"))
                             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    for directory in _extra_skill_directories(extra_skill_dirs, role):
        if directory.name in allowed:
            continue  # bundled skills cannot be shadowed by project files
        files.extend((p, Path("skills") / directory.name / p.relative_to(directory))
                     for p in sorted(directory.rglob("*")) if p.is_file())
    references = ocean_reference_root()
    files.extend((p, Path("references") / p.relative_to(references))
                 for p in sorted(references.rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    digest = hashlib.sha256()
    for source, relative in files:
        digest.update(str(relative).encode() + b"\0" + source.read_bytes() + b"\0")
    target = root / digest.hexdigest()
    if target.is_dir():
        return target
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skills-", dir=root) as temporary:
        staging = Path(temporary) / "library"
        (staging / "skills").mkdir(parents=True)
        for source, relative in files:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        # Concurrent native subagents can prepare the same role snapshot. An
        # existing complete snapshot wins; readers never see a partial copy.
        try:
            os.rename(staging, target)
        except OSError:
            if not target.is_dir():
                raise
    return target


def skill_backend(library: Path, *, default=None, artifacts_root="/"):
    return CompositeBackend(default=default if default is not None else StateBackend(), routes={
        "/skills/": FilesystemBackend(root_dir=library / "skills", virtual_mode=True),
        "/references/": FilesystemBackend(root_dir=library / "references", virtual_mode=True),
    }, artifacts_root=artifacts_root)


def skill_permissions():
    return [FilesystemPermission(operations=["write"], paths=["/skills/**", "/references/**"], mode="deny")]
