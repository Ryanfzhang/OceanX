"""Marked regions of a SKILL.md that OceanX fills in for each task.

A packaged skill may reserve a place for what the project learns::

    <!-- oceanx:lessons max=4 for="coordinator" about="which follow-ups were worth asking" -->
    <!-- /oceanx:lessons -->

    <!-- oceanx:tools max=12 -->
    <!-- /oceanx:tools -->

``max`` is how many items the region may hold and ``about`` says what belongs there, so the
author of the skill, not the meta-agent, decides where learned content goes and how much.
Only the text between the markers is ever replaced; every other line of the skill reaches
its reader as packaged. A skill without a region accepts nothing.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

KINDS = ("lessons", "tools")
# The name analysis code calls the helper functions by (``import oceanx_array_ops as ao``).
TOOL_ALIAS = "ao"
_OPEN = re.compile(r"^<!--\s*oceanx:(?P<kind>[a-z]+)(?P<attributes>(?:\s+[a-z]+=(?:\"[^\"]*\"|\S+))*)\s*-->$")
_CLOSE = re.compile(r"^<!--\s*/oceanx:(?P<kind>[a-z]+)\s*-->$")
_ATTRIBUTE = re.compile(r"([a-z]+)=(?:\"([^\"]*)\"|(\S+))")


class SkillRegionError(ValueError):
    """A skill's region markers are malformed."""


@dataclass(frozen=True)
class Region:
    kind: str
    limit: int
    about: str = ""
    reader: str | None = None  # whose task records the meta-agent reads for this skill
    start: int = 0  # index of the opening marker line
    end: int = 0  # index of the closing marker line


def find_regions(document: str) -> dict[str, Region]:
    """The regions a skill reserves, by kind. At most one of each kind."""
    found: dict[str, Region] = {}
    opened: tuple[str, int, dict[str, str]] | None = None
    for index, line in enumerate(document.splitlines()):
        text = line.strip()
        if not text.startswith("<!--") or "oceanx:" not in text:
            continue
        closing = _CLOSE.match(text)
        if closing:
            if opened is None or opened[0] != closing["kind"]:
                raise SkillRegionError(f"Closing marker without its opening marker: {text}")
            kind, start, attributes = opened
            try:
                limit = int(attributes.get("max", ""))
            except ValueError:
                limit = 0
            if limit < 1:
                raise SkillRegionError(f"The {kind} region needs max=<positive number>.")
            found[kind] = Region(kind=kind, limit=limit, about=attributes.get("about", ""),
                                 reader=attributes.get("for"), start=start, end=index)
            opened = None
            continue
        opening = _OPEN.match(text)
        if opening is None or opening["kind"] not in KINDS:
            raise SkillRegionError(f"Unknown region marker: {text}")
        if opened is not None or opening["kind"] in found:
            raise SkillRegionError(f"A skill has at most one {opening['kind']} region, not nested.")
        opened = (opening["kind"], index, {
            name: quoted or bare for name, quoted, bare in _ATTRIBUTE.findall(opening["attributes"])})
    if opened is not None:
        raise SkillRegionError(f"The {opened[0]} region is not closed.")
    return found


def fill_regions(document: str, blocks: Mapping[str, str] | None = None) -> str:
    """The skill as its reader gets it: each region replaced by its block, or removed when the
    block is empty. No marker reaches the reader, and no other line changes."""
    blocks = blocks or {}
    found = find_regions(document)
    if not found:
        return document  # a skill without regions reaches its reader byte for byte
    lines = document.splitlines()
    for region in sorted(found.values(), key=lambda r: r.start, reverse=True):
        block = [line.rstrip() for line in (blocks.get(region.kind) or "").strip("\n").splitlines()]
        before, after = lines[:region.start], lines[region.end + 1:]
        if not block and before and after and not before[-1].strip() and not after[0].strip():
            after = after[1:]  # an empty region leaves one blank line, not two
        lines = before + block + after
    return "\n".join(lines).rstrip() + "\n"


def describe_functions(source: str, *, skip: frozenset[str] = frozenset({"self_test"})) -> list[dict]:
    """The public functions of a helper module: name, signature and the first paragraph of
    the docstring. This is what a tools region lists, so the list cannot drift from the code."""
    described = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_") and node.name not in skip:
            summary = " ".join((ast.get_docstring(node) or "").split("\n\n")[0].split())
            described.append({"name": node.name, "signature": f"{node.name}({ast.unparse(node.args)})",
                              "summary": summary})
    return described


def tools_block(functions: Iterable[Mapping[str, str]], *, alias: str) -> str:
    """The lines of a tools region: one function per line, as it is called."""
    return "\n".join(f"- `{alias}.{function['signature']}`: {function['summary'] or 'No description.'}"
                     for function in functions)


def packaged_skill(directory: Path, document: str) -> str:
    """A packaged skill as a reader gets it when the project has learned nothing: the tools
    region lists the functions of the skill's own scripts, and the lessons region is empty."""
    blocks = {}
    if "tools" in find_regions(document):
        functions = [function for script in sorted((directory / "scripts").glob("*.py"))
                     for function in describe_functions(script.read_text(encoding="utf-8"))]
        blocks["tools"] = tools_block(functions, alias=TOOL_ALIAS)
    return fill_regions(document, blocks)


__all__ = ["KINDS", "TOOL_ALIAS", "Region", "SkillRegionError", "describe_functions",
           "fill_regions", "find_regions", "packaged_skill", "tools_block"]
