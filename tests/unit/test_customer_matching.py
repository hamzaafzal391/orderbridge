import pytest
from pydantic import ValidationError

from app.clients.erpnext_errors import ERPNextTemporaryError
from app.clients.ghl_errors import GHLNotFoundError
from app.models import Customer
from app.services.customer_matching import match_contact


class FakeContacts:
    def __init__(self, customer: Customer | None = None, error: Exception | None = None) -> None:
        self.customer = customer
        self.error = error

    def get_contact(self, contact_id: str) -> Customer:
        if self.error:
            raise self.error
        assert self.customer is not None
        return self.customer


class FakeFinder:
    def __init__(self, found: list[Customer] | None = None, error: Exception | None = None) -> None:
        self.found = found or []
        self.error = error
        self.searched_emails: list[str] = []

    def find_customers_by_email(self, email: str) -> list[Customer]:
        self.searched_emails.append(email)
        if self.error:
            raise self.error
        return self.found


def crm(email: str | None = "sam@example.com") -> Customer:
    return Customer(name="Sam Rivera", customer_type="Individual", email=email)


def erp(name: str) -> Customer:
    return Customer(name=name, customer_type="Company", email="sam@example.com")


def test_matched_when_exactly_one_erp_customer_has_the_email() -> None:
    result = match_contact("c1", FakeContacts(crm()), FakeFinder([erp("Acme")]))

    assert result.status == "matched"
    assert [customer.name for customer in result.erp_customers] == ["Acme"]
    assert result.crm_customer.name == "Sam Rivera"


def test_no_match_when_no_erp_customer_has_the_email() -> None:
    result = match_contact("c1", FakeContacts(crm()), FakeFinder([]))

    assert result.status == "no_match"
    assert result.erp_customers == []


def test_ambiguous_when_several_erp_customers_share_the_email() -> None:
    result = match_contact("c1", FakeContacts(crm()), FakeFinder([erp("Acme"), erp("Acme 2")]))

    assert result.status == "ambiguous"
    assert [customer.name for customer in result.erp_customers] == ["Acme", "Acme 2"]


@pytest.mark.parametrize("email", [None, "", "   "])
def test_no_email_skips_the_erp_search(email: str | None) -> None:
    finder = FakeFinder([erp("Acme")])

    result = match_contact("c1", FakeContacts(crm(email)), finder)

    assert result.status == "no_email"
    assert finder.searched_emails == []


def test_email_is_normalized_before_searching() -> None:
    finder = FakeFinder([erp("Acme")])

    match_contact("c1", FakeContacts(crm("  Sam@Example.COM ")), finder)

    assert finder.searched_emails == ["sam@example.com"]


def test_crm_errors_propagate() -> None:
    with pytest.raises(GHLNotFoundError):
        match_contact("c1", FakeContacts(error=GHLNotFoundError("nope")), FakeFinder())


def test_erp_errors_propagate() -> None:
    finder = FakeFinder(error=ERPNextTemporaryError("down"))

    with pytest.raises(ERPNextTemporaryError):
        match_contact("c1", FakeContacts(crm()), finder)


def test_result_is_immutable() -> None:
    result = match_contact("c1", FakeContacts(crm()), FakeFinder([]))

    with pytest.raises(ValidationError):
        result.status = "matched"  # type: ignore[misc]
