from typing import Self
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.clients.ghl_errors import (
    GHLAPIError,
    GHLAuthenticationError,
    GHLError,
    GHLNotFoundError,
    GHLRateLimitError,
    GHLResponseError,
    GHLTemporaryError,
)
from app.clients.ghl_models import GHLContact
from app.config import Settings, get_settings
from app.models import Customer

TEMPORARY_STATUS_CODES = {500, 502, 503, 504}


class GHLClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.base_url = str(self.settings.ghl_base_url).rstrip("/")
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

    def get_contact(self, contact_id: str) -> Customer:
        encoded_id = quote(contact_id, safe="")
        url = f"{self.base_url}/contacts/{encoded_id}"
        token = self.settings.ghl_api_token.get_secret_value()

        try:
            response = self.http_client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Version": self.settings.ghl_api_version,
                    "Accept": "application/json",
                },
            )
        except httpx.TransportError as error:
            # Timeouts, connection failures and protocol errors: worth retrying later.
            raise GHLTemporaryError(
                f"Could not reach GoHighLevel ({type(error).__name__})"
            ) from error
        except httpx.RequestError as error:
            raise GHLResponseError(
                f"Unusable GoHighLevel response ({type(error).__name__})"
            ) from error

        self._raise_for_status(response)
        return self._to_customer(self._parse_contact(response))

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return

        message = f"GoHighLevel returned HTTP {status}"
        error: GHLError
        if status in (401, 403):
            error = GHLAuthenticationError(message, status_code=status)
        elif status == 404:
            error = GHLNotFoundError(message, status_code=status)
        elif status == 429:
            error = GHLRateLimitError(message, status_code=status)
        elif status in TEMPORARY_STATUS_CODES:
            error = GHLTemporaryError(message, status_code=status)
        else:
            error = GHLAPIError(message, status_code=status)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as cause:
            raise error from cause
        raise error  # defensive: raise_for_status() should already have raised

    @staticmethod
    def _parse_contact(response: httpx.Response) -> GHLContact:
        try:
            return GHLContact.model_validate(response.json()["contact"])
        except ValidationError as error:
            # Report only where and what failed, never the offending values.
            problems = ", ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
                for item in error.errors()
            )
            raise GHLResponseError(f"Invalid contact in response ({problems})") from error
        except (ValueError, KeyError, TypeError) as error:
            raise GHLResponseError("Response body is not the expected shape") from error

    @staticmethod
    def _to_customer(contact: GHLContact) -> Customer:
        """Convert a GoHighLevel contact into OrderBridge's vendor-independent Customer."""
        company = (contact.company_name or "").strip()
        person = " ".join(part for part in (contact.first_name, contact.last_name) if part).strip()
        name = company or person or (contact.name or "").strip()
        if not name:
            raise GHLResponseError("Contact has no company name, person name or display name")

        return Customer(name=name, customer_type="Company" if company else "Individual")
