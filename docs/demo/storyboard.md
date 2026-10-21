# Demo storyboard (3 to 5 minutes)

The story: **MetroAir Supply**, an HVAC equipment distributor, sells to mechanical contractors. A
sales rep talks to a lead; the CRM and the ERP should stay in step through the whole sale, with no
re-typing, no surprises about stock or credit, and no duplicates.

All names and amounts are fictional demo data.

## The lifecycle in one picture

```
Lead interested     deal reaches "Quote sent" in the CRM
Availability        OrderBridge reads ERP stock -> "OK: 6 available in Dallas" written on the deal
Negotiation, Won    the rep agrees the price and marks the deal Won
Order               a draft Sales Order appears in ERPNext
Credit check        within the limit: ships on credit, invoiced after
                    over the limit or new customer: hold, invoice first, ship after payment
Fulfilment          Shipped, Invoiced, Paid (or Overdue) move the deal's stage by themselves
```

## Before recording

- Delete leftover test records (`OrderBridge Test`, `OrderBridge Test - 1`) from ERPNext.
- Set up the demo pipeline, fields, contacts and deals in GoHighLevel: see
  [`ghl-hvac-setup.md`](ghl-hvac-setup.md).
- The deal's agreed price is the order price; the equipment items have no list price.
- Keep the terminal font large; use `.env` values that are not shown on screen.
- Show only the `MetroAir Orders` pipeline: the account holds other pipelines.

## Scenes

| # | Scene | What to show | Possible today? |
|---|---|---|---|
| 1 | The problem (30 s) | Re-typing orders, promising stock that is not there, a credit surprise, "did it ship?" | Yes |
| 2 | Quote, then availability | Move a deal to Quote sent; the answer appears on the deal: `OK: 6 available in Dallas Warehouse - MAS (need 4)` | Yes |
| 3 | Not enough stock | A deal that asks for more than is available: `SHORT: ... Houston Warehouse - MAS has 7 available`; the rep switches warehouse | Yes |
| 4 | Won becomes an order | Mark the deal Won; a draft Sales Order appears in ERPNext; its number shows on the deal | Planned |
| 5 | Within credit: ships on credit | NorthStar ($16,800 against a $50,000 limit): the order is submitted; later it ships, is invoiced and paid | Planned |
| 6 | Over credit: hold, prepay | BluePeak (the same order against a $5,000 limit): credit hold; invoice first; ships after payment | Planned |
| 7 | The CRM follows the ERP | Ship and invoice in ERPNext; the deal moves to Shipped, Invoiced, Paid or Overdue by itself | Planned |
| 8 | No duplicates, and a paper trail | The same "won" message twice makes one order; show the audit log; stop ERPNext for a moment and show the retry | Partly (webhook, keys and audit log exist) |
| 9 | Safe by default (bonus) | `python -m app sync <contact>` as a dry run, then `--apply`: a new contractor becomes an ERPNext customer | Yes |

## Closing line (10 s)

"One safe hand-off between the CRM and the ERP, from the first quote to the last payment: stock
checked before a promise, credit checked before shipping, and no re-typing."

## Notes

- Scene 9 and parts of scene 8 can be recorded now; re-record the whole video once scenes 2 to 7
  exist.
- Marking a deal Won already reaches OrderBridge through the webhook and makes sure the customer
  exists (see [`ghl-webhook-setup.md`](ghl-webhook-setup.md)); the order itself is a later step.
