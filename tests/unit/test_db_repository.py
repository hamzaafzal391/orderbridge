from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.db.models import Base
from app.db.repository import InvalidTransitionError, Repository
from app.db.session import make_engine, make_sessionmaker


class FakeClock:
    """A clock the test controls, so stale-claim rules can be checked without waiting."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo(tmp_path: Path, clock: FakeClock) -> Repository:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return Repository(make_sessionmaker(engine), clock=clock, stale_after=timedelta(minutes=10))


# --- claiming a key -----------------------------------------------------------------------


def test_a_new_key_is_claimed(repo: Repository) -> None:
    assert repo.claim("ghl:opportunity-won:1") == "claimed"
    assert repo.status_of("ghl:opportunity-won:1") == "processing"


def test_a_key_being_processed_is_in_progress_for_everyone_else(repo: Repository) -> None:
    repo.claim("k")

    assert repo.claim("k") == "in_progress"


def test_a_succeeded_key_is_a_duplicate(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_succeeded("k", {"order": "SAL-ORD-1"})

    assert repo.claim("k") == "duplicate"
    assert repo.status_of("k") == "succeeded"


def test_a_failed_key_can_be_reclaimed_for_a_replay(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_failed("k", "ERPNextTemporaryError")

    assert repo.status_of("k") == "failed"
    assert repo.claim("k") == "reclaimed"
    assert repo.status_of("k") == "processing"


def test_attempts_count_every_takeover(repo: Repository, clock: FakeClock) -> None:
    repo.claim("k")
    repo.mark_failed("k", "ERPNextTemporaryError")
    repo.claim("k")
    clock.advance(minutes=11)
    repo.claim("k")  # stale, taken over again

    assert _attempts(repo, "k") == 3


def test_a_stale_processing_key_is_reclaimed_after_the_timeout(
    repo: Repository, clock: FakeClock
) -> None:
    repo.claim("k")  # a worker takes it, then crashes

    clock.advance(minutes=9, seconds=59)
    assert repo.claim("k") == "in_progress"  # not stale yet

    clock.advance(seconds=2)
    assert repo.claim("k") == "reclaimed"  # now older than 10 minutes


def test_a_reclaimed_key_is_fresh_again(repo: Repository, clock: FakeClock) -> None:
    repo.claim("k")
    clock.advance(minutes=11)
    assert repo.claim("k") == "reclaimed"

    assert repo.claim("k") == "in_progress"  # the new owner's claim is respected


def test_keys_do_not_affect_each_other(repo: Repository) -> None:
    assert repo.claim("a") == "claimed"
    assert repo.claim("b") == "claimed"


# --- finishing a key ----------------------------------------------------------------------


def test_results_are_stored_as_given(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_succeeded("k", {"order": "SAL-ORD-1", "lines": 1, "held": False, "note": None})

    assert _result(repo, "k") == {"order": "SAL-ORD-1", "lines": 1, "held": False, "note": None}


def test_a_failure_stores_only_the_error_class(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_failed("k", "ERPNextTemporaryError")

    assert _result(repo, "k") == {"error": "ERPNextTemporaryError"}


@pytest.mark.parametrize("finish", ["mark_succeeded", "mark_failed"])
def test_finishing_an_unknown_key_is_an_error(repo: Repository, finish: str) -> None:
    with pytest.raises(InvalidTransitionError):
        _finish(repo, finish, "never-claimed")


def test_finishing_twice_is_an_error(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_succeeded("k")

    with pytest.raises(InvalidTransitionError):
        repo.mark_succeeded("k")
    with pytest.raises(InvalidTransitionError):
        repo.mark_failed("k", "SomeError")


def test_a_failed_key_cannot_be_marked_succeeded_without_reclaiming(repo: Repository) -> None:
    repo.claim("k")
    repo.mark_failed("k", "SomeError")

    with pytest.raises(InvalidTransitionError):
        repo.mark_succeeded("k")


@pytest.mark.parametrize(
    "bad_result",
    [
        {"customer": {"name": "nested"}},
        {"names": ["a", "b"]},
        {"when": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
    ids=["nested-dict", "list", "datetime"],
)
def test_only_simple_values_can_be_stored(repo: Repository, bad_result: dict) -> None:
    repo.claim("k")

    with pytest.raises(TypeError):
        repo.mark_succeeded("k", bad_result)
    assert repo.status_of("k") == "processing"  # nothing was changed


def test_an_unknown_key_has_no_status(repo: Repository) -> None:
    assert repo.status_of("missing") is None


# --- object links -------------------------------------------------------------------------


def test_a_link_can_be_saved_and_read(repo: Repository) -> None:
    repo.save_link("opportunity", "opp-1", "Sales Order", "SAL-ORD-2026-00007")

    link = repo.get_link("opportunity", "opp-1")

    assert link is not None
    assert (link.erp_doctype, link.erp_name) == ("Sales Order", "SAL-ORD-2026-00007")


def test_an_unknown_link_is_none(repo: Repository) -> None:
    assert repo.get_link("opportunity", "nope") is None


def test_saving_a_link_again_replaces_its_target(repo: Repository) -> None:
    repo.save_link("contact", "c1", "Customer", "Acme")
    repo.save_link("contact", "c1", "Customer", "Acme - Renamed")

    link = repo.get_link("contact", "c1")
    assert link is not None
    assert link.erp_name == "Acme - Renamed"


def test_the_same_id_with_a_different_type_is_a_different_link(repo: Repository) -> None:
    repo.save_link("contact", "x1", "Customer", "Acme")
    repo.save_link("opportunity", "x1", "Sales Order", "SAL-ORD-1")

    assert repo.get_link("contact", "x1").erp_name == "Acme"  # type: ignore[union-attr]
    assert repo.get_link("opportunity", "x1").erp_name == "SAL-ORD-1"  # type: ignore[union-attr]


# --- audit log ----------------------------------------------------------------------------


def test_audit_entries_are_listed_in_order_for_their_key(
    repo: Repository, clock: FakeClock
) -> None:
    repo.record_audit("k1", "claim", "claimed")
    clock.advance(seconds=1)
    repo.record_audit("k1", "create_order", "created", {"order": "SAL-ORD-1", "lines": 1})
    repo.record_audit("other", "claim", "claimed")

    entries = repo.list_audit("k1")

    assert [(e.action, e.outcome) for e in entries] == [
        ("claim", "claimed"),
        ("create_order", "created"),
    ]
    assert entries[0].detail is None
    assert entries[1].detail == {"order": "SAL-ORD-1", "lines": 1}
    assert entries[0].created_at < entries[1].created_at
    assert entries[0].created_at.tzinfo is not None


def test_audit_detail_must_be_simple(repo: Repository) -> None:
    with pytest.raises(TypeError):
        repo.record_audit("k", "action", "outcome", {"customer": {"email": "x@example.com"}})

    assert repo.list_audit("k") == []


# --- the tables hold ids and statuses only ------------------------------------------------


def test_tables_have_only_the_documented_columns(tmp_path: Path) -> None:
    """A guard: adding a column (for example an email) must be a deliberate, reviewed change."""
    engine = make_engine(f"sqlite:///{tmp_path / 'cols.db'}")
    Base.metadata.create_all(engine)
    columns = {
        table: {column["name"] for column in inspect(engine).get_columns(table)}
        for table in inspect(engine).get_table_names()
    }

    assert columns == {
        "idempotency_keys": {"key", "status", "attempts", "result", "created_at", "updated_at"},
        "object_links": {"id", "crm_type", "crm_id", "erp_doctype", "erp_name", "created_at"},
        "audit_log": {"id", "key", "action", "outcome", "detail", "created_at"},
    }


# --- helpers ------------------------------------------------------------------------------


def _attempts(repo: Repository, key: str) -> int:
    state = repo.get_state(key)
    assert state is not None
    return state.attempts


def _result(repo: Repository, key: str) -> dict | None:
    state = repo.get_state(key)
    assert state is not None
    return state.result


def _finish(repo: Repository, finish: str, key: str) -> None:
    if finish == "mark_succeeded":
        repo.mark_succeeded(key)
    else:
        repo.mark_failed(key, "SomeError")
