import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from app.db.session import make_engine

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST is not set")
    return url


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    """A database built by the real migration, so the migration itself is tested."""
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", database_url)  # read by migrations/env.py
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        engine = make_engine(database_url)
        yield engine
        engine.dispose()
    finally:
        patch.undo()
