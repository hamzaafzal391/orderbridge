"""Alembic environment: runs migrations against DATABASE_URL.

The URL comes from the environment or `.env` through DatabaseSettings, so migrations do not need
the ERPNext or GoHighLevel settings. It is never printed.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import create_engine

from app.config import DatabaseSettings
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = DatabaseSettings().database_url.get_secret_value()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
