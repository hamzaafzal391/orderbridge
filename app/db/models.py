"""The three tables OrderBridge needs to act safely.

They hold ids, statuses and error class names only: never emails, tokens, response bodies or
other customer data.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IdempotencyKey(Base):
    """One row per unit of work (for example one "deal won" event), so it runs only once.

    status is "processing", "succeeded" or "failed".
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObjectLink(Base):
    """Remembers "this CRM object became that ERP object" (for example deal -> Sales Order)."""

    __tablename__ = "object_links"
    __table_args__ = (UniqueConstraint("crm_type", "crm_id", name="uq_object_links_crm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crm_type: Mapped[str] = mapped_column(String(50))
    crm_id: Mapped[str] = mapped_column(String(200))
    erp_doctype: Mapped[str] = mapped_column(String(100))
    erp_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """An append-only record of what OrderBridge did and how it went."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(200), index=True)
    action: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
