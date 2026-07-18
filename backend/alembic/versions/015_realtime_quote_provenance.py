"""Add auditable realtime quote batches and row provenance.

Revision ID: 015
Revises: 014
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.quote_batches (
            batch_id UUID PRIMARY KEY,
            provider VARCHAR(64) NOT NULL CHECK (provider NOT IN ('unknown', 'synthetic')),
            source VARCHAR(128) NOT NULL CHECK (source NOT IN ('unknown', 'synthetic')),
            fetch_endpoint TEXT NOT NULL,
            requested_symbols INTEGER NOT NULL CHECK (requested_symbols >= 0),
            returned_symbols INTEGER NOT NULL CHECK (returned_symbols >= 0),
            accepted_symbols INTEGER NOT NULL CHECK (accepted_symbols >= 0),
            rejected_symbols INTEGER NOT NULL CHECK (rejected_symbols >= 0),
            status VARCHAR(32) NOT NULL CHECK (status IN ('success', 'partial', 'fetch_failed', 'validation_failed', 'write_failed')),
            failure_reason TEXT,
            raw_response_hash CHAR(64),
            collector_version VARCHAR(64) NOT NULL,
            normalizer_version VARCHAR(64) NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            fetched_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_quote_batches_received_at ON market.quote_batches (received_at DESC);
        CREATE INDEX idx_quote_batches_status ON market.quote_batches (status, received_at DESC);

        CREATE TABLE market.quote_provenance (
            quote_time TIMESTAMPTZ NOT NULL,
            stock_code VARCHAR(10) NOT NULL,
            batch_id UUID NOT NULL REFERENCES market.quote_batches(batch_id),
            provider VARCHAR(64) NOT NULL CHECK (provider NOT IN ('unknown', 'synthetic')),
            source VARCHAR(128) NOT NULL CHECK (source NOT IN ('unknown', 'synthetic')),
            fetch_endpoint TEXT NOT NULL,
            provider_time TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL,
            raw_hash CHAR(64) NOT NULL,
            quality_status VARCHAR(16) NOT NULL CHECK (quality_status IN ('pass', 'rejected')),
            reject_reason TEXT,
            fallback_used BOOLEAN NOT NULL DEFAULT FALSE CHECK (fallback_used = FALSE),
            collector_version VARCHAR(64) NOT NULL,
            normalizer_version VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (quote_time, stock_code)
        );
        CREATE INDEX idx_quote_provenance_batch ON market.quote_provenance (batch_id);
        CREATE INDEX idx_quote_provenance_received_at ON market.quote_provenance (received_at DESC);

        ALTER TABLE market.quote_batches OWNER TO quant_admin;
        ALTER TABLE market.quote_provenance OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE market.quote_provenance;
        DROP TABLE market.quote_batches;
        """
    )
