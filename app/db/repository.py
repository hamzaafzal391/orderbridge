"""Idempotency keys, object links and the audit log.

Every method runs in its own short transaction. Only small simple values (ids, statuses, error
class names) may be stored: never emails, tokens, response bodies or other customer data.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, IdempotencyKey, ObjectLink

# claimed:     the key is new; you own the work and must finish it with mark_succeeded/mark_failed
# duplicate:   the work already succeeded; do nothing
# in_progress: another worker is on it right now; do nothing
# reclaimed:   an earlier attempt failed or went stale (crashed); you own the work again
ClaimResult = Literal["claimed", "duplicate", "in_progress", "reclaimed"]

# A "processing" key not touched for this long is assumed to belong to a crashed worker.
DEFAULT_STALE_AFTER = timedelta(minutes=10)

SimpleValue = str | int | float | bool | None


class InvalidTransitionError(Exception):
    """A key was finished although it is not currently being processed."""


@dataclass(frozen=True)
class KeyState:
    status: str
    attempts: int
    result: dict[str, SimpleValue] | None


@dataclass(frozen=True)
class Link:
    erp_doctype: str
    erp_name: str


@dataclass(frozen=True)
class AuditEntry:
    key: str
    action: str
    outcome: str
    detail: dict[str, SimpleValue] | None
    created_at: datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; ours are always UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _simple(values: Mapping[str, SimpleValue] | None) -> dict[str, SimpleValue] | None:
    """Accept only flat dicts of simple values, so nothing nested or unexpected is stored."""
    if values is None:
        return None
    for name, value in values.items():
        if not isinstance(name, str) or not isinstance(value, str | int | float | bool | None):
            raise TypeError("only flat dicts of simple values (str, int, float, bool, None)")
    return dict(values)


class Repository:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utcnow,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> None:
        self._sessions = sessions
        self._clock = clock  # replaced in tests to control time
        self._stale_after = stale_after

    # --- idempotency keys ----------------------------------------------------------------

    def claim(self, key: str) -> ClaimResult:
        """Try to take ownership of a unit of work. Safe to call from many workers at once.

        Insert-or-conflict decides a new key. Taking over an old one is a compare-and-swap: it
        only succeeds if the row is exactly as we just read it, so two workers can never both
        win.
        """
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                session.add(
                    IdempotencyKey(
                        key=key,
                        status="processing",
                        attempts=1,
                        result=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            return "claimed"
        except IntegrityError:
            pass  # the key already exists: decide what to do with it below

        with self._sessions.begin() as session:
            row = session.get(IdempotencyKey, key)
            if row is None:  # only if someone deleted it in between; start over
                return self.claim(key)

            if row.status == "succeeded":
                return "duplicate"

            seen_status, seen_updated_at = row.status, row.updated_at
            fresh = seen_status == "processing" and (
                _aware(seen_updated_at) > now - self._stale_after
            )
            if fresh:
                return "in_progress"

            taken = session.execute(
                update(IdempotencyKey)
                .where(
                    IdempotencyKey.key == key,
                    IdempotencyKey.status == seen_status,
                    IdempotencyKey.updated_at == seen_updated_at,
                )
                .values(
                    status="processing",
                    attempts=IdempotencyKey.attempts + 1,
                    updated_at=now,
                )
            )
            return "reclaimed" if taken.rowcount == 1 else "in_progress"

    def mark_succeeded(self, key: str, result: Mapping[str, SimpleValue] | None = None) -> None:
        self._finish(key, "succeeded", _simple(result))

    def mark_failed(self, key: str, error_class: str) -> None:
        self._finish(key, "failed", {"error": error_class})

    def _finish(self, key: str, status: str, result: dict[str, SimpleValue] | None) -> None:
        with self._sessions.begin() as session:
            done = session.execute(
                update(IdempotencyKey)
                .where(IdempotencyKey.key == key, IdempotencyKey.status == "processing")
                .values(status=status, result=result, updated_at=self._clock())
            )
            if done.rowcount != 1:
                raise InvalidTransitionError("the key is not currently being processed")

    def get_state(self, key: str) -> KeyState | None:
        with self._sessions.begin() as session:
            row = session.get(IdempotencyKey, key)
            return KeyState(row.status, row.attempts, row.result) if row else None

    def status_of(self, key: str) -> str | None:
        state = self.get_state(key)
        return state.status if state else None

    # --- object links --------------------------------------------------------------------

    def save_link(self, crm_type: str, crm_id: str, erp_doctype: str, erp_name: str) -> None:
        """Remember that a CRM object became an ERP object. Saving again replaces the target."""
        try:
            with self._sessions.begin() as session:
                session.add(
                    ObjectLink(
                        crm_type=crm_type,
                        crm_id=crm_id,
                        erp_doctype=erp_doctype,
                        erp_name=erp_name,
                        created_at=self._clock(),
                    )
                )
            return
        except IntegrityError:
            pass  # already linked: update it below

        with self._sessions.begin() as session:
            session.execute(
                update(ObjectLink)
                .where(ObjectLink.crm_type == crm_type, ObjectLink.crm_id == crm_id)
                .values(erp_doctype=erp_doctype, erp_name=erp_name)
            )

    def get_link(self, crm_type: str, crm_id: str) -> Link | None:
        with self._sessions.begin() as session:
            row = session.execute(
                select(ObjectLink).where(
                    ObjectLink.crm_type == crm_type, ObjectLink.crm_id == crm_id
                )
            ).scalar_one_or_none()
            return Link(row.erp_doctype, row.erp_name) if row else None

    # --- audit log -----------------------------------------------------------------------

    def record_audit(
        self,
        key: str,
        action: str,
        outcome: str,
        detail: Mapping[str, SimpleValue] | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            session.add(
                AuditLog(
                    key=key,
                    action=action,
                    outcome=outcome,
                    detail=_simple(detail),
                    created_at=self._clock(),
                )
            )

    def list_audit(self, key: str) -> list[AuditEntry]:
        with self._sessions.begin() as session:
            rows = session.execute(
                select(AuditLog).where(AuditLog.key == key).order_by(AuditLog.id)
            ).scalars()
            return [
                AuditEntry(row.key, row.action, row.outcome, row.detail, _aware(row.created_at))
                for row in rows
            ]
