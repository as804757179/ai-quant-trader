"""Create research-readiness audit records and seed the Sprint08 review.

Revision ID: 010
Revises: 009
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_readiness_reviews (
            review_id VARCHAR(64) PRIMARY KEY,
            stock_code VARCHAR(12) NOT NULL,
            period VARCHAR(10) NOT NULL,
            date_from DATE NOT NULL,
            date_to DATE NOT NULL,
            adjustment VARCHAR(10) NOT NULL CHECK (adjustment IN ('raw','qfq','hfq')),
            readiness_status VARCHAR(24) NOT NULL
                CHECK (readiness_status IN ('review_required','ready','rejected')),
            research_use_scope VARCHAR(32) NOT NULL
                CHECK (research_use_scope IN ('raw_price_analysis','return_backtest','execution_reference')),
            corporate_action_status VARCHAR(40) NOT NULL,
            missingness_status VARCHAR(24) NOT NULL
                CHECK (missingness_status IN ('complete','unresolved')),
            provider_validation_status VARCHAR(24) NOT NULL
                CHECK (provider_validation_status IN ('pass','partial_pass','rejected')),
            review_reason TEXT NOT NULL,
            evidence JSONB NOT NULL,
            reviewer_version VARCHAR(64) NOT NULL,
            reviewed_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (stock_code, period, date_from, date_to, adjustment, research_use_scope)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE market.research_date_reviews (
            date_review_id VARCHAR(96) PRIMARY KEY,
            dataset_scope VARCHAR(64) NOT NULL,
            stock_code VARCHAR(12) NOT NULL,
            trading_date DATE NOT NULL,
            status VARCHAR(24) NOT NULL CHECK (status IN
                ('normal_trade','suspended','not_listed','delisted','provider_missing','exchange_closed','unresolved')),
            evidence_source TEXT NOT NULL,
            evidence_time TIMESTAMPTZ NOT NULL,
            reason TEXT NOT NULL,
            reviewer_version VARCHAR(64) NOT NULL,
            reviewed_at TIMESTAMPTZ NOT NULL,
            UNIQUE (dataset_scope, stock_code, trading_date)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE market.corporate_action_reviews (
            event_id VARCHAR(64) PRIMARY KEY,
            stock_code VARCHAR(12) NOT NULL,
            event_type VARCHAR(48) NOT NULL,
            announcement_date DATE,
            record_date DATE,
            ex_date DATE,
            effective_date DATE,
            source TEXT NOT NULL,
            verification_status VARCHAR(40) NOT NULL
                CHECK (verification_status IN ('verified_no_event','verified','unresolved')),
            evidence JSONB NOT NULL,
            reviewer_version VARCHAR(64) NOT NULL,
            reviewed_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO market.research_date_reviews
            (date_review_id, dataset_scope, stock_code, trading_date, status,
             evidence_source, evidence_time, reason, reviewer_version, reviewed_at)
        SELECT 's08-primary-' || replace(s.stock_code,'.','') || '-' || to_char(c.trading_date,'YYYYMMDD'),
               'certified_store', s.stock_code, c.trading_date,
               CASE
                 WHEN NOT c.is_trading_day THEN 'exchange_closed'
                 WHEN EXISTS (
                   SELECT 1 FROM market.certified_klines k
                   WHERE k.stock_code=s.stock_code AND k.period='1d' AND k.adjustment='raw'
                     AND k.trading_date=c.trading_date
                 ) THEN 'normal_trade'
                 ELSE 'unresolved'
               END,
               c.source_reference, NOW(),
               CASE WHEN NOT c.is_trading_day THEN 'Official exchange calendar marks the date closed.'
                    WHEN EXISTS (
                      SELECT 1 FROM market.certified_klines k
                      WHERE k.stock_code=s.stock_code AND k.period='1d' AND k.adjustment='raw'
                        AND k.trading_date=c.trading_date
                    ) THEN 'Certified Store contains a validated normal-trading bar.'
                    ELSE 'Confirmed trading day has no certified bar; cause is unresolved.' END,
               'sprint08-readiness-v1', NOW()
        FROM (VALUES ('300308.SZ','SZ'),('603986.SH','SH'),('300502.SZ','SZ')) s(stock_code,exchange)
        JOIN market.trading_calendar c ON c.exchange=s.exchange
        WHERE c.trading_date BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'
        """
    )
    op.execute(
        """
        INSERT INTO market.research_date_reviews
            (date_review_id, dataset_scope, stock_code, trading_date, status,
             evidence_source, evidence_time, reason, reviewer_version, reviewed_at)
        SELECT 's08-sina-' || replace(stock_code,'.',''), 'secondary:sina_klc_archive',
               stock_code, DATE '2026-06-30', 'provider_missing',
               'Sina klc_kl archive; Sina CN_MarketData daily endpoint; Tencent fqkline raw endpoint',
               NOW(),
               'The Sina klc_kl archive omits 2026-06-30, while the separate Sina daily endpoint and Tencent raw endpoint contain matching OHLCV. This is endpoint-specific provider missingness; independent amount validation remains unavailable.',
               'sprint08-readiness-v1', NOW()
        FROM (VALUES ('300308.SZ'),('603986.SH'),('300502.SZ')) s(stock_code)
        """
    )
    op.execute(
        """
        INSERT INTO market.corporate_action_reviews
            (event_id, stock_code, event_type, announcement_date, record_date, ex_date,
             effective_date, source, verification_status, evidence, reviewer_version, reviewed_at)
        VALUES
        ('s08-ca-300308-none','300308.SZ','none',NULL,NULL,NULL,NULL,
         'https://static.cninfo.com.cn/finalpage/2026-05-09/1225286790.PDF',
         'verified_no_event',
         '{"target_range":"2026-06-01/2026-06-30","nearest_verified_event":{"type":"cash_dividend","ex_date":"2026-04-30"},"finding":"No dividend, ex-right, bonus, rights issue, split or consolidation effective inside target range."}'::jsonb,
         'sprint08-readiness-v1',NOW()),
        ('s08-ca-603986-none','603986.SH','none',NULL,NULL,NULL,NULL,
         'https://www.cninfo.com.cn/new/fulltextSearch?keyWord=603986',
         'verified_no_event',
         '{"target_range":"2026-06-01/2026-06-30","nearest_verified_event":{"type":"cash_dividend","record_date":"2026-05-25","ex_date":"2026-05-26"},"finding":"No dividend, ex-right, bonus, rights issue, split or consolidation effective inside target range."}'::jsonb,
         'sprint08-readiness-v1',NOW()),
        ('s08-ca-300502-20260611','300502.SZ','cash_dividend_and_capital_increase',
         DATE '2026-06-04',DATE '2026-06-10',DATE '2026-06-11',DATE '2026-06-11',
         'https://www.cninfo.com.cn/new/fulltextSearch?keyWord=300502',
         'verified',
         jsonb_build_object(
           'cash_dividend_per_10_shares_cny',10,
           'capital_increase_per_10_shares',4,
           'handling_status','not_implemented',
           'finding','Raw price discontinuity is explained, but return adjustment is unavailable.'
         ),
         'sprint08-readiness-v1',NOW())
        """
    )
    op.execute(
        """
        INSERT INTO market.research_readiness_reviews
            (review_id, stock_code, period, date_from, date_to, adjustment,
             readiness_status, research_use_scope, corporate_action_status,
             missingness_status, provider_validation_status, review_reason,
             evidence, reviewer_version, reviewed_at)
        SELECT 's08-' || replace(stock_code,'.','') || '-' || scope,
               stock_code, '1d', DATE '2026-06-01', DATE '2026-06-30', 'raw',
               CASE
                 WHEN scope='return_backtest' AND stock_code='300502.SZ' THEN 'rejected'
                 WHEN scope='execution_reference' THEN 'rejected'
                 ELSE 'review_required'
               END,
               scope,
               CASE WHEN stock_code='300502.SZ' THEN 'event_verified_handling_required'
                    ELSE 'verified_no_event' END,
               'complete', 'partial_pass',
               CASE
                 WHEN scope='return_backtest' AND stock_code='300502.SZ'
                   THEN 'In-range capital increase and dividend are verified; raw return adjustment is not implemented.'
                 WHEN scope='execution_reference'
                   THEN 'Historical June dataset is not an approved fresh execution-price reference.'
                 ELSE 'Sina archive missingness is attributed, but independent 2026-06-30 amount validation is unavailable.'
               END,
               jsonb_build_object(
                 'sina_20260630','provider_missing',
                 'ohlcv_cross_provider','pass',
                 'amount_cross_provider','unresolved',
                 'raw_policy','immutable_audit_baseline',
                 'release_locks','closed'
               ),
               'sprint08-readiness-v1', NOW()
        FROM (VALUES ('300308.SZ'),('603986.SH'),('300502.SZ')) s(stock_code)
        CROSS JOIN (VALUES ('raw_price_analysis'),('return_backtest'),('execution_reference')) scopes(scope)
        """
    )
    op.execute("ALTER TABLE market.research_readiness_reviews OWNER TO quant_admin")
    op.execute("ALTER TABLE market.research_date_reviews OWNER TO quant_admin")
    op.execute("ALTER TABLE market.corporate_action_reviews OWNER TO quant_admin")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.corporate_action_reviews")
    op.execute("DROP TABLE IF EXISTS market.research_date_reviews")
    op.execute("DROP TABLE IF EXISTS market.research_readiness_reviews")
