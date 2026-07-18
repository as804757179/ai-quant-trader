import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.services.ai_service import AIService


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def mappings(self):
        return self

    def all(self):
        return self.value


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    async def execute(self, statement, *_args, **_kwargs):
        self.sql.append(str(statement))
        return _Result(self.results.pop(0))


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class AiSignalSemanticsTests(unittest.TestCase):
    @staticmethod
    def _record():
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "stock_code": "600000",
            "action": "BUY",
            "confidence": 0.91,
            "risk_level": "LOW",
            "price_at": 10.0,
            "reason": "test recommendation",
            "signal_time": datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
            "valid_until": datetime.now(UTC) + timedelta(hours=1),
            "status": "active",
            "raw_agent_output": {
                "historical_data_status": "certified",
                "analysis_context_status": "ready",
            },
            "current_validity_status": "active",
            "order_created": False,
        }

    def test_signal_list_marks_buy_as_non_tradable_recommendation(self):
        db = _Db(1, [self._record()])
        service = AIService.__new__(AIService)

        with patch("app.services.ai_service.get_db", return_value=_DbContext(db)):
            response = asyncio.run(service.list_signals())

        item = response.items[0]
        self.assertEqual(item.record_type, "signal")
        self.assertEqual(item.action, "BUY")
        self.assertTrue(item.recommendation_only)
        self.assertFalse(item.tradable)
        self.assertFalse(item.research_eligible)
        self.assertEqual(item.data_authorization_status, "not_granted")
        self.assertEqual(item.current_validity_status, "active")
        self.assertEqual(item.recorded_context_status, "ready")
        self.assertIn("current_validity_status", db.sql[1])
        self.assertIn("ORDER BY s.signal_time DESC, s.id DESC", db.sql[1])
        self.assertFalse(
            any(operation in sql.upper() for sql in db.sql for operation in ("INSERT", "UPDATE", "DELETE"))
        )

    def test_missing_or_expired_effective_period_is_explicit(self):
        service = AIService.__new__(AIService)

        missing = self._record()
        missing["current_validity_status"] = "missing_valid_until"
        expired = self._record()
        expired["current_validity_status"] = "expired"

        self.assertEqual(
            service._row_to_list_item(missing).current_validity_status,
            "missing_valid_until",
        )
        self.assertEqual(
            service._row_to_list_item(expired).current_validity_status,
            "expired",
        )


if __name__ == "__main__":
    unittest.main()
