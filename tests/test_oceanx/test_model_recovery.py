import ssl
from types import SimpleNamespace

import httpx
import httpx2
import openai
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


REQUEST = httpx2.Request("POST", "https://provider.example/v1/chat/completions")


@pytest.mark.parametrize("error", [
    httpx2.ReadError(""),  # the benchmark failure of 2026-10-17: a streamed reply broke off
    httpx2.RemoteProtocolError("Server disconnected without sending a response."),
    httpx2.ConnectError(""),
    httpx2.WriteError(""),
    httpx.ReadError(""),
    ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
    ConnectionResetError(54, "Connection reset by peer"),
    openai.APIConnectionError(request=REQUEST),
], ids=lambda error: type(error).__name__)
def test_a_dropped_connection_is_retried_whatever_its_message_says(error):
    event = model_error_event(error)
    assert (event.code, event.retryable) == ("network_failure", True)
    assert event.message  # the type names an error that came without words


@pytest.mark.parametrize("error", [httpx2.ReadTimeout(""), httpx.ConnectTimeout(""),
                                   openai.APITimeoutError(request=REQUEST)], ids=lambda error: type(error).__name__)
def test_a_timeout_is_retried(error):
    assert (model_error_event(error).code, model_error_event(error).retryable) == ("provider_timeout", True)


def test_the_provider_integrations_typed_errors_decide_themselves():
    from langchain_openai.chat_models import base

    def typed(kind, status, message="provider failed"):
        return kind(message, response=httpx2.Response(status, request=REQUEST), body=None)

    cases = [(typed(base.OpenAIRateLimitError, 429), "provider_rate_limit", True),
             (typed(base.OpenAIAPIError, 500), "provider_unavailable", True),
             (base.OpenAIConnectionError(message="", request=REQUEST), "network_failure", True),
             (typed(base.OpenAIAuthenticationError, 401), "model_configuration_error", False),
             (typed(base.OpenAIInvalidRequestError, 400), "model_request_error", False),
             (typed(base.OpenAIContextOverflowError, 400, "context_length_exceeded"), "model_request_error", False),
             (typed(base.OpenAIRateLimitError, 429, "insufficient_quota"), "model_configuration_error", False)]
    for error, code, retryable in cases:
        assert (model_error_event(error).code, model_error_event(error).retryable) == (code, retryable), error


@pytest.mark.parametrize("error", [TypeError("unexpected keyword"), KeyError("messages"), AttributeError("x"),
                                   httpx2.UnsupportedProtocol("Request URL is missing a protocol."),
                                   httpx2.LocalProtocolError("")], ids=lambda error: type(error).__name__)
def test_a_fault_that_would_fail_again_is_not_retried(error):
    """Inside an agent a retryable call is sent again without limit, so a fault of OceanX's own
    code, or a request that cannot be sent, must stop the call instead."""
    assert model_error_event(error).retryable is False
