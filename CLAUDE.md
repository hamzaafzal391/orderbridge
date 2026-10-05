# OrderBridge

## Purpose
A production-style CRM-to-ERP integration. Reference implementation:
GoHighLevel (CRM) <-> OrderBridge <-> ERPNext (ERP).
The owner is learning automation and integration engineering, so clarity matters
more than cleverness.

## Stack
- Python 3.14, Pydantic, httpx, pytest, Ruff
- Later: FastAPI, PostgreSQL, SQLAlchemy + Alembic, Docker, GitHub Actions, AWS
- n8n only where workflow orchestration or human notifications are justified

## Architecture boundaries
- Business logic is separate from vendor-specific API clients.
- Vendor clients (`app/clients/`) hide vendor details and raise our own errors
  (e.g. `ERPNextError`), never raw httpx exceptions.
- Goal: GHL or ERPNext can be replaced through adapter interfaces.
- No unnecessary abstractions or infrastructure. Do not add dependencies without
  explaining why.
- Do not make unrelated refactors while implementing a feature.
- Prefer the smallest complete change that satisfies the current acceptance
  criteria.

## Testing
- Unit tests must never call live services. Use `httpx.MockTransport`.
- Integration tests may call local test services, but must be explicitly marked
  and excluded from the default unit-test command.
- Before finishing work, run: `pytest`, `ruff check .`, `ruff format --check .`

## Security
- Never expose or commit secrets. Never modify `.env` (use `.env.example`).
- Secrets use `SecretStr`; never log them or put them in error messages.
- Do not log personal customer data, authorization headers, tokens or secrets.

## Git
- Never commit, push, merge, or open a pull request unless explicitly asked.
- Show `git status` and `git diff` before asking for permission to commit.
- Never use destructive Git commands.

## Reliability requirements
- Validation, idempotency, retries, duplicate-event handling, replay,
  reconciliation, structured logs, monitoring, audit history.
- Every external API call has an explicit timeout.
- Only retry operations that are safe to repeat (reads); design idempotency
  before retrying writes.

## Learning workflow
1. Inspect the repo before suggesting changes.
2. Explain the current structure in easy language.
3. State the exact problem being solved.
4. Propose the smallest implementation plan.
5. List the files that would change.
6. Explain tradeoffs and failure cases.
7. Do not edit anything while in Plan mode.
8. After implementing, explain every changed file and important function,
   and show the directory structure.
9. Give manual and pytest verification steps.
10. Ask the owner to explain the feature back before the next major feature.
