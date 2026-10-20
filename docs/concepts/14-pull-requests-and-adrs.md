# 14. Pull requests and decision records

**In one line:** make small changes with clear descriptions, and write down why each important
decision was made.

## The idea

A lab notebook: months later you can see what was tried, what was decided and why, instead of
guessing from the code alone.

## Tiny example

A short, readable history:

```
feat(erpnext): return typed customer and classify client errors
fix(erpnext): find customers by email through Contact records
fix(erpnext): check for an existing customer name before creating
```

The format is `type(scope): what changed` (Conventional Commits).

## In OrderBridge

- One small feature per branch and pull request, squash-merged. The PR template
  ([`.github/pull_request_template.md`](../../.github/pull_request_template.md)) asks for
  What, Why, How to verify and Tradeoffs.
- Decision records in [`docs/adr/`](../adr/): why errors are classified, why matching is by email,
  why only reads are retried, why writes are never retried.
- ADRs are corrected, not erased: [ADR 0002](../adr/0002-match-by-email-never-guess.md) and
  [ADR 0004](../adr/0004-writes-never-retried-no-duplicates.md) each carry a dated correction after
  a live check disproved an assumption.
- [`CLAUDE.md`](../../CLAUDE.md) holds the project's working rules.

## Check yourself

*Why keep pull requests small and write down decisions?*

Model answer: small changes are easy to review and to undo, and written reasons let anyone
(including future you) understand why the code is the way it is.
