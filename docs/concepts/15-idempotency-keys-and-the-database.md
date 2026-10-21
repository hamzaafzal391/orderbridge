# 15. Idempotency keys and the database

**In one line:** a database row that says "this piece of work is already taken or done" lets many
workers share the job safely.

## The idea

A cloakroom ticket. Only one person can hold ticket number 42. If two people rush to the counter at
the same moment, the attendant hands the ticket to exactly one of them. The ticket (the key) is
what stops two coats from being handed out.

## Tiny example

```python
result = repo.claim("ghl:opportunity-won:1234")

if result == "claimed":
    ...  # do the work, then repo.mark_succeeded(key) or repo.mark_failed(key, "SomeError")
# "duplicate":   already done, do nothing
# "in_progress": someone else is on it right now, do nothing
# "reclaimed":   an earlier try failed or crashed, so it is yours now
```

## In OrderBridge

- [`app/db/repository.py`](../../app/db/repository.py) has `claim`, `mark_succeeded`,
  `mark_failed`, plus object links ("this deal became that Sales Order") and an audit log.
- The database decides the winner: only one insert of a new key can succeed. Taking over a failed or
  crashed key uses a compare-and-swap, an update that only works if nobody changed the row first.
- The tests prove it with real PostgreSQL and 16 threads released at the same instant: exactly one
  wins, every time
  ([`tests/integration/test_db_postgres.py`](../../tests/integration/test_db_postgres.py)).
- Only ids, statuses and error class names are stored, never customer data.
- Decision record: [ADR 0006](../adr/0006-postgresql-idempotency-keys-links-audit.md). It is built
  and tested, but not yet used by the sync flow, which is a later step.

## Check yourself

*Why can't the "look before creating" check alone stop two simultaneous runs, but a key in a database can?*

Model answer: the check only looks at the past, and two runs at the same instant both see "nothing
yet"; a unique key forces the database to let exactly one of them in.
