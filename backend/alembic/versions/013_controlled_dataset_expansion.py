"""Add controlled certified-dataset expansion audit records.

Revision ID: 013
Revises: 012
"""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.dataset_expansion_runs (
          run_id VARCHAR(80) PRIMARY KEY, dataset_id VARCHAR(80) NOT NULL,
          manifest_hash CHAR(64) NOT NULL, primary_provider VARCHAR(64) NOT NULL,
          secondary_provider VARCHAR(64) NOT NULL, date_from DATE NOT NULL,
          date_to DATE NOT NULL, status VARCHAR(24) NOT NULL CHECK(status IN
            ('pending','running','certified','rejected','fetch_failed','validation_failed','review_required')),
          started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
          failure_reason TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE market.dataset_import_checkpoints (
          run_id VARCHAR(80) NOT NULL REFERENCES market.dataset_expansion_runs(run_id),
          stock_code VARCHAR(12) NOT NULL, month_start DATE NOT NULL,
          batch_id VARCHAR(64), status VARCHAR(24) NOT NULL CHECK(status IN
            ('pending','running','certified','rejected','fetch_failed','validation_failed','review_required')),
          attempt_count INTEGER NOT NULL DEFAULT 0, rows_fetched INTEGER NOT NULL DEFAULT 0,
          rows_certified INTEGER NOT NULL DEFAULT 0, error_reason TEXT,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY(run_id,stock_code,month_start)
        );
        CREATE TABLE market.provider_validation_reviews (
          run_id VARCHAR(80) NOT NULL REFERENCES market.dataset_expansion_runs(run_id),
          stock_code VARCHAR(12) NOT NULL, trading_date DATE NOT NULL,
          primary_provider VARCHAR(64) NOT NULL, secondary_provider VARCHAR(64) NOT NULL,
          result VARCHAR(16) NOT NULL CHECK(result IN ('PASS','REVIEW','FAIL')),
          comparison JSONB NOT NULL, endpoint_versions JSONB NOT NULL,
          reviewed_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(run_id,stock_code,trading_date)
        );
        CREATE TABLE market.security_status_reviews (
          run_id VARCHAR(80) NOT NULL REFERENCES market.dataset_expansion_runs(run_id),
          stock_code VARCHAR(12) NOT NULL, effective_from DATE NOT NULL,
          effective_to DATE NOT NULL, status VARCHAR(24) NOT NULL CHECK(status IN
            ('normal_trade','suspended','exchange_closed','not_listed','delisted','ST','price_limit_exempt','provider_missing','unresolved')),
          evidence_source TEXT NOT NULL, evidence_version VARCHAR(64) NOT NULL,
          reviewed_at TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(run_id,stock_code,effective_from,status)
        );
        """
    )
    op.execute(
        """
        INSERT INTO market.trading_calendar
          (exchange,trading_date,is_trading_day,session_open_time,session_close_time,
           timezone,source,source_reference,status)
        SELECT exchange,d,
          EXTRACT(ISODOW FROM d)<6 AND NOT (
            d BETWEEN DATE '2025-10-01' AND DATE '2025-10-08' OR
            d BETWEEN DATE '2026-01-01' AND DATE '2026-01-04' OR
            d BETWEEN DATE '2026-02-15' AND DATE '2026-02-23' OR
            d BETWEEN DATE '2026-04-04' AND DATE '2026-04-06' OR
            d BETWEEN DATE '2026-05-01' AND DATE '2026-05-05' OR
            d BETWEEN DATE '2026-06-19' AND DATE '2026-06-21'),
          CASE WHEN EXTRACT(ISODOW FROM d)<6 AND NOT (
            d BETWEEN DATE '2025-10-01' AND DATE '2025-10-08' OR
            d BETWEEN DATE '2026-01-01' AND DATE '2026-01-04' OR
            d BETWEEN DATE '2026-02-15' AND DATE '2026-02-23' OR
            d BETWEEN DATE '2026-04-04' AND DATE '2026-04-06' OR
            d BETWEEN DATE '2026-05-01' AND DATE '2026-05-05' OR
            d BETWEEN DATE '2026-06-19' AND DATE '2026-06-21') THEN TIME '09:30' END,
          CASE WHEN EXTRACT(ISODOW FROM d)<6 AND NOT (
            d BETWEEN DATE '2025-10-01' AND DATE '2025-10-08' OR
            d BETWEEN DATE '2026-01-01' AND DATE '2026-01-04' OR
            d BETWEEN DATE '2026-02-15' AND DATE '2026-02-23' OR
            d BETWEEN DATE '2026-04-04' AND DATE '2026-04-06' OR
            d BETWEEN DATE '2026-05-01' AND DATE '2026-05-05' OR
            d BETWEEN DATE '2026-06-19' AND DATE '2026-06-21') THEN TIME '15:00' END,
          'Asia/Shanghai',CASE WHEN exchange='SH' THEN 'sse' ELSE 'szse' END,
          CASE WHEN exchange='SH'
            THEN 'SSE official annual holiday closure notices for 2025 and 2026'
            ELSE 'SZSE official annual holiday closure notices for 2025 and 2026' END,
          'confirmed'
        FROM generate_series(DATE '2025-07-01',DATE '2026-06-30',INTERVAL '1 day') d
        CROSS JOIN (VALUES('SH'),('SZ')) e(exchange)
        ON CONFLICT(exchange,trading_date) DO NOTHING
        """
    )
    for table in (
        "dataset_expansion_runs", "dataset_import_checkpoints",
        "provider_validation_reviews", "security_status_reviews",
    ):
        op.execute(f"ALTER TABLE market.{table} OWNER TO quant_admin")


def downgrade() -> None:
    op.execute("DROP TABLE market.security_status_reviews")
    op.execute("DROP TABLE market.provider_validation_reviews")
    op.execute("DROP TABLE market.dataset_import_checkpoints")
    op.execute("DROP TABLE market.dataset_expansion_runs")
    op.execute("DELETE FROM market.trading_calendar WHERE trading_date<DATE '2026-06-01'")
