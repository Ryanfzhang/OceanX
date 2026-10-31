"""Role-scoped, task-owned files consumed by DeepAgents' native SkillsMiddleware.

These are content-addressed bundled snapshots, not a second model-visible skill registry.
Discovery, reading and checkpointed metadata belong to DeepAgents.
"""
from __future__ import annotations

import os
import hashlib
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.permissions import FilesystemPermission

from oceanx.figure_delivery import INTERACTIVE_FIGURE_SKILLS, static_figures
from oceanx.skill_regions import packaged_skill
from oceanx.skills import (
    ocean_reference_root,
    ocean_skill_dirs,
    ocean_skill_metadata,
)


# The agent that works on a request alone, and its helpers, read what the data and search Experts read.
_EXPERT_READERS = ("ocean_process_expert", "statistical_inference_expert", "literature_reproduction_expert")
SKILL_READERS = {"single_agent": _EXPERT_READERS, "helper": _EXPERT_READERS}

# A skill sends its reader to a section of another document: "read /skills/<name>/SKILL.md, under <heading>".
# Readers skipped those sections (2026-10-26; 2026-10-31, a vorticity budget written without the physics
# section it was sent to), so a library quotes each section after the paragraph that points to it. The text
# itself lives only in the document it belongs to.
POINTER = re.compile(r"read\s+(/(?:skills|references)/\S+?\.md),\s+under\s+")


def quote_pointed_sections(text: str, document: Callable[[str], str | None]) -> str:
    """Quote, after each paragraph of ``text`` that points to a section of another document, that section
    as ``document(path)`` gives it. A pointer whose document or heading is not found is left as it is."""

    quoted: list[str] = []
    for paragraph in text.split("\n\n"):
        quoted.append(paragraph)
        for match in POINTER.finditer(paragraph):
            target = document(match.group(1))
            sections = _sections(target) if target is not None else {}
            named = " ".join(paragraph[match.end():].split())
            heading = max((name for name in sections if named.startswith(name)), key=len, default=None)
            if heading is not None:
                lines = [f"Quoted from {match.group(1)}, under {heading}:", "", *sections[heading].splitlines()]
                quoted.append("\n".join(f"> {line}" if line else ">" for line in lines))
    return "\n\n".join(quoted)


def _sections(text: str) -> dict[str, str]:
    """A Markdown document's second-level sections by heading, without the heading line."""

    sections: dict[str, str] = {}
    heading, lines = None, []
    for line in [*text.splitlines(), "## "]:
        if line.startswith("## "):
            if heading:
                sections[heading] = "\n".join(lines).strip()
            heading, lines = line[3:].strip(), []
        elif heading:
            lines.append(line)
    return sections


def prepare_skill_library(root: Path, *, role: str, capabilities=(), revisions=None) -> Path:
    """Use the current bundled content, never a legacy snapshot or database overlay.

    Existing snapshots remain immutable for active readers. A changed bundle
    gets a new directory without deleting past research or altering its files.
    ``revisions`` maps a bundled skill's name to its SKILL.md with the project's
    lessons and tools written into the regions the skill reserves for them, and
    ``<skill>/<path>`` to another file of that skill (see skill_regions.py and
    research/review.py). The packaged files are not modified; the revised text is
    part of the content hash, so a change selects a new snapshot.
    """
    revisions = revisions or {}
    allowed = {s.name for reader in SKILL_READERS.get(role, (role,))
               for s in ocean_skill_metadata(role=reader, capabilities=capabilities)}
    if static_figures():
        allowed -= INTERACTIVE_FIGURE_SKILLS  # a static run describes no plotting interface
    files = []
    for source in ocean_skill_dirs(capabilities=capabilities):
        for directory in sorted(source.iterdir()):
            if directory.name in allowed and directory.is_dir():
                files.extend((p, Path("skills") / directory.name / p.relative_to(directory))
                             for p in sorted(directory.rglob("*"))
                             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    bundled = {directory.name: directory for source in ocean_skill_dirs(capabilities=capabilities)
               for directory in sorted(source.iterdir()) if directory.is_dir()}
    references = ocean_reference_root()
    files.extend((p, Path("references") / p.relative_to(references))
                 for p in sorted(references.rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    generated = {}
    figure_lines = None
    if "scientific-figure-design" in allowed:
        from oceanx.figure_reference import figure_api_reference

        reference = figure_api_reference()
        figure_lines = len(reference.splitlines())
        generated[Path("skills/scientific-figure-design/API.md")] = reference.encode("utf-8")

    def pointed_document(path: str) -> str | None:
        """The document a pointer names, as its own readers get it (whether or not this role may open it)."""
        parts = Path(path).parts[1:]
        if parts[:1] == ("references",):
            target = (references / Path(*parts[1:])).resolve()
            return target.read_text(encoding="utf-8") if references.resolve() in target.parents and target.is_file() else None
        if parts[:1] == ("skills",) and parts[2:] == ("SKILL.md",) and parts[1] in bundled:
            source = bundled[parts[1]] / "SKILL.md"
            return revisions.get(parts[1]) or packaged_skill(source.parent, source.read_text(encoding="utf-8"))
        return None

    def content(source: Path, relative: Path) -> bytes:
        if relative.parts[0] != "skills":
            return source.read_bytes()
        document = relative.parts[2:] == ("SKILL.md",)
        revised = revisions.get(relative.parts[1] if document else "/".join(relative.parts[1:]))
        if revised is None and document:
            # Nothing learned: the region markers still must not reach a reader.
            revised = packaged_skill(source.parent, source.read_text(encoding="utf-8"))
        if document and relative.parts[1] == "scientific-figure-design" and figure_lines is not None:
            revised = revised.replace("{{FIGURE_API_LINE_COUNT}}", str(figure_lines))
        if document:
            revised = quote_pointed_sections(revised, pointed_document)
        return source.read_bytes() if revised is None else revised.encode("utf-8")

    digest = hashlib.sha256()
    for source, relative in files:
        digest.update(str(relative).encode() + b"\0" + content(source, relative) + b"\0")
    for relative, data in generated.items():
        digest.update(str(relative).encode() + b"\0" + data + b"\0")
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
            destination.write_bytes(content(source, relative))
        for relative, data in generated.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
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
