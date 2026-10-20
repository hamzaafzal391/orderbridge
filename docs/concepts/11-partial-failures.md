# 11. Partial failures

**In one line:** when a job has two steps and the second fails, you are left halfway, so the design
must make that state safe and visible.

## The idea

Moving house with two trips: the first load arrives, then the car breaks down. Nothing is lost, but
you must not start over and move the first load again.

## Tiny example

Creating a usable customer takes two writes:

```
1. create the Customer          -> done
2. create its linked Contact    -> fails
```

Without step 2 the customer cannot be found by email later.

## In OrderBridge

- `create_customer` raises `ERPNextPartialWriteError` ("customer created, contact not") and does
  **not** retry.
- A rerun finds the customer by name and reports `name_conflict` instead of creating `Name - 1`
  ([test](../../tests/unit/test_erpnext_client.py): the rerun-after-partial-write case).
- The CLI prints "a person must check ERPNext before running this again".
- Finishing the contact automatically (repair) needs stored progress, which comes with the planned
  database. Until then a person completes it. This limit is written in
  [ADR 0004](../adr/0004-writes-never-retried-no-duplicates.md).

## Check yourself

*Why do we stop and ask a person instead of just creating the contact on rerun?*

Model answer: the same-named customer might belong to a different business; only a person (or
stored progress later) can tell, and a wrong link is worse than waiting.
