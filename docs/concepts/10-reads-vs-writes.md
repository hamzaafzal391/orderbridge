# 10. Reads versus writes

**In one line:** repeating a read is harmless; repeating a write can duplicate or corrupt data, so
the two are treated differently.

## The idea

Looking at a bank balance twice changes nothing. Pressing "send payment" twice sends the money
twice. If a payment request times out, you cannot tell whether it went through.

## Tiny example

```
GET  customer  -> times out -> try again.    Safe.
POST customer  -> times out -> did it happen? We do not know.  Do NOT blindly retry.
```

## In OrderBridge

- Reads go through `_get`, which retries temporary failures
  ([`erpnext.py`](../../app/clients/erpnext.py), [`ghl.py`](../../app/clients/ghl.py)).
- Writes go through `_post`, which sends **exactly once** and is never wrapped in the retry helper.
- A network failure on a write raises `ERPNextUnknownOutcomeError`: "this may or may not have
  happened". It is not retryable.
- The name check before a create is a read, so it can retry; the create itself cannot.
- Decision record: [ADR 0004](../adr/0004-writes-never-retried-no-duplicates.md).

## Check yourself

*Why is a write never retried, even when a read with the same error would be?*

Model answer: the first attempt may have worked, so repeating it could create a duplicate; a read
changes nothing, so repeating it is harmless.
