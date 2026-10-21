# Demo storyboard (3 to 5 minutes)

The story: **MetroAir Supply**, an HVAC equipment distributor, sells to mechanical contractors on
credit. A deal closed in the CRM should become a correct, credit-checked order in the ERP, and the
sales team should see its progress without asking.

All names and amounts are fictional demo data.

## Before recording

- Delete leftover test records (`OrderBridge Test`, `OrderBridge Test - 1`) from ERPNext.
- Give the two equipment items a visible price in the demo, or show the price coming from the deal.
- In GoHighLevel, prepare a new contractor contact with an email that ERPNext does not know.
- Keep the terminal font large; use `.env` values that are not shown on screen.

## Scenes

| # | Scene | What to show | Possible today? |
|---|---|---|---|
| 1 | The problem (30 s) | The re-typing, the credit surprise, "did it ship?". Say it in one breath. | Yes |
| 2 | Safe by default | `python -m app sync <contact>`: a dry run says what it would do, writes nothing | Yes |
| 3 | A new contractor becomes a customer | `--apply` on a new contact: `created`; show the customer and its linked contact in ERPNext | Yes |
| 4 | No duplicates | Run it again: `already_matched`. Mention the name check that catches a numbered duplicate | Yes |
| 5 | Deal won becomes an order | Mark a deal Won; the Sales Order appears; its number shows on the deal | Planned |
| 6 | The credit hold | A deal from the $5,000-limit customer: draft order, "credit hold" in the CRM, finance alert. Then the $50,000 customer's deal goes straight through | Planned |
| 7 | The order moves, the CRM follows | Ship and invoice in ERPNext; the opportunity stage changes to Shipped, then Invoiced, then Paid or Overdue | Planned |
| 8 | When things go wrong | Stop ERPNext for a moment: the event is retried and recorded, nothing is duplicated; show the audit log | Planned |

## Closing line (10 s)

"One safe hand-off between the CRM and the ERP: no re-typing, no duplicates, and a credit check
before a promise is made."

## Notes

- A rough recording of scenes 1 to 4 is possible now. Re-record once scenes 5 to 7 exist.
- Scene 8 needs the database and webhook work; the audit log is the proof it did the right thing.
