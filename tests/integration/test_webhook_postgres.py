"""The webhook against a real PostgreSQL: the same message many times at the same instant.

The CRM and ERP are fakes (no live services), but the database is real, so this proves the
idempotency key really stops duplicate work when messages race.
"""

import threading
import time
from collections import Counter
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from helpers import WORKERS, race
from sqlalchemy import Engine, text

from app.api import create_app
from app.config import Settings
from app.db.repository import Repository
from app.db.session import make_sessionmaker
from app.models import Customer

pytestmark = pytest.mark.integration

SECRET = "a-long-shared-secret-for-tests"
URL = "/webhooks/ghl/deal-won"


class SlowFakeERP:
    """An ERP whose create takes a moment, so racing messages overlap."""

    def __init__(self) -> None:
        self.create_calls = 0
        self._lock = threading.Lock()

    def find_customers_by_email(self, email: str) -> list[Customer]:
        return []

    def create_customer(self, customer: Customer) -> Customer | None:
        with self._lock:
            self.create_calls += 1
        time.sleep(0.3)
        return customer


class FakeContacts:
    def get_contact(self, contact_id: str) -> Customer:
        return Customer(name="Sam Rivera", customer_type="Individual", email="sam@example.com")


@pytest.fixture
def erp() -> SlowFakeERP:
    return SlowFakeERP()


@pytest.fixture
def app(engine: Engine, erp: SlowFakeERP):
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE audit_log, object_links, idempotency_keys RESTART IDENTITY")
        )

    @contextmanager
    def clients():
        yield FakeContacts(), erp

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


def send(app_and_repo, opportunity_id: str):
    application, _ = app_and_repo
    with TestClient(application) as client:
        return client.post(
            URL,
            json={"opportunity_id": opportunity_id, "contact_id": "contact-1"},
            headers={"X-Webhook-Secret": SECRET},
        )


def test_the_same_deal_sent_many_times_at_once_creates_one_customer(app, erp: SlowFakeERP) -> None:
    responses = race(lambda _: send(app, "opp-race"))

    assert {response.status_code for response in responses} == {200}
    outcomes = Counter(response.json()["idempotency"] for response in responses)
    assert outcomes["claimed"] == 1  # exactly one message did the work
    assert outcomes["claimed"] + outcomes["in_progress"] + outcomes["duplicate"] == WORKERS
    assert erp.create_calls == 1  # and so exactly one customer was created


def test_a_message_after_the_work_finished_is_a_duplicate(app, erp: SlowFakeERP) -> None:
    race(lambda _: send(app, "opp-late"))

    late = send(app, "opp-late")

    assert late.json() == {"status": "duplicate", "idempotency": "duplicate"}
    assert erp.create_calls == 1


def test_different_deals_at_once_are_all_processed(app, erp: SlowFakeERP) -> None:
    responses = race(lambda index: send(app, f"opp-{index}"))

    assert all(response.json()["idempotency"] == "claimed" for response in responses)
    assert erp.create_calls == WORKERS
