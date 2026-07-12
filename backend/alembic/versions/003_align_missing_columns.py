"""Align incomplete host DB schema with application expectations.

Revision ID: 003
Revises: 002
Create Date: 2026-07-09

旧库若用 CREATE TABLE IF NOT EXISTS 保留了精简表结构，会导致 filled_at / valid_until 等列缺失。
本迁移用 ADD COLUMN IF NOT EXISTS 幂等补齐。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col(table: str, column: str, typedef: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {typedef}"
    )


def upgrade() -> None:
    # ── trade.orders ──
    for col, typedef in [
        ("signal_id", "UUID"),
        ("strategy_id", "INT"),
        ("commission", "NUMERIC(12,4) DEFAULT 0"),
        ("submitted_at", "TIMESTAMPTZ"),
        ("filled_at", "TIMESTAMPTZ"),
        ("cancelled_at", "TIMESTAMPTZ"),
        ("reject_reason", "TEXT"),
        ("broker_order_id", "VARCHAR(100)"),
    ]:
        _add_col("trade.orders", col, typedef)

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_mode_idempotency
        ON trade.orders (mode, idempotency_key)
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_stock ON trade.orders(stock_code, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON trade.orders(status)"
    )

    # ── trade.positions ──
    for col, typedef in [
        ("frozen_qty", "INT NOT NULL DEFAULT 0"),
        ("total_cost", "NUMERIC(20,4)"),
        ("current_price", "NUMERIC(12,4)"),
        ("unrealized_pnl", "NUMERIC(20,4)"),
        ("unrealized_pnl_pct", "NUMERIC(8,4)"),
        ("realized_pnl", "NUMERIC(20,4) DEFAULT 0"),
    ]:
        _add_col("trade.positions", col, typedef)

    # ── trade.account_records ──
    for col, typedef in [
        ("frozen_cash", "NUMERIC(20,4) DEFAULT 0"),
        ("total_pnl", "NUMERIC(20,4)"),
        ("position_count", "INT DEFAULT 0"),
        ("data_type", "VARCHAR(10) DEFAULT 'snapshot'"),
    ]:
        _add_col("trade.account_records", col, typedef)

    # ── ai.signals ──
    for col, typedef in [
        ("strategy_id", "INT"),
        ("target_price", "NUMERIC(12,4)"),
        ("stop_loss", "NUMERIC(12,4)"),
        ("raw_agent_output", "JSONB"),
        ("valid_until", "TIMESTAMPTZ"),
        ("executed_at", "TIMESTAMPTZ"),
        ("executed_price", "NUMERIC(12,4)"),
        ("pnl", "NUMERIC(12,4)"),
        ("pnl_pct", "NUMERIC(8,4)"),
        ("feedback_note", "TEXT"),
    ]:
        _add_col("ai.signals", col, typedef)

    # ── ai.agent_logs ──
    for col, typedef in [
        ("stock_code", "VARCHAR(10)"),
        ("model_used", "VARCHAR(50)"),
        ("input_tokens", "INT"),
        ("output_tokens", "INT"),
        ("latency_ms", "INT"),
        ("status", "VARCHAR(20) DEFAULT 'success'"),
        ("error_msg", "TEXT"),
        ("output", "JSONB"),
    ]:
        _add_col("ai.agent_logs", col, typedef)

    # ── risk.fuse_records ──
    for col, typedef in [
        ("portfolio_snapshot", "JSONB"),
        ("recovery_approved_by", "VARCHAR(50)"),
        ("recovery_note", "TEXT"),
        ("recovered_at", "TIMESTAMPTZ"),
    ]:
        _add_col("risk.fuse_records", col, typedef)

    # ── risk.risk_rules ──
    for col, typedef in [
        ("description", "TEXT"),
        ("updated_at", "TIMESTAMPTZ DEFAULT NOW()"),
        ("updated_by", "VARCHAR(50)"),
    ]:
        _add_col("risk.risk_rules", col, typedef)

    # ── market.klines ──
    for col, typedef in [
        ("turnover_rate", "NUMERIC(10,4)"),
        ("adj_factor", "NUMERIC(12,6) DEFAULT 1.0"),
    ]:
        _add_col("market.klines", col, typedef)

    # ── backtest.tasks ──
    for col, typedef in [
        ("strategy_id", "INT"),
        ("universe", "VARCHAR(200)"),
        ("error_msg", "TEXT"),
        ("started_at", "TIMESTAMPTZ"),
        ("finished_at", "TIMESTAMPTZ"),
        ("lookahead_checked", "BOOLEAN DEFAULT FALSE"),
        ("lookahead_issues", "JSONB"),
        ("progress", "INT DEFAULT 0"),
    ]:
        _add_col("backtest.tasks", col, typedef)

    # 确保 results 表存在
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest.results (
            id              SERIAL          PRIMARY KEY,
            task_id         INT             NOT NULL,
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
        """
    )

    # ── trade.order_history ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trade.order_history (
            id              BIGSERIAL       PRIMARY KEY
        )
        """
    )
    for col, typedef in [
        ("order_id", "UUID"),
        ("from_status", "VARCHAR(20)"),
        ("to_status", "VARCHAR(20)"),
        ("changed_at", "TIMESTAMPTZ DEFAULT NOW()"),
        ("changed_by", "VARCHAR(50)"),
        ("detail", "JSONB"),
    ]:
        _add_col("trade.order_history", col, typedef)

    # ── risk.risk_events（表可能已存在但缺列）──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk.risk_events (
            id              BIGSERIAL       PRIMARY KEY
        )
        """
    )
    for col, typedef in [
        ("rule_code", "VARCHAR(50)"),
        ("trigger_value", "NUMERIC(12,4)"),
        ("threshold", "NUMERIC(12,4)"),
        ("action_taken", "VARCHAR(20)"),
        ("detail", "JSONB"),
        ("order_id", "UUID"),
        ("is_resolved", "BOOLEAN DEFAULT FALSE"),
        ("resolved_at", "TIMESTAMPTZ"),
        ("resolved_by", "VARCHAR(50)"),
        ("created_at", "TIMESTAMPTZ DEFAULT NOW()"),
    ]:
        _add_col("risk.risk_events", col, typedef)

    # uuid 扩展（若无）
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')


def downgrade() -> None:
    # 不删除列，避免丢数据
    pass
