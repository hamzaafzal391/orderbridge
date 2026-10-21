# ADR 0005: Target scenario: an HVAC equipment distributor

- **Status:** Accepted
- **Date:** 2026-10-21

## Context

An integration is easiest to judge, build and demonstrate against one concrete business problem.
The ERPNext instance used for development already contains an HVAC distribution setup: the company
"MetroAir Supply" with Dallas and Houston warehouses, items such as a 5-ton rooftop AC unit and a
Wi-Fi thermostat, contractor customers with credit limits ($50,000 and $5,000), and orders in
different stages of delivery and billing.

HVAC distributors sell expensive equipment on credit to contractors. Three problems recur: orders
are re-typed from the CRM into the ERP, credit risk is discovered after a delivery promise is made,
and sales staff keep asking whether an order has shipped or been paid.

## Decision

The target flow is:

1. A deal is marked Won in GoHighLevel.
2. OrderBridge makes sure the customer exists in ERPNext (built).
3. It checks the customer's credit limit, counting open orders and unpaid invoices. Within the
   limit it creates the Sales Order and writes the order number back to the CRM. Over the limit it
   saves a draft order, flags a credit hold in the CRM and alerts finance.
4. As the order is shipped, invoiced, paid or goes overdue in ERPNext, the CRM opportunity stage
   is updated.

**What a deal carries (version 1):** one equipment line, supplied through GoHighLevel custom
fields: equipment SKU, quantity, agreed unit price (negotiated, so it comes from the CRM) and
delivery warehouse.

**Who owns what:** the ERP owns order, delivery and payment status; the CRM owns the sales
relationship and the deal. A field has one owner, so a change is never copied back and forth.

**Out of scope for version 1:** multi-line orders, stock reservation, pricing rules and discounts,
returns and credit notes, and any CRM other than GoHighLevel or ERP other than ERPNext.

## Consequences

- Features are chosen by the story: the credit-limit hold is the headline, because it is a rule that
  only exists once the two systems are connected.
- Both directions need to remember "this deal became that order" and must not process an event
  twice, so a database for idempotency keys, object links and an audit log comes first
  (planned, next).
- Status updates from the ERP to the CRM need a loop guard, so an update we write does not trigger
  the opposite direction again.
- The scenario is a demonstration choice, not a claim about any real company; all names and
  amounts are fictional.
