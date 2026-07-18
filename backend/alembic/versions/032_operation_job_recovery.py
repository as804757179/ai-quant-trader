"""Add recovery leases for persisted operation Jobs.

Revision ID: 032
Revises: 031
"""

from alembic import op


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit.async_jobs
            ADD COLUMN lease_token UUID,
            ADD COLUMN lease_expires_at TIMESTAMPTZ;
        CREATE INDEX idx_async_jobs_operation_lease_recovery
            ON audit.async_jobs (lease_expires_at, created_at)
            WHERE status = 'running' AND lease_expires_at IS NOT NULL;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "032 preserves operation Job recovery evidence and cannot be downgraded destructively"
    )
