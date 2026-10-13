from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.clients.erpnext import ERPNextClient
from app.clients.erpnext_errors import (
    ERPNextAPIError,
    ERPNextAuthenticationError,
    ERPNextError,
    ERPNextNotFoundError,
    ERPNextRateLimitError,
    ERPNextResponseError,
    ERPNextTemporaryError,
)
from app.config import Settings
from app.models import Customer

Handler = Callable[[httpx.Request], httpx.Response]


def make_settings() -> Settings:
    return Settings(
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
        ghl_api_token="test-ghl-token",
    )


def get_customer_with(handler: Handler, name: str = "Anyone") -> Customer:
    """Run get_customer against a fake ERPNext defined by `handler`."""
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = ERPNextClient(settings=make_settings(), http_client=http_client)
        return client.get_customer(name)


def respond(status_code: int = 200, **kwargs: object) -> Handler:
    return lambda request: httpx.Response(status_code, **kwargs)  # type: ignore[arg-type]


def customer_response(data: object) -> Handler:
    return respond(200, json={"data": data})


def test_get_customer_returns_internal_customer() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "http://erpnext.test/api/resource/Customer/NorthStar%20Mechanical%20LLC"
        )
        assert request.headers["Authorization"] == "token test-key:test-secret"
        assert request.headers["Accept"] == "application/json"

        return httpx.Response(
            200,
            json={
                "data": {
                    "name": "NorthStar Mechanical LLC",
                    "customer_type": "Company",
                    "some_unknown_field": "ignored",
                    "credit_limits": [{"company": "MetroAir Supply", "credit_limit": 50000.0}],
                }
            },
        )

    customer = get_customer_with(handle_request, "NorthStar Mechanical LLC")

    assert isinstance(customer, Customer)
    assert customer.name == "NorthStar Mechanical LLC"
    assert customer.customer_type == "Company"
    assert customer.credit_limits[0].company == "MetroAir Supply"
    assert customer.credit_limits[0].amount == Decimal(50000)


def test_missing_credit_limits_defaults_to_empty_list() -> None:
    customer = get_customer_with(customer_response({"name": "Acme"}))

    assert customer.credit_limits == []
    assert customer.customer_type is None


def test_all_credit_limits_are_kept_in_order() -> None:
    customer = get_customer_with(
        customer_response(
            {
                "name": "Acme",
                "credit_limits": [
                    {"company": "First Co", "credit_limit": 100},
                    {"company": "Second Co", "credit_limit": 250.5},
                ],
            }
        )
    )

    assert [(limit.company, limit.amount) for limit in customer.credit_limits] == [
        ("First Co", Decimal(100)),
        ("Second Co", Decimal("250.5")),
    ]


def test_returned_customer_is_immutable() -> None:
    customer = get_customer_with(customer_response({"name": "Acme"}))

    with pytest.raises(ValidationError):
        customer.name = "Changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ERPNextAuthenticationError),
        (403, ERPNextAuthenticationError),
        (404, ERPNextNotFoundError),
        (429, ERPNextRateLimitError),
        (500, ERPNextTemporaryError),
        (502, ERPNextTemporaryError),
        (503, ERPNextTemporaryError),
        (504, ERPNextTemporaryError),
        (400, ERPNextAPIError),
        (409, ERPNextAPIError),
        (501, ERPNextAPIError),
    ],
)
def test_http_status_is_classified(status_code: int, expected_error: type[ERPNextError]) -> None:
    with pytest.raises(ERPNextError) as error:
        get_customer_with(respond(status_code, json={"message": "secret-detail"}))

    assert type(error.value) is expected_error
    assert error.value.status_code == status_code
    assert isinstance(error.value.__cause__, httpx.HTTPStatusError)
    assert "secret-detail" not in str(error.value)


@pytest.mark.parametrize(
    "network_error",
    [
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
def test_timeouts_and_connection_failures_are_temporary(
    network_error: httpx.TransportError,
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        raise network_error

    with pytest.raises(ERPNextTemporaryError) as error:
        get_customer_with(handle_request)

    assert error.value.__cause__ is network_error


@pytest.mark.parametrize(
    "handler",
    [
        respond(200, content=b"<html>not json</html>"),
        respond(200, json={"message": "no data key"}),
        respond(200, json=["not", "an", "object"]),
        customer_response("not an object"),
        customer_response({"customer_type": "Company"}),
        customer_response(
            {"name": "Acme", "credit_limits": [{"company": "X", "credit_limit": "abc"}]}
        ),
    ],
    ids=[
        "invalid-json",
        "missing-data-key",
        "json-not-an-object",
        "data-not-an-object",
        "missing-name",
        "bad-credit-limit",
    ],
)
def test_malformed_response_raises_response_error(handler: Handler) -> None:
    with pytest.raises(ERPNextResponseError) as error:
        get_customer_with(handler)

    assert error.value.__cause__ is not None


def test_validation_error_message_hides_values() -> None:
    handler = customer_response(
        {"name": "Acme", "credit_limits": [{"company": "X", "credit_limit": "SENSITIVE-VALUE"}]}
    )

    with pytest.raises(ERPNextResponseError) as error:
        get_customer_with(handler)

    assert "credit_limits.0.credit_limit" in str(error.value)
    assert "SENSITIVE-VALUE" not in str(error.value)


def test_error_messages_never_contain_credentials() -> None:
    with pytest.raises(ERPNextAuthenticationError) as error:
        get_customer_with(respond(401))

    assert "test-key" not in str(error.value)
    assert "test-secret" not in str(error.value)


def test_close_does_not_close_injected_http_client() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(respond(200, json={"data": {}}))
    ) as http_client:
        ERPNextClient(settings=make_settings(), http_client=http_client).close()

        assert not http_client.is_closed


def test_close_closes_client_it_created() -> None:
    with ERPNextClient(settings=make_settings()) as client:
        assert not client.http_client.is_closed

    assert client.http_client.is_closed


def test_customer_email_is_mapped_and_blank_becomes_none() -> None:
    with_email = get_customer_with(customer_response({"name": "Acme", "email_id": " a@b.com "}))
    blank = get_customer_with(customer_response({"name": "Acme", "email_id": "  "}))

    assert with_email.email == "a@b.com"
    assert blank.email is None


def find_customers_with(handler: Handler, email: str = "sam@example.com") -> list[Customer]:
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = ERPNextClient(settings=make_settings(), http_client=http_client)
        return client.find_customers_by_email(email)


def test_find_customers_by_email_sends_filter_and_fetches_full_records() -> None:
    seen_paths: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.headers["Authorization"] == "token test-key:test-secret"
        if request.url.path == "/api/resource/Customer":
            assert request.url.params["filters"] == '[["email_id", "=", "sam@example.com"]]'
            assert request.url.params["fields"] == '["name"]'
            assert request.url.params["limit_page_length"] == "10"
            return httpx.Response(200, json={"data": [{"name": "Acme"}]})
        assert request.url.path == "/api/resource/Customer/Acme"
        return httpx.Response(
            200,
            json={
                "data": {
                    "name": "Acme",
                    "email_id": "sam@example.com",
                    "credit_limits": [{"company": "X", "credit_limit": 10}],
                }
            },
        )

    customers = find_customers_with(handle_request)

    assert [customer.name for customer in customers] == ["Acme"]
    assert customers[0].email == "sam@example.com"
    assert customers[0].credit_limits[0].amount == Decimal(10)
    assert seen_paths == ["/api/resource/Customer", "/api/resource/Customer/Acme"]


def test_find_customers_by_email_returns_empty_list_when_nothing_matches() -> None:
    assert find_customers_with(customer_response([])) == []


def test_find_customers_by_email_returns_every_match_in_order() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/resource/Customer":
            return httpx.Response(200, json={"data": [{"name": "Acme"}, {"name": "Acme 2"}]})
        return httpx.Response(200, json={"data": {"name": request.url.path.rsplit("/", 1)[1]}})

    customers = find_customers_with(handle_request)

    assert [customer.name for customer in customers] == ["Acme", "Acme 2"]


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ERPNextAuthenticationError),
        (429, ERPNextRateLimitError),
        (503, ERPNextTemporaryError),
        (400, ERPNextAPIError),
    ],
)
def test_find_customers_by_email_classifies_http_errors(
    status_code: int, expected_error: type[ERPNextError]
) -> None:
    with pytest.raises(ERPNextError) as error:
        find_customers_with(respond(status_code, json={"message": "secret-detail"}))

    assert type(error.value) is expected_error
    assert "secret-detail" not in str(error.value)
    assert "sam@example.com" not in str(error.value)


def test_find_customers_by_email_wraps_timeouts() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ERPNextTemporaryError):
        find_customers_with(handle_request)


@pytest.mark.parametrize(
    "handler",
    [
        respond(200, content=b"<html>not json</html>"),
        respond(200, json={"message": "no data key"}),
        customer_response("not a list"),
        customer_response([{"no_name": 1}]),
        customer_response([{"name": 123}]),
        customer_response(["not an object"]),
    ],
    ids=[
        "invalid-json",
        "missing-data",
        "data-not-a-list",
        "row-missing-name",
        "name-not-str",
        "row-not-object",
    ],
)
def test_find_customers_by_email_rejects_malformed_list(handler: Handler) -> None:
    with pytest.raises(ERPNextResponseError):
        find_customers_with(handler)
