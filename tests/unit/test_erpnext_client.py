from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

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
from app.clients.erpnext_models import ERPNextCustomer
from app.config import Settings

Handler = Callable[[httpx.Request], httpx.Response]


def make_settings() -> Settings:
    return Settings(
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
    )


def get_customer_with(handler: Handler, name: str = "Anyone") -> ERPNextCustomer:
    """Run get_customer against a fake ERPNext defined by `handler`."""
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = ERPNextClient(settings=make_settings(), http_client=http_client)
        return client.get_customer(name)


def respond(status_code: int = 200, **kwargs: object) -> Handler:
    return lambda request: httpx.Response(status_code, **kwargs)  # type: ignore[arg-type]


def customer_response(data: object) -> Handler:
    return respond(200, json={"data": data})


def test_get_customer_returns_typed_customer() -> None:
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

    assert isinstance(customer, ERPNextCustomer)
    assert customer.name == "NorthStar Mechanical LLC"
    assert customer.customer_type == "Company"
    assert customer.credit_limits[0].company == "MetroAir Supply"
    assert customer.credit_limits[0].credit_limit == Decimal(50000)


def test_missing_credit_limits_defaults_to_empty_list() -> None:
    customer = get_customer_with(customer_response({"name": "Acme"}))

    assert customer.credit_limits == []
    assert customer.customer_type is None


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
