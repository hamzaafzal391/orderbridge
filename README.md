# OrderBridge

[![CI](https://github.com/hamzaafzal391/orderbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/hamzaafzal391/orderbridge/actions/workflows/ci.yml)

A reliable CRM-to-ERP integration layer: **GoHighLevel (CRM) ↔ OrderBridge ↔ ERPNext (ERP)**.

> **Status: in development.** The customer engine is built, tested and verified against live
> systems. The order flow (deal won, credit-checked Sales Order, status back to the CRM) is the
> next milestone; see [Status](#status).

## The problem

Picture an HVAC equipment distributor that sells rooftop units and thermostats to mechanical
contractors, on credit. Sales works in a CRM; finance and the warehouse work in an ERP.

- When a deal closes, someone re-types the customer and the order into the ERP: slow, error-prone,
  and a source of duplicate customers.
- The rep may have promised equipment to a contractor who is already at their credit limit or has
  overdue invoices. Finance finds out after the promise.
- Once the order ships or is invoiced, the sales team has to ask "did it ship?", because the ERP
  knows and the CRM does not.

Naive integrations also fail quietly: a timeout creates a duplicate order, a bad response corrupts
data, an expired API key goes unnoticed.

OrderBridge sits between the two systems and treats reliability as the main feature:
validation, error classification, idempotency, retries and audit history.

## The target flow

```
Deal marked "Won" in GoHighLevel
  -> make sure the customer exists in ERPNext              [built]
  -> check the customer's credit limit                     [planned]
       within the limit : create the Sales Order and write its number back to the CRM
       over the limit   : save a draft order, flag "credit hold" in the CRM, alert finance
  -> the warehouse ships, invoices; the invoice is paid or goes overdue in ERPNext
  -> the CRM opportunity stage updates itself              [planned]
```

A deal carries one equipment line: SKU, quantity, agreed unit price and delivery warehouse. The
reasoning is in [ADR 0005](docs/adr/0005-target-scenario-hvac-distributor.md) and the demo script is
in [`docs/demo/storyboard.md`](docs/demo/storyboard.md).

## Architecture

```mermaid
flowchart LR
    GHL[GoHighLevel CRM] <--> OB[OrderBridge]
    OB <--> ERP[ERPNext]
    subgraph OrderBridge
        direction TB
        L[Business logic] --> C[Vendor clients / adapters]
    end
```

Business logic never talks to a vendor API directly. Vendor-specific code lives in
`app/clients/`, so either system can later be replaced by writing a new adapter.

## Status

| Area | State |
|---|---|
| ERPNext customer client (typed models, classified errors, injectable HTTP client) | Done |
| Unit tests with a fake HTTP transport (no live services) and CI on every PR | Done |
| Internal `Customer` model, independent of any vendor | Done |
| GoHighLevel contact client (read-only), mapped to `Customer` | Done |
| Read-only matching of a CRM contact to an ERP customer by email | Done |
| Create the missing ERPNext customer (never retried, checks for an existing name first; dry-run mode) | Done, verified against a live ERPNext |
| Retries with backoff for safe reads (temporary and rate-limit errors) | Done |
| `python -m app sync` command line (dry run by default) | Done |
| PostgreSQL foundation: idempotency keys, object links, audit log (built and tested; not yet used by the sync flow) | Done |
| FastAPI webhook for "deal won": secret-protected, claims an idempotency key, makes sure the customer exists, records an audit trail (the Sales Order is the next step) | Done |
| Deal to ERPNext draft Sales Order (one equipment line; deal read from the CRM, fenced to one pipeline) | Planned (next) |
| Credit-limit check: draft order and credit hold when over the limit | Planned |
| Write-back to GoHighLevel (order number, stage) | Planned |
| ERP to CRM status sync (shipped, invoiced, paid, overdue) | Planned |
| Reconciliation, replay of failed events, structured logs | Planned |
| Docker and AWS deployment | Planned |

## Reliability design

- **Errors are classified at the client boundary.** Callers see `ERPNextAuthenticationError`,
  `ERPNextNotFoundError`, `ERPNextRateLimitError`, `ERPNextTemporaryError`,
  `ERPNextResponseError` or `ERPNextAPIError`, never raw HTTP library exceptions. A future retry
  layer can then tell retryable failures (429, 5xx, timeouts) from permanent ones.
- **Responses are validated.** ERPNext replies are parsed into Pydantic models; malformed
  data becomes a clear error instead of a crash later.
- **Every outbound call has an explicit timeout.**
- **No secrets or customer data in errors or logs.** Error messages contain status codes and
  field names, never response bodies, credentials or values.
- **Tests never touch live services.** HTTP is faked with `httpx.MockTransport`.

Design decisions are recorded in [`docs/adr/`](docs/adr/). The ideas behind them are explained in
plain language in [`docs/concepts/`](docs/concepts/).

## Quickstart

Requires Python 3.14.

```bash
git clone https://github.com/hamzaafzal391/orderbridge.git
cd orderbridge
python3.14 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q
ruff check . && ruff format --check .
```

To run against real instances, copy `.env.example` to `.env` and fill in `ERPNEXT_BASE_URL`,
`ERPNEXT_API_KEY`, `ERPNEXT_API_SECRET` and `GHL_API_TOKEN`. `.env` is git-ignored.

```python
from app.clients.erpnext import ERPNextClient
from app.clients.erpnext_errors import ERPNextNotFoundError

with ERPNextClient() as client:
    try:
        customer = client.get_customer("NorthStar Mechanical LLC")
        print(customer.name, customer.credit_limits)
    except ERPNextNotFoundError:
        print("No such customer")
```

### Command line

```bash
python -m app sync <contact_id>            # dry run (default): nothing is written
python -m app sync <contact_id> --apply    # really create the missing ERPNext customer
```

It matches a GoHighLevel contact to an ERPNext customer by email and prints one plain-English
result line, for example `already_matched: matches ERPNext customer "NorthStar Mechanical LLC"`.
Other results: `would_create`, `created`, `no_email`, `ambiguous`, `name_conflict`. Customer
names may be shown; emails, tokens and credentials never are.

| Exit code | Meaning |
|---|---|
| 0 | matched, created, or would be created |
| 1 | needs a person: no email, ambiguous, or name conflict |
| 2 | bad usage |
| 3 | configuration problem or service error |

### Webhook server

A GoHighLevel workflow calls OrderBridge when a deal is marked Won. The server needs the database
and a shared secret (at least 16 characters) in your `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # use the output as WEBHOOK_SECRET
python -m app serve                                           # listens on 127.0.0.1:8000
```

```bash
curl -X POST http://127.0.0.1:8000/webhooks/ghl/deal-won \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" -H "Content-Type: application/json" \
  -d '{"opportunity_id": "opp-1", "contact_id": "<a GoHighLevel contact ID>"}'
```

The same deal sent twice, or at the same instant, is processed once. Wrong or missing secret: 401.
Temporary problem: 503. Setup steps for GoHighLevel are in
[`docs/demo/ghl-webhook-setup.md`](docs/demo/ghl-webhook-setup.md) (not yet verified against a real
workflow).

### Database (optional)

PostgreSQL stores idempotency keys, object links and an audit log. The CLI and the clients work
without it.

```bash
docker compose up -d db                     # local PostgreSQL on localhost:5436
export DATABASE_URL=postgresql+psycopg://orderbridge:orderbridge@localhost:5436/orderbridge
alembic upgrade head                        # create the tables
DATABASE_URL_TEST=postgresql+psycopg://orderbridge:orderbridge@localhost:5436/orderbridge_test \
  pytest -m integration                     # tests against the real database
```

The credentials in `docker-compose.yml` are for that throwaway local container only. The default
`pytest` run stays offline and skips the integration tests.

## Project layout

```
app/
├── __main__.py             # makes `python -m app` work
├── api.py                  # webhook server: POST /webhooks/ghl/deal-won, GET /health
├── cli.py                  # command line: `sync <contact_id> [--apply]`, `serve`
├── config.py               # settings loaded from environment / .env
├── models.py               # OrderBridge's own vendor-independent models (Customer)
├── db/                     # PostgreSQL: tables, session, repository (claim, links, audit)
├── retry.py                # bounded retries with backoff (reads only)
├── services/
│   ├── customer_matching.py  # business logic: match a CRM contact to an ERP customer
│   ├── customer_sync.py      # business logic: create the ERP customer if none exists
│   └── deal_won.py           # business logic: handle a won deal exactly once
└── clients/
    ├── erpnext.py          # ERPNext HTTP client; converts ERPNext data to Customer
    ├── erpnext_errors.py   # ERPNext error hierarchy
    ├── erpnext_models.py   # ERPNext response shapes used for validation
    ├── ghl.py              # GoHighLevel HTTP client; converts contacts to Customer
    ├── ghl_errors.py       # GoHighLevel error hierarchy
    └── ghl_models.py       # GoHighLevel response shapes used for validation
migrations/                 # Alembic database migrations
tests/unit/                 # fast tests, no network
tests/integration/          # tests against a real PostgreSQL (marked, run separately)
docker-compose.yml          # local PostgreSQL for development
docs/adr/                   # architecture decision records
.github/workflows/ci.yml    # checks (lint, format, unit tests) and integration (PostgreSQL)
```

## Workflow

Small feature branches, [Conventional Commits](https://www.conventionalcommits.org/), and
squash-merged pull requests into a protected `main` that requires passing CI.
Project rules for contributors and AI assistants are in [`CLAUDE.md`](CLAUDE.md).
