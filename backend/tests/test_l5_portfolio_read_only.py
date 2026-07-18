import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.api import portfolio as portfolio_api
from app.risk.fuse import FuseManager
from app.services.portfolio_service import PortfolioService


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        if isinstance(self.rows, list):
            return self.rows[0] if self.rows else None
        return self.rows

    def scalar(self):
        value = self.first()
        if isinstance(value, dict):
            return next(iter(value.values()), None)
        return value


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    async def execute(self, statement, *_args, **_kwargs):
        self.sql.append(str(statement))
        return _Result(self.rows)


class _SequenceDb:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    async def execute(self, statement, *_args, **_kwargs):
        sql = str(statement)
        self.sql.append(sql)
        if "SET TRANSACTION" in sql.upper():
            return _Result([])
        return _Result(self.results.pop(0))


class _DbContext:
    def __init__(self, rows_or_db):
        self.db = (
            rows_or_db if isinstance(rows_or_db, _SequenceDb) else _Db(rows_or_db)
        )

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class _Cache:
    def __init__(self):
        self.set_calls = 0
        self.get_calls = 0

    async def get_raw_strict(self, *_args):
        self.get_calls += 1
        return None

    async def set_raw_strict(self, *_args):
        self.set_calls += 1


class PortfolioReadOnlyTests(unittest.TestCase):
    def _position_row(self, *, quote_time, observed_price):
        return {
            "stock_code": "600000",
            "total_qty": 100,
            "available_qty": 0,
            "avg_cost": Decimal("10"),
            "current_price": Decimal("10"),
            "market_value": Decimal("1000"),
            "updated_at": datetime(2026, 7, 16, tzinfo=UTC),
            "name": "test",
            "sector": "test",
            "observed_price": observed_price,
            "quote_time": quote_time,
            "quote_provider": "provider",
            "quote_source": "source",
            "quote_raw_hash": "a" * 64,
            "quote_received_at": quote_time,
            "quote_batch_id": "batch",
        }

    def test_stale_or_missing_quote_does_not_use_cost_as_current_price(self):
        row = self._position_row(
            quote_time=datetime.now(UTC) - timedelta(days=1), observed_price=Decimal("12")
        )
        context = _DbContext([row])
        with patch("app.services.portfolio_service.get_db", return_value=context):
            positions = asyncio.run(PortfolioService().get_positions("simulation"))

        position = positions[0]
        self.assertIsNone(position["current_price"])
        self.assertIsNone(position["market_value"])
        self.assertIsNone(position["unrealized_pnl"])
        self.assertEqual(position["cost_basis"], 10.0)
        self.assertEqual(position["cost_basis_value"], 1000.0)
        self.assertEqual(position["valuation_status"], "unavailable")
        self.assertTrue(position["valuation_stale"])
        sql = " ".join(context.db.sql).upper()
        self.assertIn("SET TRANSACTION READ ONLY", sql)
        self.assertIn("LEFT JOIN LATERAL", sql)
        self.assertIn("Q.STOCK_CODE = P.STOCK_CODE", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertNotIn("DISTINCT ON (Q.STOCK_CODE)", sql)
        self.assertNotIn("UPDATE", sql)
        self.assertNotIn("INSERT", sql)
        self.assertNotIn("DELETE", sql)

    def test_fresh_provenanced_quote_is_explicitly_labeled(self):
        now = datetime.now(UTC)
        row = self._position_row(quote_time=now, observed_price=Decimal("12"))
        with patch(
            "app.services.portfolio_service.get_db", return_value=_DbContext([row])
        ):
            positions = asyncio.run(PortfolioService().get_positions("simulation"))

        position = positions[0]
        self.assertEqual(position["current_price"], 12.0)
        self.assertEqual(position["market_value"], 1200.0)
        self.assertEqual(position["valuation_status"], "observed")
        self.assertFalse(position["valuation_stale"])
        self.assertEqual(position["valuation_source"]["provider"], "provider")
        self.assertEqual(position["valuation_source"]["freshness_threshold_seconds"], 60)

    def test_future_quote_is_not_current_valuation(self):
        row = self._position_row(
            quote_time=datetime.now(UTC) + timedelta(minutes=1),
            observed_price=Decimal("12"),
        )
        with patch(
            "app.services.portfolio_service.get_db", return_value=_DbContext([row])
        ):
            positions = asyncio.run(PortfolioService().get_positions("simulation"))

        position = positions[0]
        self.assertIsNone(position["current_price"])
        self.assertEqual(position["valuation_status"], "unavailable")
        self.assertTrue(position["valuation_stale"])

    def test_summary_reads_current_valuation_without_writes(self):
        now = datetime.now(UTC)
        db = _SequenceDb(
            {
                "id": 1,
                "record_time": now,
                "cash": Decimal("10000"),
                "daily_pnl": Decimal("0"),
            },
            [],
            {"peak": Decimal("10000")},
            [],
        )
        cache = _Cache()
        with (
            patch(
                "app.services.portfolio_service.get_db",
                return_value=_DbContext(db),
            ),
            patch("app.services.portfolio_service.CacheManager", return_value=cache),
        ):
            summary = asyncio.run(PortfolioService().get_summary("simulation"))

        sql = " ".join(db.sql).upper()
        self.assertIn("SET TRANSACTION READ ONLY", sql)
        self.assertNotIn("UPDATE", sql)
        self.assertNotIn("INSERT", sql)
        self.assertNotIn("DELETE", sql)
        self.assertEqual(summary["valuation_status"], "cash_only")
        self.assertEqual(summary["valuation_freshness"], "fresh")
        self.assertEqual(summary["valuation_as_of"], now.isoformat())
        self.assertEqual(summary["valuation_source"]["account_record_id"], "1")
        self.assertFalse(summary["is_fused"])
        self.assertEqual(cache.get_calls, 1)
        self.assertEqual(cache.set_calls, 0)

    def test_equity_curve_is_historical_record_not_current_valuation(self):
        record_time = datetime.now(UTC) - timedelta(days=1)
        context = _DbContext(
            [
                {
                    "id": 7,
                    "record_time": record_time,
                    "total_assets": Decimal("11000"),
                    "cash": Decimal("10000"),
                    "market_value": Decimal("1000"),
                    "daily_pnl": Decimal("10"),
                    "total_pnl": Decimal("100"),
                    "total_pnl_pct": Decimal("1"),
                    "position_count": 1,
                    "position_ratio": Decimal("0.09"),
                    "data_type": "snapshot",
                }
            ]
        )
        with patch("app.services.portfolio_service.get_db", return_value=context):
            curve = asyncio.run(PortfolioService().get_equity_curve("simulation", 30))

        point = curve["items"][0]
        sql = " ".join(context.db.sql).upper()
        self.assertIn("SET TRANSACTION READ ONLY", sql)
        self.assertNotIn("UPDATE", sql)
        self.assertNotIn("INSERT", sql)
        self.assertNotIn("DELETE", sql)
        self.assertEqual(point["valuation_status"], "recorded_snapshot")
        self.assertEqual(point["valuation_freshness"], "historical_record")
        self.assertTrue(point["valuation_stale"])
        self.assertEqual(point["valuation_as_of"], record_time.isoformat())
        self.assertGreater(point["valuation_age_seconds"], 0)
        self.assertEqual(point["valuation_source"]["record_id"], "7")
        self.assertEqual(curve["valuation_status"], "historical_record")
        self.assertTrue(curve["valuation_stale"])
        self.assertEqual(curve["source_version"], "account-equity-curve-v3")

    def test_empty_equity_curve_is_explicitly_unavailable(self):
        with patch(
            "app.services.portfolio_service.get_db", return_value=_DbContext([])
        ):
            curve = asyncio.run(PortfolioService().get_equity_curve("simulation", 30))

        self.assertEqual(curve["items"], [])
        self.assertEqual(curve["valuation_status"], "unavailable")
        self.assertEqual(curve["valuation_freshness"], "stale_or_missing")
        self.assertIsNone(curve["valuation_as_of"])

    def test_portfolio_routes_are_get_only(self):
        for path in ("/summary", "/positions", "/equity-curve"):
            route = next(item for item in portfolio_api.router.routes if item.path == path)
            self.assertEqual(route.methods, {"GET"})

    def test_active_fuse_read_does_not_repair_cache(self):
        cache = _Cache()
        manager = FuseManager(None, cache)

        async def active(_mode):
            return True

        async def no_cached(_mode):
            return None

        manager._db_is_fused = active
        manager._cache_state = no_cached
        self.assertTrue(asyncio.run(manager.is_fused("simulation")))
        self.assertEqual(cache.set_calls, 0)


if __name__ == "__main__":
    unittest.main()
