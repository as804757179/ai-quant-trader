import os
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import ai, research, trade
from app.core.config import settings


ROOT = Path(__file__).resolve().parents[1]


class CoreReadOnlyContractTests(unittest.TestCase):
    def test_execution_status_contains_six_real_release_locks(self):
        keys = {
            "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
            "CERTIFIED_SCREENER_OUTPUT_ENABLED",
            "TRADING_EXECUTION_ENABLED",
            "LIVE_TRADING_ENABLED",
            "AI_ORDER_ENABLED",
            "ALLOW_SCHEDULED_ORDER",
        }
        with patch.object(settings, "TRADING_EXECUTION_ENABLED", False):
            snapshot = trade.build_execution_status()

        self.assertEqual(
            {item["key"] for item in snapshot["release_locks"]}, keys
        )
        self.assertFalse(snapshot["ai_direct_order_allowed"])

    def test_readonly_routes_only_accept_get(self):
        expected = (
            (trade.router, "/execution-status"),
            (research.router, "/readiness"),
            (ai.router, "/audit-summary"),
        )
        for router, path in expected:
            route = next(item for item in router.routes if item.path == path)
            self.assertEqual(route.methods, {"GET"})

    def test_readiness_serializer_preserves_iso_values(self):
        row = research.serialize_review(
            {
                "date_from": date(2026, 7, 1),
                "reviewed_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
                "required_fields": ["close"],
            }
        )

        self.assertEqual(row["date_from"], "2026-07-01")
        self.assertEqual(row["reviewed_at"], "2026-07-15T00:00:00+00:00")
        self.assertEqual(row["required_fields"], ["close"])

    def test_readiness_route_never_grants_research_or_trading(self):
        source = (ROOT / "app" / "api" / "research.py").read_text(encoding="utf-8")
        start = source.index('@router.get("/readiness")')
        end = source.index('@router.get("/evidence")', start)
        readiness_source = source[start:end]
        self.assertIn('"observed_only": True', readiness_source)
        self.assertIn('"research_readiness": "not_granted"', readiness_source)
        self.assertIn('"tradable": False', readiness_source)
        self.assertIn('"order_created": False', readiness_source)


if __name__ == "__main__":
    unittest.main()
