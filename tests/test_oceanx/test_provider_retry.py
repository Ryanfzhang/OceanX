import asyncio

import pytest
from oceanx.provider_retry import provider_retry_middleware


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
