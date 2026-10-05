## What
<!-- What changed, in 1-3 bullets. -->

## Why
<!-- The problem this solves. Link the issue: Closes #123 -->

## How to verify
```bash
pytest -q && ruff check . && ruff format --check .
```
<!-- Add any manual steps. -->

## Tradeoffs and risks
<!-- Alternatives you rejected, failure cases, what is deliberately not included. -->

## Checklist
- [ ] Unit tests added or updated; none call live services
- [ ] No secrets, customer data or credentials in code, logs or error messages
- [ ] No unrelated refactors
