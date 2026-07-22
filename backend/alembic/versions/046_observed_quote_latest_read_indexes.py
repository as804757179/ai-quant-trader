"""Add observed quote latest-row read indexes.

Revision ID: 046
Revises: 045
"""

from alembic import op


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX idx_quotes_stock_code_time_desc
            ON market.quotes (stock_code, time DESC);

        CREATE INDEX idx_quote_provenance_observed_latest
            ON market.quote_provenance (stock_code, quote_time DESC, received_at DESC)
            WHERE quality_status = 'pass' AND fallback_used = FALSE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS market.idx_quote_provenance_observed_latest;
        DROP INDEX IF EXISTS market.idx_quotes_stock_code_time_desc;
        """
    )
