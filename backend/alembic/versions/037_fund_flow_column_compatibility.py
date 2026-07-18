"""Restore legacy fund-flow columns without rewriting existing data."""

from alembic import op


revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.fund_flows
            ADD COLUMN IF NOT EXISTS super_large_in NUMERIC(20, 2),
            ADD COLUMN IF NOT EXISTS large_in NUMERIC(20, 2),
            ADD COLUMN IF NOT EXISTS medium_in NUMERIC(20, 2),
            ADD COLUMN IF NOT EXISTS small_in NUMERIC(20, 2),
            ADD COLUMN IF NOT EXISTS north_net_in NUMERIC(20, 2);
        """
    )


def downgrade() -> None:
    raise RuntimeError("037 preserves legacy fund-flow compatibility and must not be downgraded")
