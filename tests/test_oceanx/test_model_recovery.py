from types import SimpleNamespace

import pytest

from oceanx.model_recovery import model_error_event


class ProviderError(Exception):
    def __init__(self, status, message="provider failed", retry_after=None):
        super().__init__(message)
        self.status_code = status
        self.response = SimpleNamespace(headers={"retry-after": retry_after})


class InternalServerError(Exception):
    pass


@pytest.mark.parametrize(
    "status, code, retryable",
    [
        (401, "model_configuration_error", False),
        (403, "model_configuration_error", False),
        (400, "model_request_error", False),
        (408, "provider_timeout", True),
        (429, "provider_rate_limit", True),
        (503, "provider_unavailable", True),
    ],
)
def test_status_classification(status, code, retryable):
    event = model_error_event(ProviderError(status, "connection failed"))
    assert (event.code, event.retryable) == (code, retryable)


def test_quota_validation_and_timeout_are_distinct():
    assert not model_error_event(ProviderError(429, "insufficient_quota")).retryable
    assert not model_error_event(ValueError("invalid schema")).retryable
    assert model_error_event(TimeoutError()).code == "provider_timeout"
    error = ConnectionError("failed")
    error.__cause__ = OSError("sensitive connection details")
    assert model_error_event(error).code == "network_failure"


@pytest.mark.parametrize(
    "error",
    [
        InternalServerError("An internal error occurred"),
        RuntimeError("An internal error occurred"),
        RuntimeError("Model call failed: An internal error occurred"),
        RuntimeError("Internal server error"),
    ],
)
def test_provider_internal_errors_without_status_are_retryable(error):
    event = model_error_event(error)
    assert (event.code, event.retryable) == ("provider_unavailable", True)


def test_status_can_be_read_from_provider_response():
    error = RuntimeError("provider failed")
    error.response = SimpleNamespace(status_code=503, headers={})
    event = model_error_event(error)
    assert (event.code, event.retryable) == ("provider_unavailable", True)
