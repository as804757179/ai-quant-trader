"""Add K-line provenance and certification sidecar tables.

Revision ID: 005
Revises: 004
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.data_batches (
            batch_id VARCHAR(64) PRIMARY KEY,
            provider VARCHAR(64) NOT NULL,
            source VARCHAR(64) NOT NULL,
            period VARCHAR(10) NOT NULL,
            start_date DATE,
            end_date DATE,
            fetch_time TIMESTAMPTZ NOT NULL,
            importer_version VARCHAR(64) NOT NULL,
            total_rows INTEGER NOT NULL DEFAULT 0,
            accepted_rows INTEGER NOT NULL DEFAULT 0,
            rejected_rows INTEGER NOT NULL DEFAULT 0,
            quality_score NUMERIC(5,2),
            status VARCHAR(20) NOT NULL,
            reject_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.kline_provenance (
            time TIMESTAMPTZ NOT NULL,
            stock_code VARCHAR(10) NOT NULL,
            period VARCHAR(10) NOT NULL,
            provider VARCHAR(64) NOT NULL DEFAULT 'unknown',
            source VARCHAR(64) NOT NULL DEFAULT 'unknown',
            fetch_time TIMESTAMPTZ,
            batch_id VARCHAR(64),
            quality_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
            quality_score NUMERIC(5,2),
            is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
            raw_hash VARCHAR(128),
            importer_version VARCHAR(64),
            certification_status VARCHAR(20) NOT NULL DEFAULT 'uncertified',
            certification_time TIMESTAMPTZ,
            reject_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (time, stock_code, period),
            FOREIGN KEY (time, stock_code, period)
                REFERENCES market.klines(time, stock_code, period)
                ON DELETE CASCADE,
            FOREIGN KEY (batch_id) REFERENCES market.data_batches(batch_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_kline_provenance_certified
        ON market.kline_provenance(stock_code, period, certification_status, time DESC)
        """
    )
    op.execute(
        """
        INSERT INTO market.kline_provenance
            (time, stock_code, period, provider, source, quality_status,
             is_synthetic, certification_status, reject_reason)
        SELECT time, stock_code, period, 'unknown', 'unknown', 'unknown',
               FALSE, 'uncertified', 'legacy data has no provenance'
        FROM market.klines
        ON CONFLICT (time, stock_code, period) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.kline_provenance")
    op.execute("DROP TABLE IF EXISTS market.data_batches")
