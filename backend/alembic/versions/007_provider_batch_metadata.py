"""Add traceable provider metadata to data batches.

Revision ID: 007
Revises: 006
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column, definition in [
        ("provider_priority", "INTEGER"),
        ("fallback_used", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("fetch_endpoint", "TEXT"),
        ("raw_hash", "VARCHAR(128)"),
    ]:
        op.execute(
            f"ALTER TABLE market.data_batches ADD COLUMN IF NOT EXISTS {column} {definition}"
        )


def downgrade() -> None:
    for column in ["raw_hash", "fetch_endpoint", "fallback_used", "provider_priority"]:
        op.execute(f"ALTER TABLE market.data_batches DROP COLUMN IF EXISTS {column}")
