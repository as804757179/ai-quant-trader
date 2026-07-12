"""Create the isolated certified K-line store and pilot trading calendar.

Revision ID: 009
Revises: 008
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.certified_klines (
            stock_code VARCHAR(12) NOT NULL,
            exchange VARCHAR(4) NOT NULL CHECK (exchange IN ('SZ', 'SH')),
            period VARCHAR(10) NOT NULL,
            trading_date DATE NOT NULL,
            market_close_time TIME NOT NULL DEFAULT TIME '15:00:00',
            timezone VARCHAR(32) NOT NULL DEFAULT 'Asia/Shanghai',
            open NUMERIC(14,4) NOT NULL CHECK (open > 0),
            high NUMERIC(14,4) NOT NULL CHECK (high > 0),
            low NUMERIC(14,4) NOT NULL CHECK (low > 0),
            close NUMERIC(14,4) NOT NULL CHECK (close > 0),
            volume BIGINT NOT NULL CHECK (volume > 0),
            amount NUMERIC(22,2) NOT NULL CHECK (amount > 0),
            turnover_rate NUMERIC(10,4),
            adjustment VARCHAR(10) NOT NULL CHECK (adjustment IN ('raw', 'qfq', 'hfq')),
            price_currency VARCHAR(3) NOT NULL DEFAULT 'CNY' CHECK (price_currency = 'CNY'),
            volume_unit VARCHAR(10) NOT NULL DEFAULT 'share' CHECK (volume_unit = 'share'),
            amount_unit VARCHAR(10) NOT NULL DEFAULT 'CNY' CHECK (amount_unit = 'CNY'),
            provider VARCHAR(64) NOT NULL CHECK (provider NOT IN ('unknown', 'synthetic')),
            source VARCHAR(64) NOT NULL CHECK (source NOT IN ('unknown', 'synthetic')),
            batch_id VARCHAR(64) NOT NULL REFERENCES market.data_batches(batch_id),
            raw_hash VARCHAR(128) NOT NULL,
            quality_status VARCHAR(20) NOT NULL CHECK (quality_status = 'pass'),
            quality_score NUMERIC(5,2) NOT NULL,
            certification_status VARCHAR(20) NOT NULL CHECK (certification_status = 'certified'),
            certification_time TIMESTAMPTZ NOT NULL,
            importer_version VARCHAR(64) NOT NULL,
            normalizer_version VARCHAR(64) NOT NULL,
            schema_version VARCHAR(32) NOT NULL,
            research_readiness_status VARCHAR(24) NOT NULL
                CHECK (research_readiness_status IN ('ready', 'review_required', 'blocked')),
            review_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (stock_code, period, trading_date, adjustment),
            CHECK (high >= GREATEST(open, close, low)),
            CHECK (low <= LEAST(open, close, high)),
            CHECK (market_close_time = TIME '15:00:00'),
            CHECK (timezone = 'Asia/Shanghai')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_certified_klines_lookup
        ON market.certified_klines(stock_code, period, adjustment, trading_date DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_certified_klines_ready
        ON market.certified_klines(research_readiness_status, period, adjustment, trading_date DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE market.trading_calendar (
            exchange VARCHAR(4) NOT NULL CHECK (exchange IN ('SZ', 'SH')),
            trading_date DATE NOT NULL,
            is_trading_day BOOLEAN NOT NULL,
            session_open_time TIME,
            session_close_time TIME,
            timezone VARCHAR(32) NOT NULL DEFAULT 'Asia/Shanghai',
            source VARCHAR(128) NOT NULL,
            source_reference TEXT NOT NULL,
            status VARCHAR(20) NOT NULL CHECK (status IN ('confirmed', 'unresolved')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (exchange, trading_date)
        )
        """
    )
    op.execute(
        """
        INSERT INTO market.trading_calendar
            (exchange, trading_date, is_trading_day, session_open_time,
             session_close_time, timezone, source, source_reference, status)
        SELECT exchange,
               day::date,
               EXTRACT(ISODOW FROM day) < 6 AND day::date <> DATE '2026-06-19',
               CASE WHEN EXTRACT(ISODOW FROM day) < 6 AND day::date <> DATE '2026-06-19'
                    THEN TIME '09:30:00' END,
               CASE WHEN EXTRACT(ISODOW FROM day) < 6 AND day::date <> DATE '2026-06-19'
                    THEN TIME '15:00:00' END,
               'Asia/Shanghai',
               CASE WHEN exchange='SH' THEN 'sse' ELSE 'szse' END,
               CASE WHEN exchange='SH'
                    THEN 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20260611_10821419.shtml'
                    ELSE 'https://www.szse.cn/disclosure/notice/general/t20260611_620979.html' END,
               'confirmed'
        FROM generate_series(DATE '2026-06-01', DATE '2026-06-30', INTERVAL '1 day') day
        CROSS JOIN (VALUES ('SH'), ('SZ')) exchanges(exchange)
        """
    )
    op.execute(
        """
        INSERT INTO market.certified_klines
            (stock_code, exchange, period, trading_date, market_close_time, timezone,
             open, high, low, close, volume, amount, turnover_rate, adjustment,
             price_currency, volume_unit, amount_unit, provider, source, batch_id,
             raw_hash, quality_status, quality_score, certification_status,
             certification_time, importer_version, normalizer_version, schema_version,
             research_readiness_status, review_reason)
        SELECT k.stock_code || CASE WHEN k.stock_code LIKE ANY(ARRAY['5%','6%','9%'])
                                   THEN '.SH' ELSE '.SZ' END,
               CASE WHEN k.stock_code LIKE ANY(ARRAY['5%','6%','9%']) THEN 'SH' ELSE 'SZ' END,
               k.period,
               (k.time AT TIME ZONE 'Asia/Shanghai')::date,
               TIME '15:00:00',
               'Asia/Shanghai',
               k.open, k.high, k.low, k.close, k.volume, k.amount, k.turnover_rate,
               'raw', 'CNY', 'share', 'CNY',
               p.provider, p.source, p.batch_id, p.raw_hash, p.quality_status,
               p.quality_score, p.certification_status, p.certification_time,
               p.importer_version, 'sprint07-kline-contract-v1', 'certified-kline-v1',
               'review_required',
               'Raw prices verified; corporate-action adjustment engine is not implemented.'
        FROM market.klines k
        JOIN market.kline_provenance p USING(time, stock_code, period)
        WHERE p.importer_version = 'sprint06-sohu-daily-v1'
          AND p.certification_status = 'certified'
          AND p.quality_status = 'pass'
          AND NOT p.is_synthetic
          AND p.provider = 'sohu'
          AND p.source = 'sohu_daily_kline'
        """
    )
    op.execute("ALTER TABLE market.certified_klines OWNER TO quant_admin")
    op.execute("ALTER TABLE market.trading_calendar OWNER TO quant_admin")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.certified_klines")
    op.execute("DROP TABLE IF EXISTS market.trading_calendar")
