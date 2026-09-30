"""Provider retries stay inside a model call, never replaying an Expert's tools."""
import sys

from langchain.agents.middleware import ModelRetryMiddleware
from oceanx.model_recovery import model_error_event


def retryable_provider_error(error: Exception) -> bool:
    return model_error_event(error).retryable is True


def provider_retry_middleware():
    # The framework API requires an integer. This is not a research quota:
    # wait for transient provider recovery until the user cancels the run.
    return ModelRetryMiddleware(max_retries=sys.maxsize,
        retry_on=retryable_provider_error, on_failure="error",
        backoff_factor=2, initial_delay=2, max_delay=30, jitter=True)
