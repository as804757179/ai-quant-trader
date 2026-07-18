"""Add observed research evidence and 2026 official trading-calendar coverage.

Revision ID: 018
Revises: 017
"""

from alembic import op


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


SSE_2026_CALENDAR = (
    "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml"
)
SZSE_2026_CALENDAR = (
    "https://www.szse.cn/disclosure/notice/general/t20251222_618087.html"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_evidence_batches (
            batch_id UUID PRIMARY KEY,
            provider VARCHAR(64) NOT NULL CHECK (provider NOT IN ('unknown', 'synthetic')),
            source VARCHAR(128) NOT NULL CHECK (source NOT IN ('unknown', 'synthetic')),
            fetch_endpoint TEXT NOT NULL,
            requested_symbols INTEGER NOT NULL CHECK (requested_symbols >= 0),
            returned_items INTEGER NOT NULL CHECK (returned_items >= 0),
            accepted_items INTEGER NOT NULL CHECK (accepted_items >= 0),
            rejected_items INTEGER NOT NULL CHECK (rejected_items >= 0),
            status VARCHAR(32) NOT NULL CHECK (
                status IN ('running', 'success', 'partial', 'fetch_failed',
                           'validation_failed', 'write_failed')
            ),
            failure_reason TEXT,
            raw_response_hash VARCHAR(64),
            collector_version VARCHAR(64) NOT NULL,
            normalizer_version VARCHAR(64) NOT NULL,
            usage_status VARCHAR(32) NOT NULL CHECK (
                usage_status IN ('review_required', 'approved')
            ),
            started_at TIMESTAMPTZ NOT NULL,
            fetched_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (raw_response_hash IS NULL OR raw_response_hash ~ '^[0-9a-f]{64}$')
        );
        CREATE INDEX idx_research_evidence_batches_received_at
        ON market.research_evidence_batches (received_at DESC);
        CREATE INDEX idx_research_evidence_batches_status
        ON market.research_evidence_batches (status, received_at DESC);

        CREATE TABLE market.research_evidence (
            evidence_id UUID PRIMARY KEY,
            batch_id UUID NOT NULL REFERENCES market.research_evidence_batches(batch_id),
            evidence_type VARCHAR(32) NOT NULL CHECK (
                evidence_type IN ('announcement', 'news', 'financial_report')
            ),
            stock_code VARCHAR(12) NOT NULL,
            source_document_id VARCHAR(128) NOT NULL,
            provider VARCHAR(64) NOT NULL CHECK (provider NOT IN ('unknown', 'synthetic')),
            source VARCHAR(128) NOT NULL CHECK (source NOT IN ('unknown', 'synthetic')),
            publisher_name TEXT NOT NULL,
            title TEXT NOT NULL,
            document_url TEXT NOT NULL,
            source_published_date DATE,
            source_published_at TIMESTAMPTZ,
            source_timestamp_raw TEXT,
            publication_time_precision VARCHAR(16) NOT NULL CHECK (
                publication_time_precision IN ('exact', 'date', 'unresolved')
            ),
            fetched_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL,
            first_observed_at TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ NOT NULL,
            availability_basis VARCHAR(32) NOT NULL CHECK (
                availability_basis IN ('source_timestamp', 'system_first_observed')
            ),
            raw_hash VARCHAR(64),
            document_bytes INTEGER CHECK (document_bytes IS NULL OR document_bytes >= 0),
            quality_status VARCHAR(16) NOT NULL CHECK (
                quality_status IN ('observed', 'rejected')
            ),
            reject_reason TEXT,
            fallback_used BOOLEAN NOT NULL DEFAULT FALSE CHECK (fallback_used = FALSE),
            collector_version VARCHAR(64) NOT NULL,
            normalizer_version VARCHAR(64) NOT NULL,
            usage_status VARCHAR(32) NOT NULL CHECK (
                usage_status IN ('review_required', 'approved')
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (provider, source_document_id, raw_hash),
            CHECK (raw_hash IS NULL OR raw_hash ~ '^[0-9a-f]{64}$'),
            CHECK (
                (quality_status = 'observed' AND raw_hash IS NOT NULL AND reject_reason IS NULL)
                OR (quality_status = 'rejected' AND reject_reason IS NOT NULL)
            )
        );
        CREATE INDEX idx_research_evidence_lookup
        ON market.research_evidence (stock_code, evidence_type, available_at DESC);
        CREATE INDEX idx_research_evidence_batch
        ON market.research_evidence (batch_id);
        CREATE INDEX idx_research_evidence_quality
        ON market.research_evidence (quality_status, received_at DESC);

        ALTER TABLE market.research_evidence_batches OWNER TO quant_admin;
        ALTER TABLE market.research_evidence OWNER TO quant_admin;
        """
    )
    op.execute(
        f"""
        WITH calendar_sources(exchange, source, source_reference) AS (
            VALUES
                ('SH', 'sse', '{SSE_2026_CALENDAR}'),
                ('SZ', 'szse', '{SZSE_2026_CALENDAR}')
        )
        INSERT INTO market.trading_calendar
            (exchange, trading_date, is_trading_day, session_open_time,
             session_close_time, timezone, source, source_reference, status)
        SELECT calendar_sources.exchange,
               day::date,
               EXTRACT(ISODOW FROM day) < 6
                   AND NOT (
                       day::date BETWEEN DATE '2026-01-01' AND DATE '2026-01-03'
                       OR day::date BETWEEN DATE '2026-02-15' AND DATE '2026-02-23'
                       OR day::date BETWEEN DATE '2026-04-04' AND DATE '2026-04-06'
                       OR day::date BETWEEN DATE '2026-05-01' AND DATE '2026-05-05'
                       OR day::date BETWEEN DATE '2026-06-19' AND DATE '2026-06-21'
                       OR day::date BETWEEN DATE '2026-09-25' AND DATE '2026-09-27'
                       OR day::date BETWEEN DATE '2026-10-01' AND DATE '2026-10-07'
                   ),
               CASE WHEN EXTRACT(ISODOW FROM day) < 6
                          AND NOT (
                              day::date BETWEEN DATE '2026-01-01' AND DATE '2026-01-03'
                              OR day::date BETWEEN DATE '2026-02-15' AND DATE '2026-02-23'
                              OR day::date BETWEEN DATE '2026-04-04' AND DATE '2026-04-06'
                              OR day::date BETWEEN DATE '2026-05-01' AND DATE '2026-05-05'
                              OR day::date BETWEEN DATE '2026-06-19' AND DATE '2026-06-21'
                              OR day::date BETWEEN DATE '2026-09-25' AND DATE '2026-09-27'
                              OR day::date BETWEEN DATE '2026-10-01' AND DATE '2026-10-07'
                          ) THEN TIME '09:30:00' END,
               CASE WHEN EXTRACT(ISODOW FROM day) < 6
                          AND NOT (
                              day::date BETWEEN DATE '2026-01-01' AND DATE '2026-01-03'
                              OR day::date BETWEEN DATE '2026-02-15' AND DATE '2026-02-23'
                              OR day::date BETWEEN DATE '2026-04-04' AND DATE '2026-04-06'
                              OR day::date BETWEEN DATE '2026-05-01' AND DATE '2026-05-05'
                              OR day::date BETWEEN DATE '2026-06-19' AND DATE '2026-06-21'
                              OR day::date BETWEEN DATE '2026-09-25' AND DATE '2026-09-27'
                              OR day::date BETWEEN DATE '2026-10-01' AND DATE '2026-10-07'
                          ) THEN TIME '15:00:00' END,
               'Asia/Shanghai',
               calendar_sources.source,
               calendar_sources.source_reference,
               'confirmed'
        FROM generate_series(DATE '2026-01-01', DATE '2026-12-31', INTERVAL '1 day') day
        CROSS JOIN calendar_sources
        ON CONFLICT (exchange, trading_date) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS market.research_evidence;
        DROP TABLE IF EXISTS market.research_evidence_batches;
        """
    )
    op.execute(
        f"""
        DELETE FROM market.trading_calendar
        WHERE trading_date BETWEEN DATE '2026-01-01' AND DATE '2026-12-31'
          AND (
              (exchange = 'SH' AND source = 'sse' AND source_reference = '{SSE_2026_CALENDAR}')
              OR (exchange = 'SZ' AND source = 'szse' AND source_reference = '{SZSE_2026_CALENDAR}')
          )
        """
    )
