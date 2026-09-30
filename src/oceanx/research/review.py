"""One project's research-improvement state, as the desktop and CLI review it.

Bundles the project's research memory, lessons, node-label review and policy
choice under ``<project>/.oceanx/research/``. Every change here is a human
decision; the meta model only ever creates lesson proposals.
"""
from __future__ import annotations

from pathlib import Path

from oceanx.research import acceptance
from oceanx.research.labels import review_set
from oceanx.research.lessons import LessonBook
from oceanx.research.memory import ResearchMemory
from oceanx.research.policy import (
    DEFAULT_POLICY, active_policy, available_policies, find_policy, project_choice)
from oceanx.research.tree_store import atomic_write_text

REVIEWER = "desktop user"


class ProjectResearch:
    def __init__(self, paths):
        self.root = Path(paths.root) / "research"
        self.memory = ResearchMemory(self.root)
        self.lessons = LessonBook(self.memory)

    def policy(self):
        return active_policy(self.root)

    def policies(self) -> dict:
        return {"active": self.policy().name, "project_choice": project_choice(self.root),
                "acceptance_frozen": acceptance.is_frozen(),
                "available": [{"name": p.name, "version": p.version, "description": p.description}
                              for p in available_policies()]}

    def activate_policy(self, name: str) -> None:
        find_policy(name)  # must exist
        atomic_write_text(self.root / "active_policy", "" if name == DEFAULT_POLICY else name)

    @staticmethod
    def label_review(tree) -> list[dict]:
        return review_set(tree) if tree.store.path.exists() else []

    def set_label(self, tree, node_id: str, label: str) -> None:
        tree.label(node_id, label, labeler=REVIEWER)
        if tree.store.path.exists():
            self.memory.digest(tree.store.path)  # keep the digest's labels current


__all__ = ["ProjectResearch", "REVIEWER"]
