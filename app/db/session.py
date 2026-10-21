from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


class DatabaseNotConfiguredError(Exception):
    """DATABASE_URL is not set, so database features cannot be used."""


def make_engine(url: str) -> Engine:
    # pool_pre_ping drops connections the server has closed, instead of failing on first use.
    return create_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False keeps loaded rows readable after the transaction ends.
    return sessionmaker(engine, expire_on_commit=False)


def engine_from_settings(settings: Settings) -> Engine:
    url: SecretStr | None = settings.database_url
    if url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return make_engine(url.get_secret_value())
