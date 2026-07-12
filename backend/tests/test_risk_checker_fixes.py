"""风控修复：无效价格、流动性、仓位 severity、阈值加载。"""

import asyncio
import os
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("MAX_SINGLE_POSITION_RATIO", "0.10")
os.environ.setdefault("WARN_SINGLE_POSITION_RATIO", "0.08")

from app.risk.checker import PreTradeRiskChecker


def _stock(code: str = "000001", is_st: bool = False, list_days: int = 365) -> dict:
    return {
        "code": code,
        "is_st": is_st,
        "list_date": date.today() - timedelta(days=list_days),
        "sector": "银行",
    }


def _portfolio(total: float = 1_000_000, mv: float = 0) -> dict:
    return {
        "total_assets": total,
        "cash": total - mv,
        "total_market_value": mv,
        "daily_pnl": 0,
        "daily_pnl_pct": 0,
        "drawdown_from_peak": 0,
        "positions": {},
    }


def test_invalid_price_blocks_order() -> None:
    async def _run() -> None:
        db = AsyncMock()
        # stock exists
        stock_result = MagicMock()
        stock_result.mappings.return_value.first.return_value = _stock()
        # risk_rules load empty / fail gracefully
        rules_result = MagicMock()
        rules_result.mappings.return_value.all.return_value = []
        # log event insert
        insert_result = MagicMock()

        db.execute = AsyncMock(side_effect=[rules_result, stock_result, insert_result])

        monitor = MagicMock()
        monitor.get_portfolio_snapshot = AsyncMock(return_value=_portfolio())

        checker = PreTradeRiskChecker(db, monitor)
        with patch.object(checker, "_get_current_price", AsyncMock(return_value=0.0)):
            report = await checker.check(
                {
                    "stock_code": "000001",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": None,
                },
                "simulation",
            )
        assert report.passed is False
        assert "INVALID_PRICE" in report.blocked_by

    asyncio.run(_run())


def test_zero_daily_amount_blocks_liquidity() -> None:
    async def _run() -> None:
        db = AsyncMock()
        rules_result = MagicMock()
        rules_result.mappings.return_value.all.return_value = []
        stock_result = MagicMock()
        stock_result.mappings.return_value.first.return_value = _stock()
        # order count + risk event logs (multiple)
        order_count = MagicMock()
        order_count.mappings.return_value.first.return_value = {"cnt": 0}
        insert_result = MagicMock()

        db.execute = AsyncMock(
            side_effect=[
                rules_result,
                stock_result,
                order_count,
                insert_result,  # may log liquidity fail
            ]
        )

        monitor = MagicMock()
        monitor.get_portfolio_snapshot = AsyncMock(return_value=_portfolio())
        checker = PreTradeRiskChecker(db, monitor)

        with (
            patch.object(checker, "_get_current_price", AsyncMock(return_value=10.0)),
            patch.object(
                checker, "_get_today_quote", AsyncMock(return_value={"amount": 0})
            ),
            patch.object(checker, "_log_risk_event", AsyncMock()),
            patch.object(checker, "_get_today_order_count", AsyncMock(return_value=0)),
        ):
            report = await checker.check(
                {
                    "stock_code": "000001",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": 10.0,
                },
                "simulation",
            )
        assert report.passed is False
        assert "MIN_DAILY_AMOUNT" in report.blocked_by

    asyncio.run(_run())


def test_single_position_severity_pass_warn_block() -> None:
    async def _run() -> None:
        db = AsyncMock()
        checker = PreTradeRiskChecker(db, MagicMock())
        checker._rules_loaded = True
        checker.thresholds = {
            "MAX_SINGLE_POSITION": 0.10,
            "WARN_SINGLE_POSITION": 0.08,
            "MAX_TOTAL_POSITION": 0.80,
            "MAX_DAILY_LOSS": 0.03,
            "MAX_DRAWDOWN": 0.15,
            "MAX_ORDER_FREQ": 20,
            "MIN_DAILY_AMOUNT": 50_000_000,
            "MAX_SECTOR_CONCENTRATION": 0.40,
        }
        portfolio = _portfolio(1_000_000)

        # 5% -> PASS
        r1 = await checker._check_single_position("000001", 50_000, portfolio)
        assert r1.passed is True
        assert r1.severity == "PASS"

        # 9% -> WARN
        r2 = await checker._check_single_position("000001", 90_000, portfolio)
        assert r2.passed is False
        assert r2.severity == "WARN"
        assert r2.rule_code == "WARN_SINGLE_POSITION"

        # 15% -> BLOCK
        r3 = await checker._check_single_position("000001", 150_000, portfolio)
        assert r3.passed is False
        assert r3.severity == "BLOCK"
        assert r3.rule_code == "MAX_SINGLE_POSITION"

    asyncio.run(_run())


def test_st_stock_blocked() -> None:
    async def _run() -> None:
        db = AsyncMock()
        rules_result = MagicMock()
        rules_result.mappings.return_value.all.return_value = []
        stock_result = MagicMock()
        stock_result.mappings.return_value.first.return_value = _stock(is_st=True)
        db.execute = AsyncMock(side_effect=[rules_result, stock_result])

        monitor = MagicMock()
        monitor.get_portfolio_snapshot = AsyncMock(return_value=_portfolio())
        checker = PreTradeRiskChecker(db, monitor)

        with (
            patch.object(checker, "_get_today_quote", AsyncMock(
                return_value={"price": 10, "amount": 100_000_000}
            )),
            patch.object(checker, "_get_today_order_count", AsyncMock(return_value=0)),
            patch.object(checker, "_log_risk_event", AsyncMock()),
        ):
            report = await checker.check(
                {
                    "stock_code": "000001",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": 10.0,
                },
                "simulation",
            )
        assert report.passed is False
        assert "BLOCK_ST" in report.blocked_by

    asyncio.run(_run())
