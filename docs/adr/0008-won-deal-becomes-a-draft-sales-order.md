# ADR 0008: A won deal becomes a draft Sales Order, read from the CRM and fenced to one pipeline

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

The webhook (ADR 0007) receives "deal won" and only makes sure the customer exists. The next step
creates the Sales Order. Two things shape the design:

- The CRM account in use is a real, working account with other pipelines, so a won deal in an
  unrelated pipeline must never create an ERP order.
- A webhook message is not a trustworthy source for money: anyone holding the shared secret, or a
  misconfigured workflow, could send any values.

## Decision

**What a deal carries (ADR 0005):** one equipment line, in GoHighLevel opportunity custom fields:
SKU, quantity, agreed unit price and delivery warehouse. The ERP items have no selling price, so the
deal's agreed price is the order rate.

**Read the deal, do not trust the message.** The webhook message still carries only
`opportunity_id` and `contact_id`. After claiming the idempotency key, OrderBridge reads the
opportunity from the GoHighLevel API and takes the SKU, quantity, price, warehouse, status and
pipeline from there. It requires the status to be Won.

**Fence the account.**
1. The demo lives in its own pipeline ("MetroAir Orders"), with custom fields prefixed "MetroAir".
2. The GoHighLevel workflow trigger is filtered to that pipeline.
3. OrderBridge checks the deal's pipeline against a configured allowlist (`GHL_PIPELINE_ID`) and
   writes nothing for any other pipeline (`wrong_pipeline`), even if the workflow were misconfigured.

**The order is a draft.** A draft changes no stock and no accounts. The credit-check step will submit
it when the customer is within the limit and leave it as a draft credit hold when over.

**Never create two orders for one deal.**
- The idempotency key is one per deal (ADR 0007).
- An object link records "this deal became that Sales Order" (ADR 0006).
- The order carries a reference marker, `GHL-<opportunity id>`, in ERPNext's standard customer PO
  field. Before creating, OrderBridge looks for an order with that marker and reuses it. So if an
  order was created but saving the link failed, a replay finds the order instead of making another.
- The order itself is written once and never retried (ADR 0004). A network failure on that write
  raises "outcome unknown".

**Outcomes that need a person** (recorded as failed so they can be replayed after the data is
fixed, and answered with HTTP 200): `no_email`, `ambiguous`, `name_conflict`, `deal_not_won`,
`wrong_pipeline`, `incomplete_deal` (a missing, zero or negative field), `unknown_item` and
`unknown_warehouse`.

## Out of scope

Multi-line orders, stock checks and reservations, pricing rules and discounts, the credit check
(next step), writing the order number back to the CRM (a later step), and any pipeline other than
the configured one.

## Consequences

- One extra GoHighLevel read per new deal (reads are retried).
- Using the PO field as the marker needs no custom field in ERPNext, but a person editing that field
  on a draft order would defeat the de-duplication for that order.
- The permission needed to read opportunities is already granted; writing back later will need a
  write permission.
- GoHighLevel's response shape for custom-field values is confirmed against the real account before
  the code is written, not assumed.
