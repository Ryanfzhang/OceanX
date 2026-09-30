"""Small file-backed research helpers.

Agent Server and DeepAgents own child identity, status, continuation and
completion. OceanX only assigns deterministic task-local files and validates
the report that a child actually wrote.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from oceanx.research.delegation import current_delegation
from oceanx.research.tree import summary_field

_active_host = None
_RESULT_BINDING = re.compile(
    r"\[([A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*)\]"
)


def report_summary(text: str) -> str:
    """Return the report's own opening Summary without another model call."""
    section = re.search(r"(?im)^##[ \t]+Summary[ \t]*\r?$", text)
    if section is None:
        return ""
    remaining = text[section.end():]
    end = re.search(r"(?m)^#{1,6}[ \t]+", remaining)
    return remaining[: end.start() if end else len(remaining)].strip()


def file_revision(path: Path) -> tuple[int, int, int] | None:
    """Return file identity for associating an Agent run with its own write."""
    if path.is_symlink() or not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def format_expert_receipt(
    summary: str,
    report_path: Path | None,
    published_results: tuple[tuple[str, str], ...] = (),
) -> str:
    """Return the report summary plus server-verified desktop bindings."""
    sections = [summary.strip()]
    sections.append(
        "Published results (only these bracket bindings open in the desktop):\n"
        + (
            "\n".join(f"- [{key}] — {title}" for key, title in published_results)
            if published_results
            else "- None"
        )
    )
    sections.append(f"Report: {report_path if report_path else 'None'}")
    return "\n\n".join(sections)


def parse_expert_receipt(text: str) -> tuple[str, str | None]:
    """Read the ordinary-text Expert handoff used by UI projection."""
    match = re.search(r"(?im)^Report:\s*(.+?)\s*$", text)
    if match is None:
        return text.strip(), None
    report = match.group(1).strip()
    return text[:match.start()].strip(), None if report.lower() == "none" else report


def expert_result_preview(summary: str) -> str:
    """Extract the answer-bearing Result field for compact UI display."""
    return re.sub(r"\s+", " ", summary_field(summary, "Result") or summary).strip()


def result_bindings(text: str) -> tuple[str, ...]:
    """Return Agent-owned result references in stable document order."""
    return tuple(dict.fromkeys(_RESULT_BINDING.findall(text)))


def host():
    if _active_host is None:
        raise RuntimeError("OceanX research requires the Agent Server lifespan")
    return _active_host


def expert_agent_key(task_id: str, role: str, question: str, node_id: str | None = None) -> str:
    """The same identity for an Expert's files, execution and UI participant.

    A structured tree binding decides the root branch; otherwise the legacy text
    match is used. Both give the same key when the question names its node.
    """
    match = re.search(r"(?<![A-Za-z0-9])B(\d+)(?:\.\d+)*(?![A-Za-z0-9])", question)
    if node_id:
        branch = node_id.split(".")[0]
    else:
        branch = f"B{match.group(1)}" if match else question.strip()
    role_name = {
        "ocean_process_expert": "ocean-process",
        "statistical_inference_expert": "statistics",
        "literature_reproduction_expert": "literature",
        "scientific_discussion_partner": "discussion",
    }.get(role, role.replace("_", "-"))
    identity = "\x1f".join((task_id, role, branch)).encode("utf-8")
    return f"{role_name}-{hashlib.sha256(identity).hexdigest()[:10]}"


def expert_assignment_key(question: str) -> str:
    """Return one stable report directory for one tree question.

    A root branch keeps one Expert identity, while B1, B1.1 and B1.2 keep
    separate reports. This lets sibling follow-ups read the same immutable
    parent answer without overwriting it.
    """
    match = re.search(r"(?<![A-Za-z0-9])(B\d+(?:\.\d+)*)(?![A-Za-z0-9])", question)
    if match:
        return match.group(1)
    digest = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:12]
    return f"assignment-{digest}"


@dataclass(frozen=True)
class AgentRun:
    """Ephemeral binding to identities already assigned by Agent Server."""

    workspace_id: str
    task_id: str
    request_id: str
    thread_id: str
    server_run_id: str
    role: str
    question: str = ""
    node_id: str | None = None
    delegation_id: str | None = None
    attempt_id: str | None = None
    delegation_started_at: str | None = None

    @classmethod
    def from_config(cls, config, role: str, *, question: str = ""):
        c = config["configurable"]
        delegation = current_delegation()
        parent_thread = str(c["thread_id"])
        # Native DeepAgents ``task`` calls inherit the Coordinator config. A
        # child still needs its own durable workspace, so derive it from the
        # request, role and assigned scientific question. DeepAgents remains
        # the sole owner of task execution and completion.
        thread_id = parent_thread
        if c.get("ls_agent_type") == "subagent":
            thread_id = expert_agent_key(str(c["task_id"]), role, question,
                                         delegation.node_id if delegation else None)
        return cls(
            workspace_id=c["workspace_id"], task_id=c["task_id"],
            request_id=c["request_id"], thread_id=thread_id,
            server_run_id=str(c.get("run_id") or config.get("metadata", {}).get("run_id", "")),
            role=role, question=question,
            node_id=delegation.node_id if delegation else None,
            delegation_id=delegation.delegation_id if delegation else None,
            attempt_id=delegation.attempt_id if delegation else None,
            delegation_started_at=delegation.started_at if delegation else None,
        )

    @property
    def agent_run_id(self) -> str:
        # The Agent Server run belongs to the Coordinator.  Scientific-call
        # metering and persistent execution belong to this native child.
        # Using the parent run id here would make parallel branches consume
        # one another's allowance and collapse their execution histories.
        return self.thread_id

class ResearchServices:
    def __init__(self, host):
        self.host = host
        self.expert_code_execution = host.expert_code_execution

    def report_path(self, run: AgentRun) -> Path:
        root = self.host.task_workspace_projector.expert_session_root(
            run.task_id, run.thread_id
        )
        return root / "reports" / expert_assignment_key(run.question) / "report.md"

    def collect_report(
        self,
        run: AgentRun,
        *,
        materialize_text: str | None = None,
        previous_revision: tuple[int, int, int] | None = None,
    ) -> tuple[str, Path | None]:
        """Collect an Agent-owned file when present, without judging its delivery."""
        path = self.report_path(run)
        if materialize_text is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(materialize_text, encoding="utf-8")
            temporary.replace(path)
        if file_revision(path) is None or (
            previous_revision is not None and file_revision(path) == previous_revision
        ):
            return "", None
        text = path.read_text(encoding="utf-8")
        return (text, path) if text.strip() else ("", None)
