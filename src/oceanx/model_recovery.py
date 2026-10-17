"""Provider error classification shared by model-call retries and UI reporting.

A failure is judged first by its type, which says what failed whatever its message says:
- LangChain's provider integrations raise typed errors (``ModelError``) that state themselves
  whether the same request may succeed: rate limits, provider failures (5xx), connections and
  timeouts may, a refused key or a malformed request may not;
- a transport failure the provider SDK does not wrap is an HTTP-client or socket error. A read
  that broke while a streamed reply came in arrived as ``httpx2.ReadError`` with an empty
  message, was not retried, and failed a whole benchmark question (2026-10-17).
Only an error whose type says nothing, such as one that reached the gateway from the Agent
Server as text, is judged by its HTTP status or its words. What is still unknown, a fault in
OceanX's own code included, is not retried: inside an agent a retryable call is sent again
without limit (provider_retry.py).
"""

from __future__ import annotations

import importlib
import logging
import math
import ssl

from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)

from oceanx.agent_contract import ErrorEvent

log = logging.getLogger(__name__)
RECOVERABLE_MODEL_CODES = frozenset(
    {
        "network_failure",
        "provider_timeout",
        "provider_rate_limit",
        "provider_unavailable",
        "empty_model_response",
    }
)


def _types(modules: tuple[str, ...], names: tuple[str, ...]) -> tuple[type[BaseException], ...]:
    """The named exception types of whichever of these libraries are installed."""
    found: list[type[BaseException]] = []
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        found += [error for error in (getattr(module, name, None) for name in names)
                  if isinstance(error, type) and issubclass(error, BaseException)]
    return tuple(found)


# The HTTP clients of the provider SDKs (the OpenAI SDK moved to httpx2) and the SDKs themselves.
_CLIENTS, _SDKS = ("httpx", "httpx2"), ("openai", "anthropic")
TIMEOUT_ERRORS = (TimeoutError, ModelTimeoutError, *_types(_CLIENTS, ("TimeoutException",)),
                  *_types(_SDKS, ("APITimeoutError",)))
# A connection that could not be made or was dropped, a read or write that broke. Not every
# transport error: a malformed request or an unsupported URL would fail again the same way.
NETWORK_ERRORS = (ConnectionError, ssl.SSLEOFError, ModelConnectionError,
                  *_types(_CLIENTS, ("NetworkError", "RemoteProtocolError")),
                  *_types(_SDKS, ("APIConnectionError",)))


def _typed_code(exc: Exception) -> str | None:
    """What the error's type says about a transient failure; None when it says nothing."""
    if isinstance(exc, ModelRateLimitError):
        return "provider_rate_limit"
    if isinstance(exc, TIMEOUT_ERRORS):
        return "provider_timeout"
    if isinstance(exc, ModelAPIError):
        return "provider_unavailable"
    if isinstance(exc, NETWORK_ERRORS):
        return "network_failure"
    return None


def _code_from_status_or_words(status, name: str, lower: str) -> str:
    """For an error whose type says nothing, e.g. one passed on as text."""
    if status == 429 or "ratelimit" in name or "rate limit" in lower:
        return "provider_rate_limit"
    if status == 408 or "timeout" in name:
        return "provider_timeout"
    if (
        (isinstance(status, int) and 500 <= status <= 599)
        or "internalservererror" in name
        or "internal server error" in lower
        or "an internal error occurred" in lower
    ):
        return "provider_unavailable"
    if "connection" in name or any(s in lower for s in ("connection", "incomplete response", "peer closed")):
        return "network_failure"
    return "model_error"


def model_error_event(exc: Exception) -> ErrorEvent:
    """Classify provider failures without mistaking auth/validation for transport."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(response, "status", None)
    # A transport error may come without words; then its type is what it says.
    message = str(exc) or type(exc).__name__
    lower = message.lower()
    name = type(exc).__name__.lower()
    # Only safe diagnostics: do not log exception bodies, credentials or URLs.
    cause = exc.__cause__ or exc.__context__
    log.warning(
        "Model failure type=%s status=%s cause=%s",
        type(exc).__name__,
        status,
        type(cause).__name__ if cause else None,
    )
    # A quota error may come as a rate limit (429), so the words are read here too.
    permanent = (
        isinstance(exc, (ModelAuthenticationError, ModelPermissionDeniedError))
        or status in (401, 402, 403)
        or any(
            s in lower
            for s in (
                "invalid api key",
                "incorrect api key",
                "insufficient_quota",
                "insufficient balance",
                "authentication",
                "permission denied",
            )
        )
    )
    if permanent:
        return ErrorEvent(
            message=message, code="model_configuration_error", retryable=False, recoverable=False
        )
    if status in (400, 404, 422) or (isinstance(exc, ModelError) and not exc.is_retryable):
        return ErrorEvent(
            message=message, code="model_request_error", retryable=False, recoverable=False
        )
    code = _typed_code(exc) or _code_from_status_or_words(status, name, lower)
    retry_after = None
    headers = getattr(response, "headers", {}) or {}
    try:
        value = float(headers.get("retry-after", ""))
        if math.isfinite(value) and value >= 0:
            retry_after = value
    except (TypeError, ValueError):
        pass
    return ErrorEvent(
        message=message,
        code=code,
        retryable=code in RECOVERABLE_MODEL_CODES,
        retry_after_seconds=retry_after,
    )
