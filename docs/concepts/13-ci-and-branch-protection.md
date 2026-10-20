# 13. CI and branch protection

**In one line:** a robot runs the checks on every change, and the main branch refuses changes that
have not passed.

## The idea

A pre-flight checklist that cannot be skipped. People forget steps; a robot does not.

## Tiny example

On every pull request GitHub runs, in order:

```
ruff check .            # lint: common mistakes
ruff format --check .   # formatting is consistent
pytest -q               # all unit tests pass
```

## In OrderBridge

- The workflow: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), one job called
  `checks`. It has read-only permissions and no secrets.
- A GitHub ruleset on `main` requires a pull request, requires `checks` to pass, blocks force
  pushes and deletion, and keeps history linear. Merges are squash merges, so `main` has one clean
  commit per change.
- Dependabot opens weekly update PRs, and the same checks decide whether an update is safe
  ([`.github/dependabot.yml`](../../.github/dependabot.yml)).
- CI has no `.env` on purpose: tests that secretly needed real settings would fail there.

## Check yourself

*Why require the checks to pass before anything can merge?*

Model answer: so broken code cannot reach `main`, even by accident, and the rule applies to
everyone, including the owner.
