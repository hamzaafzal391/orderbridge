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

        api_key = self.settings.erpnext_api_key.get_secret_value()
        api_secret = self.settings.erpnext_api_secret.get_secret_value()

        try:
            response = self.http_client.get(
                url,
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
        return self._to_customer(self._parse_customer(response))

    @staticmethod
    def _to_customer(erpnext_customer: ERPNextCustomer) -> Customer:
        """Convert ERPNext's shape into OrderBridge's vendor-independent Customer."""
        return Customer(
            name=erpnext_customer.name,
            customer_type=erpnext_customer.customer_type,
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
