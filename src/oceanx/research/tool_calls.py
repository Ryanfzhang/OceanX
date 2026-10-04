"""Tool calls a model garbled: drop stray closing brackets, and ask once more when that is not enough.

A reply whose tool-call arguments are not valid JSON reaches the agent loop as an invalid tool call with
no valid one, so the loop ends without an answer. In the 40-call batch the Coordinator of Q07 sent
``{"changes": [], "view": "full"}}`` on its third call and the whole question failed after 21 seconds.
"""
from __future__ import annotations

import dataclasses
import json

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

_CLOSERS = frozenset("}]")


def _repaired_arguments(args):
    """The arguments object when ``args`` is one complete JSON object followed only by closing brackets."""
    if not isinstance(args, str):
        return None
    text = args.strip()
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    if not isinstance(value, dict) or any(char not in _CLOSERS and not char.isspace() for char in text[end:]):
        return None
    return value


def repaired_message(message):
    """``message`` with the invalid tool calls that only carry stray closing brackets made valid."""
    if not isinstance(message, AIMessage) or not message.invalid_tool_calls:
        return message
    fixed, remaining = [], []
    for call in message.invalid_tool_calls:
        arguments = _repaired_arguments(call.get("args"))
        if arguments is None or not call.get("name") or not call.get("id"):
            remaining.append(call)
        else:
            fixed.append({"name": call["name"], "args": arguments, "id": call["id"], "type": "tool_call"})
    if not fixed:
        return message
    return message.model_copy(update={"tool_calls": [*message.tool_calls, *fixed],
                                      "invalid_tool_calls": remaining})


def _repaired_response(response):
    result = getattr(response, "result", None)
    if isinstance(result, list):
        return dataclasses.replace(response, result=[repaired_message(message) for message in result])
    return repaired_message(response)


def _unusable(response) -> bool:
    """The reply asked for a tool but no call in it can run, so the loop would end without an answer."""
    result = getattr(response, "result", None)
    reply = result[-1] if isinstance(result, list) and result else response
    return isinstance(reply, AIMessage) and bool(reply.invalid_tool_calls) and not reply.tool_calls


class ToolCallRepairMiddleware(AgentMiddleware):
    """Repair the model's reply; if no tool call in it can run, ask once more and take what comes."""

    def wrap_model_call(self, request, handler):
        response = _repaired_response(handler(request))
        return _repaired_response(handler(request)) if _unusable(response) else response

    async def awrap_model_call(self, request, handler):
        response = _repaired_response(await handler(request))
        return _repaired_response(await handler(request)) if _unusable(response) else response
