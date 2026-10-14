"""Business logic: make sure a CRM contact has a matching ERP customer.

Vendor-neutral like customer_matching: it only needs the capabilities in the protocols below.
It writes at most once, and only when matching proves there is no customer yet.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models import Customer
from app.services.customer_matching import ContactSource, CustomerFinder, match_contact


class CustomerCreator(Protocol):
    """Anything that can create an ERP customer (e.g. ERPNextClient)."""

    def create_customer(self, customer: Customer) -> Customer | None:
        """Return the created customer, or None if that name is already taken (nothing changed)."""
        ...


class ERPCustomers(CustomerFinder, CustomerCreator, Protocol):
    """An ERP that can both search and create customers."""


class SyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    # already_matched: exactly one ERP customer already has this email; nothing written
    # created:         no match, so a customer was created in the ERP
    # would_create:    no match; a real run would create one (dry run, nothing written)
    # no_email:        the CRM contact has no email; nothing written
    # ambiguous:       several ERP customers share the email; nothing written
    # name_conflict:   no email match, but an ERP customer with the same name exists;
    #                  nothing written, a person must decide
    status: Literal[
        "already_matched", "created", "would_create", "no_email", "ambiguous", "name_conflict"
    ]
    crm_customer: Customer
    erp_customers: list[Customer] = Field(default_factory=list)


def sync_contact(
    contact_id: str,
    contacts: ContactSource,
    customers: ERPCustomers,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Create the ERP customer for a CRM contact if, and only if, it does not exist yet.

    Errors from the clients propagate; the caller decides what to do. With dry_run=True
    nothing is ever written.
    """
    match = match_contact(contact_id, contacts, customers)

    if match.status == "matched":
        return SyncResult(
            status="already_matched",
            crm_customer=match.crm_customer,
            erp_customers=match.erp_customers,
        )
    if match.status in ("no_email", "ambiguous"):
        return SyncResult(
            status=match.status,
            crm_customer=match.crm_customer,
            erp_customers=match.erp_customers,
        )

    # status == "no_match": the only case where a write is allowed.
    if dry_run:
        return SyncResult(status="would_create", crm_customer=match.crm_customer)

    created = customers.create_customer(match.crm_customer)
    if created is None:
        return SyncResult(status="name_conflict", crm_customer=match.crm_customer)
    return SyncResult(status="created", crm_customer=match.crm_customer, erp_customers=[created])
