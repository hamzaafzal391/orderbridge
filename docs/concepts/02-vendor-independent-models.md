# 02. Vendor-independent models

**In one line:** OrderBridge has its own definition of a "customer", separate from how any vendor
describes one.

## The idea

A company uses one internal language even though customers write to it in many languages. Each
vendor describes the same customer differently, so we keep our own form and translate into it.

```
ERPNext:       {"customer_name": ..., "credit_limits": [{"credit_limit": 50000}]}
GoHighLevel:   {"firstName": ..., "companyName": ..., "email": ...}
OrderBridge:   Customer(name=..., customer_type=..., email=..., credit_limits=[...])
```

## Tiny example

```python
class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)  # cannot be changed after it is created

    name: str
    customer_type: str | None = None
    email: str | None = None
    credit_limits: list[CreditLimit] = Field(default_factory=list)
```

## In OrderBridge

- Ours: [`app/models.py`](../../app/models.py). It knows nothing about any vendor.
- ERPNext's shape: [`app/clients/erpnext_models.py`](../../app/clients/erpnext_models.py). GoHighLevel's:
  [`app/clients/ghl_models.py`](../../app/clients/ghl_models.py).
- Frozen models mean one part of the code cannot quietly change data another part is using.
- A vendor's field `credit_limit` becomes our `amount`: our words, not theirs.

## Check yourself

*Why is `Customer` in `app/models.py` but `ERPNextCustomer` in the clients folder?*

Model answer: the folder shows who owns the shape: `models.py` is ours and never changes because a
vendor changes; the clients folder holds vendor shapes that change when the vendor does.
