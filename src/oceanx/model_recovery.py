"""Provider error classification shared by model-call retries and UI reporting."""

from __future__ import annotations

import logging
import math

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


def model_error_event(exc: Exception) -> ErrorEvent:
    """Classify provider failures without mistaking auth/validation for transport."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(response, "status", None)
    message = str(exc)
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
    permanent = status in (401, 402, 403) or any(
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
    if permanent:
        return ErrorEvent(
            message=message, code="model_configuration_error", retryable=False, recoverable=False
        )
    if status in (400, 404, 422):
        return ErrorEvent(
            message=message, code="model_request_error", retryable=False, recoverable=False
        )
    code = "model_error"
    if status == 429 or "ratelimit" in name or "rate limit" in lower:
        code = "provider_rate_limit"
    elif status == 408 or isinstance(exc, TimeoutError) or "timeout" in name:
        code = "provider_timeout"
    elif (
        (isinstance(status, int) and 500 <= status <= 599)
        or "internalservererror" in name
        or "internal server error" in lower
        or "an internal error occurred" in lower
    ):
        code = "provider_unavailable"
    elif (
        isinstance(exc, ConnectionError)
        or "connection" in name
        or any(s in lower for s in ("connection", "incomplete response", "peer closed"))
    ):
        code = "network_failure"
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
