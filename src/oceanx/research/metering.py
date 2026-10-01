"""Record framework model calls as telemetry, never as execution authority."""
import re
import time
from contextvars import ContextVar
from datetime import UTC, datetime

from langchain_core.callbacks import AsyncCallbackHandler

# True while a native Expert runs. The Coordinator's meter is inherited by that nested
# run, so it skips those calls and leaves them to the Expert's own meter.
INSIDE_EXPERT: ContextVar[bool] = ContextVar("oceanx_inside_expert", default=False)
_SKILL_FILE = re.compile(r"/skills/([a-z0-9-]+)/SKILL\.md")


def _skills_read(tool_calls) -> list[str]:
    """The skills a call opened, so a run shows whether its lesson skill was read."""
    paths = (str((call.get("args") or {}).get("file_path", ""))
             for call in tool_calls if call.get("name") == "read_file")
    return sorted({match.group(1) for path in paths if (match := _SKILL_FILE.search(path))})


class CallMeter(AsyncCallbackHandler):
    raise_error = True

    def __init__(self, store, config, role, run=None):
        self.store, self.config, self.role, self.run = store, config, role, run
        self.calls = {}
        self.started = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, tags=None, metadata=None, **kwargs):
        if self.run is None and INSIDE_EXPERT.get():
            return
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
            skills_read=_skills_read(message.tool_calls),
            model=message.response_metadata.get("model_name"),
            finish_reason=message.response_metadata.get("finish_reason"), state="completed")
        self._finish(key)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        key = str(run_id)
        if key in self.calls:
            # The wrapped chain says which transport step failed (e.g. ConnectTimeout vs ReadTimeout).
            causes, cause = [], error.__cause__ or error.__context__
            while cause is not None and len(causes) < 6:
                causes.append(type(cause).__name__)
                cause = cause.__cause__ or cause.__context__
            self.calls[key].update(state="failed", error_type=type(error).__name__,
                                   error_causes=causes)
            self._finish(key)

    def _finish(self, key):
        self.calls[key].update(ended_at=datetime.now(UTC).isoformat(),
                              duration_seconds=time.monotonic() - self.started[key])
        self.store.record_model_call(self.calls[key])
