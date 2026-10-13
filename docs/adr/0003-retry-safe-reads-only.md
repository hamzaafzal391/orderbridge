# ADR 0003: Retry temporary failures, for safe reads only

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

Both vendor clients already classify failures (ADR 0001). A single timeout, 503 or 429 still
failed the whole operation, although repeating the request would usually succeed. Retrying is
only safe when repeating a request cannot cause harm. A repeated read is harmless; a repeated
write could create a duplicate customer or order.

## Decision

- Add `app/retry.py` with `RetryPolicy` and `call_with_retries`.
- Errors declare whether retrying can help with `retryable = True`. Only the rate-limit (429)
  and temporary (5xx, timeout, connection failure) errors do. Authentication, not-found,
  malformed-response and other API errors are never retried.
- Defaults: 3 attempts in total, waits of about 0.5s then 1s (doubling, capped at 5s), with
  jitter so many clients do not retry at the same moment. A numeric `Retry-After` header on a
  429 replaces the computed wait (capped at 5s); date-form headers are ignored.
- After the last attempt the last error is raised unchanged, so callers see the same error
  types as before.
- Retries are applied inside each client's `_get` only. Every GET retries independently, so a
  multi-request lookup repeats only the step that failed.
- Writes are **not** retried. They will be once they are idempotent (safe to repeat).
- The policy is injectable (`retry_policy=`), including `sleep` and `jitter`, so tests run
  instantly and deterministically.

## Consequences

- Fewer failures from short outages and rate limits, at the cost of bounded extra latency: up
  to about three 10-second timeouts plus roughly 1.5 seconds of waiting per request.
- The ERPNext and GoHighLevel error classes still duplicate each other; the shared
  `retryable` and `retry_after` attributes let the retry code work with both without
  merging them.
- Retry waits happen in the calling thread (`time.sleep`). That is fine for a script or worker,
  but an async web endpoint would need a different approach later.
