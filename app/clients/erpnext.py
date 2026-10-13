import json
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import ValidationError

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
from app.config import Settings, get_settings
from app.models import CreditLimit, Customer

TEMPORARY_STATUS_CODES = {500, 502, 503, 504}
# More than one match already means "ambiguous"; no need to fetch an unbounded list.
MAX_CONTACT_MATCHES = 10


class ERPNextClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.base_url = str(self.settings.erpnext_base_url).rstrip("/")
        # Only close an httpx client we created ourselves; an injected one
        # belongs to the caller.
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(timeout=10.0)

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_customer(self, customer_name: str) -> Customer:
        encoded_name = quote(customer_name, safe="")
        url = f"{self.base_url}/api/resource/Customer/{encoded_name}"

        response = self._get(url)
        return self._to_customer(self._parse_customer(response))

    def find_customers_by_email(self, email: str) -> list[Customer]:
        """Return every ERPNext customer linked to a contact with this email (usually 0 or 1).

        ERPNext keeps emails on Contact records, which link to customers. We search the
        contacts instead of `Customer.email_id`, because that field is only filled when a
        customer's separate "primary contact" link is set. Any email on any linked contact
        counts; contacts that are not linked to a customer are ignored.
        """
        contacts_response = self._get(
            f"{self.base_url}/api/resource/Contact",
            params={
                "filters": json.dumps([["Contact Email", "email_id", "=", email]]),
                "fields": json.dumps(["name"]),
                "limit_page_length": MAX_CONTACT_MATCHES,
            },
        )

        customer_names: dict[str, None] = {}  # a dict keeps order and drops duplicates
        for contact_name in self._parse_name_list(contacts_response):
            contact_response = self._get(
                f"{self.base_url}/api/resource/Contact/{quote(contact_name, safe='')}"
            )
            for customer_name in self._parse_linked_customer_names(contact_response):
                customer_names[customer_name] = None

        # The contact does not carry credit limits etc., so load each full customer record.
        return [self.get_customer(name) for name in customer_names]

    def _get(self, url: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        """Send an authenticated GET and return the response, or raise a classified error."""
        api_key = self.settings.erpnext_api_key.get_secret_value()
        api_secret = self.settings.erpnext_api_secret.get_secret_value()

        try:
            response = self.http_client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"token {api_key}:{api_secret}",
                    "Accept": "application/json",
                },
            )
        except httpx.TransportError as error:
            # Timeouts, connection failures and protocol errors: worth retrying later.
            raise ERPNextTemporaryError(
                f"Could not reach ERPNext ({type(error).__name__})"
            ) from error
        except httpx.RequestError as error:
            raise ERPNextResponseError(
                f"Unusable ERPNext response ({type(error).__name__})"
            ) from error

        self._raise_for_status(response)
        return response

    @staticmethod
    def _parse_name_list(response: httpx.Response) -> list[str]:
        try:
            names = [row["name"] for row in response.json()["data"]]
        except (ValueError, KeyError, TypeError) as error:
            raise ERPNextResponseError("Response body is not the expected shape") from error
        if not all(isinstance(name, str) for name in names):
            raise ERPNextResponseError("Response body is not the expected shape")
        return names

    @staticmethod
    def _parse_linked_customer_names(response: httpx.Response) -> list[str]:
        """Names of the customers a contact is linked to (other link types are ignored)."""
        try:
            links = response.json()["data"].get("links", [])
            names = [link["link_name"] for link in links if link["link_doctype"] == "Customer"]
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ERPNextResponseError("Response body is not the expected shape") from error
        if not all(isinstance(name, str) for name in names):
            raise ERPNextResponseError("Response body is not the expected shape")
        return names

    @staticmethod
    def _to_customer(erpnext_customer: ERPNextCustomer) -> Customer:
        """Convert ERPNext's shape into OrderBridge's vendor-independent Customer."""
        return Customer(
            name=erpnext_customer.name,
            customer_type=erpnext_customer.customer_type,
            email=(erpnext_customer.email_id or "").strip() or None,
            credit_limits=[
                CreditLimit(company=limit.company, amount=limit.credit_limit)
                for limit in erpnext_customer.credit_limits
            ],
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return

        message = f"ERPNext returned HTTP {status}"
        error: ERPNextError
        if status in (401, 403):
            error = ERPNextAuthenticationError(message, status_code=status)
        elif status == 404:
            error = ERPNextNotFoundError(message, status_code=status)
        elif status == 429:
            error = ERPNextRateLimitError(message, status_code=status)
        elif status in TEMPORARY_STATUS_CODES:
            error = ERPNextTemporaryError(message, status_code=status)
        else:
            error = ERPNextAPIError(message, status_code=status)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as cause:
            raise error from cause
        raise error  # defensive: raise_for_status() should already have raised

    @staticmethod
    def _parse_customer(response: httpx.Response) -> ERPNextCustomer:
        try:
            return ERPNextCustomer.model_validate(response.json()["data"])
        except ValidationError as error:
            # Report only where and what failed, never the offending values.
            problems = ", ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
                for item in error.errors()
            )
            raise ERPNextResponseError(f"Invalid customer in response ({problems})") from error
        except (ValueError, KeyError, TypeError) as error:
            raise ERPNextResponseError("Response body is not the expected shape") from error
