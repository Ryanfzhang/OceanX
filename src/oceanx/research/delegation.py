"""Structured research-tree binding for native DeepAgents delegation.

DeepAgents' ``task`` tool only accepts ``description`` and ``subagent_type``. The
Coordinator keeps using that native tool (same name, description, middleware prompt
and execution path); this middleware only

* shows the model one extra optional ``node_id`` argument, and
* around each ``task`` execution, issues ``delegation_id``/``attempt_id``, records a
  ``delegated`` event in the tree log and exposes the binding to the child graph
  through a context variable, and
* refuses an explicit unknown node after the short wait, without starting a child.

The child graph reads :func:`current_delegation` instead of parsing node IDs from
free text. When the model omits ``node_id`` the legacy text match is used and the
binding is logged as ``inferred`` so its reliability can be measured.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

NODE_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])(B\d+(?:\.\d+)*)(?![A-Za-z0-9])")
# Tool calls of one Coordinator turn run together and a tree update writes in a worker thread,
# so a task can start before the same turn's update has written the node it names. Once that
# update holds the tree lock, has_node waits for it; this covers the moment before it does.
NODE_WAIT_SECONDS = 2.0
NODE_ID_ARG_DESCRIPTION = (
    "Research-tree node ID this question answers, for example B1.2. "
    "Omit only for questions that are not research-tree nodes."
)
_VISUAL_NOUN = re.compile(
    r"(?i)\b(?:figure|plot|map|chart|graph|visual(?:ization|isation)?|image)\b|"
    r"(?:图表|地图|可视化|绘图|图像)"
)
_VISUAL_DELIVERY_VERB = re.compile(
    r"(?i)\b(?:publish|save|render|create|make|produce|deliver|missing|omitted|redraw)\b|"
    r"(?:补图|出图|保存|生成|绘制|重画|缺少)"
)
VISUAL_FOLLOWUP_REFUSAL = (
    "Not started: this is a visual-only follow-up, but the researcher did not request a visual. "
    "Use the existing scientific report in the final synthesis instead."
)


def explicitly_requests_visual(text: str) -> bool:
    """A narrow, auditable check for an explicit visual deliverable in the user's own words."""
    return bool(_VISUAL_NOUN.search(text or ""))


def visual_only_followup(text: str) -> bool:
    """Recognize a delivery retry, not an analysis that happens to discuss a mapped field."""
    return bool(_VISUAL_NOUN.search(text or "") and _VISUAL_DELIVERY_VERB.search(text or ""))


@dataclass(frozen=True)
class Delegation:
    node_id: str | None
    delegation_id: str
    attempt_id: str
    binding: str  # explicit | inferred | unbound
    subagent_type: str
    started_at: str


_CURRENT: ContextVar[Delegation | None] = ContextVar("oceanx_delegation", default=None)


def current_delegation() -> Delegation | None:
    return _CURRENT.get()


def infer_node_id(text: str) -> str | None:
    match = NODE_ID_PATTERN.search(text or "")
    return match.group(1) if match else None


def resolve_delegation(args: dict, tree=None) -> Delegation:
    """Bind one task call to a tree node; never raises for a bad model argument."""
    explicit = str(args.get("node_id") or "").strip() or None
    node_id = explicit or infer_node_id(str(args.get("description") or ""))
    binding = "explicit" if explicit else ("inferred" if node_id else "unbound")
    if node_id is not None and tree is not None and not tree.has_node(node_id):
        node_id, binding = None, "unbound"
    return Delegation(
        node_id=node_id,
        delegation_id=uuid.uuid4().hex,
        attempt_id=uuid.uuid4().hex,
        binding=binding,
        subagent_type=str(args.get("subagent_type") or ""),
        started_at=datetime.now(UTC).isoformat(),
    )


def _extended_task_tool(native):
    """The native task tool as the model sees it, plus optional ``node_id``."""
    from langchain_core.tools import StructuredTool
    from pydantic import Field, create_model

    base = getattr(native, "args_schema", None)
    fields: dict[str, Any] = {}
    if base is not None and hasattr(base, "model_fields"):
        for name, info in base.model_fields.items():
            fields[name] = (info.annotation, info)
    fields["node_id"] = (str | None, Field(default=None, description=NODE_ID_ARG_DESCRIPTION))
    schema = create_model("OceanXTaskToolSchema", **fields)

    def _never_executed(**_: Any) -> str:  # execution stays with the native tool
        raise RuntimeError("The display-only task schema must not be executed.")

    return StructuredTool.from_function(
        name=native.name, description=native.description, func=_never_executed,
        args_schema=schema, infer_schema=False,
    )


class StructuredDelegationMiddleware(AgentMiddleware):
    """Coordinator middleware: advertise ``node_id`` and bind each ``task`` call to it."""

    def __init__(
        self, tree=None, node_wait_seconds: float = NODE_WAIT_SECONDS,
        original_question: str = "",
    ):
        super().__init__()
        self.tree = tree
        self.node_wait_seconds = node_wait_seconds
        self.original_question = original_question
        self._display_tool = None

    # --- model side: advertise node_id ------------------------------------
    def _request_with_node_id(self, request):
        tools = list(request.tools or [])
        for index, tool in enumerate(tools):
            if getattr(tool, "name", None) == "task" and not isinstance(tool, dict):
                if self._display_tool is None:
                    self._display_tool = _extended_task_tool(tool)
                tools[index] = self._display_tool
                return request.override(tools=tools)
        return request

    def wrap_model_call(self, request, handler):
        return handler(self._request_with_node_id(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request_with_node_id(request))

    # --- tool side: bind, log, expose ------------------------------------
    def _prepare(self, request):
        call = request.tool_call
        if call.get("name") != "task":
            return request, None
        args = dict(call.get("args") or {})
        delegation = resolve_delegation(args, self.tree)
        args.pop("node_id", None)
        if self.tree is not None and delegation.node_id is not None:
            self.tree.record_delegation(delegation)
        return request.override(tool_call={**call, "args": args}), delegation

    def _awaited_node(self, request, deadline: float) -> bool:
        """Whether a task call names a node the tree does not hold yet and may still receive."""
        call = request.tool_call
        if self.tree is None or call.get("name") != "task" or time.monotonic() >= deadline:
            return False
        args = call.get("args") or {}
        node_id = (str(args.get("node_id") or "").strip()
                   or infer_node_id(str(args.get("description") or "")))
        return bool(node_id) and not self.tree.has_node(node_id)

    def _refused_explicit_node(self, request):
        call = request.tool_call
        if self.tree is None or call.get("name") != "task":
            return None
        node_id = str((call.get("args") or {}).get("node_id") or "").strip()
        if not node_id or self.tree.has_node(node_id):
            return None
        return ToolMessage(
            content=(f"Not started: research-tree node {node_id} does not exist. "
                     "Add or select it with update_research_tree, then delegate again."),
            tool_call_id=call["id"], name="task", status="error")

    def _refused_unrequested_visual_followup(self, request):
        call = request.tool_call
        if self.tree is None or call.get("name") != "task":
            return None
        args = call.get("args") or {}
        description = str(args.get("description") or "")
        if explicitly_requests_visual(self.original_question) or not visual_only_followup(description):
            return None
        node_id = str(args.get("node_id") or "").strip() or infer_node_id(description)
        if not node_id or not self.tree.has_node(node_id) or not self.tree.attempts(node_id):
            return None
        return ToolMessage(
            content=VISUAL_FOLLOWUP_REFUSAL,
            tool_call_id=call["id"], name="task", status="error",
        )

    def wrap_tool_call(self, request, handler):
        deadline = time.monotonic() + self.node_wait_seconds
        while self._awaited_node(request, deadline):
            time.sleep(0.05)
        refused = self._refused_explicit_node(request)
        if refused is not None:
            return refused
        refused = self._refused_unrequested_visual_followup(request)
        if refused is not None:
            return refused
        request, delegation = self._prepare(request)
        token = _CURRENT.set(delegation)
        try:
            return handler(request)
        finally:
            _CURRENT.reset(token)

    async def awrap_tool_call(self, request, handler):
        deadline = time.monotonic() + self.node_wait_seconds
        while self._awaited_node(request, deadline):
            await asyncio.sleep(0.05)
        refused = self._refused_explicit_node(request)
        if refused is not None:
            return refused
        refused = self._refused_unrequested_visual_followup(request)
        if refused is not None:
            return refused
        request, delegation = self._prepare(request)
        token = _CURRENT.set(delegation)
        try:
            return await handler(request)
        finally:
            _CURRENT.reset(token)


__all__ = [
    "Delegation", "StructuredDelegationMiddleware", "current_delegation",
    "explicitly_requests_visual", "infer_node_id", "resolve_delegation", "visual_only_followup",
]
