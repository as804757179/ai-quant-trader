"""Add order execution-safety audit fields.

Revision ID: 006
Revises: 005
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column, definition in [
        ("order_source", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
        ("order_reason", "TEXT"),
        ("caller", "VARCHAR(64)"),
        ("approval_status", "VARCHAR(20) NOT NULL DEFAULT 'unknown'"),
        ("approval_id", "VARCHAR(100)"),
        ("risk_check_id", "VARCHAR(100)"),
        ("data_certification_status", "VARCHAR(20) NOT NULL DEFAULT 'unknown'"),
        ("created_by", "VARCHAR(64)"),
        ("created_from_task", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ]:
        op.execute(
            f"ALTER TABLE trade.orders ADD COLUMN IF NOT EXISTS {column} {definition}"
        )
    op.execute(
        "UPDATE trade.orders SET order_source = trigger_source "
        "WHERE order_source = 'unknown' AND trigger_source IS NOT NULL"
    )


def downgrade() -> None:
    for column in [
        "created_from_task",
        "created_by",
        "data_certification_status",
        "risk_check_id",
        "approval_id",
        "approval_status",
        "caller",
        "order_reason",
        "order_source",
    ]:
        op.execute(f"ALTER TABLE trade.orders DROP COLUMN IF EXISTS {column}")
