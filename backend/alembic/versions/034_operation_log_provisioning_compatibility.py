"""Restore audit operation-log columns required by credential provisioning."""

from alembic import op


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit.operation_logs
            ADD COLUMN IF NOT EXISTS operator VARCHAR(50),
            ADD COLUMN IF NOT EXISTS result VARCHAR(32);
        """
    )


def downgrade() -> None:
    raise RuntimeError("034 preserves credential-provisioning audit compatibility and must not be downgraded")
