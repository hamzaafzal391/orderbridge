# 06. Retries, backoff and jitter

**In one line:** when a request fails for a temporary reason, wait a little and try again, a limited
number of times, with growing and slightly random waits.

## The idea

If a shop is busy, you do not knock on the door every second. You wait a bit, then a bit longer.
If a hundred people all wait exactly one minute, they all arrive together again, so a little
randomness (jitter) spreads them out.

## Tiny example

```
attempt 1 fails (503)  -> wait about 0.5s
attempt 2 fails (503)  -> wait about 1.0s
attempt 3 fails (503)  -> give up, raise the last error unchanged
```

If a 429 reply says `Retry-After: 2`, we wait 2 seconds instead (never more than 5).

## In OrderBridge

- [`app/retry.py`](../../app/retry.py): `RetryPolicy` (3 attempts, 0.5s base, 5s cap) and
  `call_with_retries`.
- It retries only errors marked `retryable`, and only inside each client's `_get` (reads).
- `sleep` and `jitter` can be replaced in tests, so tests run instantly and exactly.
- Worst case for one request is about three 10-second timeouts plus roughly 1.5 seconds of waiting.
- Decision record: [ADR 0003](../adr/0003-retry-safe-reads-only.md).

## Check yourself

*Why wait longer each time, and add a bit of randomness?*

Model answer: longer waits give a struggling server time to recover; randomness stops many clients
from retrying at the same instant.
