from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ERPNextCreditLimit(BaseModel):
    # ERPNext sends many fields we do not need; ignore them.
    model_config = ConfigDict(extra="ignore")

    company: str
    credit_limit: Decimal


class ERPNextCustomer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    customer_type: str | None = None
    credit_limits: list[ERPNextCreditLimit] = Field(default_factory=list)
