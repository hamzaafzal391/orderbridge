# ADR 0009: The sales lifecycle, and building the availability check first

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

ADR 0005 described the target flow as starting when a deal is marked Won. Real sales start earlier:
a lead shows interest, the rep needs to know whether the goods are available, the answer goes back
to the deal, the price is negotiated, and only then is the deal won, invoiced, paid and shipped. The
ERP is useful *during* the sale, not only after it. That is also a better story to demonstrate.

## Decision

The target lifecycle is:

| Step | What happens | Direction |
|---|---|---|
| Interest | A deal with an equipment line (SKU, quantity, delivery warehouse) reaches "Quote sent" | CRM |
| **Availability** | OrderBridge reads the ERP stock for that SKU and writes the answer onto the deal | ERP to CRM |
| Negotiation | The price is agreed; the deal is marked Won | CRM |
| Order | OrderBridge creates the draft Sales Order (ADR 0008) | CRM to ERP |
| Credit | Within the customer's credit limit: the order is submitted and ships on credit, then is invoiced. Over the limit, or a new customer: the order is held, invoiced first, and ships after payment | ERP rules |
| Fulfilment | Shipped, invoiced, paid or overdue in the ERP move the deal's stage | ERP to CRM |

**The credit result decides the path**, not just a yes or no. The demo contrast: NorthStar
($16,800 against a $50,000 limit) ships on credit; BluePeak (the same order against a $5,000 limit)
must pay first.

**Build order.**
1. The availability check (this decision).
2. Won deal becomes a draft Sales Order (ADR 0008, unchanged apart from reusing the code that reads
   a deal).
3. The credit check and the two payment paths.
4. ERP to CRM status updates.
5. Reconciliation, logging, packaging and deployment.

**Why the availability check first.** It only *reads* from the ERP, so it cannot put wrong data into
it; it is a strong opening scene; and the code that reads a deal and writes a field back to the CRM
is reused by every later step.

**How availability is worked out.** Per warehouse: on hand minus reserved. Reserved comes from
submitted orders; draft orders reserve nothing. The result is written to a text field on the deal,
for example `OK: 6 available in Dallas Warehouse - MAS (need 4)` or `SHORT: 2 available in Dallas
Warehouse - MAS (need 4). Houston Warehouse - MAS has 7 available.` The message holds the SKU,
quantities and warehouse names only, never customer data.

**No idempotency key for the check.** Stock changes over time, so a repeated check should give a
fresh answer, and repeating it is harmless. It is still recorded in the audit log. Writing the same
value into the same field again is also harmless, so that one write is allowed to use the retry policy
(ADR 0003). This is a deliberate exception to "writes are never retried", justified only because the
write is idempotent; it is not a pattern to copy to writes that create things.

## Consequences

- The CRM integration needs the permission to *edit* opportunities as well as read them. Until it is
  granted, the check still works as a dry run, and writing fails with a clear authentication error.
- The availability answer is a snapshot and reserves nothing; reserving is the order's job.
- ADR 0005's flow is superseded by this lifecycle; its scenario, deal contents and field ownership
  still stand. ADR 0008 remains the design for the order step.
- A custom field renamed in the CRM changes its key, so field keys are fixed in code and checked
  against the real account.
