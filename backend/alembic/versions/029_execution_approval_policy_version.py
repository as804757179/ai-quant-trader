"""Bind execution approvals to an explicit policy version.

Revision ID: 029
Revises: 028
"""

from alembic import op


revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE trade.execution_approvals
            ADD COLUMN policy_version VARCHAR(64);
        UPDATE trade.execution_approvals
        SET policy_version = 'execution-authorization-v1'
        WHERE policy_version IS NULL;
        ALTER TABLE trade.execution_approvals
            ALTER COLUMN policy_version SET NOT NULL;
        ALTER TABLE trade.execution_approvals
            ADD CONSTRAINT chk_execution_approvals_policy_version
            CHECK (char_length(btrim(policy_version)) BETWEEN 1 AND 64);
        """
    )


def downgrade() -> None:
    raise RuntimeError("029 binds approval audit records to policy versions and must not be downgraded")
