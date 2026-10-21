"""Repository behaviour against a real PostgreSQL, including true concurrency.

Run with:  DATABASE_URL_TEST=postgresql+psycopg://... pytest -m integration
Locally, `docker compose up -d db` provides the database (see docker-compose.yml).
These tests are excluded from the default run, which stays offline.
"""

import os
import threading
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from app.db.models import Base
from app.db.repository import Repository
from app.db.session import make_engine, make_sessionmaker

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
WORKERS = 16


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


@pytest.fixture
def repo(engine: Engine) -> Repository:
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE audit_log, object_links, idempotency_keys RESTART IDENTITY")
        )
    return Repository(make_sessionmaker(engine))


def race(work, workers: int = WORKERS) -> list:
    """Run `work(index)` in many threads released at the same instant; return all results."""
    barrier = threading.Barrier(workers)
    results: list = [None] * workers

    def run(index: int) -> None:
        barrier.wait()
        results[index] = work(index)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


# --- the migration matches the models ------------------------------------------------------


def test_the_migration_creates_exactly_the_modelled_tables_and_columns(engine: Engine) -> None:
    schema = inspect(engine)

    assert {name for name in schema.get_table_names() if name != "alembic_version"} == set(
        Base.metadata.tables
    )
    for name, table in Base.metadata.tables.items():
        assert {column["name"] for column in schema.get_columns(name)} == set(table.columns.keys())


def test_object_links_are_unique_per_crm_object(engine: Engine) -> None:
    constraints = inspect(engine).get_unique_constraints("object_links")

    assert [c["column_names"] for c in constraints] == [["crm_type", "crm_id"]]


# --- the same rules as the unit tests, on the real database ---------------------------------


def test_claim_lifecycle(repo: Repository) -> None:
    assert repo.claim("k") == "claimed"
    assert repo.claim("k") == "in_progress"

    repo.mark_succeeded("k", {"order": "SAL-ORD-1"})

    assert repo.claim("k") == "duplicate"
    state = repo.get_state("k")
    assert state is not None
    assert state.result == {"order": "SAL-ORD-1"}


def test_a_failed_key_is_reclaimed_with_a_new_attempt(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_failed("k", "ERPNextTemporaryError")

    assert repo.claim("k") == "reclaimed"

    state = repo.get_state("k")
    assert state is not None
    assert (state.status, state.attempts) == ("processing", 2)


def test_links_and_audit_round_trip(repo: Repository) -> None:
    repo.save_link("opportunity", "opp-1", "Sales Order", "SAL-ORD-1")
    repo.save_link("opportunity", "opp-1", "Sales Order", "SAL-ORD-2")
    repo.record_audit("k", "create_order", "created", {"order": "SAL-ORD-2", "lines": 1})

    link = repo.get_link("opportunity", "opp-1")
    entries = repo.list_audit("k")

    assert link is not None
    assert link.erp_name == "SAL-ORD-2"
    assert [(e.action, e.detail) for e in entries] == [
        ("create_order", {"order": "SAL-ORD-2", "lines": 1})
    ]
    assert entries[0].created_at.tzinfo is not None


# --- the point of the database: simultaneous workers --------------------------------------


def test_only_one_of_many_simultaneous_claims_wins(engine: Engine, repo: Repository) -> None:
    sessions = make_sessionmaker(engine)

    results = race(lambda _: Repository(sessions).claim("deal-won:1"))

    assert Counter(results) == {"claimed": 1, "in_progress": WORKERS - 1}


def test_only_one_of_many_simultaneous_takeovers_of_a_stale_key_wins(
    engine: Engine, repo: Repository
) -> None:
    sessions = make_sessionmaker(engine)
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    Repository(sessions, clock=lambda: long_ago).claim("deal-won:2")  # a worker that crashed

    results = race(lambda _: Repository(sessions).claim("deal-won:2"))

    assert Counter(results) == {"reclaimed": 1, "in_progress": WORKERS - 1}
    state = repo.get_state("deal-won:2")
    assert state is not None
    assert state.attempts == 2


def test_only_one_of_many_simultaneous_replays_of_a_failed_key_wins(
    engine: Engine, repo: Repository
) -> None:
    sessions = make_sessionmaker(engine)
    repo.claim("deal-won:3")
    repo.mark_failed("deal-won:3", "ERPNextTemporaryError")

    results = race(lambda _: Repository(sessions).claim("deal-won:3"))

    assert Counter(results) == {"reclaimed": 1, "in_progress": WORKERS - 1}


def test_simultaneous_claims_of_a_finished_key_are_all_duplicates(
    engine: Engine, repo: Repository
) -> None:
    sessions = make_sessionmaker(engine)
    repo.claim("deal-won:4")
    repo.mark_succeeded("deal-won:4")

    results = race(lambda _: Repository(sessions).claim("deal-won:4"))

    assert Counter(results) == {"duplicate": WORKERS}


def test_simultaneous_saves_of_the_same_link_leave_one_row(
    engine: Engine, repo: Repository
) -> None:
    sessions = make_sessionmaker(engine)

    race(lambda index: Repository(sessions).save_link("contact", "c1", "Customer", f"Acme {index}"))

    with engine.begin() as connection:
        count = connection.execute(text("SELECT count(*) FROM object_links")).scalar_one()
    assert count == 1
