# 05. Classified errors

**In one line:** instead of one vague "something failed", raise an error that says what kind of
failure it was, so the caller knows what to do next.

## The idea

A restaurant waiter says "we're out of that" or "the kitchen is closed for ten minutes", not "the
supplier's truck had a flat tire". The kind of problem decides your next move.

## Tiny example

```python
try:
    customer = erp.get_customer("Acme")
except ERPNextNotFoundError:
    ...  # a normal answer: no such customer
except ERPNextTemporaryError:
    ...  # trying again later may work
except ERPNextError:
    ...  # anything else from ERPNext
```

| Failure | Error | Worth retrying? |
|---|---|---|
| 401, 403 | `...AuthenticationError` | No: a person must fix the credentials |
| 404 | `...NotFoundError` | No: a normal answer |
| 429 | `...RateLimitError` | Yes, after waiting |
| 500, 502, 503, 504, timeout, no connection | `...TemporaryError` | Yes, with backoff |
| Garbage reply | `...ResponseError` | No: investigate |
| Anything else | `...APIError` | No |

## In OrderBridge

- [`app/clients/erpnext_errors.py`](../../app/clients/erpnext_errors.py) and
  [`ghl_errors.py`](../../app/clients/ghl_errors.py). Each error has a `retryable` flag.
- The original error is kept with `raise ... from error`, so debugging still works.
- Callers never see raw `httpx` errors, so the HTTP library could change without touching them.
- Decision record: [ADR 0001](../adr/0001-vendor-client-errors.md).

## Check yourself

*Why retry a 503 but not a 401?*

Model answer: a 503 is a temporary server problem that may clear; a 401 means our credentials are
rejected and asking again gets the same answer.
