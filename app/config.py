from functools import lru_cache

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    erpnext_base_url: HttpUrl
    erpnext_api_key: SecretStr
    erpnext_api_secret: SecretStr

    ghl_api_token: SecretStr
    ghl_base_url: HttpUrl = HttpUrl("https://services.leadconnectorhq.com")
    # GoHighLevel requires a Version header; kept configurable because docs differ on its value.
    ghl_api_version: str = "2021-07-28"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
