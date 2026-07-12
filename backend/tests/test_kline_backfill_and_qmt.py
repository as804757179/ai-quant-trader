"""合成 K 线、回测兜底、Mock QMT 适配器。"""

import asyncio
import os
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("BACKTEST_ALLOW_SYNTHETIC_KLINE", "true")
os.environ.setdefault("SYNTHETIC_KLINE_SMOKE_TEST", "true")

from app.backtest.engine import BacktestEngine
from app.backtest.service import run_backtest_in_memory
from app.core.config import settings
from app.data.kline_backfill import (
    estimate_limit_for_range,
    generate_synthetic_klines,
)
from app.trade.qmt.factory import create_qmt_adapter
from app.trade.qmt.mock_adapter import MockQmtAdapter
from app.trade.qmt.xtquant_adapter import QmtNotAvailableError


def test_generate_synthetic_klines_weekdays_only() -> None:
    rows = generate_synthetic_klines(
        "000001", date(2024, 1, 1), date(2024, 1, 14)
    )
    assert len(rows) > 5
    # 可复现
    rows2 = generate_synthetic_klines(
        "000001", date(2024, 1, 1), date(2024, 1, 14)
    )
    assert rows[0]["close"] == rows2[0]["close"]
    assert all(r["close"] > 0 for r in rows)


def test_estimate_limit() -> None:
    n = estimate_limit_for_range(date(2024, 1, 1), date(2024, 6, 1))
    assert 60 <= n <= 1000


def test_e2e_backtest_with_synthetic_memory() -> None:
    """无 DB 时用合成 K 线跑通双均线回测。"""
    start = date(2024, 1, 2)
    end = date(2024, 6, 28)
    rows = []
    for k in generate_synthetic_klines("000001", start, end):
        rows.append(
            {
                "stock_code": "000001",
                "trade_date": k["time"][:10],
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "volume": k["volume"],
                "amount": k["amount"],
            }
        )
    bars = BacktestEngine.bars_from_rows(rows)
    out = run_backtest_in_memory(
        strategy_type="dual_ma",
        bars_by_stock=bars,
        start_date=start,
        end_date=end,
        stock_codes=["000001"],
        initial_cash=1_000_000,
        params={"fast_period": 5, "slow_period": 20, "position_pct": 0.3},
    )
    assert out["trading_days"] > 50
    assert "metrics" in out
    assert "total_return" in out["metrics"]


def test_mock_qmt_buy_and_t1() -> None:
    async def _run() -> None:
        m = MockQmtAdapter(initial_cash=100_000)
        await m.connect()
        buy = await m.submit_order(
            stock_code="000001",
            side="BUY",
            quantity=100,
            limit_price=10.0,
        )
        assert buy.status == "FILLED"
        pos = await m.get_positions()
        assert len(pos) == 1
        assert pos[0].available_qty == 0  # T+1

        sell = await m.submit_order(
            stock_code="000001",
            side="SELL",
            quantity=100,
            limit_price=10.5,
        )
        assert sell.status == "FAILED"  # 不可卖

        m.release_t1()
        sell2 = await m.submit_order(
            stock_code="000001",
            side="SELL",
            quantity=100,
            limit_price=10.5,
        )
        assert sell2.status == "FILLED"
        acc = await m.get_account()
        assert acc.cash > 0

    asyncio.run(_run())


def test_factory_paper_is_mock() -> None:
    adapter = create_qmt_adapter("paper")
    assert isinstance(adapter, MockQmtAdapter)
    assert adapter.name == "mock"


def test_factory_live_never_falls_back_to_mock() -> None:
    with patch.dict(os.environ, {"QMT_FORCE_MOCK": "true"}):
        with pytest.raises(QmtNotAvailableError):
            create_qmt_adapter("live")


def test_backfill_one_synthetic_path() -> None:
    async def _run() -> None:
        client = MagicMock()
        client.fetch_kline = AsyncMock(return_value=None)
        client.close = AsyncMock()

        svc = __import__(
            "app.data.kline_backfill", fromlist=["KlineBackfillService"]
        ).KlineBackfillService(client=client)

        with (
            patch.object(svc, "save_klines", AsyncMock(return_value=10)) as save,
            patch.object(settings, "SYNTHETIC_KLINE_SMOKE_TEST", True),
        ):
            n, source = await svc.backfill_one(
                "000001",
                allow_synthetic=True,
                start_date=date.today() - timedelta(days=30),
                end_date=date.today(),
            )
            assert source == "synthetic"
            assert n == 10
            save.assert_awaited()

    asyncio.run(_run())
