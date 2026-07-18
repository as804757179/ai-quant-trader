"""Allow explicit in-progress status for realtime quote batches.

Revision ID: 017
Revises: 016
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.quote_batches
            DROP CONSTRAINT quote_batches_status_check;
        ALTER TABLE market.quote_batches
            ADD CONSTRAINT quote_batches_status_check
            CHECK (status IN (
                'running', 'success', 'partial', 'fetch_failed', 'validation_failed', 'write_failed'
            ));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.quote_batches
            ADD CONSTRAINT quote_batches_no_running_before_downgrade
            CHECK (status <> 'running') NOT VALID;
        ALTER TABLE market.quote_batches
            VALIDATE CONSTRAINT quote_batches_no_running_before_downgrade;
        ALTER TABLE market.quote_batches
            DROP CONSTRAINT quote_batches_status_check;
        ALTER TABLE market.quote_batches
            ADD CONSTRAINT quote_batches_status_check
            CHECK (status IN ('success', 'partial', 'fetch_failed', 'validation_failed', 'write_failed'));
        ALTER TABLE market.quote_batches
            DROP CONSTRAINT quote_batches_no_running_before_downgrade;
        """
    )
