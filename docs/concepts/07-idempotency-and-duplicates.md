# 07. Idempotency and duplicates

**In one line:** an operation is idempotent when doing it twice has the same effect as doing it
once.

## The idea

Pressing the "up" button on an elevator twice does not make it go up two floors. Creating a customer
is not like that by default: do it twice and you get two customers.

## Tiny example

```
run 1: no customer for sam@example.com  -> create "Sam Rivera"          (created)
run 2: email now matches                -> do nothing                   (already_matched)
```

## In OrderBridge (today)

OrderBridge is safe against duplicates "by construction":

1. **Match first:** an email match means nothing is written
   ([`customer_matching.py`](../../app/services/customer_matching.py)).
2. **Look before creating:** if a customer with that name exists, return `name_conflict` and change
   nothing ([`erpnext.py`](../../app/clients/erpnext.py)).
3. **Check after creating:** if ERPNext answers with a numbered name (`Name - 1`), raise
   `ERPNextDuplicateCreatedError`.

**The lesson:** we first assumed ERPNext refuses duplicate names. It does not: it silently creates
`Name - 1`. A live test found this, and steps 2 and 3 were added. See
[ADR 0004](../adr/0004-writes-never-retried-no-duplicates.md).

**Known gap:** two runs at the exact same moment can both pass step 2. Fully closing it needs a
stored key or a lock in a database (planned, not built).

## Check yourself

*Why can't we fully prevent two simultaneous runs from creating a duplicate yet?*

Model answer: neither run can see what the other is doing at that instant; it needs something
shared, like a database record or lock.
