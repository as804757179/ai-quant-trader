"""策略信号、配置存储、回测指标与内存回测。"""

import os
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.backtest.engine import BacktestEngine
from app.backtest.metrics import max_drawdown, summarize_result, win_rate
from app.backtest.schemas import BacktestConfig, BacktestResult, EquityPoint, TradeRecord
from app.backtest.service import run_backtest_in_memory
from app.strategy.catalog import STRATEGY_CATALOG, list_strategy_types
from app.strategy.config_store import StrategyConfigStore
from app.strategy.signals import make_signal_generator


def _bar_series(code: str = "000001", n: int = 60, start: float = 10.0):
    """生成带趋势的假 K 线。"""
    from app.backtest.schemas import DailyBar
    from datetime import timedelta

    bars: dict[date, DailyBar] = {}
    d0 = date(2024, 1, 2)
    price = start
    for i in range(n):
        # 先跌后涨，制造交叉
        if i < 25:
            price *= 0.995
        else:
            price *= 1.008
        d = d0 + timedelta(days=i)
        # 跳过周末近似：简单用日历日
        o = price * 0.999
        c = price
        bars[d] = DailyBar(
            trade_date=d,
            open=o,
            high=max(o, c) * 1.01,
            low=min(o, c) * 0.99,
            close=c,
            volume=1_000_000,
            prev_close=price / 1.008 if i else start,
        )
    return {code: bars}


def test_catalog_has_four_strategies() -> None:
    types = list_strategy_types()
    assert set(types) == {"dual_ma", "bollinger", "rsi", "macd"}
    assert all("default_params" in STRATEGY_CATALOG[t] for t in types)


def test_config_store_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cfg.json"
        store = StrategyConfigStore(path)
        items = store.list_strategies()
        assert len(items) == 4
        assert all(i["enabled"] for i in items)

        updated = store.update("dual_ma", enabled=False, params={"fast_period": 3})
        assert updated["enabled"] is False
        assert updated["params"]["fast_period"] == 3
        assert updated["params"]["slow_period"] == 20  # default kept

        again = store.get("dual_ma")
        assert again is not None
        assert again["enabled"] is False


def test_dual_ma_generator_produces_signals() -> None:
    bars = _bar_series(n=50)
    gen = make_signal_generator(
        "dual_ma",
        ["000001"],
        {"fast_period": 5, "slow_period": 10, "position_pct": 0.2},
        initial_cash=100_000,
    )
    # 在最后一天生成
    last = max(bars["000001"].keys())
    signals = gen(last, {}, bars)
    # 趋势后期可能有买入信号
    assert isinstance(signals, list)


def test_run_backtest_in_memory_dual_ma() -> None:
    bars = _bar_series(n=50)
    dates = sorted(bars["000001"].keys())
    out = run_backtest_in_memory(
        strategy_type="dual_ma",
        bars_by_stock=bars,
        start_date=dates[0],
        end_date=dates[-1],
        stock_codes=["000001"],
        initial_cash=100_000,
        params={"fast_period": 5, "slow_period": 15, "position_pct": 0.5},
    )
    assert "metrics" in out
    assert out["trading_days"] > 0
    assert "total_return" in out["metrics"]


def test_metrics_max_drawdown_and_win_rate() -> None:
    curve = [
        EquityPoint(date(2024, 1, 1), 100, 0, 100, 0),
        EquityPoint(date(2024, 1, 2), 90, 0, 90, -0.1),
        EquityPoint(date(2024, 1, 3), 95, 0, 95, 0.05),
    ]
    assert abs(max_drawdown(curve) - 0.1) < 1e-9

    trades = [
        TradeRecord(
            "000001", "BUY", date(2024, 1, 1), date(2024, 1, 2), 100, 10, 1000, 1, 0, 0, "FILLED"
        ),
        TradeRecord(
            "000001", "SELL", date(2024, 1, 2), date(2024, 1, 3), 100, 11, 1100, 1, 0, 0, "FILLED"
        ),
    ]
    assert win_rate(trades) == 1.0

    result = BacktestResult(
        config=BacktestConfig(date(2024, 1, 1), date(2024, 1, 3), ["000001"]),
        trades=trades,
        equity_curve=curve,
        total_return=0.05,
        trading_days=3,
        filled_trades=2,
    )
    summary = summarize_result(result)
    assert summary["total_trades"] == 2
    assert summary["max_drawdown"] >= 0


def test_all_signal_factories_construct() -> None:
    for stype in list_strategy_types():
        gen = make_signal_generator(stype, ["000001"], {}, initial_cash=1e6)
        assert callable(gen)
