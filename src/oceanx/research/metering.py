"""Record framework model calls as telemetry, never as execution authority."""
import time
from datetime import UTC, datetime

from langchain_core.callbacks import AsyncCallbackHandler

class CallMeter(AsyncCallbackHandler):
    raise_error = True

    def __init__(self, store, config, role, run=None):
        self.store, self.config, self.role, self.run = store, config, role, run
        self.calls = {}
        self.started = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, tags=None, metadata=None, **kwargs):
        c = self.config["configurable"]
        key = str(run_id)
        self.started[key] = time.monotonic()
        self.calls[key] = {
            "call_id": key, "request_id": c["request_id"], "thread_id": c["thread_id"],
            "server_run_id": str(c.get("run_id") or self.config.get("metadata", {}).get("run_id", "")),
            "agent_run_id": self.run.agent_run_id if self.run else None,
            # Research-tree attribution (improvement data only; never shown to a model).
            "node_id": getattr(self.run, "node_id", None),
            "delegation_id": getattr(self.run, "delegation_id", None),
            "attempt_id": getattr(self.run, "attempt_id", None),
            "role": self.role,
            "kind": "summary" if (metadata or {}).get("lc_source") == "summarization" else "normal",
            "state": "running", "started_at": datetime.now(UTC).isoformat(),
            "input_characters": sum(len(str(m.content)) for batch in messages for m in batch),
            "message_count": sum(map(len, messages)),
        }
        self.store.record_model_call(self.calls[key])

    async def on_llm_new_token(self, token, *, run_id, **kwargs):
        key = str(run_id)
        if key in self.calls and "first_chunk_seconds" not in self.calls[key]:
            self.calls[key]["first_chunk_seconds"] = time.monotonic() - self.started[key]

    async def on_llm_end(self, response, *, run_id, **kwargs):
        key = str(run_id)
        if key not in self.calls:
            return
        message = response.generations[0][0].message
        self.calls[key].update(usage=message.usage_metadata,
            tool_calls=len(message.tool_calls),
            model=message.response_metadata.get("model_name"),
            finish_reason=message.response_metadata.get("finish_reason"), state="completed")
        self._finish(key)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        key = str(run_id)
        if key in self.calls:
            self.calls[key].update(state="failed", error_type=type(error).__name__)
            self._finish(key)

    def _finish(self, key):
        self.calls[key].update(ended_at=datetime.now(UTC).isoformat(),
                              duration_seconds=time.monotonic() - self.started[key])
        self.store.record_model_call(self.calls[key])
