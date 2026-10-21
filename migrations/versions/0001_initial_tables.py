"""Initial tables: idempotency keys, object links, audit log

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "object_links",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("crm_type", sa.String(50), nullable=False),
        sa.Column("crm_id", sa.String(200), nullable=False),
        sa.Column("erp_doctype", sa.String(100), nullable=False),
        sa.Column("erp_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("crm_type", "crm_id", name="uq_object_links_crm"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("detail", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_key", "audit_log", ["key"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_key", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("object_links")
    op.drop_table("idempotency_keys")
