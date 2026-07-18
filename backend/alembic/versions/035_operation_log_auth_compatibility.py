"""Restore audit columns used by authenticated service operations."""

from alembic import op


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit.operation_logs
            ADD COLUMN IF NOT EXISTS session_id VARCHAR(64),
            ADD COLUMN IF NOT EXISTS ip_address INET,
            ADD COLUMN IF NOT EXISTS entity_type VARCHAR(50),
            ADD COLUMN IF NOT EXISTS entity_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS before_data JSONB,
            ADD COLUMN IF NOT EXISTS after_data JSONB;
        """
    )


def downgrade() -> None:
    raise RuntimeError("035 preserves authenticated audit compatibility and must not be downgraded")
