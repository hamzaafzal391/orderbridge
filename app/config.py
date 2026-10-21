from functools import lru_cache

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    erpnext_base_url: HttpUrl
    erpnext_api_key: SecretStr
    erpnext_api_secret: SecretStr
    # Required by ERPNext on every new customer; the Selling Settings have no defaults.
    erpnext_default_customer_group: str = "Commercial"
    erpnext_default_territory: str = "Rest Of The World"

    ghl_api_token: SecretStr
    ghl_base_url: HttpUrl = HttpUrl("https://services.leadconnectorhq.com")
    # GoHighLevel requires a Version header; kept configurable because docs differ on its value.
    ghl_api_version: str = "2021-07-28"

    # Optional: the CLI and the clients work without a database.
    database_url: SecretStr | None = None

    # Optional: required only to run the webhook server (`python -m app serve`). GoHighLevel's
    # workflow sends it in the X-Webhook-Secret header.
    webhook_secret: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class DatabaseSettings(BaseSettings):
    """Only the database URL, so migrations do not need the ERPNext or GoHighLevel settings."""

    database_url: SecretStr

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
