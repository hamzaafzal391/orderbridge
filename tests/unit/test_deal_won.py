from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.clients.erpnext_errors import ERPNextPartialWriteError, ERPNextTemporaryError
from app.clients.ghl_errors import GHLNotFoundError
from app.db.models import Base
from app.db.repository import Repository
from app.db.session import make_engine, make_sessionmaker
from app.models import Customer
from app.services.deal_won import DealWonEvent, handle_deal_won, idempotency_key

EVENT = DealWonEvent(opportunity_id="opp-1", contact_id="contact-1")
KEY = "ghl:opportunity-won:opp-1"


class FakeContacts:
    def __init__(self, customer: Customer | None = None, error: Exception | None = None) -> None:
        self.customer = customer or crm()
        self.error = error
        self.looked_up: list[str] = []

    def get_contact(self, contact_id: str) -> Customer:
        self.looked_up.append(contact_id)
        if self.error:
            raise self.error
        return self.customer


class FakeERP:
    def __init__(
        self,
        existing: list[Customer] | None = None,
        create_result: Customer | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self.existing = existing or []
        self.create_result = create_result
        self.create_error = create_error
        self.created_from: list[Customer] = []

    def find_customers_by_email(self, email: str) -> list[Customer]:
        return self.existing

    def create_customer(self, customer: Customer) -> Customer | None:
        self.created_from.append(customer)
        if self.create_error:
            raise self.create_error
        return self.create_result


def crm(email: str | None = "sam@example.com") -> Customer:
    return Customer(name="Sam Rivera", customer_type="Individual", email=email)


def erp_customer(name: str) -> Customer:
    return Customer(name=name, customer_type="Company", email="sam@example.com")


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return Repository(make_sessionmaker(engine), stale_after=timedelta(minutes=10))


def state(repo: Repository):
    found = repo.get_state(KEY)
    assert found is not None
    return found


# --- the message ---------------------------------------------------------------------------


def test_the_idempotency_key_is_per_deal() -> None:
    assert idempotency_key("opp-1") == "ghl:opportunity-won:opp-1"
    assert idempotency_key("opp-1") != idempotency_key("opp-2")


def test_ids_are_trimmed_and_extra_fields_ignored() -> None:
    event = DealWonEvent.model_validate(
        {"opportunity_id": "  opp-9 ", "contact_id": "c9", "email": "x@example.com", "x": 1}
    )

    assert (event.opportunity_id, event.contact_id) == ("opp-9", "c9")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"opportunity_id": "o"},
        {"contact_id": "c"},
        {"opportunity_id": "", "contact_id": "c"},
        {"opportunity_id": "   ", "contact_id": "c"},
        {"opportunity_id": "o" * 201, "contact_id": "c"},
        {"opportunity_id": 123, "contact_id": "c"},
        {"opportunity_id": None, "contact_id": "c"},
    ],
)
def test_invalid_messages_are_rejected(body: dict) -> None:
    with pytest.raises(ValidationError):
        DealWonEvent.model_validate(body)


# --- normal outcomes -----------------------------------------------------------------------


def test_a_new_customer_is_created_and_the_key_succeeds(repo: Repository) -> None:
    erp = FakeERP(create_result=erp_customer("Sam Rivera"))

    result = handle_deal_won(EVENT, repo, FakeContacts(), erp)

    assert (result.status, result.idempotency) == ("created", "claimed")
    assert len(erp.created_from) == 1
    assert state(repo).status == "succeeded"
    assert state(repo).result == {"sync_status": "created"}


def test_an_existing_customer_succeeds_without_writing(repo: Repository) -> None:
    erp = FakeERP(existing=[erp_customer("Acme")])

    result = handle_deal_won(EVENT, repo, FakeContacts(), erp)

    assert result.status == "already_matched"
    assert erp.created_from == []
    assert state(repo).status == "succeeded"


@pytest.mark.parametrize(
    ("status", "contacts", "erp"),
    [
        ("no_email", FakeContacts(crm(None)), FakeERP()),
        ("ambiguous", FakeContacts(), FakeERP(existing=[erp_customer("A"), erp_customer("B")])),
        ("name_conflict", FakeContacts(), FakeERP(create_result=None)),
    ],
)
def test_outcomes_that_need_a_person_are_recorded_as_failed(
    repo: Repository, status: str, contacts: FakeContacts, erp: FakeERP
) -> None:
    result = handle_deal_won(EVENT, repo, contacts, erp)

    assert result.status == status
    assert state(repo).status == "failed"
    assert state(repo).result == {"error": f"needs_review:{status}"}


def test_a_needs_review_deal_can_be_replayed_after_the_data_is_fixed(repo: Repository) -> None:
    handle_deal_won(EVENT, repo, FakeContacts(crm(None)), FakeERP())  # no email: needs a person

    fixed = handle_deal_won(
        EVENT, repo, FakeContacts(crm("sam@example.com")), FakeERP(existing=[erp_customer("Acme")])
    )

    assert (fixed.status, fixed.idempotency) == ("already_matched", "reclaimed")
    assert state(repo).status == "succeeded"


# --- repeats and races ---------------------------------------------------------------------


def test_the_same_deal_twice_does_the_work_once(repo: Repository) -> None:
    erp = FakeERP(create_result=erp_customer("Sam Rivera"))
    contacts = FakeContacts()

    first = handle_deal_won(EVENT, repo, contacts, erp)
    second = handle_deal_won(EVENT, repo, contacts, erp)

    assert (first.status, second.status) == ("created", "duplicate")
    assert second.idempotency == "duplicate"
    assert len(erp.created_from) == 1
    assert contacts.looked_up == ["contact-1"]  # the second message did not even look it up


def test_a_deal_being_processed_elsewhere_is_left_alone(repo: Repository) -> None:
    repo.claim(KEY)  # another worker owns it right now
    erp = FakeERP(create_result=erp_customer("Sam Rivera"))
    contacts = FakeContacts()

    result = handle_deal_won(EVENT, repo, contacts, erp)

    assert (result.status, result.idempotency) == ("in_progress", "in_progress")
    assert contacts.looked_up == []
    assert erp.created_from == []


def test_different_deals_are_independent(repo: Repository) -> None:
    erp = FakeERP(create_result=erp_customer("Sam Rivera"))

    one = handle_deal_won(
        DealWonEvent(opportunity_id="a", contact_id="c"), repo, FakeContacts(), erp
    )
    two = handle_deal_won(
        DealWonEvent(opportunity_id="b", contact_id="c"), repo, FakeContacts(), erp
    )

    assert (one.idempotency, two.idempotency) == ("claimed", "claimed")


# --- failures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ERPNextTemporaryError("down"),
        ERPNextPartialWriteError("half done"),
        GHLNotFoundError("gone"),
        RuntimeError("a bug"),
    ],
    ids=["temporary", "partial-write", "crm-not-found", "unexpected"],
)
def test_a_failure_marks_the_key_failed_and_is_raised(repo: Repository, error: Exception) -> None:
    contacts = FakeContacts(error=error)

    with pytest.raises(type(error)):
        handle_deal_won(EVENT, repo, contacts, FakeERP())

    assert state(repo).status == "failed"
    assert state(repo).result == {"error": type(error).__name__}
    assert [e.outcome for e in repo.list_audit(KEY)] == ["claimed", type(error).__name__]


def test_a_failed_deal_succeeds_when_replayed(repo: Repository) -> None:
    with pytest.raises(ERPNextTemporaryError):
        handle_deal_won(
            EVENT, repo, FakeContacts(), FakeERP(create_error=ERPNextTemporaryError("x"))
        )

    retry = handle_deal_won(EVENT, repo, FakeContacts(), FakeERP(create_result=erp_customer("Sam")))

    assert (retry.status, retry.idempotency) == ("created", "reclaimed")
    assert state(repo).status == "succeeded"
    assert state(repo).attempts == 2


# --- the audit trail -----------------------------------------------------------------------


def test_the_audit_log_records_the_steps_with_ids_only(repo: Repository) -> None:
    handle_deal_won(EVENT, repo, FakeContacts(), FakeERP(create_result=erp_customer("Sam Rivera")))

    entries = repo.list_audit(KEY)

    assert [(e.action, e.outcome) for e in entries] == [("webhook", "claimed"), ("sync", "created")]
    for entry in entries:
        assert entry.detail == {"opportunity_id": "opp-1", "contact_id": "contact-1"}
        assert "sam@example.com" not in str(entry.detail)
        assert "Sam Rivera" not in str(entry.detail)


def test_duplicates_are_audited_too(repo: Repository) -> None:
    erp = FakeERP(existing=[erp_customer("Acme")])
    handle_deal_won(EVENT, repo, FakeContacts(), erp)
    handle_deal_won(EVENT, repo, FakeContacts(), erp)

    outcomes = [(e.action, e.outcome) for e in repo.list_audit(KEY)]

    assert outcomes == [
        ("webhook", "claimed"),
        ("sync", "already_matched"),
        ("webhook", "duplicate"),
    ]
