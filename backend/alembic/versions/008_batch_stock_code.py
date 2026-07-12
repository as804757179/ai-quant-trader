"""Add stock scope to data batches.

Revision ID: 008
Revises: 007
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE market.data_batches ADD COLUMN IF NOT EXISTS stock_code VARCHAR(10)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_batches_importer_stock "
        "ON market.data_batches(importer_version, stock_code, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS market.idx_data_batches_importer_stock")
    op.execute("ALTER TABLE market.data_batches DROP COLUMN IF EXISTS stock_code")
