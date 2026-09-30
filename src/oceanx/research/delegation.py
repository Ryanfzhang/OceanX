"""Structured research-tree binding for native DeepAgents delegation.

DeepAgents' ``task`` tool only accepts ``description`` and ``subagent_type``. The
Coordinator keeps using that native tool (same name, description, middleware prompt
and execution path); this middleware only

* shows the model one extra optional ``node_id`` argument, and
* around each ``task`` execution, issues ``delegation_id``/``attempt_id``, records a
  ``delegated`` event in the tree log and exposes the binding to the child graph
  through a context variable.

The child graph reads :func:`current_delegation` instead of parsing node IDs from
free text. When the model omits ``node_id`` the legacy text match is used and the
binding is logged as ``inferred`` so its reliability can be measured.
"""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware

NODE_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])(B\d+(?:\.\d+)*)(?![A-Za-z0-9])")
NODE_ID_ARG_DESCRIPTION = (
    "Research-tree node ID this question answers, for example B1.2. "
    "Omit only for questions that are not research-tree nodes."
)


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

    def __init__(self, tree=None):
        super().__init__()
        self.tree = tree
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

    def wrap_tool_call(self, request, handler):
        request, delegation = self._prepare(request)
        token = _CURRENT.set(delegation)
        try:
            return handler(request)
        finally:
            _CURRENT.reset(token)

    async def awrap_tool_call(self, request, handler):
        request, delegation = self._prepare(request)
        token = _CURRENT.set(delegation)
        try:
            return await handler(request)
        finally:
            _CURRENT.reset(token)


__all__ = [
    "Delegation", "StructuredDelegationMiddleware", "current_delegation", "infer_node_id",
    "resolve_delegation",
]
