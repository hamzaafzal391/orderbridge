"""Bounded retries with exponential backoff, for READ requests only.

An error is retried only if it says so: it has `retryable = True`. Vendor clients mark their
temporary and rate-limit errors that way. Never wrap a write in `call_with_retries` until the
write is idempotent (safe to repeat).
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass


def default_jitter(delay: float) -> float:
    """Spread retries out: wait between 50% and 100% of the planned delay."""
    return random.uniform(0.5 * delay, delay)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3  # total tries, including the first one
    base_delay: float = 0.5  # seconds before the first retry; doubles each time
    max_delay: float = 5.0  # no single wait is longer than this
    sleep: Callable[[float], None] = time.sleep  # replaced in tests
    jitter: Callable[[float], float] = default_jitter  # replaced in tests

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


def parse_retry_after(value: str | None) -> float | None:
    """Read a Retry-After header given in seconds. Dates and garbage give None."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def call_with_retries[T](func: Callable[[], T], policy: RetryPolicy) -> T:
    """Call `func`, retrying while it raises a retryable error, up to the policy's limit.

    After the last attempt the last error is raised unchanged. Errors that are not retryable
    are raised immediately.
    """
    attempt = 1
    while True:
        try:
            return func()
        except Exception as error:
            if not getattr(error, "retryable", False) or attempt >= policy.max_attempts:
                raise

            retry_after = getattr(error, "retry_after", None)
            if retry_after is not None:
                delay = min(retry_after, policy.max_delay)
            else:
                delay = policy.jitter(min(policy.base_delay * 2 ** (attempt - 1), policy.max_delay))
            policy.sleep(delay)
            attempt += 1
