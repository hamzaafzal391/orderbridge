from decimal import Decimal, InvalidOperation
from typing import Self, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.clients.ghl_errors import (
    GHLAPIError,
    GHLAuthenticationError,
    GHLError,
    GHLNotFoundError,
    GHLRateLimitError,
    GHLResponseError,
    GHLTemporaryError,
)
from app.clients.ghl_models import (
    GHLContact,
    GHLCustomFieldDefinition,
    GHLOpportunity,
)
from app.config import Settings, get_settings
from app.models import Customer, Deal
from app.retry import RetryPolicy, call_with_retries, parse_retry_after

TEMPORARY_STATUS_CODES = {500, 502, 503, 504}

# A custom field's key is fixed when it is created in GoHighLevel (renaming the field changes
# it), and the id is looked up from the key at run time. Keys confirmed against the real account.
SKU_FIELD = "opportunity.metroair_sku"
QUANTITY_FIELD = "opportunity.metroair_quantity"
WAREHOUSE_FIELD = "opportunity.metroair_warehouse"
UNIT_PRICE_FIELD = "opportunity.metroair_unit_price"
AVAILABILITY_FIELD = "opportunity.metroair_availability"
DEAL_FIELDS = (SKU_FIELD, QUANTITY_FIELD, WAREHOUSE_FIELD, UNIT_PRICE_FIELD, AVAILABILITY_FIELD)

Model = TypeVar("Model", bound=BaseModel)


class GHLClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retry_policy = retry_policy or RetryPolicy()
        self.base_url = str(self.settings.ghl_base_url).rstrip("/")
        # Only close an httpx client we created ourselves; an injected one
        # belongs to the caller.
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(timeout=10.0)
        # Custom-field ids by key, per location: looked up once, then reused by this client.
        self._field_ids: dict[str, dict[str, str]] = {}

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_contact(self, contact_id: str) -> Customer:
        encoded_id = quote(contact_id, safe="")
        response = self._get(f"{self.base_url}/contacts/{encoded_id}")
        return self._to_customer(self._parse_contact(response))

    def get_deal(self, opportunity_id: str) -> Deal:
        """Read a deal (GoHighLevel calls it an opportunity) and its equipment line.

        An equipment field that has no value comes back as None; whether that matters is the
        caller's decision. A field that does not exist in the account at all is an error: it
        means someone renamed or deleted it, and guessing would be dangerous.
        """
        opportunity = self._read_opportunity(opportunity_id)
        field_ids = self._custom_field_ids(opportunity.location_id)
        values = {value.id: value.field_value for value in opportunity.custom_fields or []}

        def value_of(field_key: str) -> str | int | float | bool | None:
            return values.get(field_ids[field_key])

        return Deal(
            id=opportunity.id,
            contact_id=opportunity.contact_id,
            status=opportunity.status,
            pipeline_id=opportunity.pipeline_id,
            sku=self._as_text(value_of(SKU_FIELD)),
            quantity=self._as_number(value_of(QUANTITY_FIELD)),
            warehouse=self._as_text(value_of(WAREHOUSE_FIELD)),
            unit_price=self._as_number(value_of(UNIT_PRICE_FIELD)),
        )

    def set_deal_field(self, opportunity_id: str, field_key: str, value: str) -> None:
        """Write one text custom field on a deal. Other fields are not touched.

        Repeating this exact write changes nothing the second time, so it is allowed to use the
        retry policy. That is a deliberate exception to "writes are never retried" (ADR 0009);
        it must not be copied to writes that create things.
        """
        opportunity = self._read_opportunity(opportunity_id)
        field_ids = self._custom_field_ids(opportunity.location_id)
        if field_key not in field_ids:
            raise GHLResponseError(f"Custom field {field_key} does not exist in GoHighLevel")

        encoded_id = quote(opportunity_id, safe="")
        self._send(
            "PUT",
            f"{self.base_url}/opportunities/{encoded_id}",
            payload={"customFields": [{"id": field_ids[field_key], "fieldValue": value}]},
        )

    def set_availability_note(self, opportunity_id: str, note: str) -> None:
        """Write the stock answer onto the deal's availability field."""
        self.set_deal_field(opportunity_id, AVAILABILITY_FIELD, note)

    def _read_opportunity(self, opportunity_id: str) -> GHLOpportunity:
        encoded_id = quote(opportunity_id, safe="")
        response = self._get(f"{self.base_url}/opportunities/{encoded_id}")
        return self._parse_model(response, "opportunity", GHLOpportunity, "opportunity")

    def _custom_field_ids(self, location_id: str) -> dict[str, str]:
        """Map each of our field keys to GoHighLevel's id for it (cached per location)."""
        if location_id not in self._field_ids:
            response = self._get(
                f"{self.base_url}/locations/{quote(location_id, safe='')}/customFields",
                params={"model": "opportunity"},
            )
            try:
                items = response.json()["customFields"]
            except (ValueError, KeyError, TypeError) as error:
                raise GHLResponseError("Response body is not the expected shape") from error
            if not isinstance(items, list):
                raise GHLResponseError("Response body is not the expected shape")
            definitions = [
                self._validate(item, GHLCustomFieldDefinition, "custom field") for item in items
            ]
            self._field_ids[location_id] = {
                definition.field_key: definition.id for definition in definitions
            }

        known = self._field_ids[location_id]
        missing = [key for key in DEAL_FIELDS if key not in known]
        if missing:
            raise GHLResponseError(f"Custom fields missing in GoHighLevel: {', '.join(missing)}")
        return known

    @staticmethod
    def _as_text(value: str | float | bool | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise GHLResponseError("A deal text field has an unexpected type")
        return value.strip() or None

    @staticmethod
    def _as_number(value: str | float | bool | None) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise GHLResponseError("A deal number field has an unexpected type")
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation as error:
            raise GHLResponseError("A deal number field is not a number") from error
        if not number.is_finite():
            raise GHLResponseError("A deal number field is not a number")
        return number

    def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """Send an authenticated GET, retrying temporary failures (reads are safe to repeat)."""
        return self._send("GET", url, params=params)

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Send a request with retries. Only call this for requests that are safe to repeat."""
        return call_with_retries(
            lambda: self._send_once(method, url, params, payload), self.retry_policy
        )

    def _send_once(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None,
        payload: dict[str, object] | None,
    ) -> httpx.Response:
        """One attempt: return the response, or raise a classified error."""
        token = self.settings.ghl_api_token.get_secret_value()

        try:
            response = self.http_client.request(
                method,
                url,
                params=params,
                json=payload,
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
        return response

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
            error = GHLRateLimitError(
                message,
                status_code=status,
                retry_after=parse_retry_after(response.headers.get("Retry-After")),
            )
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

    @classmethod
    def _parse_model(
        cls, response: httpx.Response, key: str, model: type[Model], label: str
    ) -> Model:
        """Validate response.json()[key] as `model`, reporting where it failed, never the values."""
        try:
            data = response.json()[key]
        except (ValueError, KeyError, TypeError) as error:
            raise GHLResponseError("Response body is not the expected shape") from error
        return cls._validate(data, model, label)

    @staticmethod
    def _validate(data: object, model: type[Model], label: str) -> Model:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            problems = ", ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
                for item in error.errors()
            )
            raise GHLResponseError(f"Invalid {label} in response ({problems})") from error

    @staticmethod
    def _to_customer(contact: GHLContact) -> Customer:
        """Convert a GoHighLevel contact into OrderBridge's vendor-independent Customer."""
        company = (contact.company_name or "").strip()
        person = " ".join(part for part in (contact.first_name, contact.last_name) if part).strip()
        name = company or person or (contact.name or "").strip()
        if not name:
            raise GHLResponseError("Contact has no company name, person name or display name")

        return Customer(
            name=name,
            customer_type="Company" if company else "Individual",
            email=(contact.email or "").strip() or None,
        )
