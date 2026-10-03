"""Deep Agents + LangGraph runtime used by every OceanX participant."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langgraph.types import Command

from oceanx.agent_contract import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ConversationMessage,
    ErrorEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
    UsageSnapshot,
    _message_text,
)
from oceanx.model_config import create_chat_model
from oceanx.model_recovery import model_error_event

log = logging.getLogger(__name__)


NATIVE_TASK_DESCRIPTION = """Ask one available OceanX participant one scientific question.

Available participants:
{available_agents}

Write the description as short ordinary text with the same four exact English labels every time:
Question (include the research-tree node ID when present), Parent question, Parent answer, Parent report.
Write None for the three parent fields when there is no parent. Copy a parent's question when its result is attached,
report Summary and report path from the research tree. Do not prescribe methods, metrics, figures or an
output format. The participant chooses its methods and returns Result, Evidence and limitations, Further
analysis, and Report. Put independent questions from the same frontier in parallel task calls; keep
dependent questions sequential."""


def _configure_native_harness(provider: str) -> None:
    """Use native tools; retain explicit research subagents instead of a nested generalist."""

    register_harness_profile(
        provider,
        HarnessProfile(
            tool_description_overrides={"task": NATIVE_TASK_DESCRIPTION},
            excluded_tools=frozenset(),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _ai_message(value: Any) -> AIMessage | None:
    if isinstance(value, AIMessage):
        return value
    if isinstance(value, dict):
        for key in ("output", "message"):
            if isinstance(value.get(key), AIMessage):
                return value[key]
        generations = value.get("generations")
        if isinstance(generations, list):
            for generation in generations:
                if isinstance(generation, list):
                    for item in generation:
                        message = getattr(item, "message", None)
                        if isinstance(message, AIMessage):
                            return message
                message = getattr(generation, "message", None)
                if isinstance(message, AIMessage):
                    return message
    message = getattr(value, "message", None)
    return message if isinstance(message, AIMessage) else None


def _usage(message: AIMessage) -> UsageSnapshot:
    usage = message.usage_metadata or {}
    return UsageSnapshot(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )




def _tool_output(value: Any) -> tuple[str, bool]:
    if isinstance(value, Command) and isinstance(value.update, dict):
        receipts = [_tool_output(message) for message in value.update.get("messages", [])]
        return "\n".join(text for text, _ in receipts), any(error for _, error in receipts)
    # Agent Server serializes LangGraph Command before placing it in the SSE
    # event.  This is the same native task receipt, not a second OceanX result
    # format; unwrap it only for UI projection.
    if isinstance(value, dict) and isinstance(value.get("update"), dict):
        receipts = [_tool_output(message) for message in value["update"].get("messages", [])]
        return "\n".join(text for text, _ in receipts), any(error for _, error in receipts)
    status = getattr(value, "status", None)
    content = (value.get("content", value) if isinstance(value, dict)
               else getattr(value, "content", value))
    if isinstance(value, dict):
        status = value.get("status", status)
    if isinstance(content, str):
        text = content
    else:
        text = str(content)
    return text, status == "error"


class DeepAgentEngine:
    """Product gateway around one checkpointed LangGraph thread."""

    def __init__(
        self,
        *,
        graph: Any,
        thread_id: str,
        operation_id_factory: Any,
    ) -> None:
        self.graph = graph
        self.thread_id = thread_id
        self.operation_id_factory = operation_id_factory
        self._stream_turn_index = 0

    def set_request_options(self, **options: Any) -> None:
        setter = getattr(self.graph, "set_request_options", None)
        if setter is not None:
            setter(**options)

    def _config(self, request_id: str | None) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": self.thread_id,
                "request_id": request_id or self.thread_id,
            },
            # Match DeepAgents' own compiled-graph default.  This is a graph-step
            # ceiling, not the Expert model-call allowance.
            "recursion_limit": 9_999,
        }

    async def _input_messages(self, config: dict[str, Any], text: str) -> list[BaseMessage]:
        return [HumanMessage(content=text)]

    async def _refresh_messages(self, config: dict[str, Any]) -> BaseMessage | None:
        snapshot = await self.graph.aget_state(config)
        raw = snapshot.values.get("messages", ()) if snapshot.values else ()
        return raw[-1] if raw and isinstance(raw[-1], BaseMessage) else None

    async def submit_message(
        self, text: str, *, request_id: str | None = None
    ) -> AsyncIterator[StreamEvent]:
        config = self._config(request_id)
        inputs = {"messages": await self._input_messages(config, text)}
        self._stream_turn_index = 0
        pending_calls: deque[dict[str, Any]] = deque()
        tool_started: dict[str, tuple[float, str, str | None]] = {}
        opaque_tool_runs: set[str] = set()
        model_turns: dict[str, str] = {}
        completed_model_runs: set[str] = set()
        turn_index = self._stream_turn_index
        last_model_message: AIMessage | None = None
        try:
            async for event in self.graph.astream_events(inputs, config=config, version="v2"):
                name = str(event.get("event") or "")
                run_id = str(event.get("run_id") or "")
                parent_ids = {
                    str(parent_id)
                    for parent_id in (event.get("parent_ids") or ())
                    if parent_id
                }
                # A tool is an event boundary. In particular, native ``task``
                # runs another DeepAgent graph internally. LangGraph exposes
                # those child model/tool events in the same v2 event stream,
                # but they are the tool's private implementation rather than
                # turns made by this agent. Project only the outer tool receipt
                # into the parent stream.
                if parent_ids & opaque_tool_runs:
                    continue
                data = event.get("data") or {}
                is_summary = (event.get("metadata") or {}).get("lc_source") == "summarization"
                if name == "on_chat_model_start":
                    turn_index += 1
                    self._stream_turn_index = turn_index
                    turn_id = f"{request_id or self.thread_id}:turn:{turn_index}"
                    model_turns[run_id] = turn_id
                    continue
                if name == "on_chat_model_stream":
                    if is_summary:
                        continue
                    chunk = data.get("chunk")
                    if isinstance(chunk, AIMessageChunk):
                        delta = _message_text(chunk)
                        if delta:
                            yield AssistantTextDelta(
                                text=delta,
                                turn_id=model_turns.get(run_id),
                                request_id=request_id,
                            )
                    continue
                if name == "on_chat_model_end":
                    if run_id in completed_model_runs:
                        continue
                    completed_model_runs.add(run_id)
                    message = _ai_message(data.get("output"))
                    if message is None:
                        continue
                    if is_summary:
                        usage = _usage(message)
                        # Meter internal work without presenting its prose as a
                        # research answer, tool request, or final response.
                        yield AssistantTurnComplete(
                            message=ConversationMessage.from_langchain(AIMessage(content="")),
                            usage=usage,
                            turn_id=model_turns.get(run_id),
                            request_id=request_id,
                        )
                        continue
                    last_model_message = message
                    log.info("Model response request=%s turn=%s finish=%s text_chars=%s tools=%s",
                             request_id, turn_index,
                             message.response_metadata.get("finish_reason") or
                             message.response_metadata.get("stop_reason"),
                             len(_message_text(message)), len(message.tool_calls))
                    turn_id = model_turns.get(run_id) or f"{request_id or self.thread_id}:turn:{turn_index}"
                    for call in message.tool_calls:
                        pending_calls.append(
                            {
                                "id": str(call.get("id") or ""),
                                "name": str(call.get("name") or ""),
                                "args": dict(call.get("args") or {}),
                                "turn_id": turn_id,
                            }
                        )
                    yield AssistantTurnComplete(
                        message=ConversationMessage.from_langchain(message),
                        usage=_usage(message),
                        turn_id=turn_id,
                        request_id=request_id,
                    )
                    continue
                if name == "on_tool_start":
                    opaque_tool_runs.add(run_id)
                    tool_name = str(event.get("name") or "")
                    tool_input = data.get("input")
                    named = [item for item in pending_calls if item["name"] == tool_name]
                    # A middleware may drop an argument before execution (delegation drops
                    # node_id), so the model's call can hold more than the executed input.
                    call = next(
                        (item for item in named
                         if not isinstance(tool_input, dict) or item["args"] == tool_input),
                        None,
                    ) or next(
                        (item for item in named if isinstance(tool_input, dict) and all(
                            key in item["args"] and item["args"][key] == value
                            for key, value in tool_input.items())),
                        None,
                    )
                    if call is not None:
                        pending_calls.remove(call)
                    else:
                        call = {
                            "id": run_id,
                            "name": tool_name,
                            "args": dict(data.get("input") or {}),
                            "turn_id": f"{request_id or self.thread_id}:turn:{turn_index}",
                        }
                    call_id = call["id"] or run_id
                    operation_id = self.operation_id_factory(
                        request_id or self.thread_id, "langgraph", call_id
                    )
                    tool_started[run_id] = (time.monotonic(), call_id, operation_id)
                    yield ToolExecutionStarted(
                        tool_name=tool_name,
                        tool_input=dict(call["args"]),
                        tool_call_id=call_id,
                        turn_id=call["turn_id"],
                        request_id=request_id,
                        operation_id=operation_id,
                    )
                    continue
                if name in {"on_tool_end", "on_tool_error"}:
                    tool_name = str(event.get("name") or "")
                    started, call_id, operation_id = tool_started.pop(
                        run_id, (time.monotonic(), run_id, run_id)
                    )
                    output, status_error = _tool_output(
                        data.get("output") if name == "on_tool_end" else data.get("error")
                    )
                    yield ToolExecutionCompleted(
                        tool_name=tool_name,
                        output=output,
                        is_error=name == "on_tool_error" or status_error,
                        tool_call_id=call_id,
                        turn_id=f"{request_id or self.thread_id}:turn:{turn_index}",
                        request_id=request_id,
                        operation_id=operation_id,
                        duration_seconds=max(0.0, time.monotonic() - started),
                    )
            final_message = await self._refresh_messages(config)
            if (isinstance(final_message, AIMessage)
                    and final_message.additional_kwargs.get("oceanx_delivered")):
                # File-backed delivery is not an extra model call. Do not bill its
                # prose a second time; preserve it as the participant's final answer.
                yield AssistantTurnComplete(
                    message=ConversationMessage.from_langchain(final_message),
                    usage=UsageSnapshot(input_tokens=0, output_tokens=0),
                    turn_id=f"{request_id or self.thread_id}:delivery", request_id=request_id,
                )
                return
            if (last_model_message is None or not _message_text(last_model_message).strip()
                    or last_model_message.tool_calls):
                metadata = last_model_message.response_metadata if last_model_message else {}
                extra = last_model_message.additional_kwargs if last_model_message else {}
                finish = metadata.get("finish_reason") or metadata.get("stop_reason")
                log.warning("Missing model answer request=%s finish=%s tool_calls=%s",
                            request_id, finish,
                            len(last_model_message.tool_calls) if last_model_message else 0)
                if finish in {"length", "max_tokens", "content_filter", "refusal"} or extra.get("refusal"):
                    yield ErrorEvent(message=f"Model did not deliver an answer (finish_reason={finish or 'refusal'}).",
                                     code="model_output_error", retryable=False)
                else:
                    yield ErrorEvent(message="Model stream ended without a final answer.",
                                     code="empty_model_response", retryable=True)
        except Exception as exc:  # noqa: BLE001 - provider adapters have no common error base
            await self._refresh_messages(config)
            yield model_error_event(exc)


async def build_deep_agent_graph(*, profile, tools, system_prompt, cwd, operation_id_factory,
                                 subagents=None, middleware=None, checkpointer=None, skill_library=None,
                                 filesystem_backend=None, filesystem_tools="all",
                                 research_tree=None):
    """Build only a graph. Agent Server supplies persistence and executes it."""
    model = create_chat_model(profile)
    from deepagents._models import get_model_provider

    from oceanx.provider_retry import provider_retry_middleware
    _configure_native_harness(get_model_provider(model))
    from oceanx.native_skills import skill_backend, skill_permissions
    backend = filesystem_backend if filesystem_backend is not None else (
        skill_backend(skill_library) if skill_library is not None else StateBackend())
    permissions = skill_permissions() if skill_library is not None else []
    domain_tools = list(tools.as_langchain_tools(cwd=cwd, operation_id_factory=operation_id_factory))
    if research_tree is not None:
        from oceanx.research.tree_tools import research_tree_tool
        domain_tools.append(research_tree_tool(research_tree))
    return create_deep_agent(model=model, tools=domain_tools,
        system_prompt=system_prompt, subagents=subagents or [], backend=backend,
        skills=["/skills/"] if skill_library is not None else None, permissions=permissions,
        checkpointer=checkpointer, name="oceanx", middleware=[
            *(middleware or []), provider_retry_middleware(),
            FilesystemMiddleware(backend=backend, tools=filesystem_tools, _permissions=permissions,
                                 tool_token_limit_before_evict=4_000)])




__all__ = ["NATIVE_TASK_DESCRIPTION", "DeepAgentEngine", "build_deep_agent_graph"]
