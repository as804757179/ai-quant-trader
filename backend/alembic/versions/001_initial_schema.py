"""Initial schema - all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    for schema in (
        "market",
        "fundamental",
        "ai",
        "strategy",
        "backtest",
        "trade",
        "risk",
        "audit",
    ):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # ── fundamental.stocks ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS fundamental.stocks (
            code            VARCHAR(10)     PRIMARY KEY,
            name            VARCHAR(50)     NOT NULL,
            full_name       VARCHAR(100),
            market          VARCHAR(5)      NOT NULL,
            board           VARCHAR(20),
            sector          VARCHAR(50),
            sub_sector      VARCHAR(50),
            list_date       DATE,
            delist_date     DATE,
            total_shares    BIGINT,
            float_shares    BIGINT,
            is_st           BOOLEAN         DEFAULT FALSE,
            is_active       BOOLEAN         DEFAULT TRUE,
            currency        VARCHAR(5)      DEFAULT 'CNY',
            created_at      TIMESTAMPTZ     DEFAULT NOW(),
            updated_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_stocks_sector ON fundamental.stocks(sector)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_stocks_board ON fundamental.stocks(board)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_name "
        "ON fundamental.stocks USING gin(name gin_trgm_ops)"
    )

    # ── fundamental.financial_reports ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS fundamental.financial_reports (
            id              BIGSERIAL       PRIMARY KEY,
            stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
            report_type     VARCHAR(10)     NOT NULL,
            report_date     DATE            NOT NULL,
            publish_date    DATE,
            revenue         NUMERIC(20,2),
            gross_profit    NUMERIC(20,2),
            operating_profit NUMERIC(20,2),
            net_profit      NUMERIC(20,2),
            eps             NUMERIC(10,4),
            total_assets    NUMERIC(20,2),
            total_liab      NUMERIC(20,2),
            equity          NUMERIC(20,2),
            bvps            NUMERIC(10,4),
            oper_cashflow   NUMERIC(20,2),
            pe_ratio        NUMERIC(10,2),
            pb_ratio        NUMERIC(10,2),
            ps_ratio        NUMERIC(10,2),
            roe             NUMERIC(8,4),
            roa             NUMERIC(8,4),
            debt_ratio      NUMERIC(8,4),
            gross_margin    NUMERIC(8,4),
            revenue_yoy     NUMERIC(8,4),
            profit_yoy      NUMERIC(8,4),
            data_source     VARCHAR(50),
            created_at      TIMESTAMPTZ     DEFAULT NOW(),
            UNIQUE(stock_code, report_type, report_date)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reports_stock_date "
        "ON fundamental.financial_reports(stock_code, report_date DESC)"
    )

    # ── fundamental.announcements ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS fundamental.announcements (
            id              BIGSERIAL       PRIMARY KEY,
            stock_code      VARCHAR(10)     REFERENCES fundamental.stocks(code),
            title           VARCHAR(500)    NOT NULL,
            category        VARCHAR(50),
            publish_time    TIMESTAMPTZ     NOT NULL,
            content_url     TEXT,
            content_text    TEXT,
            is_vectorized   BOOLEAN         DEFAULT FALSE,
            created_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_announcements_stock "
        "ON fundamental.announcements(stock_code, publish_time DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_announcements_cat "
        "ON fundamental.announcements(category)"
    )

    # ── market.klines (TimescaleDB hypertable) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS market.klines (
            time            TIMESTAMPTZ     NOT NULL,
            stock_code      VARCHAR(10)     NOT NULL,
            period          VARCHAR(10)     NOT NULL,
            open            NUMERIC(12,4)   NOT NULL,
            high            NUMERIC(12,4)   NOT NULL,
            low             NUMERIC(12,4)   NOT NULL,
            close           NUMERIC(12,4)   NOT NULL,
            volume          BIGINT          NOT NULL,
            amount          NUMERIC(20,2)   NOT NULL,
            vwap            NUMERIC(12,4),
            turnover_rate   NUMERIC(8,4),
            adj_factor      NUMERIC(12,6)   DEFAULT 1.0,
            adj_close       NUMERIC(12,4),
            PRIMARY KEY (time, stock_code, period)
        )
    """)
    op.execute("""
        SELECT create_hypertable(
            'market.klines',
            'time',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_klines_stock_period "
        "ON market.klines(stock_code, period, time DESC)"
    )
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS market.klines_weekly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 week', time) AS week,
            stock_code,
            first(open, time)   AS open,
            max(high)           AS high,
            min(low)            AS low,
            last(close, time)   AS close,
            sum(volume)         AS volume,
            sum(amount)         AS amount
        FROM market.klines
        WHERE period = '1d'
        GROUP BY week, stock_code
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_retention_policy(
            'market.klines',
            INTERVAL '6 months',
            if_not_exists => TRUE,
            schedule_interval => INTERVAL '1 day'
        )
    """)

    # ── market.quotes ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS market.quotes (
            time            TIMESTAMPTZ     NOT NULL,
            stock_code      VARCHAR(10)     NOT NULL,
            price           NUMERIC(12,4),
            open            NUMERIC(12,4),
            high            NUMERIC(12,4),
            low             NUMERIC(12,4),
            prev_close      NUMERIC(12,4),
            change          NUMERIC(12,4),
            change_pct      NUMERIC(8,4),
            volume          BIGINT,
            amount          NUMERIC(20,2),
            bid1_price      NUMERIC(12,4),  bid1_vol BIGINT,
            bid2_price      NUMERIC(12,4),  bid2_vol BIGINT,
            bid3_price      NUMERIC(12,4),  bid3_vol BIGINT,
            ask1_price      NUMERIC(12,4),  ask1_vol BIGINT,
            ask2_price      NUMERIC(12,4),  ask2_vol BIGINT,
            ask3_price      NUMERIC(12,4),  ask3_vol BIGINT,
            PRIMARY KEY (time, stock_code)
        )
    """)
    op.execute("""
        SELECT create_hypertable(
            'market.quotes',
            'time',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        )
    """)
    op.execute("""
        SELECT add_retention_policy(
            'market.quotes',
            INTERVAL '7 days',
            if_not_exists => TRUE
        )
    """)

    # ── market.fund_flows ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS market.fund_flows (
            time            TIMESTAMPTZ     NOT NULL,
            stock_code      VARCHAR(10)     NOT NULL,
            super_large_in  NUMERIC(20,2),
            large_in        NUMERIC(20,2),
            medium_in       NUMERIC(20,2),
            small_in        NUMERIC(20,2),
            main_net_in     NUMERIC(20,2),
            north_net_in    NUMERIC(20,2),
            PRIMARY KEY (time, stock_code)
        )
    """)
    op.execute("""
        SELECT create_hypertable(
            'market.fund_flows',
            'time',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE
        )
    """)

    # ── ai.signals ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai.signals (
            id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
            strategy_id     INT,
            action          VARCHAR(10)     NOT NULL
                            CHECK (action IN ('BUY', 'SELL', 'HOLD')),
            confidence      NUMERIC(5,4)    NOT NULL
                            CHECK (confidence BETWEEN 0 AND 1),
            risk_level      VARCHAR(10)     NOT NULL DEFAULT 'MEDIUM'
                            CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'EXTREME')),
            price_at        NUMERIC(12,4)   NOT NULL,
            target_price    NUMERIC(12,4),
            stop_loss       NUMERIC(12,4),
            reason          TEXT            NOT NULL,
            agent_votes     JSONB           NOT NULL DEFAULT '{}',
            raw_agent_output JSONB,
            signal_time     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            valid_until     TIMESTAMPTZ,
            status          VARCHAR(20)     DEFAULT 'active'
                            CHECK (status IN ('active','executed','expired','cancelled')),
            executed_at     TIMESTAMPTZ,
            executed_price  NUMERIC(12,4),
            pnl             NUMERIC(12,4),
            pnl_pct         NUMERIC(8,4),
            feedback_note   TEXT,
            created_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_signals_stock "
        "ON ai.signals(stock_code, signal_time DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON ai.signals(status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_signals_action "
        "ON ai.signals(action, signal_time DESC)"
    )

    # ── ai.agent_logs ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai.agent_logs (
            id              BIGSERIAL       PRIMARY KEY,
            signal_id       UUID            REFERENCES ai.signals(id),
            stock_code      VARCHAR(10),
            agent_name      VARCHAR(50)     NOT NULL,
            model_used      VARCHAR(50),
            input_tokens    INT,
            output_tokens   INT,
            latency_ms      INT,
            status          VARCHAR(20)     DEFAULT 'success',
            error_msg       TEXT,
            output          JSONB,
            created_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_signal ON ai.agent_logs(signal_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_time ON ai.agent_logs(created_at DESC)"
    )

    # ── backtest.tasks / results ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS backtest.tasks (
            id              SERIAL          PRIMARY KEY,
            strategy_id     INT,
            name            VARCHAR(200),
            start_date      DATE            NOT NULL,
            end_date        DATE            NOT NULL,
            initial_cash    NUMERIC(20,2)   DEFAULT 1000000,
            universe        VARCHAR(50),
            status          VARCHAR(20)     DEFAULT 'pending'
                            CHECK (status IN ('pending','running','done','failed','cancelled')),
            progress        INT             DEFAULT 0,
            error_msg       TEXT,
            created_at      TIMESTAMPTZ     DEFAULT NOW(),
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            lookahead_checked BOOLEAN       DEFAULT FALSE,
            lookahead_issues  JSONB
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS backtest.results (
            id              SERIAL          PRIMARY KEY,
            task_id         INT             NOT NULL REFERENCES backtest.tasks(id),
            walk_forward_period VARCHAR(50),
            total_return    NUMERIC(10,4),
            annual_return   NUMERIC(10,4),
            max_drawdown    NUMERIC(10,4),
            sharpe_ratio    NUMERIC(8,4),
            calmar_ratio    NUMERIC(8,4),
            win_rate        NUMERIC(8,4),
            profit_loss_ratio NUMERIC(8,4),
            total_trades    INT,
            avg_holding_days NUMERIC(8,2),
            benchmark_return NUMERIC(10,4),
            alpha           NUMERIC(10,4),
            beta            NUMERIC(8,4),
            information_ratio NUMERIC(8,4),
            equity_curve    JSONB,
            drawdown_curve  JSONB,
            monthly_returns JSONB,
            trade_list      JSONB,
            oos_return      NUMERIC(10,4),
            oos_sharpe      NUMERIC(8,4),
            created_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)

    # ── trade.orders ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade.orders (
            id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            idempotency_key VARCHAR(64)     NOT NULL,
            stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
            signal_id       UUID            REFERENCES ai.signals(id),
            strategy_id     INT,
            side            VARCHAR(5)      NOT NULL
                            CHECK (side IN ('BUY', 'SELL')),
            order_type      VARCHAR(10)     DEFAULT 'LIMIT'
                            CHECK (order_type IN ('MARKET', 'LIMIT')),
            quantity        INT             NOT NULL CHECK (quantity > 0),
            limit_price     NUMERIC(12,4),
            filled_quantity INT             DEFAULT 0,
            avg_fill_price  NUMERIC(12,4),
            commission      NUMERIC(12,4)   DEFAULT 0,
            status          VARCHAR(20)     DEFAULT 'PENDING'
                            CHECK (status IN ('PENDING','SUBMITTED','PARTIAL','FILLED','CANCELLED','FAILED')),
            mode            VARCHAR(15)     NOT NULL
                            CHECK (mode IN ('simulation', 'paper', 'live')),
            trigger_source  VARCHAR(20)     DEFAULT 'auto',
            operator        VARCHAR(50),
            created_at      TIMESTAMPTZ     DEFAULT NOW(),
            submitted_at    TIMESTAMPTZ,
            filled_at       TIMESTAMPTZ,
            cancelled_at    TIMESTAMPTZ,
            broker_order_id VARCHAR(100),
            reject_reason   TEXT
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_mode_idempotency "
        "ON trade.orders (mode, idempotency_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_stock "
        "ON trade.orders(stock_code, created_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON trade.orders(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_signal ON trade.orders(signal_id)")

    # ── trade.order_history ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade.order_history (
            id              BIGSERIAL       PRIMARY KEY,
            order_id        UUID            NOT NULL REFERENCES trade.orders(id),
            from_status     VARCHAR(20),
            to_status       VARCHAR(20)     NOT NULL,
            changed_at      TIMESTAMPTZ     DEFAULT NOW(),
            changed_by      VARCHAR(50),
            detail          JSONB
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_hist_order ON trade.order_history(order_id)"
    )

    # ── trade.positions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade.positions (
            id              BIGSERIAL       PRIMARY KEY,
            stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
            mode            VARCHAR(15)     NOT NULL,
            total_qty       INT             NOT NULL DEFAULT 0,
            available_qty   INT             NOT NULL DEFAULT 0,
            frozen_qty      INT             NOT NULL DEFAULT 0,
            avg_cost        NUMERIC(12,4),
            total_cost      NUMERIC(20,4),
            current_price   NUMERIC(12,4),
            market_value    NUMERIC(20,4),
            unrealized_pnl  NUMERIC(20,4),
            unrealized_pnl_pct NUMERIC(8,4),
            realized_pnl    NUMERIC(20,4)   DEFAULT 0,
            updated_at      TIMESTAMPTZ     DEFAULT NOW(),
            UNIQUE (stock_code, mode)
        )
    """)

    # ── trade.account_records ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade.account_records (
            id              BIGSERIAL       PRIMARY KEY,
            mode            VARCHAR(15)     NOT NULL,
            record_time     TIMESTAMPTZ     DEFAULT NOW(),
            total_assets    NUMERIC(20,4)   NOT NULL,
            cash            NUMERIC(20,4)   NOT NULL,
            market_value    NUMERIC(20,4)   NOT NULL,
            frozen_cash     NUMERIC(20,4)   DEFAULT 0,
            daily_pnl       NUMERIC(20,4),
            total_pnl       NUMERIC(20,4),
            total_pnl_pct   NUMERIC(8,4),
            position_count  INT             DEFAULT 0,
            position_ratio  NUMERIC(5,4),
            data_type       VARCHAR(10)     DEFAULT 'snapshot'
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_mode_time "
        "ON trade.account_records(mode, record_time DESC)"
    )

    # ── risk.risk_rules + default rules ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.risk_rules (
            id              SERIAL          PRIMARY KEY,
            rule_code       VARCHAR(50)     UNIQUE NOT NULL,
            rule_name       VARCHAR(100)    NOT NULL,
            rule_type       VARCHAR(20)     NOT NULL,
            is_hard         BOOLEAN         DEFAULT TRUE,
            threshold       NUMERIC(12,4)   NOT NULL,
            action          VARCHAR(20)     NOT NULL,
            is_enabled      BOOLEAN         DEFAULT TRUE,
            description     TEXT,
            updated_at      TIMESTAMPTZ     DEFAULT NOW(),
            updated_by      VARCHAR(50)
        )
    """)
    op.execute("""
        INSERT INTO risk.risk_rules
            (rule_code, rule_name, rule_type, is_hard, threshold, action, is_enabled, description, updated_by)
        VALUES
            ('MAX_SINGLE_POSITION', '单票最大仓位', 'position', TRUE, 0.10, 'block', TRUE, '单票持仓不得超过总资产10%', 'system'),
            ('MAX_TOTAL_POSITION', '总仓位上限', 'position', TRUE, 0.80, 'block', TRUE, '总持仓不得超过总资产80%', 'system'),
            ('MAX_DAILY_LOSS', '日最大亏损', 'loss', TRUE, 0.03, 'fuse', TRUE, '单日亏损超过3%触发熔断', 'system'),
            ('MAX_DRAWDOWN', '最大回撤熔断', 'loss', TRUE, 0.15, 'fuse', TRUE, '回撤超过15%停止所有交易', 'system'),
            ('MAX_ORDER_FREQ', '单日最大下单次数', 'frequency', TRUE, 20, 'block', TRUE, '单日下单不超过20次', 'system'),
            ('WARN_SINGLE_POSITION', '单票仓位预警', 'position', FALSE, 0.08, 'alert', TRUE, '单票仓位超过8%发出警告', 'system'),
            ('WARN_TOTAL_POSITION', '总仓位预警', 'position', FALSE, 0.70, 'alert', TRUE, '总仓位超过70%发出警告', 'system'),
            ('MIN_DAILY_AMOUNT', '最低日成交额', 'liquidity', TRUE, 50000000, 'block', TRUE, '日成交额低于5000万禁止买入', 'system'),
            ('BLOCK_ST', '禁止买入ST', 'special', TRUE, 0, 'block', TRUE, '禁止买入ST股', 'system'),
            ('MAX_SECTOR_CONCENTRATION', '行业集中度', 'concentration', TRUE, 0.40, 'block', TRUE, '单行业不超过40%', 'system')
        ON CONFLICT (rule_code) DO NOTHING
    """)

    # ── risk.risk_events ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.risk_events (
            id              BIGSERIAL       PRIMARY KEY,
            rule_code       VARCHAR(50)     NOT NULL,
            trigger_value   NUMERIC(12,4)   NOT NULL,
            threshold       NUMERIC(12,4)   NOT NULL,
            action_taken    VARCHAR(20)     NOT NULL,
            detail          JSONB,
            order_id        UUID            REFERENCES trade.orders(id),
            is_resolved     BOOLEAN         DEFAULT FALSE,
            resolved_at     TIMESTAMPTZ,
            resolved_by     VARCHAR(50),
            created_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)

    # ── risk.fuse_records ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.fuse_records (
            id              SERIAL          PRIMARY KEY,
            mode            VARCHAR(15)     NOT NULL,
            fuse_reason     VARCHAR(200)    NOT NULL,
            triggered_at    TIMESTAMPTZ     DEFAULT NOW(),
            portfolio_snapshot JSONB,
            recovery_approved_by VARCHAR(50),
            recovery_note   TEXT,
            recovered_at    TIMESTAMPTZ,
            is_active       BOOLEAN         DEFAULT TRUE
        )
    """)

    # ── audit.operation_logs + trigger ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.operation_logs (
            id              BIGSERIAL       PRIMARY KEY,
            session_id      VARCHAR(64),
            operator        VARCHAR(50),
            ip_address      INET,
            operation       VARCHAR(100)    NOT NULL,
            entity_type     VARCHAR(50),
            entity_id       VARCHAR(100),
            before_data     JSONB,
            after_data      JSONB,
            result          VARCHAR(20),
            error_detail    TEXT,
            created_at      TIMESTAMPTZ     DEFAULT NOW()
        )
    """)
    op.execute("REVOKE UPDATE, DELETE ON audit.operation_logs FROM PUBLIC")

    op.execute("""
        CREATE OR REPLACE FUNCTION audit.log_order_change()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO audit.operation_logs(operation, entity_type, entity_id, before_data, after_data)
            VALUES (
                'ORDER_STATUS_CHANGE',
                'order',
                NEW.id::text,
                to_jsonb(OLD),
                to_jsonb(NEW)
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_order_audit ON trade.orders")
    op.execute("""
        CREATE TRIGGER trg_order_audit
        AFTER UPDATE ON trade.orders
        FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION audit.log_order_change()
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrade not allowed in production environment")