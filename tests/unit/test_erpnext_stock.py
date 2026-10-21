"""ERPNext client: reading stock. The fake answers in the shape the real ERPNext returned."""

import json
from decimal import Decimal

import httpx
import pytest

from app.clients.erpnext import ERPNextClient
from app.clients.erpnext_errors import (
    ERPNextAuthenticationError,
    ERPNextNotFoundError,
    ERPNextResponseError,
    ERPNextTemporaryError,
)
from app.config import Settings
from app.models import StockLevel
from app.retry import RetryPolicy

NO_RETRY = RetryPolicy(max_attempts=1)

DALLAS = {
    "warehouse": "Dallas Warehouse - MAS",
    "actual_qty": 7.0,
    "reserved_qty": 1.0,
}
HOUSTON = {
    "warehouse": "Houston Warehouse - MAS",
    "actual_qty": 7.0,
    "reserved_qty": 0.0,
}


class FakeERPNext:
    """Answers the Bin (stock) and Item questions the client asks, and records them."""

    def __init__(self, bins: object, items: object | None = None) -> None:
        self.bins = bins
        self.items = [{"name": "ANY"}] if items is None else items
        self.requests: list[httpx.Request] = []
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"exception": "secret details"})
        if request.url.path == "/api/resource/Bin":
            return httpx.Response(200, json={"data": self.bins})
        if request.url.path == "/api/resource/Item":
            return httpx.Response(200, json={"data": self.items})
        return httpx.Response(404)


def make_client(handler: object, retry_policy: RetryPolicy = NO_RETRY) -> ERPNextClient:
    settings = Settings(
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
        ghl_api_token="test-ghl-token",
    )
    http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return ERPNextClient(settings=settings, http_client=http_client, retry_policy=retry_policy)


def test_stock_is_read_per_warehouse_and_available_is_on_hand_minus_reserved() -> None:
    fake = FakeERPNext([DALLAS, HOUSTON])
    levels = make_client(fake).get_stock("AC-5TON-RTU")

    assert levels == [
        StockLevel(warehouse="Dallas Warehouse - MAS", on_hand=Decimal(7), reserved=Decimal(1)),
        StockLevel(warehouse="Houston Warehouse - MAS", on_hand=Decimal(7), reserved=Decimal(0)),
    ]
    assert [level.available for level in levels] == [6, 7]


def test_the_request_asks_for_that_item_with_the_credentials() -> None:
    fake = FakeERPNext([DALLAS])
    make_client(fake).get_stock("AC-5TON-RTU")

    (request,) = fake.requests  # stock was found, so no second question about the item
    assert request.url.path == "/api/resource/Bin"
    assert request.headers["Authorization"] == "token test-key:test-secret"
    assert json.loads(request.url.params["filters"]) == [["item_code", "=", "AC-5TON-RTU"]]
    assert request.url.params["limit_page_length"] == "100"


def test_an_awkward_sku_is_sent_safely_inside_the_filter() -> None:
    sku = 'A&B "C" =?/'
    fake = FakeERPNext([DALLAS])
    make_client(fake).get_stock(sku)
    assert json.loads(fake.requests[0].url.params["filters"]) == [["item_code", "=", sku]]


def test_warehouses_come_back_sorted_by_name() -> None:
    levels = make_client(FakeERPNext([HOUSTON, DALLAS])).get_stock("X")
    assert [level.warehouse for level in levels] == [
        "Dallas Warehouse - MAS",
        "Houston Warehouse - MAS",
    ]


def test_missing_quantities_count_as_zero() -> None:
    rows = [{"warehouse": "Dallas Warehouse - MAS", "actual_qty": None}]
    (level,) = make_client(FakeERPNext(rows)).get_stock("X")
    assert (level.on_hand, level.reserved, level.available) == (0, 0, 0)


def test_fractions_stay_exact() -> None:
    rows = [{"warehouse": "W", "actual_qty": 2.5, "reserved_qty": 0.1}]
    (level,) = make_client(FakeERPNext(rows)).get_stock("X")
    assert level.available == Decimal("2.4")


def test_oversold_stock_is_negative_not_hidden() -> None:
    rows = [{"warehouse": "W", "actual_qty": 2, "reserved_qty": 5}]
    (level,) = make_client(FakeERPNext(rows)).get_stock("X")
    assert level.available == -3


def test_an_item_that_exists_but_was_never_stocked_has_no_levels() -> None:
    fake = FakeERPNext([], items=[{"name": "NEW-ITEM"}])
    assert make_client(fake).get_stock("NEW-ITEM") == []
    assert fake.requests[1].url.path == "/api/resource/Item"
    assert json.loads(fake.requests[1].url.params["filters"]) == [["name", "=", "NEW-ITEM"]]


def test_an_unknown_item_is_not_found_rather_than_out_of_stock() -> None:
    with pytest.raises(ERPNextNotFoundError) as caught:
        make_client(FakeERPNext([], items=[])).get_stock("NOPE")
    assert not caught.value.retryable


@pytest.mark.parametrize(
    "bins",
    [
        {"not": "a list"},
        [{"actual_qty": 1}],  # no warehouse
        [{"warehouse": "W", "actual_qty": "lots"}],
        ["text"],
    ],
)
def test_malformed_stock_is_a_response_error_without_values(bins: object) -> None:
    with pytest.raises(ERPNextResponseError) as caught:
        make_client(FakeERPNext(bins)).get_stock("X")
    assert "lots" not in str(caught.value)


def test_a_response_without_data_is_a_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(ERPNextResponseError):
        make_client(handler).get_stock("X")


def test_a_rejected_key_is_an_authentication_error() -> None:
    fake = FakeERPNext([DALLAS])
    fake.status = 403
    with pytest.raises(ERPNextAuthenticationError) as caught:
        make_client(fake).get_stock("X")
    assert "secret details" not in str(caught.value)


def test_reading_stock_is_retried_on_a_temporary_error() -> None:
    fake = FakeERPNext([DALLAS])
    answers = [503, 200]

    def flaky(request: httpx.Request) -> httpx.Response:
        if answers and request.url.path == "/api/resource/Bin":
            status = answers.pop(0)
            if status != 200:
                return httpx.Response(status)
        return fake(request)

    policy = RetryPolicy(max_attempts=2, sleep=lambda _: None)
    assert len(make_client(flaky, policy).get_stock("X")) == 1


def test_it_gives_up_when_the_server_stays_down() -> None:
    fake = FakeERPNext([DALLAS])
    fake.status = 503
    policy = RetryPolicy(max_attempts=2, sleep=lambda _: None)
    with pytest.raises(ERPNextTemporaryError):
        make_client(fake, policy).get_stock("X")
    assert len(fake.requests) == 2
