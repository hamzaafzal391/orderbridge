# GoHighLevel setup for the HVAC demo

What to create in GoHighLevel so that a won deal carries an equipment line (SKU, quantity, agreed
unit price, delivery warehouse). This is done in the GoHighLevel screens; nothing here needs code.

You are using an account that already holds real pipelines. Everything below therefore lives in
**its own pipeline** with **its own custom fields**, all named with a `MetroAir` prefix, and the
workflow is limited to that pipeline. Existing pipelines, deals and fields are never touched.

> Names, companies, emails and amounts are fictional demo data.

## 1. The pipeline

Settings, then Pipelines, then Create new pipeline.

- **Name:** `MetroAir Orders`
- **Stages, in this order:** Quote sent, Negotiation, Order placed, Credit hold, Shipped, Invoiced, Paid

"Won" is not a stage: GoHighLevel keeps it as the deal's **status** (Open, Won, Lost, Abandoned).
Later steps move the deal through Order placed, Credit hold, Shipped, Invoiced and Paid.

## 2. Custom fields for deals

Settings, then Custom Fields, then Add Custom Field. For each one choose the object
**Opportunities** (not Contacts).

| Name (exactly) | Type | Options / notes |
|---|---|---|
| `MetroAir SKU` | Dropdown (single) | `AC-5TON-RTU`, `THERMOSTAT-WIFI` |
| `MetroAir Quantity` | Number | |
| `MetroAir Unit Price` | Monetary (or Number) | the agreed price per unit, in USD |
| `MetroAir Warehouse` | Dropdown (single) | `Dallas Warehouse - MAS`, `Houston Warehouse - MAS` |
| `MetroAir ERP order number` | **Text (single line)**, not Number | left empty; a later step writes `SAL-ORD-...` into it |
| `MetroAir Availability` | Text (multi-line, if offered) | left empty; OrderBridge writes the stock answer here |

Type the option values exactly as shown: they must match the ERPNext item and warehouse names.
GoHighLevel generates a key for each field (something like `opportunity.metroair_sku`); I will read
the real keys from the API afterwards, so you do not need to copy them.

## 3. Demo contacts

Contacts, then Add Contact. Matching works on the **email**, so these emails matter.

| Contact | Company name | Email | Why |
|---|---|---|---|
| Jordan Lee | NorthStar Mechanical LLC | `jordan.lee@northstar.example.test` | an existing ERPNext customer with a $50,000 credit limit |
| Maya Patel | BluePeak Facilities LLC | `maya.patel@example.test` | an existing ERPNext customer with a $5,000 credit limit |
| Dana Ortiz | Lone Star Air Systems LLC | `dana.ortiz@lonestarair.example.test` | a brand-new contractor: OrderBridge creates its ERPNext customer |

**One change in ERPNext, so your own email stays out of the demo video:** open the contact
`Jordan Lee-NorthStar Mechanical LLC` (Selling, then Contacts) and change its email to
`jordan.lee@northstar.example.test`. Right now it holds a personal address.

## 4. Demo deals

Opportunities, then Add Opportunity, in the `MetroAir Orders` pipeline, stage **Quote sent**,
status **Open**. Fill the custom fields and set the deal value to quantity times unit price.

| Deal name | Contact | SKU | Quantity | Unit price | Warehouse | Value |
|---|---|---|---|---|---|---|
| NorthStar: 4 rooftop units | Jordan Lee | AC-5TON-RTU | 4 | 4200 | Dallas Warehouse - MAS | 16,800 |
| BluePeak: 4 rooftop units | Maya Patel | AC-5TON-RTU | 4 | 4200 | Dallas Warehouse - MAS | 16,800 |
| Lone Star: 10 thermostats | Dana Ortiz | THERMOSTAT-WIFI | 10 | 95 | Houston Warehouse - MAS | 950 |

Do **not** mark any of them Won yet: that is what triggers the workflow.

What the demo uses them for: NorthStar is within its credit limit, BluePeak is well over its
$5,000 limit (the credit hold, a later step), and Lone Star is a new customer.

## 5. Let the integration write to deals

OrderBridge writes the stock answer onto the deal, so the Private Integration token needs the
permission to **edit opportunities**, not only read them. In Settings, then Private Integrations,
open your integration and add the opportunity write permission (often labelled "Edit Opportunities").
Keep the read permissions you already have. I will confirm it with one harmless write to a demo deal.

## 6. The two workflows (after the code is ready)

Do this step only when I tell you the matching code is merged. It is described here so you know what
is coming.

**Workflow A, "quote requested" (the availability check):**
- **Triggers:** Pipeline Stage Changed to **Quote Sent**, and Opportunity Created, both filtered to
  the pipeline **`MetroAir Orders`**.
- **Action:** Webhook to `/webhooks/ghl/quote-requested`. The body carries only the opportunity id.

**Workflow B, "deal won" (the order):**
- **Trigger:** Opportunity Status Changed, with the filters **Pipeline is `MetroAir Orders`** and
  **Status is Won**.
- **Action:** Webhook to `/webhooks/ghl/deal-won`, as in [`ghl-webhook-setup.md`](ghl-webhook-setup.md).

The pipeline filter is what keeps your real pipelines out of both. OrderBridge also checks the
pipeline on its own side, and it reads the deal itself from GoHighLevel, so a message cannot change
the SKU, quantity or price.

## 7. Tell me when it is done

Reply with "setup done". I will then check, read-only through the API, that the pipeline, the six
fields and the three deals exist, and note their real ids and keys. I will not change anything in
GoHighLevel.

## Checklist

- [ ] Pipeline `MetroAir Orders` with 7 stages
- [ ] 6 opportunity custom fields (order number as Text)
- [ ] The token can edit opportunities
- [ ] 3 demo contacts with the emails above
- [ ] ERPNext contact `Jordan Lee-NorthStar Mechanical LLC` has the demo email
- [ ] 3 demo deals, all still Open
- [ ] For the video: show only the `MetroAir Orders` pipeline
