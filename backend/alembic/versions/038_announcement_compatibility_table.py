"""Restore the legacy announcement compatibility table when absent."""

from alembic import op


revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamental.announcements (
            id BIGSERIAL PRIMARY KEY,
            stock_code VARCHAR(10) REFERENCES fundamental.stocks(code),
            title VARCHAR(500) NOT NULL,
            category VARCHAR(50),
            publish_time TIMESTAMPTZ NOT NULL,
            content_url TEXT,
            content_text TEXT,
            is_vectorized BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_announcements_stock
        ON fundamental.announcements(stock_code, publish_time DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_announcements_cat
        ON fundamental.announcements(category)
        """
    )


def downgrade() -> None:
    raise RuntimeError("038 preserves legacy announcement compatibility and must not be downgraded")
