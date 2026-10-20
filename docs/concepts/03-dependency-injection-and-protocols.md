# 03. Dependency injection and protocols

**In one line:** a function receives the helpers it needs as inputs, instead of creating them
itself, so they can be swapped.

## The idea

A coffee machine that takes any pod versus one that only takes one brand. If the helpers are
handed in, you can use real ones in production and fake ones in tests, with no change to the
function.

## Tiny example

```python
# Receives its helpers: anything with the right method will do.
def match_contact(contact_id, contacts, customers): ...


# The locked-in alternative (harder to swap, harder to test):
def match_contact(contact_id):
    ghl = GHLClient()
    erp = ERPNextClient()
```

A **protocol** says what a helper must be able to do, without saying what it is:

```python
class ContactSource(Protocol):
    def get_contact(self, contact_id: str) -> Customer: ...
```

Anything with a matching `get_contact` fits, with no inheritance needed.

## In OrderBridge

- [`app/services/customer_matching.py`](../../app/services/customer_matching.py) defines the
  protocols; [`customer_sync.py`](../../app/services/customer_sync.py) builds on them.
- The clients also accept an injected `httpx.Client`, which is how tests plug in a fake server.
- [`tests/unit/test_customer_sync.py`](../../tests/unit/test_customer_sync.py) uses tiny fake
  classes, with no network involved.

## Check yourself

*Why does `match_contact` take `contacts` and `customers` as inputs?*

Model answer: so the real clients, other systems or test fakes can be plugged in without changing
the function.
