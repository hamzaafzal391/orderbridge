# 12. Fake servers versus live checks

**In one line:** unit tests use a fake server so they are fast and safe, but a fake only proves your
code against what you *believe* the real system does.

## The idea

A flight simulator can pass a pilot even if the simulator is built wrong. Real flights still need a
real check.

## Tiny example

```python
transport = httpx.MockTransport(handler)  # a fake ERPNext made of one function
client = ERPNextClient(settings=..., http_client=httpx.Client(transport=transport))
```

## In OrderBridge: three times reality disagreed with us

1. **Customer email:** we assumed ERPNext copies a contact's email onto the Customer. It does not
   unless a separate "primary contact" link is set, so the email lookup now searches Contacts
   ([ADR 0002](../adr/0002-match-by-email-never-guess.md)).
2. **Duplicate names:** our fake server rejected a repeated name, but the real ERPNext silently
   creates `Name - 1`. Tests passed while the real system would have made duplicates; a live write
   found it ([ADR 0004](../adr/0004-writes-never-retried-no-duplicates.md)).
3. **Docs disagreed with each other:** GoHighLevel's `Version` header differed between sources, so
   it is a setting you can change without code.

What we do now: unit tests never touch live services (a project rule), important assumptions get
one careful live check, and the fake is rewritten to copy what was observed.

## Check yourself

*Why did the unit tests pass even though the real ERPNext created a duplicate?*

Model answer: the fake server behaved the way I assumed, not the way ERPNext really behaves, so the
tests could not see the difference.
