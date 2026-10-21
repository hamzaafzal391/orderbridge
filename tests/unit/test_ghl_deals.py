"""GoHighLevel client: reading a deal and writing one field back.

The fake server below answers in the shape the real account returned (checked read-only):
a deal names its custom fields by id and leaves out fields that were never filled in.
"""

import json

import httpx
import pytest

from app.clients.ghl import AVAILABILITY_FIELD, GHLClient
from app.clients.ghl_errors import (
    GHLAuthenticationError,
    GHLNotFoundError,
    GHLResponseError,
    GHLTemporaryError,
)
from app.config import Settings
from app.models import Deal
from app.retry import RetryPolicy

LOCATION = "loc1"
FIELD_IDS = {
    "opportunity.metroair_sku": "f-sku",
    "opportunity.metroair_quantity": "f-qty",
    "opportunity.metroair_warehouse": "f-wh",
    "opportunity.metroair_unit_price": "f-price",
    "opportunity.metroair_availability": "f-avail",
    "opportunity.metroair_erp_order_number": "f-order",
}
FULL_VALUES = [
    {"id": "f-qty", "fieldValue": 4},
    {"id": "f-sku", "fieldValue": "AC-5TON-RTU"},
    {"id": "f-wh", "fieldValue": "Dallas Warehouse - MAS"},
    {"id": "f-price", "fieldValue": 4200},
]
NO_RETRY = RetryPolicy(max_attempts=1)


def opportunity(custom_fields: object = FULL_VALUES, **overrides: object) -> dict:
    body = {
        "id": "opp1",
        "locationId": LOCATION,
        "pipelineId": "pipe1",
        "pipelineStageId": "stage1",
        "status": "open",
        "contactId": "contact1",
        "monetaryValue": 16800,
        "customFields": custom_fields,
        "contact": {"id": "contact1", "name": "Jordan Lee"},  # ignored extra data
    }
    body.update(overrides)
    return body


class FakeGHL:
    """A fake GoHighLevel that records what it was asked and can be told to misbehave."""

    def __init__(self, deal: dict | None = None, field_ids: dict[str, str] | None = None) -> None:
        self.deal = opportunity() if deal is None else deal
        self.field_ids = FIELD_IDS if field_ids is None else field_ids
        self.requests: list[httpx.Request] = []
        self.put_failures: list[int] = []  # statuses to answer with before succeeding
        self.get_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.startswith("/locations/"):
            definitions = [{"id": i, "fieldKey": k, "name": k} for k, i in self.field_ids.items()]
            return httpx.Response(200, json={"customFields": definitions})
        if request.method == "PUT":
            if self.put_failures:
                return httpx.Response(self.put_failures.pop(0), json={"message": "secret body"})
            return httpx.Response(200, json={"opportunity": self.deal})
        if self.get_status != 200:
            return httpx.Response(self.get_status, json={"message": "secret body"})
        return httpx.Response(200, json={"opportunity": self.deal, "traceId": "t"})

    def calls(self, method: str, path_start: str) -> list[httpx.Request]:
        return [
            r for r in self.requests if r.method == method and r.url.path.startswith(path_start)
        ]


def make_client(fake: FakeGHL, retry_policy: RetryPolicy = NO_RETRY) -> GHLClient:
    settings = Settings(
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
        ghl_api_token="test-ghl-token",
        ghl_base_url="http://ghl.test",
    )
    http_client = httpx.Client(transport=httpx.MockTransport(fake))
    return GHLClient(settings=settings, http_client=http_client, retry_policy=retry_policy)


# --- get_deal -----------------------------------------------------------------------------


def test_get_deal_reads_the_deal_and_its_equipment_line() -> None:
    fake = FakeGHL()
    deal = make_client(fake).get_deal("opp1")

    assert deal == Deal(
        id="opp1",
        contact_id="contact1",
        status="open",
        pipeline_id="pipe1",
        sku="AC-5TON-RTU",
        quantity=4,
        warehouse="Dallas Warehouse - MAS",
        unit_price=4200,
    )
    request = fake.calls("GET", "/opportunities/")[0]
    assert request.url.path == "/opportunities/opp1"
    assert request.headers["Authorization"] == "Bearer test-ghl-token"
    assert request.headers["Version"] == "2021-07-28"
    assert fake.calls("GET", "/locations/")[0].url.params["model"] == "opportunity"


def test_get_deal_encodes_the_id_in_the_url() -> None:
    fake = FakeGHL()
    make_client(fake).get_deal("a/b")
    assert fake.calls("GET", "/opportunities/")[0].url.raw_path == b"/opportunities/a%2Fb"


def test_fields_that_were_never_filled_in_are_none() -> None:
    # GoHighLevel leaves them out entirely: no id, no null.
    fake = FakeGHL(opportunity([{"id": "f-qty", "fieldValue": 4}]))
    deal = make_client(fake).get_deal("opp1")

    assert deal.quantity == 4
    assert deal.sku is None
    assert deal.warehouse is None
    assert deal.unit_price is None


@pytest.mark.parametrize("custom_fields", [None, []])
def test_a_deal_with_no_custom_field_values_is_still_readable(custom_fields: object) -> None:
    deal = make_client(FakeGHL(opportunity(custom_fields))).get_deal("opp1")
    assert deal.sku is None and deal.quantity is None


def test_a_deal_without_a_contact_is_readable() -> None:
    body = opportunity()
    del body["contactId"]
    assert make_client(FakeGHL(body)).get_deal("opp1").contact_id is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4, 4), (4.0, 4), (2.5, 2.5), ("12", 12), (" 7 ", 7), ("", None)],
)
def test_numbers_are_read_as_decimals(value: object, expected: object) -> None:
    fields = [{"id": "f-qty", "fieldValue": value}]
    assert make_client(FakeGHL(opportunity(fields))).get_deal("opp1").quantity == expected


@pytest.mark.parametrize("value", ["four", True, "NaN", "Infinity"])
def test_a_number_field_that_is_not_a_number_is_a_response_error(value: object) -> None:
    fields = [{"id": "f-qty", "fieldValue": value}]
    with pytest.raises(GHLResponseError) as caught:
        make_client(FakeGHL(opportunity(fields))).get_deal("opp1")
    assert not caught.value.retryable
    assert str(value) not in str(caught.value)


def test_a_text_field_with_a_number_in_it_is_a_response_error() -> None:
    fields = [{"id": "f-sku", "fieldValue": 12345}]
    with pytest.raises(GHLResponseError):
        make_client(FakeGHL(opportunity(fields))).get_deal("opp1")


def test_blank_text_counts_as_not_filled_in() -> None:
    fields = [{"id": "f-sku", "fieldValue": "   "}]
    assert make_client(FakeGHL(opportunity(fields))).get_deal("opp1").sku is None


def test_a_renamed_or_deleted_field_fails_loudly() -> None:
    ids = {k: v for k, v in FIELD_IDS.items() if k != "opportunity.metroair_warehouse"}
    with pytest.raises(GHLResponseError, match="metroair_warehouse"):
        make_client(FakeGHL(field_ids=ids)).get_deal("opp1")


def test_field_ids_are_looked_up_once_per_client() -> None:
    fake = FakeGHL()
    client = make_client(fake)
    client.get_deal("opp1")
    client.get_deal("opp1")
    assert len(fake.calls("GET", "/locations/")) == 1


def test_an_unknown_deal_is_not_found() -> None:
    fake = FakeGHL()
    fake.get_status = 404
    with pytest.raises(GHLNotFoundError):
        make_client(fake).get_deal("nope")


def test_a_deal_missing_required_data_is_a_response_error_without_values() -> None:
    body = opportunity()
    del body["pipelineId"]
    with pytest.raises(GHLResponseError, match="pipelineId") as caught:
        make_client(FakeGHL(body)).get_deal("opp1")
    assert "Jordan" not in str(caught.value)


@pytest.mark.parametrize("payload", [{"unexpected": 1}, ["a list"], "text"])
def test_a_response_that_is_not_a_deal_is_a_response_error(payload: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = GHLClient(make_client(FakeGHL()).settings, http_client, NO_RETRY)
    with pytest.raises(GHLResponseError):
        client.get_deal("opp1")


def test_reading_a_deal_is_retried_on_a_temporary_error() -> None:
    calls = {"count": 0}
    fake = FakeGHL()

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/opportunities/opp1":
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(503)
        return fake(request)

    client = make_client(fake, RetryPolicy(max_attempts=2, sleep=lambda _: None))
    client.http_client = httpx.Client(transport=httpx.MockTransport(flaky))
    assert client.get_deal("opp1").sku == "AC-5TON-RTU"
    assert calls["count"] == 2


# --- set_deal_field -----------------------------------------------------------------------


def test_set_deal_field_sends_only_that_field() -> None:
    fake = FakeGHL()
    make_client(fake).set_deal_field("opp1", AVAILABILITY_FIELD, "OK: 6 available")

    (put,) = fake.calls("PUT", "/opportunities/")
    assert put.url.path == "/opportunities/opp1"
    assert put.headers["Authorization"] == "Bearer test-ghl-token"
    assert json.loads(put.content) == {
        "customFields": [{"id": "f-avail", "fieldValue": "OK: 6 available"}]
    }


def test_an_unknown_field_is_refused_before_anything_is_written() -> None:
    fake = FakeGHL()
    with pytest.raises(GHLResponseError):
        make_client(fake).set_deal_field("opp1", "opportunity.not_a_field", "x")
    assert fake.calls("PUT", "/") == []


def test_writing_to_a_deal_that_is_missing_fields_fails_before_writing() -> None:
    ids = {k: v for k, v in FIELD_IDS.items() if k != AVAILABILITY_FIELD}
    fake = FakeGHL(field_ids=ids)
    with pytest.raises(GHLResponseError, match="metroair_availability"):
        make_client(fake).set_deal_field("opp1", AVAILABILITY_FIELD, "x")
    assert fake.calls("PUT", "/") == []


def test_the_idempotent_field_write_is_retried_on_a_temporary_error() -> None:
    fake = FakeGHL()
    fake.put_failures = [503, 502]
    sleeps: list[float] = []
    policy = RetryPolicy(max_attempts=3, sleep=sleeps.append, jitter=lambda delay: delay)

    make_client(fake, policy).set_deal_field("opp1", AVAILABILITY_FIELD, "OK")

    assert len(fake.calls("PUT", "/opportunities/")) == 3
    assert len(sleeps) == 2


def test_the_field_write_gives_up_after_the_last_attempt() -> None:
    fake = FakeGHL()
    fake.put_failures = [503, 503, 503, 503]
    policy = RetryPolicy(max_attempts=3, sleep=lambda _: None)

    with pytest.raises(GHLTemporaryError):
        make_client(fake, policy).set_deal_field("opp1", AVAILABILITY_FIELD, "OK")
    assert len(fake.calls("PUT", "/opportunities/")) == 3


@pytest.mark.parametrize("status", [401, 403])
def test_a_missing_write_permission_is_an_authentication_error_and_not_retried(
    status: int,
) -> None:
    fake = FakeGHL()
    fake.put_failures = [status, status]
    policy = RetryPolicy(max_attempts=3, sleep=lambda _: None)

    with pytest.raises(GHLAuthenticationError) as caught:
        make_client(fake, policy).set_deal_field("opp1", AVAILABILITY_FIELD, "OK")
    assert len(fake.calls("PUT", "/opportunities/")) == 1
    assert "secret body" not in str(caught.value)
    assert "test-ghl-token" not in str(caught.value)
