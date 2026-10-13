# ADR 0002: Match CRM contacts to ERP customers by email, and never guess

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

OrderBridge must decide whether a GoHighLevel contact already exists as an ERPNext customer.
The two systems share no ID. Names are unreliable: typos, trading names and duplicates are
common. A wrong match is worse than no match, because later features (order sync) would
attach data to the wrong customer.

## Decision

- Match on **email**, compared case-insensitively after trimming whitespace.
- The service returns one of four explicit results instead of picking the "best" one:

| Result | Meaning |
|---|---|
| `matched` | exactly one ERP customer has this email |
| `no_match` | none do (including ERP customers with no email on file) |
| `no_email` | the CRM contact has no email, so matching is impossible |
| `ambiguous` | several ERP customers share the email; a human must decide |

- The service is **read-only** and depends on two small protocols (`ContactSource`,
  `CustomerFinder`), not on the vendor clients, so either system can be replaced.
- Errors from the clients propagate unchanged; the caller decides about retries.

## Consequences

- ERPNext stores a customer's email on its primary contact and copies it into the read-only
  `email_id` field. Customers without a primary-contact email are invisible to this lookup and
  report `no_match`. That can cause a false "no match", but never a wrong match.
- The ERPNext email filter is built from ERPNext's documented API and covered by unit tests with
  a fake server; it still needs one check against a live ERPNext instance.
- Creating missing customers is deliberately out of scope: it needs idempotency and duplicate
  handling designed first.
- A stored GoHighLevel contact ID on the ERPNext customer would be more robust long term, and
  can replace or complement email matching later.
