import asyncio

import httpx2
import pytest

from oceanx import provider_retry
from oceanx.provider_retry import call_with_retries, provider_retry_middleware


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, 429, 503])
async def test_retry_preserves_request_without_replaying_graph(status):
    middleware = provider_retry_middleware()
    middleware.initial_delay = 0
    middleware.jitter = False
    calls = []
    request = object()

    async def handler(value):
        calls.append(value)
        if len(calls) < 7:
            error = ConnectionError("temporary outage")
            if status is not None:
                error = RuntimeError(f"HTTP {status}")
                error.status_code = status
            raise error
        return "delivered"

    assert await middleware.awrap_model_call(request, handler) == "delivered"
    assert calls == [request] * 7


@pytest.mark.asyncio
async def test_permanent_failure_is_not_retried():
    middleware = provider_retry_middleware()
    calls = []

    async def handler(value):
        calls.append(value)
        raise ValueError("insufficient_quota")

    with pytest.raises(ValueError, match="insufficient_quota"):
        await middleware.awrap_model_call(None, handler)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generic_provider_internal_error_retries_same_model_call():
    middleware = provider_retry_middleware()
    middleware.initial_delay = 0
    middleware.jitter = False
    calls = []
    request = object()

    async def handler(value):
        calls.append(value)
        if len(calls) < 4:
            raise RuntimeError("An internal error occurred")
        return "delivered"

    assert await middleware.awrap_model_call(request, handler) == "delivered"
    assert calls == [request] * 4


@pytest.mark.asyncio
async def test_cancellation_during_provider_wait_propagates():
    middleware = provider_retry_middleware()
    attempted = asyncio.Event()

    async def handler(value):
        attempted.set()
        raise ConnectionError("offline")

    task = asyncio.create_task(middleware.awrap_model_call(None, handler))
    await attempted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_a_reply_whose_stream_broke_is_requested_again():
    """The benchmark failure of 2026-10-17: httpx2.ReadError without a message, after HTTP 200."""
    middleware = provider_retry_middleware()
    middleware.initial_delay = 0
    middleware.jitter = False
    calls = []
    request = object()

    async def handler(value):
        calls.append(value)
        if len(calls) < 3:
            raise httpx2.ReadError("")
        return "delivered"

    assert await middleware.awrap_model_call(request, handler) == "delivered"
    assert calls == [request] * 3


def test_a_call_outside_an_agent_is_retried_by_the_same_rule_a_bounded_number_of_times(monkeypatch):
    waits = []
    monkeypatch.setattr(provider_retry.time, "sleep", waits.append)
    replies = iter([httpx2.ReadError(""), ConnectionResetError(54, "reset"), "the reply"])

    def call():
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    assert call_with_retries(call) == "the reply" and len(waits) == 2
    assert 1.5 <= waits[0] <= 2.5 and 3 <= waits[1] <= 5  # the middleware's waits
    # What would fail again is raised at once; a provider that stays away, after the last try.
    with pytest.raises(TypeError):
        call_with_retries(lambda: (_ for _ in ()).throw(TypeError("a fault of our own")))
    tries = []

    def offline():
        tries.append(1)
        raise httpx2.ConnectError("")

    with pytest.raises(httpx2.ConnectError):
        call_with_retries(offline)
    assert len(tries) == provider_retry.OFFLINE_ATTEMPTS and max(waits) <= provider_retry.MAX_DELAY * 1.25


def test_the_meta_model_used_offline_retries_its_requests(monkeypatch):
    """The learning step, the readings of final answers (also benchmarking/server/read_answers.py)
    and the node labels call the model through default_llm."""
    from types import SimpleNamespace

    from oceanx import model_config
    from oceanx.research.llm import default_llm
    replies = iter([httpx2.ReadError(""), SimpleNamespace(text="ok")])

    class Model:
        def invoke(self, prompt):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(model_config, "_load_settings_payload", dict)
    monkeypatch.setattr(model_config, "load_model_profile", lambda role: role)
    monkeypatch.setattr(model_config, "create_chat_model", lambda profile: Model())
    monkeypatch.setattr(provider_retry.time, "sleep", lambda seconds: None)
    assert default_llm()("prompt") == "ok"
