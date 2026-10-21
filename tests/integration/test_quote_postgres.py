"""The availability check against a real PostgreSQL: the same quote request many times at once.

Unlike "deal won", this check has no idempotency key: every request must be answered and audited,
and none may be blocked or fail. The CRM and ERP are fakes (no live services).
"""

from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from helpers import WORKERS, race
from sqlalchemy import Engine, text

from app.api import create_app
from app.config import Settings
from app.db.repository import Repository
from app.db.session import make_sessionmaker
from app.models import Deal, StockLevel

pytestmark = pytest.mark.integration

SECRET = "a-long-shared-secret-for-tests"
URL = "/webhooks/ghl/quote-requested"
AUDIT_KEY = "availability:opp-race"


class FakeCRM:
    def get_deal(self, opportunity_id: str) -> Deal:
        return Deal(
            id=opportunity_id,
            status="open",
            pipeline_id="pipe1",
            sku="AC-5TON-RTU",
            quantity=Decimal(4),
            warehouse="Dallas Warehouse - MAS",
        )

    def set_availability_note(self, opportunity_id: str, note: str) -> None:
        pass


class FakeERP:
    def get_stock(self, sku: str) -> list[StockLevel]:
        return [
            StockLevel(warehouse="Dallas Warehouse - MAS", on_hand=Decimal(7), reserved=Decimal(1))
        ]


@pytest.fixture
def app_and_repo(engine: Engine):
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE audit_log, object_links, idempotency_keys RESTART IDENTITY")
        )

    @contextmanager
    def clients():
        yield FakeCRM(), FakeERP()

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
        ghl_api_token="test-ghl-token",
        webhook_secret=SECRET,
        ghl_pipeline_id="pipe1",
    )
    repo = Repository(make_sessionmaker(engine))
    return create_app(settings, repository=repo, clients=clients), repo


def send(application):
    with TestClient(application) as client:
        return client.post(
            URL, json={"opportunity_id": "opp-race"}, headers={"X-Webhook-Secret": SECRET}
        )


def test_many_simultaneous_requests_are_all_answered_and_all_audited(app_and_repo) -> None:
    application, repo = app_and_repo
    responses = race(lambda _: send(application))

    assert {response.status_code for response in responses} == {200}
    assert {response.json()["status"] for response in responses} == {"available"}
    assert len(repo.list_audit(AUDIT_KEY)) == WORKERS
    assert repo.status_of(AUDIT_KEY) is None  # no idempotency key was ever created
