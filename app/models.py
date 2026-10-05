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
    credit_limits: list[CreditLimit] = Field(default_factory=list)
