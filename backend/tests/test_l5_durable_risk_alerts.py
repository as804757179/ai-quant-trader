import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "l5-durable-alerts-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.api import risk as risk_api
from app.risk.alerts import list_persisted_risk_alerts, summarize_persisted_risk_alerts
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager


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

    def scalar(self):
        return self.rows


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        self.params.append(params or {})
        return _Result(self.results.pop(0))


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class _Cache:
    def __init__(self):
        self.values = []

    async def set_raw_strict(self, key, value):
        self.values.append((key, value))

    async def delete_raw_strict(self, key):
        self.values.append((key, None))


class L5DurableRiskAlertsTests(unittest.TestCase):
    @staticmethod
    def _event(
        *,
        action_taken="warn",
        rule_code="MAX_DRAWDOWN",
        trigger_value=Decimal("0.12"),
        threshold=Decimal("0.10"),
    ):
        return {
            "id": 7,
            "rule_code": rule_code,
            "trigger_value": trigger_value,
            "threshold": threshold,
            "action_taken": action_taken,
            "detail": {"message": "风险阈值触发", "mode": "simulation"},
            "is_resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "created_at": datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
        }

    def test_list_reads_persisted_events_with_stable_pagination(self):
        db = _Db({"total": 3}, [self._event()])

        result = run(
            list_persisted_risk_alerts(
                db,
                page=2,
                page_size=1,
                level="warning",
                alert_type="MAX_DRAWDOWN",
            )
        )

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["page_size"], 1)
        self.assertEqual(result["items"][0]["level"], "WARNING")
        self.assertEqual(result["items"][0]["alert_type"], "MAX_DRAWDOWN")
        self.assertEqual(db.params[1]["offset"], 1)
        self.assertIn("risk.risk_events", db.sql[0])
        self.assertIn("ORDER BY created_at DESC, id DESC", db.sql[1])
        self.assertFalse(
            any(
                operation in sql.upper()
                for sql in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_nullable_legacy_thresholds_remain_unknown(self):
        db = _Db({"total": 1}, [self._event(trigger_value=None, threshold=None)])

        result = run(list_persisted_risk_alerts(db, page=1, page_size=1))

        self.assertIsNone(result["items"][0]["trigger_value"])
        self.assertIsNone(result["items"][0]["threshold"])

    def test_summary_uses_the_same_persisted_window(self):
        db = _Db(
            {"total": 4},
            [self._event(action_taken="critical", rule_code="FUSE_ACTIVATED")],
        )

        result = run(summarize_persisted_risk_alerts(db, limit=1))

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["available_total"], 4)
        self.assertEqual(result["critical"], 1)
        self.assertEqual(result["latest"]["alert_type"], "FUSE_ACTIVATED")
        self.assertEqual(result["source"], "risk.risk_events")

    def test_alert_endpoint_keeps_limit_compatibility(self):
        response_data = {"items": [], "total": 0, "page": 1, "page_size": 10}
        loader = AsyncMock(return_value=response_data)
        with (
            patch("app.api.risk.get_db", return_value=_DbContext(object())),
            patch("app.api.risk.list_persisted_risk_alerts", loader),
        ):
            response = run(
                risk_api.list_recent_alerts(
                    limit=10,
                    page=1,
                    page_size=None,
                    level=None,
                    alert_type=None,
                )
            )

        self.assertEqual(response.data, response_data)
        self.assertEqual(loader.await_args.kwargs["page_size"], 10)

    def test_fuse_activation_appends_a_durable_critical_event(self):
        db = _Db(None, None, None)
        cache = _Cache()
        with patch("app.ws.publisher.publish_alert", new_callable=AsyncMock):
            run(
                FuseManager(db, cache).activate(
                    "simulation",
                    "drawdown",
                    {"total_assets": 1},
                    activated_by="00000000-0000-0000-0000-000000000001",
                )
            )

        self.assertIn("risk.fuse_records", db.sql[1])
        self.assertIn("risk.risk_events", db.sql[2])
        self.assertEqual(db.params[2]["rule_code"], "FUSE_ACTIVATED")
        self.assertEqual(db.params[2]["action_taken"], "critical")
        self.assertEqual(len(cache.values), 1)

    def test_repeated_fuse_activation_remains_idempotent_and_audited(self):
        db = _Db("active", None)
        cache = _Cache()

        run(
            FuseManager(db, cache).activate(
                "simulation",
                "drawdown",
                {"total_assets": 1},
                activated_by="00000000-0000-0000-0000-000000000001",
            )
        )

        self.assertEqual(len(db.sql), 2)
        self.assertIn("risk.risk_events", db.sql[1])
        self.assertEqual(db.params[1]["rule_code"], "FUSE_ACTIVATION_NOOP")
        self.assertEqual(db.params[1]["action_taken"], "noop")
        self.assertEqual(len(cache.values), 1)

    def test_actual_early_risk_rejections_append_durable_events(self):
        order_request = {
            "stock_code": "600000",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 10,
        }
        scenarios = (
            (None, "STOCK_NOT_FOUND"),
            ({"code": "600000"}, "OBSERVED_QUOTE_UNAVAILABLE"),
        )

        for stock, expected_code in scenarios:
            db = _Db([], stock, None, None)
            report = run(
                PreTradeRiskChecker(db, object()).check(
                    order_request,
                    "simulation",
                    record_events=True,
                )
            )

            self.assertEqual(report.blocked_by, [expected_code])
            self.assertIn("risk.risk_events", db.sql[-1])
            self.assertEqual(db.params[-1]["rule_code"], expected_code)
            self.assertEqual(db.params[-1]["action_taken"], "block")


if __name__ == "__main__":
    unittest.main()
