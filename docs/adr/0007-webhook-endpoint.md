# ADR 0007: A webhook endpoint for "deal won", protected by a shared secret

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The target flow (ADR 0005) starts when a deal is marked Won in GoHighLevel. OrderBridge needs a
front door that GoHighLevel can call. It must reject strangers, cope with the same message arriving
more than once or at the same instant, and never leak customer data in its answers. The database
foundation (ADR 0006) provides the idempotency keys; this is the first thing to use them.

## Decision

- A small FastAPI app (`app/api.py`) with `GET /health` and `POST /webhooks/ghl/deal-won`, started
  with `python -m app serve`. The web layer only authenticates and translates; the logic is in the
  framework-free `app/services/deal_won.py`, the same split as the command line.
- **The trigger** is a GoHighLevel workflow with a "Webhook" action that we configure: trigger
  "opportunity status changed to Won", POST to our URL with our own small JSON body
  (`opportunity_id`, `contact_id`) and a secret header. GoHighLevel's built-in event format and its
  signature scheme are not used, so we control the body and need no marketplace app.
- **Authentication** is a shared secret in the `X-Webhook-Secret` header, compared in constant
  time. A wrong, missing or empty secret gets 401 with a generic body, before the message is even
  looked at, and nothing is written. The server refuses to start without a secret of at least 16
  characters (an empty secret would otherwise let a request with no header through).
- **One key per deal**, `ghl:opportunity-won:<opportunity_id>`. The handler claims it before doing
  anything, so a repeated message is a `duplicate`, a simultaneous one is `in_progress`, and a
  failed one can be replayed (`reclaimed`).
- **What it does for now:** make sure the deal's customer exists in ERPNext (the existing
  `sync_contact`, with real writes). Creating the Sales Order is a later step.
- **Answers:**

| Situation | HTTP | Why |
|---|---|---|
| Processed, repeated or in progress | 200 with a status | nothing more to do |
| No email, ambiguous or name conflict | 200 with the status | a retry cannot fix it; recorded as failed so it can be replayed after the data is fixed |
| Temporary problem (service down, rate limit) | 503, with `Retry-After` when known | worth retrying later |
| Any other failure | 500, generic body | see the audit log |
| Bad secret | 401 | |
| Malformed message | 422 | |

- Answers never contain customer data, emails, secrets or exception text. The audit log holds ids
  and statuses only. Only exception class names are logged.
- Documentation pages (`/docs`, `/openapi.json`) are switched off.

## Consequences

- Two deal-won messages sent at the same instant create one customer. This is proven against a real
  PostgreSQL with 16 simultaneous requests, and closes the race gap documented in ADR 0004 for this
  entry point. The command line does not use the key yet.
- Processing is synchronous. A slow ERPNext (with retries) could exceed the caller's timeout; a
  background queue is a later improvement.
- One key per deal means a deal re-opened and won again is treated as a duplicate. That is
  deliberate for now.
- No rate limiting or body-size limit on the endpoint yet; the secret is the only protection, so it
  must be served over HTTPS.
- Not verified: GoHighLevel's documentation does not clearly describe the workflow Webhook action's
  headers and merge-field names, and its retry behaviour on a 5xx answer is unknown. The setup guide
  says to catch one real request first.
- New dependencies: `fastapi` (the web framework) and `uvicorn` (the server that runs it).
