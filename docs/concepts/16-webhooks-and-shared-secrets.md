# 16. Webhooks and shared secrets

**In one line:** a webhook is a doorbell that one system rings when something happens, and a shared
secret is the password only the real caller knows.

## The idea

Instead of OrderBridge asking GoHighLevel every minute "any new won deals?", GoHighLevel rings our
doorbell the moment a deal is won. That is quicker and needs no repeated checking.

But anyone could ring that doorbell, so the caller must also say a password at the door. If it is
wrong or missing, the door stays shut and nothing happens.

## Tiny example

```bash
curl -X POST https://example.test/webhooks/ghl/deal-won \
  -H "X-Webhook-Secret: <the shared secret>" \
  -H "Content-Type: application/json" \
  -d '{"opportunity_id": "opp-1", "contact_id": "contact-1"}'
```

The answer is a short status such as `{"status": "created", "idempotency": "claimed"}`. Sending the
very same message again answers `duplicate` and does nothing.

## In OrderBridge

- [`app/api.py`](../../app/api.py) is the front door. It checks the secret in constant time (so the
  time it takes reveals nothing), validates the message, then hands over to
  [`app/services/deal_won.py`](../../app/services/deal_won.py), which holds the logic.
- The deal's idempotency key (`ghl:opportunity-won:<id>`) makes repeated and simultaneous messages
  safe ([page 15](15-idempotency-keys-and-the-database.md)).
- The status code tells the caller what to do: 200 for "handled" (including "a person must look"),
  503 for "try again later", 401 for a wrong secret, 422 for a malformed message.
- A real mistake caught on the way: an empty secret would have let a request with no header through.
  The server now refuses to start with a secret shorter than 16 characters, and an empty header never
  passes. A test breaks the check on purpose to prove the tests would notice.
- Answers never include customer data or error text. Decision record:
  [ADR 0007](../adr/0007-webhook-endpoint.md). Setup guide:
  [`docs/demo/ghl-webhook-setup.md`](../demo/ghl-webhook-setup.md).

## Check yourself

*Why does the endpoint answer 503 for "ERPNext is down" but 200 for "this contact has no email"?*

Model answer: 503 means trying again later could work; "no email" is a problem a retry cannot fix, so
we record it for a person and answer 200, so the caller does not keep retrying pointlessly.
