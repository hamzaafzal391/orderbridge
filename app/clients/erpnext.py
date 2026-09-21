from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings


class ERPNextClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = str(self.settings.erpnext_base_url).rstrip("/")

    def get_customer(self, customer_name: str) -> dict[str, Any]:
        encoded_name = quote(customer_name, safe="")
        url = f"{self.base_url}/api/resource/Customer/{encoded_name}"

        api_key = self.settings.erpnext_api_key.get_secret_value()
        api_secret = self.settings.erpnext_api_secret.get_secret_value()

        response = httpx.get(
            url,
            headers={
                "Authorization": f"token {api_key}:{api_secret}",
                "Accept": "application/json",
            },
            timeout=10.0,
        )

        response.raise_for_status()
        payload = response.json()

        return payload["data"]