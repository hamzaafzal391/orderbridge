# 04. Validation with Pydantic

**In one line:** check data the moment it arrives, so bad data fails loudly and early instead of
causing a strange bug later.

## The idea

A security check at the airport: everything is inspected at the door, and once you are inside you
can trust it. Pydantic is that check for data.

## Tiny example

```python
class ERPNextCustomer(BaseModel):
    name: str  # required
    customer_type: str | None = None
    credit_limits: list[ERPNextCreditLimit] = Field(default_factory=list)
```

- A reply with no `name`, or a credit limit that is not a number, is rejected.
- Extra fields ERPNext sends that we do not list are ignored (`extra="ignore"`).
- Money is a `Decimal`, because floats can drift (`0.1 + 0.2` is not exactly `0.3`).

## In OrderBridge

- Each client validates the vendor's reply, then converts it to `Customer`
  ([`erpnext.py`](../../app/clients/erpnext.py), [`ghl.py`](../../app/clients/ghl.py)).
- A failure becomes `ERPNextResponseError` or `GHLResponseError`.
- The error message names the **field and the kind of problem** (for example
  `credit_limits.0.credit_limit: decimal_parsing`), never the value, because values can be
  customer data. A test checks this.
- Settings are validated too ([`app/config.py`](../../app/config.py)); secrets use `SecretStr` so
  they never show up when printed.

## Check yourself

*Why do error messages show field names but not values?*

Model answer: messages end up in logs and alerts many people can read, and values may be
customer data or secrets; the field name is enough to debug.
