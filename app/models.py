"""OrderBridge's own data shapes.

Nothing in this file may know about a specific vendor (ERPNext, GoHighLevel, ...).
Vendor clients convert their own shapes into these.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CreditLimit(BaseModel):
    model_config = ConfigDict(frozen=True)

    company: str
    amount: Decimal


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    customer_type: str | None = None
    email: str | None = None
    credit_limits: list[CreditLimit] = Field(default_factory=list)


class StockLevel(BaseModel):
    """How much of one item sits in one warehouse.

    `reserved` is stock promised to submitted orders. Draft orders reserve nothing.
    """

    model_config = ConfigDict(frozen=True)

    warehouse: str
    on_hand: Decimal
    reserved: Decimal

    @property
    def available(self) -> Decimal:
        """What could still be promised to a new customer. Negative means oversold."""
        return self.on_hand - self.reserved


class Deal(BaseModel):
    """One sale in the CRM: one equipment line for one contact.

    The equipment fields are optional because a rep may not have filled them in yet (and the
    price is only agreed later). Deciding whether a deal is complete enough is business logic,
    so it happens in the services, not in the CRM client.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    contact_id: str | None = None
    status: str
    pipeline_id: str
    sku: str | None = None
    quantity: Decimal | None = None
    warehouse: str | None = None
    unit_price: Decimal | None = None
