# Connecting GoHighLevel to the webhook

How to make a deal marked Won in GoHighLevel reach OrderBridge. Written for a local demo; the same
steps apply once the server is deployed.

> **Not yet verified against a real GoHighLevel workflow.** GoHighLevel's official documentation
> does not clearly describe the Webhook action's headers or the merge-field names for IDs, and
> nothing here is known about how it retries after an error. Steps 4 and 5 therefore tell you to
> look at one real request before trusting any field name.

## 1. Settings

In your own `.env` (never committed):

```
DATABASE_URL=postgresql+psycopg://orderbridge:orderbridge@localhost:5436/orderbridge
WEBHOOK_SECRET=<a long random value>
GHL_PIPELINE_ID=<the id of the MetroAir Orders pipeline>
```

Generate the secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The server refuses to start with a secret shorter than 16 characters, or without `GHL_PIPELINE_ID`
(the one pipeline OrderBridge may act on; deals in any other pipeline are ignored).

## 2. Start the database and the server

```bash
docker compose up -d db
alembic upgrade head
python -m app serve            # listens on 127.0.0.1:8000
curl http://127.0.0.1:8000/health
```

## 3. Make it reachable from GoHighLevel

GoHighLevel's servers cannot reach `localhost`. For a demo, run a tunnel that gives you a public
HTTPS address, for example Cloudflare's quick tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Use HTTPS only: the secret travels in a header, so a plain-HTTP address would expose it. Treat a
tunnel as temporary and rotate the secret afterwards. Once OrderBridge is deployed, the deployed
HTTPS address replaces the tunnel.

## 4. Build the workflow in GoHighLevel

Automation, then Workflows, then a new workflow:

- **Trigger:** Opportunity Status Changed, filtered to the pipeline you use and the status Won.
- **Action:** Webhook (custom webhook), method POST.
  - **URL:** `https://<your-public-address>/webhooks/ghl/deal-won`
  - **Header:** `X-Webhook-Secret` with your secret.
  - **Body (JSON):** two fields, filled from the merge-field picker:

```json
{
  "opportunity_id": "<the opportunity's ID merge field>",
  "contact_id": "<the contact's ID merge field>"
}
```

## 5. Look at one real request before trusting it

Before pointing the workflow at OrderBridge, point it at a request catcher (any free "webhook
tester" site) and move a **test** deal to Won. Check the real field names and that the IDs are the
ones you expect, then change the URL to OrderBridge. Do not send real customer data to a third-party
catcher: use a test contact.

## 6. Test it

Move a test deal to Won. Then look at what OrderBridge recorded:

```bash
docker exec orderbridge-db-1 psql -U orderbridge -d orderbridge -c \
  "select key, status, attempts, result from idempotency_keys order by updated_at desc limit 5"
docker exec orderbridge-db-1 psql -U orderbridge -d orderbridge -c \
  "select action, outcome, detail from audit_log order by id desc limit 10"
```

Moving the same deal to Won again must report a duplicate and create nothing.

## What the answers mean

| HTTP | Meaning | What to do |
|---|---|---|
| 200 `already_matched` / `created` | Done | nothing |
| 200 `duplicate` / `in_progress` | The same deal was already handled, or is being handled | nothing |
| 200 `no_email` / `ambiguous` / `name_conflict` | A person must fix the data | fix it, then send the same event again |
| 401 | Wrong or missing secret | check the header value |
| 422 | The body is not what OrderBridge expects | check the field names from step 5 |
| 503 | ERPNext or GoHighLevel is temporarily unavailable | the same event can be sent again |
| 500 | Something else failed | read the audit log |

## Replaying a failed event

A failed deal can be sent again: trigger the workflow for the same deal, or call the endpoint with
`curl`. The failed key is reclaimed and processed again; a succeeded one never runs twice.

## Security notes

- The secret is the only protection: use HTTPS, keep it out of screenshots and recordings, and
  change it if it leaks.
- Answers and logs contain no customer data; the audit log stores ids and statuses only.

## The second endpoint: quote requested (availability check)

`POST /webhooks/ghl/quote-requested`, with the same
`X-Webhook-Secret` header and a body that carries only the opportunity id:

```json
{ "opportunity_id": "<the opportunity's ID merge field>" }
```

It reads the deal, reads the ERP stock and writes the answer onto the deal's `MetroAir Availability`
field. It answers `200` with `{"status", "message", "written"}`; `503` for a temporary problem.
The status is `available`, `short`, `incomplete_deal`, `unknown_item` or `wrong_pipeline`.
Writing needs the Private Integration token to be allowed to edit opportunities (a missing permission
answers 500 and is recorded in the audit log). Check it first with
`python -m app availability <opportunity_id>`, a dry run that writes nothing. Unlike "deal won" it is not made one-time-only: stock changes, so each trigger gives a fresh
answer, and repeating it is harmless. The workflow setup is in [`ghl-hvac-setup.md`](ghl-hvac-setup.md).
