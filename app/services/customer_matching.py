"""Business logic: find the ERP customer that corresponds to a CRM contact.

This module knows nothing about GoHighLevel or ERPNext. It only needs two capabilities,
described by the protocols below; the vendor clients happen to provide them.
Read-only: it never creates or changes anything.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models import Customer


class ContactSource(Protocol):
    """Anything that can load a CRM contact as a Customer (e.g. GHLClient)."""

    def get_contact(self, contact_id: str) -> Customer: ...


class CustomerFinder(Protocol):
    """Anything that can find ERP customers by email (e.g. ERPNextClient)."""

    def find_customers_by_email(self, email: str) -> list[Customer]: ...


class MatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    # matched:   exactly one ERP customer has this email
    # no_match:  none do (this includes ERP customers with no email on file)
    # no_email:  the CRM contact has no email, so matching is impossible
    # ambiguous: several ERP customers share this email; we never pick one
    status: Literal["matched", "no_match", "no_email", "ambiguous"]
    crm_customer: Customer
    erp_customers: list[Customer] = Field(default_factory=list)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def match_contact(
    contact_id: str, contacts: ContactSource, customers: CustomerFinder
) -> MatchResult:
    """Look up a CRM contact and report which ERP customer, if any, shares its email.

    Errors from the clients (GHLError, ERPNextError) are not caught here; the caller
    decides whether to retry or alert.
    """
    crm_customer = contacts.get_contact(contact_id)

    email = normalize_email(crm_customer.email or "")
    if not email:
        return MatchResult(status="no_email", crm_customer=crm_customer)

    found = customers.find_customers_by_email(email)
    if not found:
        return MatchResult(status="no_match", crm_customer=crm_customer)
    if len(found) > 1:
        return MatchResult(status="ambiguous", crm_customer=crm_customer, erp_customers=found)
    return MatchResult(status="matched", crm_customer=crm_customer, erp_customers=found)
