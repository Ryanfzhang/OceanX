"""Desktop/benchmark stream projection of the single Coordinator server run."""
from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import convert_to_messages
from oceanx.runtime import OCEAN_RUNTIME_PROFILE_VERSION


def coordinator_thread_id(task_id: str) -> str:
    """Return the durable Agent Server thread owned by one research task."""

    return str(uuid5(NAMESPACE_URL, OCEAN_RUNTIME_PROFILE_VERSION + ":" + task_id))


def agent_server_client():
    from langgraph_sdk import get_client
    return get_client(api_key=None, headers={
        "authorization": "Bearer " + os.environ["OCEAN_SERVER_TOKEN"]
    })


def decode(value):
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        kind = value.get("type")
        if kind in {"ai", "human", "system", "tool", "AIMessageChunk"} and "content" in value:
            if kind == "AIMessageChunk":
                from langchain_core.messages import AIMessageChunk
                return AIMessageChunk(**{k: v for k, v in value.items() if k != "type"})
            return convert_to_messages([value])[0]
        return {k: decode(v) for k, v in value.items()}
    return value


def server_error_message(value) -> str:
    """Turn Agent Server error envelopes into one readable desktop message."""
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        error = value.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
    text = str(value).strip()
    return text or "The Coordinator run failed."


class ServerGraphStream:
    """Expose server SSE in the existing UI event format; all execution stays on the server."""
    handles_context = True
    def __init__(self, *, client, binding):
        self.client, self.binding = client, binding
        self.thread_id = coordinator_thread_id(binding["task_id"])

    async def aget_state(self, config):
        state = await self.client.threads.get_state(self.thread_id)
        return SimpleNamespace(values=decode(state.get("values", {})), next=state.get("next", []))

    def set_request_options(self, **options):
        self.binding["request_options"] = {
            **self.binding.get("request_options", {}),
            **options,
        }

    async def astream_events(self, inputs, config, version="v2"):
        c = {**self.binding, "request_id": config["configurable"]["request_id"]}
        if inputs:
            messages = inputs.get("messages", [])
            c["original_question"] = messages[-1].text if messages else ""
            inputs = {"messages": [m.model_dump(mode="json") if isinstance(m, BaseMessage) else m for m in messages],
                      "research_complete": False, "final_answer": ""}
        await self.client.threads.create(thread_id=self.thread_id, if_exists="do_nothing")
        run = await self.client.runs.create(self.thread_id, "coordinator", input=inputs,
            # Preserve DeepAgents' native graph-step default when Agent Server
            # supplies the invocation config. Expert model calls are limited
            # independently by ModelCallLimitMiddleware inside the subagent.
            config={"configurable": c, "recursion_limit": 9_999},
            metadata={"oceanx_request_id": c["request_id"]},
            multitask_strategy="enqueue", stream_mode=["events", "values"])
        # Cancellation is native Agent Server behavior.  Closing this joined
        # stream interrupts its run and therefore the active DeepAgents
        # subtree; the desktop gateway does not enumerate runs, wait for graph
        # teardown, or manually stop Expert resources.
        async for part in self.client.runs.join_stream(
            self.thread_id,
            run["run_id"],
            cancel_on_disconnect=True,
        ):
            if part.event == "events":
                yield decode(part.data)
            elif part.event == "error":
                raise RuntimeError(server_error_message(part.data))
        finished = await self.client.runs.get(self.thread_id, run["run_id"])
        if finished["status"] in {"error", "timeout", "interrupted"}:
            raise RuntimeError(f"Coordinator run ended with {finished['status']}")
