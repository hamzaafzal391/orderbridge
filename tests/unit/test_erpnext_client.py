import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.clients.erpnext import ERPNextClient
from app.clients.erpnext_errors import (
    ERPNextAPIError,
    ERPNextAuthenticationError,
    ERPNextDuplicateCreatedError,
    ERPNextError,
    ERPNextNotFoundError,
    ERPNextPartialWriteError,
    ERPNextRateLimitError,
    ERPNextResponseError,
    ERPNextTemporaryError,
    ERPNextUnknownOutcomeError,
)
from app.config import Settings
from app.models import Customer
from app.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]

# Most tests exercise a single attempt; retry behaviour has its own tests below.
NO_RETRY = RetryPolicy(max_attempts=1)


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
        client = ERPNextClient(
            settings=make_settings(), http_client=http_client, retry_policy=NO_RETRY
        )
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


def fake_erpnext(contacts: dict[str, list[dict[str, str]]]) -> Handler:
    """A fake ERPNext. `contacts` maps each matching contact's name to its `links`.

    Every customer named in a link exists and has one credit limit.
    """

    def handle_request(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/resource/Contact":
            return httpx.Response(200, json={"data": [{"name": name} for name in contacts]})
        if path.startswith("/api/resource/Contact/"):
            name = path.removeprefix("/api/resource/Contact/")
            return httpx.Response(200, json={"data": {"name": name, "links": contacts[name]}})
        name = path.removeprefix("/api/resource/Customer/")
        return httpx.Response(
            200,
            json={"data": {"name": name, "credit_limits": [{"company": "X", "credit_limit": 10}]}},
        )

    return handle_request


def customer_link(name: str) -> dict[str, str]:
    return {"link_doctype": "Customer", "link_name": name}


def find_customers_with(handler: Handler, email: str = "sam@example.com") -> list[Customer]:
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = ERPNextClient(
            settings=make_settings(), http_client=http_client, retry_policy=NO_RETRY
        )
        return client.find_customers_by_email(email)


def test_find_customers_by_email_searches_contacts_then_loads_linked_customers() -> None:
    requests: list[httpx.Request] = []
    inner = fake_erpnext({"Jordan Lee-Acme": [customer_link("Acme")]})

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return inner(request)

    customers = find_customers_with(handle_request)

    assert [customer.name for customer in customers] == ["Acme"]
    assert customers[0].credit_limits[0].amount == Decimal(10)
    assert [request.url.raw_path.decode().split("?")[0] for request in requests] == [
        "/api/resource/Contact",
        "/api/resource/Contact/Jordan%20Lee-Acme",
        "/api/resource/Customer/Acme",
    ]
    contact_search = requests[0].url.params
    assert contact_search["filters"] == '[["Contact Email", "email_id", "=", "sam@example.com"]]'
    assert contact_search["fields"] == '["name"]'
    assert contact_search["limit_page_length"] == "10"
    assert all(
        request.headers["Authorization"] == "token test-key:test-secret" for request in requests
    )


def test_find_customers_by_email_returns_empty_list_when_no_contact_matches() -> None:
    assert find_customers_with(fake_erpnext({})) == []


def test_contacts_not_linked_to_a_customer_are_ignored() -> None:
    handler = fake_erpnext(
        {
            "No links": [],
            "Supplier contact": [{"link_doctype": "Supplier", "link_name": "Parts Inc"}],
        }
    )

    assert find_customers_with(handler) == []


def test_each_linked_customer_is_returned_once_in_order() -> None:
    handler = fake_erpnext(
        {
            "Contact A": [customer_link("Acme"), customer_link("Beta")],
            "Contact B": [customer_link("Acme"), customer_link("Gamma")],
        }
    )

    customers = find_customers_with(handler)

    assert [customer.name for customer in customers] == ["Acme", "Beta", "Gamma"]


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ERPNextAuthenticationError),
        (429, ERPNextRateLimitError),
        (503, ERPNextTemporaryError),
        (400, ERPNextAPIError),
    ],
)
@pytest.mark.parametrize("failing_step", ["contact-search", "contact-read", "customer-read"])
def test_find_customers_by_email_classifies_http_errors(
    failing_step: str, status_code: int, expected_error: type[ERPNextError]
) -> None:
    inner = fake_erpnext({"Contact A": [customer_link("Acme")]})
    failing_path = {
        "contact-search": "/api/resource/Contact",
        "contact-read": "/api/resource/Contact/Contact%20A",
        "customer-read": "/api/resource/Customer/Acme",
    }[failing_step]

    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.raw_path.decode().split("?")[0] == failing_path:
            return httpx.Response(status_code, json={"message": "secret-detail"})
        return inner(request)

    with pytest.raises(ERPNextError) as error:
        find_customers_with(handle_request)

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
def test_find_customers_by_email_rejects_malformed_contact_list(handler: Handler) -> None:
    with pytest.raises(ERPNextResponseError):
        find_customers_with(handler)


@pytest.mark.parametrize(
    "contact_body",
    [
        b"<html>not json</html>",
        b'{"message": "no data key"}',
        b'{"data": ["not", "an", "object"]}',
        b'{"data": {"links": "not a list"}}',
        b'{"data": {"links": [{"link_doctype": "Customer"}]}}',
        b'{"data": {"links": [{"link_doctype": "Customer", "link_name": 5}]}}',
    ],
    ids=[
        "invalid-json",
        "missing-data",
        "data-not-an-object",
        "links-not-a-list",
        "link-missing-name",
        "link-name-not-str",
    ],
)
def test_find_customers_by_email_rejects_malformed_contact_record(contact_body: bytes) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/resource/Contact":
            return httpx.Response(200, json={"data": [{"name": "Contact A"}]})
        return httpx.Response(200, content=contact_body)

    with pytest.raises(ERPNextResponseError):
        find_customers_with(handle_request)


class Flaky:
    """A fake server that fails with `failures` in turn (a status code or an exception), then succeeds."""

    def __init__(
        self, failures: list[int | Exception], ok: Handler, headers: dict[str, str] | None = None
    ):
        self.failures = list(failures)
        self.ok = ok
        self.headers = headers or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(failure, headers=self.headers)
        return self.ok(request)


def retrying(handler: Handler, sleeps: list[float], max_attempts: int = 3) -> ERPNextClient:
    """A client whose retry waits are recorded instead of slept (the caller closes it)."""
    policy = RetryPolicy(max_attempts=max_attempts, sleep=sleeps.append, jitter=lambda delay: delay)
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return ERPNextClient(settings=make_settings(), http_client=http_client, retry_policy=policy)


@pytest.mark.parametrize(
    "failure",
    [503, 502, 500, 504, 429, httpx.ConnectTimeout("timed out"), httpx.ConnectError("refused")],
    ids=["503", "502", "500", "504", "429", "timeout", "connection-error"],
)
def test_temporary_failure_is_retried_then_succeeds(failure: int | Exception) -> None:
    server = Flaky([failure], customer_response({"name": "Acme"}))
    sleeps: list[float] = []

    with retrying(server, sleeps) as client:
        customer = client.get_customer("Acme")

    assert customer.name == "Acme"
    assert len(server.requests) == 2
    assert sleeps == [0.5]


def test_retry_after_header_sets_the_wait() -> None:
    server = Flaky([429], customer_response({"name": "Acme"}), headers={"Retry-After": "2"})
    sleeps: list[float] = []

    with retrying(server, sleeps) as client:
        client.get_customer("Acme")

    assert sleeps == [2.0]


def test_rate_limit_error_carries_retry_after() -> None:
    server = Flaky([429], respond(200), headers={"Retry-After": "7"})

    with (
        retrying(server, [], max_attempts=1) as client,
        pytest.raises(ERPNextRateLimitError) as error,
    ):
        client.get_customer("Acme")

    assert error.value.retry_after == 7.0


def test_persistent_temporary_failure_gives_up_after_max_attempts() -> None:
    server = Flaky([503, 503, 503, 503], respond(200))
    sleeps: list[float] = []

    with retrying(server, sleeps) as client, pytest.raises(ERPNextTemporaryError) as error:
        client.get_customer("Acme")

    assert error.value.status_code == 503
    assert len(server.requests) == 3
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize("failure", [401, 403, 404, 400, 409], ids=str)
def test_permanent_errors_are_not_retried(failure: int) -> None:
    server = Flaky([failure, failure], customer_response({"name": "Acme"}))
    sleeps: list[float] = []

    with retrying(server, sleeps) as client, pytest.raises(ERPNextError):
        client.get_customer("Acme")

    assert len(server.requests) == 1
    assert sleeps == []


def test_malformed_response_is_not_retried() -> None:
    server = Flaky([], respond(200, content=b"<html>not json</html>"))

    with retrying(server, []) as client, pytest.raises(ERPNextResponseError):
        client.get_customer("Acme")

    assert len(server.requests) == 1


def test_find_customers_retries_only_the_failing_step() -> None:
    inner = fake_erpnext({"Contact A": [customer_link("Acme")]})
    seen: list[str] = []
    failed_once: list[bool] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/resource/Contact/Contact A" and not failed_once:
            failed_once.append(True)
            return httpx.Response(503)
        return inner(request)

    with retrying(handle_request, []) as client:
        customers = client.find_customers_by_email("sam@example.com")

    assert [customer.name for customer in customers] == ["Acme"]
    assert seen == [
        "/api/resource/Contact",
        "/api/resource/Contact/Contact A",  # failed
        "/api/resource/Contact/Contact A",  # retried
        "/api/resource/Customer/Acme",
    ]


def test_retries_never_leak_secrets_into_the_final_error() -> None:
    server = Flaky([503, 503, 503], respond(200))

    with retrying(server, []) as client, pytest.raises(ERPNextTemporaryError) as error:
        client.get_customer("Acme")

    assert "test-key" not in str(error.value)
    assert "test-secret" not in str(error.value)


# --- create_customer (the first write) ---------------------------------------------------
#
# The fake server below mimics what a live ERPNext was observed to do: it does NOT reject a
# second customer with an existing name, it silently creates "Name - 1" instead.


def new_customer(
    email: str | None = "sam@example.com", customer_type: str | None = "Individual"
) -> Customer:
    return Customer(name="Sam Rivera", customer_type=customer_type, email=email)


Reply = int | httpx.Response | Exception


class RecordingServer:
    """A fake ERPNext for create_customer.

    - `existing_names`: customers already in ERPNext (what the name check finds).
    - `number_duplicates`: when a POSTed name already exists, ERPNext answers 200 with
      "Name - 1" (the real behaviour). `race=True` makes the name check miss it, as if another
      run created the customer between our check and our write.
    - `*_reply` override the answer to the name check, customer POST or contact POST with a
      status code, a ready response, or an exception to raise.
    """

    def __init__(
        self,
        existing_names: list[str] | None = None,
        race: bool = False,
        check_reply: Reply | None = None,
        customer_reply: Reply | None = None,
        contact_reply: Reply | None = None,
    ) -> None:
        self.existing_names = list(existing_names or [])
        self.race = race
        self.check_reply = check_reply
        self.customer_reply = customer_reply
        self.contact_reply = contact_reply
        self.requests: list[httpx.Request] = []

    @staticmethod
    def _answer(reply: Reply) -> httpx.Response:
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(reply, json={"data": {}, "message": "secret-detail"})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if request.method == "GET" and path == "/api/resource/Customer":  # the name check
            if self.check_reply is not None:
                return self._answer(self.check_reply)
            names = [] if self.race else self.existing_names
            return httpx.Response(200, json={"data": [{"name": name} for name in names]})

        if path == "/api/resource/Customer":  # POST customer
            if self.customer_reply is not None:
                return self._answer(self.customer_reply)
            name = json.loads(request.content)["customer_name"]
            if name in self.existing_names:
                name = f"{name} - 1"  # ERPNext numbers duplicates instead of rejecting them
            return httpx.Response(200, json={"data": {"name": name}})

        if self.contact_reply is not None:  # POST contact
            return self._answer(self.contact_reply)
        return httpx.Response(200, json={"data": {}})

    @property
    def calls(self) -> list[str]:
        """Each request as 'METHOD /path', in order."""
        return [f"{request.method} {request.url.path}" for request in self.requests]

    def posts(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]


CHECK = "GET /api/resource/Customer"
POST_CUSTOMER = "POST /api/resource/Customer"
POST_CONTACT = "POST /api/resource/Contact"


def create_with(
    server: RecordingServer,
    customer: Customer | None = None,
    settings: Settings | None = None,
    sleeps: list[float] | None = None,
    max_attempts: int = 3,
) -> Customer | None:
    """Run create_customer with retries ENABLED, to prove writes never use them."""
    policy = RetryPolicy(
        max_attempts=max_attempts,
        sleep=(sleeps if sleeps is not None else []).append,
        jitter=lambda delay: delay,
    )
    with httpx.Client(transport=httpx.MockTransport(server)) as http_client:
        client = ERPNextClient(
            settings=settings or make_settings(), http_client=http_client, retry_policy=policy
        )
        return client.create_customer(customer or new_customer())


def test_create_customer_checks_the_name_then_posts_customer_then_linked_contact() -> None:
    server = RecordingServer()

    created = create_with(server)

    assert server.calls == [CHECK, POST_CUSTOMER, POST_CONTACT]
    assert all(
        request.headers["Authorization"] == "token test-key:test-secret"
        for request in server.requests
    )
    check = server.requests[0].url.params
    assert check["filters"] == '[["customer_name", "=", "Sam Rivera"]]'
    assert check["fields"] == '["name"]'
    assert check["limit_page_length"] == "1"
    assert json.loads(server.requests[1].content) == {
        "customer_name": "Sam Rivera",
        "customer_type": "Individual",
        "customer_group": "Commercial",
        "territory": "Rest Of The World",
    }
    assert json.loads(server.requests[2].content) == {
        "first_name": "Sam Rivera",
        "email_ids": [{"email_id": "sam@example.com", "is_primary": 1}],
        "links": [{"link_doctype": "Customer", "link_name": "Sam Rivera"}],
    }
    assert created is not None
    assert created.name == "Sam Rivera"
    assert created.email == "sam@example.com"


def test_create_customer_uses_configured_group_and_territory() -> None:
    settings = Settings(
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
        ghl_api_token="test-ghl-token",
        erpnext_default_customer_group="Government",
        erpnext_default_territory="United States",
    )
    server = RecordingServer()

    create_with(server, settings=settings)

    body = json.loads(server.posts()[0].content)
    assert (body["customer_group"], body["territory"]) == ("Government", "United States")


def test_create_customer_without_a_type_defaults_to_individual() -> None:
    server = RecordingServer()

    create_with(server, new_customer(customer_type=None))

    assert json.loads(server.posts()[0].content)["customer_type"] == "Individual"


def test_create_customer_without_email_creates_no_contact() -> None:
    server = RecordingServer()

    created = create_with(server, new_customer(email=None))

    assert server.calls == [CHECK, POST_CUSTOMER]
    assert created is not None
    assert created.email is None


def test_existing_name_returns_none_and_writes_nothing() -> None:
    server = RecordingServer(existing_names=["Sam Rivera"])

    created = create_with(server)

    assert created is None
    assert server.calls == [CHECK]  # no POST at all: no numbered duplicate, no contact


@pytest.mark.parametrize(
    "duplicate_reply",
    [
        httpx.Response(409, json={"exception": "frappe.exceptions.DuplicateEntryError"}),
        httpx.Response(409, content=b"conflict"),
        httpx.Response(
            417, json={"exception": "frappe.exceptions.DuplicateEntryError: Customer Sam Rivera"}
        ),
    ],
    ids=["409-with-body", "409-without-json", "417-duplicate-entry"],
)
def test_a_duplicate_rejection_is_still_handled_if_erpnext_ever_sends_one(
    duplicate_reply: httpx.Response,
) -> None:
    server = RecordingServer(customer_reply=duplicate_reply)

    assert create_with(server) is None
    assert server.calls == [CHECK, POST_CUSTOMER]  # no contact


def test_other_417_validation_error_is_not_mistaken_for_a_duplicate() -> None:
    reply = httpx.Response(417, json={"exception": "frappe.exceptions.ValidationError: bad"})

    with pytest.raises(ERPNextAPIError):
        create_with(RecordingServer(customer_reply=reply))


def test_numbered_customer_from_a_race_raises_and_links_no_contact() -> None:
    # Another run created "Sam Rivera" between our name check and our write, so ERPNext
    # answered the POST with "Sam Rivera - 1".
    server = RecordingServer(existing_names=["Sam Rivera"], race=True)

    with pytest.raises(ERPNextDuplicateCreatedError) as error:
        create_with(server)

    assert server.calls == [CHECK, POST_CUSTOMER]  # the contact is NOT attached to the duplicate
    assert not error.value.retryable
    assert "Sam Rivera" not in str(error.value)
    assert "sam@example.com" not in str(error.value)


def test_name_check_is_a_read_and_is_retried_on_a_temporary_error() -> None:
    attempts: list[int] = []

    class FlakyCheck(RecordingServer):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and not attempts:
                attempts.append(1)
                self.requests.append(request)
                return httpx.Response(503)
            return super().__call__(request)

    server = FlakyCheck()
    sleeps: list[float] = []

    created = create_with(server, sleeps=sleeps)

    assert created is not None
    assert server.calls == [CHECK, CHECK, POST_CUSTOMER, POST_CONTACT]  # only the READ repeated
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ERPNextAuthenticationError),
        (403, ERPNextAuthenticationError),
        (400, ERPNextAPIError),
    ],
)
def test_name_check_permanent_errors_stop_before_any_write(
    status_code: int, expected_error: type[ERPNextError]
) -> None:
    server = RecordingServer(check_reply=status_code)

    with pytest.raises(ERPNextError) as error:
        create_with(server)

    assert type(error.value) is expected_error
    assert server.calls == [CHECK]
    assert "secret-detail" not in str(error.value)


@pytest.mark.parametrize(
    "check_body",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, json={"message": "no data key"}),
        httpx.Response(200, json={"data": [{"no_name": 1}]}),
    ],
    ids=["invalid-json", "missing-data", "row-missing-name"],
)
def test_malformed_name_check_reply_stops_before_any_write(check_body: httpx.Response) -> None:
    server = RecordingServer(check_reply=check_body)

    with pytest.raises(ERPNextResponseError):
        create_with(server)

    assert server.calls == [CHECK]


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ERPNextAuthenticationError),
        (403, ERPNextAuthenticationError),
        (429, ERPNextRateLimitError),
        (500, ERPNextTemporaryError),
        (503, ERPNextTemporaryError),
        (400, ERPNextAPIError),
    ],
)
def test_customer_post_errors_are_classified_and_never_retried(
    status_code: int, expected_error: type[ERPNextError]
) -> None:
    server = RecordingServer(customer_reply=status_code)
    sleeps: list[float] = []

    with pytest.raises(ERPNextError) as error:
        create_with(server, sleeps=sleeps)

    assert type(error.value) is expected_error
    assert server.calls == [CHECK, POST_CUSTOMER]  # the POST happened exactly once
    assert sleeps == []  # never waited, because the write is never retried
    assert "secret-detail" not in str(error.value)
    assert "Sam Rivera" not in str(error.value)
    assert "sam@example.com" not in str(error.value)


@pytest.mark.parametrize(
    "network_error",
    [
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("refused"),
    ],
    ids=["connect-timeout", "read-timeout", "connection-error"],
)
def test_network_failure_on_a_write_is_unknown_outcome_and_never_retried(
    network_error: httpx.TransportError,
) -> None:
    server = RecordingServer(customer_reply=network_error)
    sleeps: list[float] = []

    with pytest.raises(ERPNextUnknownOutcomeError) as error:
        create_with(server, sleeps=sleeps)

    assert server.calls == [CHECK, POST_CUSTOMER]
    assert sleeps == []
    assert error.value.__cause__ is network_error
    assert not error.value.retryable
    assert "Sam Rivera" not in str(error.value)


@pytest.mark.parametrize(
    "contact_reply",
    [400, 401, 429, 503, httpx.ReadTimeout("timed out"), httpx.ConnectError("refused")],
    ids=["400", "401", "429", "503", "timeout", "connection-error"],
)
def test_contact_failure_after_customer_created_is_a_partial_write(
    contact_reply: int | Exception,
) -> None:
    server = RecordingServer(contact_reply=contact_reply)

    with pytest.raises(ERPNextPartialWriteError) as error:
        create_with(server)

    assert server.calls == [CHECK, POST_CUSTOMER, POST_CONTACT]  # each write exactly once
    assert isinstance(error.value.__cause__, ERPNextError)
    assert not error.value.retryable
    assert "Sam Rivera" not in str(error.value)
    assert "sam@example.com" not in str(error.value)
    assert "secret-detail" not in str(error.value)


def test_rerun_after_a_partial_write_reports_the_existing_name_instead_of_duplicating() -> None:
    # First run: customer created, contact failed. The customer now exists in ERPNext.
    first = RecordingServer(contact_reply=503)
    with pytest.raises(ERPNextPartialWriteError):
        create_with(first)

    # Rerun: the name check finds it, so nothing is written and no "Sam Rivera - 1" appears.
    rerun = RecordingServer(existing_names=["Sam Rivera"])
    assert create_with(rerun) is None
    assert rerun.calls == [CHECK]


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, json={"message": "no data key"}),
        httpx.Response(200, json={"data": {"customer_type": "Company"}}),
    ],
    ids=["invalid-json", "missing-data", "missing-name"],
)
def test_malformed_customer_reply_raises_response_error_and_creates_no_contact(
    reply: httpx.Response,
) -> None:
    server = RecordingServer(customer_reply=reply)

    with pytest.raises(ERPNextResponseError):
        create_with(server)

    assert server.calls == [CHECK, POST_CUSTOMER]
