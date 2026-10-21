"""The quote-requested endpoint: authentication, validation, answers and status codes."""

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import ConfigurationError, create_app
from app.clients.erpnext_errors import ERPNextRateLimitError, ERPNextTemporaryError
from app.clients.ghl_errors import GHLAuthenticationError, GHLTemporaryError
from app.config import Settings
from app.db.models import Base
from app.db.repository import Repository
from app.db.session import make_engine, make_sessionmaker
from app.models import Deal, StockLevel

SECRET = "a-long-shared-secret-for-tests"
URL = "/webhooks/ghl/quote-requested"
PIPELINE = "pipe1"
AUDIT_KEY = "availability:opp-1"


class FakeCRM:
    def __init__(self, deal: Deal | None = None) -> None:
        self.deal = deal or Deal(
            id="opp-1",
            status="open",
            pipeline_id=PIPELINE,
            sku="AC-5TON-RTU",
            quantity=Decimal(4),
            warehouse="Dallas Warehouse - MAS",
        )
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None
        self.written: list[tuple[str, str]] = []

    def get_deal(self, opportunity_id: str) -> Deal:
        if self.read_error:
            raise self.read_error
        return self.deal

    def set_availability_note(self, opportunity_id: str, note: str) -> None:
        if self.write_error:
            raise self.write_error
        self.written.append((opportunity_id, note))


class FakeERP:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.asked = 0

    def get_stock(self, sku: str) -> list[StockLevel]:
        self.asked += 1
        if self.error:
            raise self.error
        return [
            StockLevel(warehouse="Dallas Warehouse - MAS", on_hand=Decimal(7), reserved=Decimal(1))
        ]


class FakeWorld:
    def __init__(self) -> None:
        self.crm = FakeCRM()
        self.erp = FakeERP()
        self.opened = 0
        self.closed = 0

    @contextmanager
    def __call__(self):
        self.opened += 1
        try:
            yield self.crm, self.erp
        finally:
            self.closed += 1


def make_settings(**overrides: object) -> Settings:
    values = {
        "erpnext_base_url": "http://erpnext.test",
        "erpnext_api_key": "test-key",
        "erpnext_api_secret": "test-secret",
        "ghl_api_token": "test-ghl-token",
        "webhook_secret": SECRET,
        "ghl_pipeline_id": PIPELINE,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    engine = make_engine(f"sqlite:///{tmp_path / 'quote.db'}")
    Base.metadata.create_all(engine)
    return Repository(make_sessionmaker(engine), stale_after=timedelta(minutes=10))


@pytest.fixture
def world() -> FakeWorld:
    return FakeWorld()


@pytest.fixture
def client(repo: Repository, world: FakeWorld) -> TestClient:
    return TestClient(create_app(make_settings(), repository=repo, clients=world))


def post(client: TestClient, body: object = None, secret: str | None = SECRET):
    headers = {"X-Webhook-Secret": secret} if secret is not None else {}
    return client.post(
        URL, json={"opportunity_id": "opp-1"} if body is None else body, headers=headers
    )


# --- startup ------------------------------------------------------------------------------


def test_the_server_refuses_to_start_without_a_pipeline(repo: Repository) -> None:
    with pytest.raises(ConfigurationError, match="ghl_pipeline_id"):
        create_app(make_settings(ghl_pipeline_id=None), repository=repo)


def test_an_empty_pipeline_setting_is_also_refused(repo: Repository) -> None:
    with pytest.raises(ConfigurationError, match="ghl_pipeline_id"):
        create_app(make_settings(ghl_pipeline_id=""), repository=repo)


# --- authentication and validation -----------------------------------------------------------


@pytest.mark.parametrize("secret", [None, "", "wrong", SECRET + "x"])
def test_a_wrong_or_missing_secret_is_unauthorized_and_does_nothing(
    client: TestClient, world: FakeWorld, secret: str | None
) -> None:
    response = post(client, secret=secret)
    assert response.status_code == 401
    assert world.opened == 0
    assert world.crm.written == []


@pytest.mark.parametrize(
    "body", [{}, {"opportunity_id": ""}, {"opportunity_id": "  "}, {"opportunity_id": 5}, []]
)
def test_an_invalid_message_is_rejected_without_work(
    client: TestClient, world: FakeWorld, body: object
) -> None:
    assert post(client, body).status_code == 422
    assert world.opened == 0


def test_extra_fields_in_the_message_are_ignored(client: TestClient, world: FakeWorld) -> None:
    body = {"opportunity_id": "opp-1", "sku": "HACKED", "quantity": 999}
    assert post(client, body).status_code == 200
    assert world.crm.written[0][1].startswith("OK:")  # the deal's data was used, not the message's


# --- answers ----------------------------------------------------------------------------------


def test_a_quote_request_writes_the_answer_and_reports_it(
    client: TestClient, world: FakeWorld
) -> None:
    response = post(client)

    assert response.status_code == 200
    assert response.json() == {
        "status": "available",
        "message": "OK: 6 available in Dallas Warehouse - MAS (need 4)",
        "written": True,
    }
    assert world.crm.written == [("opp-1", "OK: 6 available in Dallas Warehouse - MAS (need 4)")]


def test_asking_again_gives_a_fresh_answer_each_time(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    for _ in range(3):
        assert post(client).status_code == 200
    assert world.erp.asked == 3
    assert len(world.crm.written) == 3
    assert len(repo.list_audit(AUDIT_KEY)) == 3


def test_a_deal_in_another_pipeline_is_answered_200_and_nothing_is_written(
    client: TestClient, world: FakeWorld
) -> None:
    world.crm.deal = world.crm.deal.model_copy(update={"pipeline_id": "other"})
    response = post(client)

    assert response.status_code == 200  # 200, so GoHighLevel does not retry
    assert response.json() == {"status": "wrong_pipeline", "message": None, "written": False}
    assert world.crm.written == [] and world.erp.asked == 0


def test_an_incomplete_deal_is_answered_200_and_the_rep_is_told(
    client: TestClient, world: FakeWorld
) -> None:
    world.crm.deal = world.crm.deal.model_copy(update={"sku": None})
    body = post(client).json()

    assert body["status"] == "incomplete_deal"
    assert world.crm.written == [("opp-1", "CANNOT CHECK: the deal needs SKU.")]


# --- failures ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error", [GHLTemporaryError("down"), ERPNextTemporaryError("down")], ids=["crm", "erp"]
)
def test_a_temporary_failure_answers_503(
    client: TestClient, world: FakeWorld, error: Exception
) -> None:
    world.crm.read_error = error if isinstance(error, GHLTemporaryError) else None
    world.erp.error = error if isinstance(error, ERPNextTemporaryError) else None

    response = post(client)
    assert response.status_code == 503
    assert world.crm.written == []


def test_a_rate_limit_answers_503_with_retry_after(client: TestClient, world: FakeWorld) -> None:
    world.erp.error = ERPNextRateLimitError("slow down", retry_after=2.2)
    response = post(client)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "3"


def test_a_missing_write_permission_answers_a_generic_500_and_is_audited(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    world.crm.write_error = GHLAuthenticationError(
        "Bearer test-ghl-token rejected", status_code=403
    )
    response = post(client)

    assert response.status_code == 500
    assert response.json() == {"detail": "processing failed; see the audit log"}
    assert "test-ghl-token" not in response.text
    (entry,) = repo.list_audit(AUDIT_KEY)
    assert entry.outcome == "GHLAuthenticationError"


def test_answers_and_audit_never_contain_customer_data_or_secrets(
    client: TestClient, world: FakeWorld, repo: Repository
) -> None:
    world.crm.read_error = RuntimeError("jordan.lee@northstar.example.test " + SECRET)
    response = post(client)

    assert response.status_code == 500
    assert "jordan" not in response.text and SECRET not in response.text
    assert "jordan" not in str(repo.list_audit(AUDIT_KEY))


def test_clients_are_closed_after_every_request_even_on_failure(
    client: TestClient, world: FakeWorld
) -> None:
    post(client)
    world.crm.read_error = GHLTemporaryError("down")
    post(client)
    assert world.opened == world.closed == 2


def test_the_audit_log_holds_ids_and_results_only(client: TestClient, repo: Repository) -> None:
    post(client)
    (entry,) = repo.list_audit(AUDIT_KEY)
    assert (entry.action, entry.outcome) == ("availability", "available")
    assert entry.detail == {"opportunity_id": "opp-1", "apply": True}
