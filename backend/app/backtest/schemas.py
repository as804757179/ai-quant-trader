from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable


@dataclass
class DailyBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    amount: float = 0.0
    prev_close: float | None = None
    turnover_rate: float | None = None
    is_suspended: bool = False
    is_st: bool = False


@dataclass
class BacktestConfig:
    start_date: date
    end_date: date
    universe: list[str]
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_rate: float = 0.002
    min_commission: float = 5.0
    execution_mode: str = "open_auction"  # open_auction | continuous
    lot_size: int = 100
    trusted_mode: bool = False
    trusted_calendar: list[date] | None = None


@dataclass
class BacktestSignal:
    stock_code: str
    side: str
    quantity: int
    signal_date: date
    order_type: str = "MARKET"
    limit_price: float | None = None
    reason: str = ""


@dataclass
class TradeRecord:
    stock_code: str
    side: str
    signal_date: date
    execution_date: date
    quantity: int
    fill_price: float
    amount: float
    commission: float
    stamp_tax: float
    slippage_cost: float
    status: str
    fail_reason: str | None = None
    transfer_fee: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class PositionSnapshot:
    stock_code: str
    total_qty: int
    available_qty: int
    avg_cost: float
    market_price: float
    market_value: float
    total_cost: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class EquityPoint:
    trade_date: date
    cash: float
    market_value: float
    total_assets: float
    daily_return: float = 0.0


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    final_cash: float = 0.0
    final_market_value: float = 0.0
    total_return: float = 0.0
    trading_days: int = 0
    filled_trades: int = 0
    failed_trades: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


SignalGenerator = Callable[
    [date, dict[str, PositionSnapshot], dict[str, dict[date, DailyBar]]],
    list[BacktestSignal],
]
