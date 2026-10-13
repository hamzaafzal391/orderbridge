from collections.abc import Callable

import httpx
import pytest

from app.clients.ghl import GHLClient
from app.clients.ghl_errors import (
    GHLAPIError,
    GHLAuthenticationError,
    GHLError,
    GHLNotFoundError,
    GHLRateLimitError,
    GHLResponseError,
    GHLTemporaryError,
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
        ghl_base_url="http://ghl.test",
    )


def get_contact_with(handler: Handler, contact_id: str = "abc123") -> Customer:
    """Run get_contact against a fake GoHighLevel defined by `handler`."""
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GHLClient(settings=make_settings(), http_client=http_client)
        return client.get_contact(contact_id)


def respond(status_code: int = 200, **kwargs: object) -> Handler:
    return lambda request: httpx.Response(status_code, **kwargs)  # type: ignore[arg-type]


def contact_response(contact: object) -> Handler:
    return respond(200, json={"contact": contact})


def test_get_contact_sends_expected_request_and_returns_customer() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://ghl.test/contacts/abc%2F123"
        assert request.headers["Authorization"] == "Bearer test-ghl-token"
        assert request.headers["Version"] == "2021-07-28"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(
            200,
            json={
                "contact": {
                    "id": "abc/123",
                    "firstName": "Sam",
                    "lastName": "Rivera",
                    "companyName": "NorthStar Mechanical LLC",
                    "email": "ignored@example.com",
                }
            },
        )

    customer = get_contact_with(handle_request, "abc/123")

    assert isinstance(customer, Customer)
    assert customer.name == "NorthStar Mechanical LLC"
    assert customer.customer_type == "Company"
    assert customer.credit_limits == []


@pytest.mark.parametrize(
    ("contact", "expected_name", "expected_type"),
    [
        ({"id": "1", "firstName": "Sam", "lastName": "Rivera"}, "Sam Rivera", "Individual"),
        ({"id": "1", "firstName": "Sam"}, "Sam", "Individual"),
        ({"id": "1", "name": "Sam R."}, "Sam R.", "Individual"),
        ({"id": "1", "companyName": "  Acme  ", "firstName": "Sam"}, "Acme", "Company"),
        ({"id": "1", "companyName": "", "firstName": "Sam"}, "Sam", "Individual"),
    ],
    ids=["full-name", "first-only", "display-name", "company-wins", "blank-company"],
)
def test_contact_is_mapped_to_customer(
    contact: dict[str, str], expected_name: str, expected_type: str
) -> None:
    customer = get_contact_with(contact_response(contact))

    assert customer.name == expected_name
    assert customer.customer_type == expected_type


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, GHLAuthenticationError),
        (403, GHLAuthenticationError),
        (404, GHLNotFoundError),
        (429, GHLRateLimitError),
        (500, GHLTemporaryError),
        (502, GHLTemporaryError),
        (503, GHLTemporaryError),
        (504, GHLTemporaryError),
        (400, GHLAPIError),
        (422, GHLAPIError),
        (501, GHLAPIError),
    ],
)
def test_http_status_is_classified(status_code: int, expected_error: type[GHLError]) -> None:
    with pytest.raises(GHLError) as error:
        get_contact_with(respond(status_code, json={"message": "secret-detail"}))

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

    with pytest.raises(GHLTemporaryError) as error:
        get_contact_with(handle_request)

    assert error.value.__cause__ is network_error


@pytest.mark.parametrize(
    "handler",
    [
        respond(200, content=b"<html>not json</html>"),
        respond(200, json={"message": "no contact key"}),
        respond(200, json=["not", "an", "object"]),
        contact_response("not an object"),
        contact_response({"firstName": "Sam"}),
        contact_response({"id": "1"}),
        contact_response({"id": "1", "firstName": "  ", "companyName": " "}),
    ],
    ids=[
        "invalid-json",
        "missing-contact-key",
        "json-not-an-object",
        "contact-not-an-object",
        "missing-id",
        "no-name-at-all",
        "blank-names",
    ],
)
def test_malformed_response_raises_response_error(handler: Handler) -> None:
    with pytest.raises(GHLResponseError):
        get_contact_with(handler)


def test_validation_error_message_hides_values() -> None:
    handler = contact_response({"id": ["SENSITIVE-VALUE"]})

    with pytest.raises(GHLResponseError) as error:
        get_contact_with(handler)

    assert "id" in str(error.value)
    assert "SENSITIVE-VALUE" not in str(error.value)


def test_error_messages_never_contain_token() -> None:
    with pytest.raises(GHLAuthenticationError) as error:
        get_contact_with(respond(401))

    assert "test-ghl-token" not in str(error.value)


def test_close_does_not_close_injected_http_client() -> None:
    transport = httpx.MockTransport(respond(200, json={"contact": {}}))

    with httpx.Client(transport=transport) as http_client:
        GHLClient(settings=make_settings(), http_client=http_client).close()

        assert not http_client.is_closed


def test_close_closes_client_it_created() -> None:
    with GHLClient(settings=make_settings()) as client:
        assert not client.http_client.is_closed

    assert client.http_client.is_closed


@pytest.mark.parametrize(
    ("email", "expected"),
    [(" sam@example.com ", "sam@example.com"), ("", None), ("   ", None), (None, None)],
)
def test_contact_email_is_mapped_and_blank_becomes_none(
    email: str | None, expected: str | None
) -> None:
    customer = get_contact_with(contact_response({"id": "1", "firstName": "Sam", "email": email}))

    assert customer.email == expected
