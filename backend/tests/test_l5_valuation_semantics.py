import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "l5-valuation-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.api import risk as risk_api
from app.risk.checker import PreTradeRiskChecker
from app.risk.monitor import RiskMonitor
from app.trade.base_trader import OrderRequest
from app.trade.preflight import OrderPreflight


def run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        if isinstance(self.rows, list):
            return self.rows[0] if self.rows else None
        return self.rows

    def all(self):
        if isinstance(self.rows, list):
            return self.rows
        return [] if self.rows is None else [self.rows]


class _SequenceDb:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    async def execute(self, statement, *_args, **_kwargs):
        self.sql.append(str(statement))
        return _Result(self.results.pop(0))


class _DbContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return False


class _UnavailableMonitor:
    async def get_portfolio_snapshot(self, _mode):
        return {"valuation_status": "unavailable"}


class _ValuationChecker(PreTradeRiskChecker):
    def __init__(self):
        super().__init__(object(), _UnavailableMonitor())
        self.logged_events = 0

    async def _ensure_thresholds(self):
        self._rules_loaded = True
        self.thresholds = {}

    async def _get_stock(self, _code):
        return {"is_st": False, "list_date": None, "sector": "test"}

    async def _get_observed_quote(self, _code):
        return {"price": 10, "amount": 1_000_000}

    async def _log_risk_event(self, *_args):
        self.logged_events += 1


class _CapturingRisk:
    def __init__(self):
        self.kwargs = None

    async def check(self, *_args, **kwargs):
        self.kwargs = kwargs
        from app.risk.checker import RiskCheckReport

        return RiskCheckReport(passed=False, blocked_by=["TEST_BLOCK"])


class _SnapshotMonitor:
    async def get_portfolio_snapshot(self, _mode):
        return {
            "total_assets": None,
            "cash": None,
            "total_market_value": None,
            "daily_pnl": None,
            "daily_pnl_pct": None,
            "drawdown_from_peak": None,
            "positions": {
                "600000": {
                    "name": "test",
                    "sector": "test",
                    "total_qty": 100,
                    "current_price": None,
                    "market_value": None,
                    "unrealized_pnl": None,
                    "valuation_status": "unavailable",
                    "valuation_freshness": "stale_or_missing",
                    "valuation_as_of": None,
                    "valuation_age_seconds": None,
                    "valuation_source": None,
                }
            },
            "account_snapshot_time": "2026-07-17T00:00:00+00:00",
            "account_snapshot_age_seconds": 86_400,
            "account_snapshot_freshness": "stale_or_missing",
            "valuation_status": "unavailable",
            "valuation_stale": True,
            "valuation_freshness": "stale_or_missing",
            "valuation_as_of": None,
            "valuation_age_seconds": None,
            "valuation_unavailable_positions": ["600000"],
            "valuation_source": {"quote_count": 0},
            "source": "test",
            "source_version": "test",
        }


class L5ValuationSemanticsTests(unittest.TestCase):
    @staticmethod
    def _account(record_time):
        return {
            "id": "account-1",
            "cash": Decimal("10000"),
            "daily_pnl": Decimal("-100"),
            "record_time": record_time,
            "total_assets": Decimal("11000"),
        }

    @staticmethod
    def _position(quote_time):
        return {
            "stock_code": "600000",
            "total_qty": 100,
            "available_qty": 100,
            "avg_cost": Decimal("10"),
            "current_price": Decimal("10"),
            "market_value": Decimal("1000"),
            "unrealized_pnl": Decimal("0"),
            "unrealized_pnl_pct": Decimal("0"),
            "name": "test",
            "sector": "test",
            "observed_price": Decimal("12"),
            "quote_time": quote_time,
            "quote_provider": "provider",
            "quote_source": "source",
            "quote_raw_hash": "a" * 64,
            "quote_received_at": quote_time,
            "quote_batch_id": "batch-1",
        }

    def test_fresh_provenanced_quote_is_the_only_current_valuation(self):
        now = datetime.now(UTC)
        db = _SequenceDb(
            self._account(now),
            [self._position(now)],
            {"peak": Decimal("12000")},
        )

        snapshot = run(RiskMonitor(db).get_portfolio_snapshot("simulation"))

        position = snapshot["positions"]["600000"]
        self.assertEqual(snapshot["valuation_status"], "observed")
        self.assertEqual(snapshot["total_market_value"], 1200.0)
        self.assertEqual(snapshot["total_assets"], 11200.0)
        self.assertEqual(position["current_price"], 12.0)
        self.assertEqual(position["market_value"], 1200.0)
        self.assertEqual(position["recorded_market_value"], 1000.0)
        self.assertEqual(position["valuation_source"]["provider"], "provider")
        self.assertTrue(any("market.quote_provenance" in sql for sql in db.sql))
        self.assertFalse(any("UPDATE" in sql.upper() for sql in db.sql))

    def test_stale_quote_or_account_marks_portfolio_unavailable(self):
        now = datetime.now(UTC)
        stale_quote = run(
            RiskMonitor(
                _SequenceDb(
                    self._account(now),
                    [self._position(now - timedelta(days=1))],
                    {"peak": Decimal("12000")},
                )
            ).get_portfolio_snapshot("simulation")
        )
        stale_account = run(
            RiskMonitor(
                _SequenceDb(
                    self._account(now - timedelta(days=1)),
                    [],
                    {"peak": Decimal("10000")},
                )
            ).get_portfolio_snapshot("simulation")
        )

        self.assertEqual(stale_quote["valuation_status"], "unavailable")
        self.assertEqual(stale_quote["valuation_unavailable_positions"], ["600000"])
        self.assertIsNone(stale_quote["total_market_value"])
        self.assertIsNone(stale_quote["positions"]["600000"]["current_price"])
        self.assertEqual(stale_account["account_snapshot_freshness"], "stale_or_missing")
        self.assertEqual(stale_account["valuation_status"], "unavailable")
        self.assertIsNone(stale_account["cash"])

    def test_unavailable_portfolio_blocks_risk_without_side_effect(self):
        checker = _ValuationChecker()

        report = run(
            checker.check(
                {
                    "stock_code": "600000",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": 10,
                },
                "simulation",
                record_events=False,
            )
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.blocked_by, ["PORTFOLIO_VALUATION_UNAVAILABLE"])
        self.assertEqual(checker.logged_events, 0)

    def test_actual_preflight_cannot_override_observed_quote_requirement(self):
        risk = _CapturingRisk()
        preflight = OrderPreflight(risk, object())

        run(
            preflight.check_risk(
                OrderRequest(
                    stock_code="600000",
                    side="BUY",
                    order_type="LIMIT",
                    quantity=100,
                    limit_price=10,
                ),
                "simulation",
                record_risk_events=True,
            )
        )

        self.assertEqual(risk.kwargs, {"record_events": True})

    def test_exposure_endpoint_keeps_unavailable_values_null(self):
        with (
            patch("app.api.risk.get_db", return_value=_DbContext()),
            patch("app.api.risk.RiskMonitor", return_value=_SnapshotMonitor()),
        ):
            response = run(risk_api.get_risk_exposure("simulation"))

        data = response.data
        self.assertIsNone(data["total_assets"])
        self.assertIsNone(data["position_ratio"])
        self.assertIsNone(data["positions"][0]["market_value"])
        self.assertIsNone(data["positions"][0]["ratio"])
        self.assertEqual(data["valuation_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
