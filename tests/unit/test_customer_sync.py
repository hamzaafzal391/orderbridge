import pytest
from pydantic import ValidationError

from app.clients.erpnext_errors import ERPNextPartialWriteError, ERPNextTemporaryError
from app.clients.ghl_errors import GHLNotFoundError
from app.models import Customer
from app.services.customer_sync import sync_contact


class FakeContacts:
    def __init__(self, customer: Customer | None = None, error: Exception | None = None) -> None:
        self.customer = customer
        self.error = error

    def get_contact(self, contact_id: str) -> Customer:
        if self.error:
            raise self.error
        assert self.customer is not None
        return self.customer


class FakeERP:
    """Fake ERP: `existing` is what an email search finds; `create_result` is what a create returns."""

    def __init__(
        self,
        existing: list[Customer] | None = None,
        create_result: Customer | None = None,
        find_error: Exception | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self.existing = existing or []
        self.create_result = create_result
        self.find_error = find_error
        self.create_error = create_error
        self.created_from: list[Customer] = []

    def find_customers_by_email(self, email: str) -> list[Customer]:
        if self.find_error:
            raise self.find_error
        return self.existing

    def create_customer(self, customer: Customer) -> Customer | None:
        self.created_from.append(customer)
        if self.create_error:
            raise self.create_error
        return self.create_result


def crm(email: str | None = "sam@example.com") -> Customer:
    return Customer(name="Sam Rivera", customer_type="Individual", email=email)


def erp(name: str) -> Customer:
    return Customer(name=name, customer_type="Company", email="sam@example.com")


def test_already_matched_writes_nothing() -> None:
    erp_side = FakeERP(existing=[erp("Acme")])

    result = sync_contact("c1", FakeContacts(crm()), erp_side)

    assert result.status == "already_matched"
    assert [customer.name for customer in result.erp_customers] == ["Acme"]
    assert erp_side.created_from == []


def test_no_match_creates_the_customer_exactly_once() -> None:
    created = Customer(name="Sam Rivera", customer_type="Individual", email="sam@example.com")
    erp_side = FakeERP(create_result=created)

    result = sync_contact("c1", FakeContacts(crm()), erp_side)

    assert result.status == "created"
    assert result.erp_customers == [created]
    assert erp_side.created_from == [crm()]


def test_name_conflict_when_the_name_is_already_taken() -> None:
    erp_side = FakeERP(create_result=None)

    result = sync_contact("c1", FakeContacts(crm()), erp_side)

    assert result.status == "name_conflict"
    assert result.erp_customers == []
    assert len(erp_side.created_from) == 1


def test_dry_run_reports_would_create_and_writes_nothing() -> None:
    erp_side = FakeERP(create_result=erp("Sam Rivera"))

    result = sync_contact("c1", FakeContacts(crm()), erp_side, dry_run=True)

    assert result.status == "would_create"
    assert erp_side.created_from == []


@pytest.mark.parametrize("dry_run", [False, True])
def test_no_email_never_writes(dry_run: bool) -> None:
    erp_side = FakeERP(create_result=erp("Sam Rivera"))

    result = sync_contact("c1", FakeContacts(crm(None)), erp_side, dry_run=dry_run)

    assert result.status == "no_email"
    assert erp_side.created_from == []


@pytest.mark.parametrize("dry_run", [False, True])
def test_ambiguous_never_writes(dry_run: bool) -> None:
    erp_side = FakeERP(existing=[erp("Acme"), erp("Acme 2")], create_result=erp("x"))

    result = sync_contact("c1", FakeContacts(crm()), erp_side, dry_run=dry_run)

    assert result.status == "ambiguous"
    assert [customer.name for customer in result.erp_customers] == ["Acme", "Acme 2"]
    assert erp_side.created_from == []


def test_crm_errors_propagate_and_nothing_is_written() -> None:
    erp_side = FakeERP()

    with pytest.raises(GHLNotFoundError):
        sync_contact("c1", FakeContacts(error=GHLNotFoundError("nope")), erp_side)

    assert erp_side.created_from == []


def test_search_errors_propagate_and_nothing_is_written() -> None:
    erp_side = FakeERP(find_error=ERPNextTemporaryError("down"))

    with pytest.raises(ERPNextTemporaryError):
        sync_contact("c1", FakeContacts(crm()), erp_side)

    assert erp_side.created_from == []


def test_create_errors_propagate() -> None:
    erp_side = FakeERP(create_error=ERPNextPartialWriteError("half done"))

    with pytest.raises(ERPNextPartialWriteError):
        sync_contact("c1", FakeContacts(crm()), erp_side)


def test_result_is_immutable() -> None:
    result = sync_contact("c1", FakeContacts(crm()), FakeERP(existing=[erp("Acme")]))

    with pytest.raises(ValidationError):
        result.status = "created"  # type: ignore[misc]
