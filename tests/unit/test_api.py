from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import ConfigurationError, create_app
from app.clients.erpnext_errors import (
    ERPNextAuthenticationError,
    ERPNextPartialWriteError,
    ERPNextRateLimitError,
    ERPNextTemporaryError,
)
from app.clients.ghl_errors import GHLTemporaryError
from app.config import Settings
from app.db.models import Base
from app.db.repository import Repository
from app.db.session import make_engine, make_sessionmaker
from app.models import Customer

SECRET = "a-long-shared-secret-for-tests"
URL = "/webhooks/ghl/deal-won"
BODY = {"opportunity_id": "opp-1", "contact_id": "contact-1"}
KEY = "ghl:opportunity-won:opp-1"


class FakeContacts:
    def __init__(
        self, error: Exception | None = None, email: str | None = "sam@example.com"
    ) -> None:
        self.error = error
        self.email = email

    def get_contact(self, contact_id: str) -> Customer:
        if self.error:
            raise self.error
        return Customer(name="Sam Rivera", customer_type="Individual", email=self.email)


class FakeERP:
    def __init__(self, existing: list[Customer] | None = None) -> None:
        self.existing = existing or []
        self.create_calls = 0
        self.create_error: Exception | None = None

    def find_customers_by_email(self, email: str) -> list[Customer]:
        return self.existing

    def create_customer(self, customer: Customer) -> Customer | None:
        self.create_calls += 1
        if self.create_error:
            raise self.create_error
        return customer


class FakeWorld:
    """Stands in for the two real clients and counts how often they are opened and closed."""

    def __init__(self, contacts: FakeContacts | None = None, erp: FakeERP | None = None) -> None:
        self.contacts = contacts or FakeContacts()
        self.erp = erp or FakeERP()
        self.opened = 0
        self.closed = 0

    @contextmanager
    def __call__(self):
        self.opened += 1
        try:
            yield self.contacts, self.erp
        finally:
            self.closed += 1


def make_settings(**overrides: object) -> Settings:
    values = {
        "erpnext_base_url": "http://erpnext.test",
        "erpnext_api_key": "test-key",
        "erpnext_api_secret": "test-secret",
        "ghl_api_token": "test-ghl-token",
        "webhook_secret": SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    engine = make_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    return Repository(make_sessionmaker(engine), stale_after=timedelta(minutes=10))


@pytest.fixture
def world() -> FakeWorld:
    return FakeWorld()


@pytest.fixture
def client(repo: Repository, world: FakeWorld) -> TestClient:
    return TestClient(create_app(make_settings(), repository=repo, clients=world))


def post(client: TestClient, body: object = BODY, secret: str | None = SECRET):
    headers = {"X-Webhook-Secret": secret} if secret is not None else {}
    return client.post(URL, json=body, headers=headers)


# --- health and startup --------------------------------------------------------------------


def test_health_needs_no_secret(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_documentation_pages_are_not_exposed(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("secret", [None, "", "short-secret"])
def test_the_server_refuses_to_start_without_a_strong_secret(
    secret: str | None, repo: Repository
) -> None:
    with pytest.raises(ConfigurationError, match="webhook_secret"):
        create_app(make_settings(webhook_secret=secret), repository=repo)


def test_the_server_refuses_to_start_without_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="database_url"):
        create_app(make_settings())


def test_a_startup_error_never_contains_the_secret(repo: Repository) -> None:
    with pytest.raises(ConfigurationError) as error:
        create_app(make_settings(webhook_secret="tiny"), repository=repo)

    assert "tiny" not in str(error.value)


# --- authentication ------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, "", "wrong-secret", SECRET + "x", SECRET[:-1]])
def test_a_wrong_or_missing_secret_is_unauthorized_and_changes_nothing(
    client: TestClient, repo: Repository, world: FakeWorld, secret: str | None
) -> None:
    response = post(client, secret=secret)

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}
    assert repo.get_state(KEY) is None  # no key claimed
    assert repo.list_audit(KEY) == []  # nothing recorded
    assert world.opened == 0  # no client even opened


def test_a_bad_secret_hides_validation_details(client: TestClient) -> None:
    response = post(client, body={"nonsense": True}, secret="wrong-secret")

    assert response.status_code == 401  # strangers learn nothing about the message format


def test_the_secret_never_appears_in_any_answer(client: TestClient, world: FakeWorld) -> None:
    answers = [
        post(client),
        post(client, secret="wrong"),
        post(client, body={"bad": 1}),
    ]

    for response in answers:
        assert SECRET not in response.text


# --- validation ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"opportunity_id": "o"},
        {"opportunity_id": "", "contact_id": "c"},
        {"opportunity_id": "o" * 201, "contact_id": "c"},
        {"opportunity_id": 123, "contact_id": "c"},
    ],
)
def test_an_invalid_message_is_rejected_without_work(
    client: TestClient, world: FakeWorld, body: dict
) -> None:
    response = post(client, body=body)

    assert response.status_code == 422
    assert world.opened == 0


def test_extra_fields_in_the_message_are_ignored(client: TestClient) -> None:
    body = {**BODY, "email": "x@example.com", "anything": "else"}

    assert post(client, body=body).status_code == 200


def test_a_body_that_is_not_json_is_rejected(client: TestClient) -> None:
    response = client.post(URL, content=b"not json", headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 422


# --- normal outcomes -----------------------------------------------------------------------


def test_a_new_deal_creates_the_customer(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    response = post(client)

    assert response.status_code == 200
    assert response.json() == {"status": "created", "idempotency": "claimed"}
    assert world.erp.create_calls == 1
    assert repo.get_state(KEY).status == "succeeded"  # type: ignore[union-attr]


def test_an_existing_customer_is_reported(client: TestClient, world: FakeWorld) -> None:
    world.erp.existing = [Customer(name="Acme", email="sam@example.com")]

    response = post(client)

    assert response.json() == {"status": "already_matched", "idempotency": "claimed"}
    assert world.erp.create_calls == 0


def test_the_same_message_twice_creates_one_customer(client: TestClient, world: FakeWorld) -> None:
    first = post(client)
    second = post(client)

    assert first.json() == {"status": "created", "idempotency": "claimed"}
    assert second.json() == {"status": "duplicate", "idempotency": "duplicate"}
    assert world.erp.create_calls == 1


def test_a_deal_being_processed_elsewhere_is_left_alone(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    repo.claim(KEY)

    response = post(client)

    assert response.status_code == 200
    assert response.json() == {"status": "in_progress", "idempotency": "in_progress"}
    assert world.opened == 1
    assert world.erp.create_calls == 0


def test_needs_review_outcomes_answer_200_so_the_caller_does_not_retry(
    repo: Repository,
) -> None:
    world = FakeWorld(contacts=FakeContacts(email=None))
    client = TestClient(create_app(make_settings(), repository=repo, clients=world))

    response = post(client)

    assert response.status_code == 200
    assert response.json()["status"] == "no_email"
    assert repo.get_state(KEY).result == {"error": "needs_review:no_email"}  # type: ignore[union-attr]


# --- failures ------------------------------------------------------------------------------


def test_a_temporary_failure_answers_503_and_can_be_replayed(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    world.erp.create_error = ERPNextTemporaryError("ERPNext is down")

    failed = post(client)
    world.erp.create_error = None
    replay = post(client)

    assert failed.status_code == 503
    assert failed.json() == {"detail": "temporarily unavailable"}
    assert "Retry-After" not in failed.headers
    assert replay.status_code == 200
    assert replay.json() == {"status": "created", "idempotency": "reclaimed"}
    assert repo.get_state(KEY).attempts == 2  # type: ignore[union-attr]


def test_a_rate_limit_answers_503_with_retry_after(client: TestClient, world: FakeWorld) -> None:
    world.erp.create_error = ERPNextRateLimitError("slow down", status_code=429, retry_after=2.5)

    response = post(client)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "3"


def test_a_crm_outage_answers_503(repo: Repository) -> None:
    world = FakeWorld(contacts=FakeContacts(error=GHLTemporaryError("down")))
    client = TestClient(create_app(make_settings(), repository=repo, clients=world))

    assert post(client).status_code == 503


@pytest.mark.parametrize(
    "error",
    [
        ERPNextAuthenticationError("bad credentials", status_code=401),
        ERPNextPartialWriteError("customer created, contact not"),
        RuntimeError("a bug"),
    ],
    ids=["auth", "partial-write", "unexpected"],
)
def test_other_failures_answer_a_generic_500(
    client: TestClient, world: FakeWorld, repo: Repository, error: Exception
) -> None:
    world.erp.create_error = error

    response = post(client)

    assert response.status_code == 500
    assert response.json() == {"detail": "processing failed; see the audit log"}
    assert repo.get_state(KEY).result == {"error": type(error).__name__}  # type: ignore[union-attr]


def test_answers_never_contain_customer_data_or_error_text(
    client: TestClient, world: FakeWorld
) -> None:
    world.erp.create_error = ERPNextPartialWriteError("Sam Rivera sam@example.com secret detail")
    answers = [post(client)]
    world.erp.create_error = None
    answers += [post(client), post(client)]

    for response in answers:
        assert "Sam Rivera" not in response.text
        assert "sam@example.com" not in response.text
        assert "secret detail" not in response.text


# --- resources and audit -------------------------------------------------------------------


def test_clients_are_closed_after_every_request(client: TestClient, world: FakeWorld) -> None:
    post(client)
    world.erp.create_error = ERPNextTemporaryError("down")
    post(client, body={"opportunity_id": "opp-2", "contact_id": "c2"})

    assert world.opened == 2
    assert world.closed == 2


def test_each_request_is_recorded_in_the_audit_log(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    post(client)
    post(client)

    assert [(e.action, e.outcome) for e in repo.list_audit(KEY)] == [
        ("webhook", "claimed"),
        ("sync", "created"),
        ("webhook", "duplicate"),
    ]
