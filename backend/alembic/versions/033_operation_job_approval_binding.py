"""Bind governed operation Jobs to consumed approvals.

Revision ID: 033
Revises: 032
"""

from alembic import op


revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit.async_jobs
            ADD COLUMN operation_approval_id UUID
                REFERENCES trade.execution_approvals(approval_id) ON DELETE RESTRICT;
        CREATE UNIQUE INDEX uq_async_jobs_operation_approval
            ON audit.async_jobs (operation_approval_id)
            WHERE operation_approval_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "033 preserves operation Job approval bindings and cannot be downgraded destructively"
    )
