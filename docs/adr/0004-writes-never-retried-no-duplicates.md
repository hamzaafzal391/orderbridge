# ADR 0004: Writes are never retried, and must not create duplicates

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

Matching (ADR 0002) can report `no_match`. The next step is to create the ERPNext customer.
Unlike a read, repeating a write can do harm: if a request times out we cannot know whether
ERPNext applied it, and a blind retry could create a second customer. There is no database yet
to remember what has already been done, so full idempotency keys have to wait.

## Decision

- `sync_contact` writes only when matching returns `no_match`, and at most once. `matched`,
  `no_email` and `ambiguous` never write. `dry_run=True` never writes at all.
- ERPNext names a customer by its name, so a second customer with the same name is rejected
  (HTTP 409, or a `DuplicateEntryError` in the reply). `create_customer` turns that into
  "name already taken" and the service reports `name_conflict`: nothing is changed and a person
  decides. We never attach a contact to an existing same-named customer, because it could be a
  different business.
- Writes use a single-attempt `_post` that is never wrapped in the retry helper (ADR 0003).
- A network failure on a write raises `ERPNextUnknownOutcomeError` (not retryable): the write
  may or may not have happened.
- A customer needs a linked contact carrying the email, otherwise the next match would not find
  it. That is a second write. If it fails after the customer was created, the client raises
  `ERPNextPartialWriteError` (not retryable) and the contact must be added by a person.
- New customers get a configurable group and territory (`ERPNEXT_DEFAULT_CUSTOMER_GROUP`,
  `ERPNEXT_DEFAULT_TERRITORY`), because ERPNext requires both and has no defaults set.

## Consequences

- Running the same sync twice never creates two customers: the second run matches by email, or
  hits the name rule.
- After a half-finished write, a rerun reports `name_conflict` and a person completes the
  contact. This is safe but not automatic.
- Automatic repair and true idempotency (storing a key per CRM contact, recording each step)
  need the database and audit history planned later.
- Two runs at the same moment cannot both create the customer: ERPNext's unique name decides,
  and the loser gets `name_conflict`.
- Open question to confirm on the first real write: that this ERPNext answers a duplicate name
  with 409 or `DuplicateEntryError`. The code accepts either.
