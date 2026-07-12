"""Ensure backtest.results has full metrics columns.

Revision ID: 004
Revises: 003
Create Date: 2026-07-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [
        ("annual_return", "NUMERIC(10,4)"),
        ("max_drawdown", "NUMERIC(10,4)"),
        ("sharpe_ratio", "NUMERIC(8,4)"),
        ("calmar_ratio", "NUMERIC(8,4)"),
        ("win_rate", "NUMERIC(8,4)"),
        ("profit_loss_ratio", "NUMERIC(8,4)"),
        ("total_trades", "INT"),
        ("avg_holding_days", "NUMERIC(8,2)"),
        ("benchmark_return", "NUMERIC(10,4)"),
        ("alpha", "NUMERIC(10,4)"),
        ("beta", "NUMERIC(8,4)"),
        ("information_ratio", "NUMERIC(8,4)"),
        ("equity_curve", "JSONB"),
        ("drawdown_curve", "JSONB"),
        ("monthly_returns", "JSONB"),
        ("trade_list", "JSONB"),
        ("oos_return", "NUMERIC(10,4)"),
        ("oos_sharpe", "NUMERIC(8,4)"),
        ("walk_forward_period", "VARCHAR(50)"),
        ("total_return", "NUMERIC(10,4)"),
    ]
    for name, typedef in cols:
        op.execute(
            f"ALTER TABLE backtest.results ADD COLUMN IF NOT EXISTS {name} {typedef}"
        )


def downgrade() -> None:
    pass
