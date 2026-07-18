import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from services import signal_scan, strategy_pool


class _Result:
    def __init__(self, *, rows=None, codes=None):
        self._rows = rows or []
        self._codes = codes or []

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def fetchall(self):
        return self._codes


class _Session:
    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return self._result


class _Cache:
    def __init__(self):
        self.publish = AsyncMock()
        self.set_lock = AsyncMock(return_value=True)
        self.release_lock = AsyncMock()
        self.close = AsyncMock()


class StrategyPoolFailClosedTests(unittest.TestCase):
    @staticmethod
    def _factory(*, result=None, error=None):
        return lambda: _Session(result=result, error=error)

    @staticmethod
    def _verified_strategy():
        return {
            "id": 7,
            "name": "verified",
            "strategy_type": "dual_ma",
            "trade_mode": "simulation",
            "universe": "watchlist",
            "config_version_id": 12,
            "config_version": 2,
            "params": {"fast_period": 5},
            "config_hash": "a" * 64,
            "catalog_hash": "b" * 64,
        }

    def test_active_strategies_fail_closed_when_unavailable_empty_or_unverified(self):
        cases = (
            ("unavailable", None, RuntimeError("database unavailable")),
            ("empty", _Result(rows=[]), None),
            (
                "unverified_config",
                _Result(rows=[{**self._verified_strategy(), "params": {}}]),
                None,
            ),
        )
        fallback = AsyncMock(return_value=["000001"])
        for name, result, error in cases:
            with (
                self.subTest(name=name),
                patch.object(
                    strategy_pool,
                    "_get_session_factory",
                    return_value=self._factory(result=result, error=error),
                ),
                patch.object(
                    strategy_pool,
                    "get_active_stock_codes",
                    new=fallback,
                    create=True,
                ),
            ):
                strategies = asyncio.run(strategy_pool.get_active_strategies())
            self.assertEqual(strategies, [])
        fallback.assert_not_awaited()

    def test_active_strategies_accepts_only_verified_records(self):
        unverified = {**self._verified_strategy(), "id": 0}
        with patch.object(
            strategy_pool,
            "_get_session_factory",
            return_value=self._factory(
                result=_Result(rows=[unverified, self._verified_strategy()])
            ),
        ):
            strategies = asyncio.run(strategy_pool.get_active_strategies())

        self.assertEqual([item["id"] for item in strategies], [7])
        self.assertEqual(strategies[0]["config"]["version_id"], 12)

    def test_watchlist_fails_closed_for_invalid_id_unavailable_empty_or_bad_codes(self):
        fallback = AsyncMock(return_value=["000001"])
        with patch.object(
            strategy_pool,
            "get_active_stock_codes",
            new=fallback,
            create=True,
        ):
            self.assertEqual(asyncio.run(strategy_pool.get_strategy_stock_codes(0)), [])

            cases = (
                ("unavailable", None, RuntimeError("watchlist unavailable")),
                ("empty", _Result(codes=[]), None),
                ("malformed_code", _Result(codes=[(None,)]), None),
            )
            for name, result, error in cases:
                with self.subTest(name=name), patch.object(
                    strategy_pool,
                    "_get_session_factory",
                    return_value=self._factory(result=result, error=error),
                ):
                    codes = asyncio.run(strategy_pool.get_strategy_stock_codes(7))
                self.assertEqual(codes, [])
        fallback.assert_not_awaited()

    def test_watchlist_returns_verified_codes(self):
        with patch.object(
            strategy_pool,
            "_get_session_factory",
            return_value=self._factory(result=_Result(codes=[("000001",), ("600000",)])),
        ):
            codes = asyncio.run(strategy_pool.get_strategy_stock_codes(7))

        self.assertEqual(codes, ["000001", "600000"])

    def test_empty_strategy_pool_skips_ai_and_recommendations(self):
        ai = type("AI", (), {})()
        ai.analyze = AsyncMock()
        ai.submit_order = AsyncMock()
        cache = _Cache()
        active_strategies = AsyncMock(return_value=[])
        stock_codes = AsyncMock()

        with (
            patch.object(signal_scan, "create_backend_client", return_value=object()),
            patch.object(signal_scan, "get_active_strategies", new=active_strategies),
            patch.object(signal_scan, "get_strategy_stock_codes", new=stock_codes),
        ):
            service = signal_scan.SignalScanService(ai_analyzer=ai, cache=cache)
            stats = asyncio.run(service.scan_all())

        active_strategies.assert_awaited_once()
        stock_codes.assert_not_awaited()
        ai.analyze.assert_not_awaited()
        ai.submit_order.assert_not_awaited()
        cache.publish.assert_not_awaited()
        self.assertEqual(stats["stocks_scanned"], 0)
        self.assertEqual(stats["recommendations_created"], 0)

    def test_active_strategy_query_requires_current_approved_version(self):
        source = (ROOT / "worker" / "services" / "strategy_pool.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("strategy.strategy_version_heads", source)
        self.assertIn("strategy.strategy_version_approvals", source)
        self.assertIn("a.status = 'approved'", source)
        self.assertNotIn("WHERE is_active = TRUE", source)


if __name__ == "__main__":
    unittest.main()
