# ADR 0002: Match CRM contacts to ERP customers by email, and never guess

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

OrderBridge must decide whether a GoHighLevel contact already exists as an ERPNext customer.
The two systems share no ID. Names are unreliable: typos, trading names and duplicates are
common. A wrong match is worse than no match, because later features (order sync) would
attach data to the wrong customer.

## Decision

- Match on **email**, compared case-insensitively after trimming whitespace.
- The service returns one of four explicit results instead of picking the "best" one:

| Result | Meaning |
|---|---|
| `matched` | exactly one ERP customer has this email |
| `no_match` | none do (including ERP customers with no email on file) |
| `no_email` | the CRM contact has no email, so matching is impossible |
| `ambiguous` | several ERP customers share the email; a human must decide |

- The service is **read-only** and depends on two small protocols (`ContactSource`,
  `CustomerFinder`), not on the vendor clients, so either system can be replaced.
- Errors from the clients propagate unchanged; the caller decides about retries.

## Consequences

- ERPNext keeps emails on Contact records that link to customers. The lookup searches contacts
  by email (any email on the contact, case-insensitive), follows each contact's links to
  customers, and loads each distinct customer once. The "primary contact" flag is not required.
  Contacts that are not linked to a customer are ignored. A customer with no linked contact
  carrying the email reports `no_match`: possibly a false "no match", never a wrong match.
- Correction (2026-10-13): the first version filtered `Customer.email_id`. A live check against
  ERPNext v16 showed that field stays empty unless the customer's separate "Customer Primary
  Contact" link is set, so real customers were missed. The lookup was changed to search
  contacts and verified live.
- The lookup costs one contact search, one read per matching contact, and one read per distinct
  customer (each usually one request).
- Creating missing customers is deliberately out of scope: it needs idempotency and duplicate
  handling designed first.
- A stored GoHighLevel contact ID on the ERPNext customer would be more robust long term, and
  can replace or complement email matching later.
