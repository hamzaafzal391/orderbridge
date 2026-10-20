# 01. Adapters and translators

**In one line:** an adapter is code that talks to one outside system and hides its quirks behind a
simple, standard shape.

## The idea

A travel plug adapter lets your charger work in any country. The charger never changes; only the
adapter does. In OrderBridge, GoHighLevel and ERPNext each speak their own "language" (their own
field names, errors and rules). A client class translates each one into our language, so the rest
of the app never needs to know which system it is talking to.

## Tiny example

```python
customer = ghl_client.get_contact("abc123")  # GoHighLevel's words in...
customer = erpnext_client.get_customer("Acme")  # ERPNext's words in...
# ...and either way you get OrderBridge's own Customer out.
```

## In OrderBridge

- [`app/clients/ghl.py`](../../app/clients/ghl.py) and
  [`app/clients/erpnext.py`](../../app/clients/erpnext.py) are the two adapters.
- Each has a private `_to_customer` function: the one place that knows both vocabularies.
- Business logic lives in [`app/services/`](../../app/services/) and never imports a vendor client.
- Adding HubSpot or Odoo later means writing one new adapter (planned, not built).

## Check yourself

*Why would replacing ERPNext with a different ERP only touch one file?*

Model answer: because only the ERPNext client knows ERPNext's shapes; everything else uses our own
`Customer`.
