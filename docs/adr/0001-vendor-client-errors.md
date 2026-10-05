# ADR 0001: Vendor clients raise their own classified errors

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

`ERPNextClient` talks to ERPNext over HTTP using `httpx`. Letting `httpx` exceptions (or
`KeyError` from a malformed body) escape would tie all calling code to one HTTP library and to
one vendor. It would also make failures hard to handle correctly: a wrong API key and a
temporary outage both look like "an HTTP error", but only one of them is worth retrying.

## Decision

The client translates every failure at its boundary into an `ERPNextError` subclass:

| Failure | Error | Retryable later? |
|---|---|---|
| 401, 403 | `ERPNextAuthenticationError` | No |
| 404 | `ERPNextNotFoundError` | No |
| 429 | `ERPNextRateLimitError` | Yes, after waiting |
| 500, 502, 503, 504, timeout, connection failure | `ERPNextTemporaryError` | Yes, with backoff |
| Malformed or unexpected response | `ERPNextResponseError` | No |
| Any other unsuccessful response | `ERPNextAPIError` | No |

Details:

- The original exception is kept with `raise ... from error` for debugging.
- Error messages contain only the status code, an exception type name or field names, never
  response bodies, headers, credentials or customer values.
- Responses are validated with Pydantic models; validation failures become
  `ERPNextResponseError`.

## Consequences

- Business logic depends on our error types, not on `httpx`; replacing the HTTP library or the
  ERP only touches the client.
- A retry layer can be added later by reading the error type, with no change to the client.
- Cost: a small amount of extra code and a few more tests.
- `ERPNextRateLimitError` could have been merged into `ERPNextTemporaryError`; it stays separate
  because it needs a different waiting strategy.
