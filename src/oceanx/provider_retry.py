"""Provider retries stay inside a model call, never replaying an Expert's tools.

One rule decides what is sent again (model_recovery.model_error_event), with the same waits
everywhere. Inside an agent a call waits for the provider without limit, until the user cancels
the run. Outside an agent (the learning step, readings of final answers, labels) a call is tried
a bounded number of times, so that an unattended update ends.
"""
import random
import sys
import time
from collections.abc import Callable
from typing import TypeVar

from langchain.agents.middleware import ModelRetryMiddleware

from oceanx.model_recovery import model_error_event

INITIAL_DELAY, BACKOFF, MAX_DELAY = 2.0, 2.0, 30.0  # seconds
OFFLINE_ATTEMPTS = 6  # about a minute of waiting outside an agent, then the error is raised
T = TypeVar("T")


def retryable_provider_error(error: Exception) -> bool:
    return model_error_event(error).retryable is True


def provider_retry_middleware():
    # The framework API requires an integer. This is not a research quota:
    # wait for transient provider recovery until the user cancels the run.
    return ModelRetryMiddleware(max_retries=sys.maxsize,
        retry_on=retryable_provider_error, on_failure="error",
        backoff_factor=BACKOFF, initial_delay=INITIAL_DELAY, max_delay=MAX_DELAY, jitter=True)


def call_with_retries(call: Callable[[], T], *, attempts: int = OFFLINE_ATTEMPTS) -> T:
    """One model request outside an agent, sent again after a failure the same rule accepts."""
    tried = 0
    while True:
        try:
            return call()
        except Exception as error:
            tried += 1
            if tried >= attempts or not retryable_provider_error(error):
                raise
            delay = min(MAX_DELAY, INITIAL_DELAY * BACKOFF ** (tried - 1))
            time.sleep(delay * random.uniform(0.75, 1.25))  # the middleware's jitter
