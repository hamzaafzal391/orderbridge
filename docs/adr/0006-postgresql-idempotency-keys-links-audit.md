# ADR 0006: PostgreSQL for idempotency keys, object links and an audit log

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The target flow (ADR 0005) needs OrderBridge to remember things between events: that a "deal won"
event was already processed, that a deal became a particular Sales Order, and what happened along
the way. Until now the duplicate protection was "by construction" (ADR 0004): look before creating,
check afterwards. That cannot stop two runs at the exact same moment from both passing the check,
because neither can see the other.

## Decision

Add PostgreSQL with three small tables, accessed through one repository module
(`app/db/repository.py`), using SQLAlchemy and Alembic migrations.

| Table | Purpose |
|---|---|
| `idempotency_keys` | One row per unit of work (for example `ghl:opportunity-won:<id>`), with a status and an attempt count |
| `object_links` | "This CRM object became that ERP object", unique per CRM object |
| `audit_log` | Append-only record of actions and outcomes |

**The claim.** Before doing work, a worker calls `claim(key)`:

| Situation | Result | What the worker does |
|---|---|---|
| New key | `claimed` | does the work, then marks it succeeded or failed |
| Already succeeded | `duplicate` | nothing |
| Being processed by someone, recently | `in_progress` | nothing |
| Failed earlier (a replay), or processing but stale | `reclaimed` | does the work again |

A new key is decided by the database's unique constraint: only one insert can win. Taking over a
failed or stale key is a compare-and-swap: an update that only succeeds if the row is exactly as it
was just read, so two workers cannot both take it over. A `processing` key untouched for 10
minutes is treated as belonging to a crashed worker.

**What is stored.** Only ids, statuses, counts and error class names, as flat dictionaries of simple
values (anything nested raises an error). Never emails, tokens, response bodies or names. A test
fixes the exact column list, so adding a column is a deliberate, reviewed change.

**Optional.** `DATABASE_URL` is optional: the CLI and the clients work without a database.
Migrations read only the database URL, so they do not need ERPNext or GoHighLevel settings.

**Testing.** Rules are unit-tested offline on SQLite with a controllable clock. Behaviour that
depends on a real database, including 16 threads racing to claim the same key, runs against real
PostgreSQL in tests marked `integration`. These are excluded from the default run and have their own
CI job with a PostgreSQL service container.

## Consequences

- Once the claim is used in the sync flow, the race gap documented in ADR 0004 is closed. This step
  only built and tested the foundation; the webhook ([ADR 0007](0007-webhook-endpoint.md)) is the
  first thing to use it.
- A stale timeout that is too short could let a slow job run twice; ten minutes is conservative and
  adjustable in code.
- New dependencies: `sqlalchemy` (SQL toolkit), `alembic` (schema migrations) and `psycopg`
  (PostgreSQL driver, with prebuilt wheels for Python 3.14).
- SQLite behaves differently from PostgreSQL under concurrency, which is why the concurrency
  guarantees are tested on PostgreSQL itself.
- The local database uses development-only credentials in `docker-compose.yml`, on localhost port
  5436; they are for a throwaway container and must not be reused.
