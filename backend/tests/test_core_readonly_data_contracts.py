import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import backtest, portfolio, research, stock, strategy, trade


class CoreReadOnlyDataContractTests(unittest.TestCase):
    def test_new_data_routes_are_get_only(self):
        expected = (
            (portfolio.router, "/equity-curve"),
            (stock.router, "/market/status"),
            (research.router, "/candidate-status"),
            (strategy.router, "/runtime-status"),
            (backtest.router, "/validation-summary"),
            (trade.router, "/execution-status"),
        )
        for router, path in expected:
            route = next(item for item in router.routes if item.path == path)
            self.assertEqual(route.methods, {"GET"})

    def test_quote_freshness_is_explicit(self):
        now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
        fresh = stock.classify_quote_status(
            now - timedelta(seconds=10), now, 60, "open"
        )
        stale = stock.classify_quote_status(
            now - timedelta(seconds=61), now, 60, "open"
        )
        closed = stock.classify_quote_status(
            now - timedelta(hours=2), now, 60, "closed"
        )
        empty = stock.classify_quote_status(None, now, 60, "open")

        self.assertEqual(fresh, ("fresh", 10))
        self.assertEqual(stale, ("stale", 61))
        self.assertEqual(closed, ("market_closed", 7200))
        self.assertEqual(empty, ("empty", None))

    def test_strategy_runtime_hash_is_stable_and_declares_data_profile(self):
        first = strategy.build_strategy_runtime_status()
        second = strategy.build_strategy_runtime_status()

        self.assertEqual(first["config_hash"], second["config_hash"])
        self.assertTrue(first["items"])
        for item in first["items"]:
            self.assertTrue(item["requirement_profile"])
            self.assertTrue(item["required_fields"])


if __name__ == "__main__":
    unittest.main()
