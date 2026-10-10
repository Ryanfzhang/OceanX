"""One project's learned library, as its tasks, the desktop and the CLI use it.

Bundles the project's research memory, its lessons and its tools under
``<project>/.oceanx/research/``. The meta-agent maintains both; the owner can look at every
lesson and tool and mark it right or wrong.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oceanx.research.lessons import LessonBook
from oceanx.research.memory import ResearchMemory
from oceanx.research.policy import active_policy
from oceanx.research.referee import Referee
from oceanx.research.toolbook import MODULE as TOOL_MODULE
from oceanx.research.toolbook import SKILL as TOOL_SKILL
from oceanx.research.toolbook import ToolBook
from oceanx.skill_regions import fill_regions

REVIEWER = "desktop user"
# Set for an experiment arm: its lessons and tools are a frozen snapshot that nothing may change.
LIBRARY_FROZEN_ENV = "OCEANX_LIBRARY_FROZEN"
# The two files that are a project's library, by their name in a frozen snapshot.
LIBRARY_FILES = {"lessons.json": "lessons/lessons.json", "tools.json": "tools/tools.json"}


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class ProjectResearch:
    def __init__(self, paths):
        self.root = Path(paths.root) / "research"
        self.memory = ResearchMemory(self.root)
        self.lessons = LessonBook(self.memory)
        self.tools = ToolBook(self.memory)
        self.referee = Referee(self.memory)

    @staticmethod
    def policy():
        return active_policy()

    def skills(self, *, research: bool) -> dict[str, str]:
        """The skill files this project changes, as its agents get them: the SKILL.md of every
        skill that reserves a region, by skill name, and the helper script by its path.

        The tools region always lists the helper functions the project mounts, and the script
        the skill links to holds the same functions. Lessons come from research trees and would
        work against a bounded request, so they are written only for research tasks.
        """
        from oceanx.skills import load_ocean_skill
        rendered = {TOOL_SKILL: fill_regions(load_ocean_skill(TOOL_SKILL)[0],
                                             {"tools": self.tools.block()}),
                    f"{TOOL_SKILL}/scripts/{TOOL_MODULE}.py": self.tools.source()}
        for skill, region in self.lessons.regions().items():
            block = self.lessons.block(skill, region) if research else ""
            rendered[skill] = fill_regions(load_ocean_skill(skill)[0], {"lessons": block})
        return rendered

    def learned_in(self, role: str, *, research: bool, capabilities=()) -> list[str]:
        """The skills ``role`` can open that now carry something the project learned: lessons
        (in research tasks) or a learned helper function. An agent opens a skill only when it
        is told to, so a task names these to their readers; a project that has learned nothing
        names none."""
        from oceanx.skills import ocean_skill_metadata
        readable = {skill.name for skill in ocean_skill_metadata(role=role, capabilities=capabilities)}
        with_lessons = {lesson.get("skill") for lesson in self.lessons.active()} if research else set()
        found = [skill for skill in self.lessons.regions() if skill in readable and skill in with_lessons]
        if TOOL_SKILL in readable and any(tool["source"] == "learned" for tool in self.tools.mounted()):
            found.append(TOOL_SKILL)
        return found

    def version(self) -> str | None:
        """Names the lessons and tools a task runs with; None when the project has neither."""
        parts = [part for part in (self.lessons.version(), self.tools.version()) if part]
        return "+".join(parts) or None

    def update(self, stores: list[Path], *, llm: Callable[[str], str] | None = None,
               reviewer: Callable[[str], str] | None = None, force: bool = False,
               retention_days: int | None = None) -> dict:
        """The periodic update. Without a model it only brings the records and the call counts
        up to date; with one, the final answers of newly finished tasks are read first
        (referee.py), then the meta-agent reviews the lessons and learns tools. Each of the
        two steps knows which tasks it has read, so one that failed is tried again."""
        options = {} if retention_days is None else {"retention_days": retention_days}
        result = {"consolidation": self.memory.consolidate(stores, **options)}
        digests = self.memory.load_digests()
        result["tool_usage"] = self.tools.record_usage(digests)
        if llm is not None:
            result["referee"] = self.referee.read_new(stores, digests, llm)
            result["lessons"] = self.lessons.review(llm, force=force)
            result["tools"] = self.tools.learn(llm, stores, reviewer=reviewer, force=force)
        return result

    def mark(self, kind: str, item_id: str, verdict: str, *, reviewer: str = REVIEWER) -> None:
        if kind == "lesson":
            self.lessons.mark(item_id, verdict, reviewer=reviewer)
        elif kind == "tool":
            self.tools.mark(item_id, verdict, reviewer=reviewer)
        else:
            raise ValueError("kind must be lesson or tool.")

    def overview(self) -> dict:
        return {**self.lessons.overview(), "tools": self.tools.overview(),
                "tool_changes": self.tools.changes(), "version": self.version()}

    # --- frozen snapshots, for experiment arms ---------------------------------------
    def library_hashes(self) -> dict[str, str | None]:
        """SHA-256 of each library file; None for one the project does not have."""
        return {name: _sha256(self.root / relative) for name, relative in LIBRARY_FILES.items()}

    def snapshot(self, target: Path) -> dict:
        """Freeze the library into ``target``: the lessons and tools as they are now, and the
        change logs that say how each came about. A snapshot is never overwritten."""
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise ValueError(f"{target} is not empty; a frozen snapshot is never edited.")
        target.mkdir(parents=True, exist_ok=True)
        for name, relative in LIBRARY_FILES.items():
            if (self.root / relative).is_file():
                shutil.copyfile(self.root / relative, target / name)
        for kind in ("lessons", "tools"):
            if (self.root / kind / "changes.jsonl").is_file():
                shutil.copyfile(self.root / kind / "changes.jsonl", target / f"{kind}-changes.jsonl")
        record = {"version": self.version(), "sha256": self.library_hashes(),
                  "frozen_at": datetime.now(UTC).isoformat(),
                  "lessons": self.lessons.shown_ids(),
                  "tools": [tool["name"] for tool in self.tools.mounted()]}
        (target / "snapshot.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record

    def install(self, snapshot: Path) -> dict[str, str | None]:
        """Start this project from a frozen snapshot. Returns the hashes of what it now has."""
        for name, relative in LIBRARY_FILES.items():
            if (Path(snapshot) / name).is_file():
                (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(snapshot) / name, self.root / relative)
        self.lessons.render_skills()  # for reading; tasks build their skills from the two files
        return self.library_hashes()


__all__ = ["LIBRARY_FILES", "LIBRARY_FROZEN_ENV", "REVIEWER", "ProjectResearch"]
