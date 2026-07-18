import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import system
from app.core.auth import route_access


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    async def execute(self, statement, _params=None):
        self.sql.append(str(statement))
        return self.results.pop(0)


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class SystemHealthContractTests(unittest.TestCase):
    def test_system_health_is_read_only_and_keeps_domains_separate(self):
        db = _Db(
            _Result(),
            _Result(
                {
                    "total": 3,
                    "ready": 1,
                    "review_required": 1,
                    "rejected": 1,
                    "latest_reviewed_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
                }
            ),
        )
        with patch("app.api.system.get_db", return_value=_DbContext(db)):
            response = asyncio.run(system.get_system_health())

        payload = response.data
        self.assertEqual(payload["infrastructure"]["status"], "observed")
        self.assertEqual(payload["data_qualification"]["status"], "records_observed")
        self.assertEqual(payload["data_qualification"]["research_readiness"], "not_granted")
        self.assertEqual(payload["business_release"]["status"], "not_granted")
        self.assertFalse(payload["business_release"]["tradable"])
        self.assertIn("SELECT 1", db.sql[0])
        self.assertIn("market.research_readiness_reviews", db.sql[1])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_system_health_marks_database_and_data_as_unavailable_on_probe_failure(self):
        db = _Db()
        with patch("app.api.system.get_db", return_value=_DbContext(db)):
            response = asyncio.run(system.get_system_health())

        payload = response.data
        self.assertEqual(payload["infrastructure"]["status"], "partial_observed")
        self.assertEqual(payload["infrastructure"]["components"][1]["status"], "unavailable")
        self.assertEqual(payload["data_qualification"]["status"], "unavailable")
        self.assertEqual(payload["business_release"]["status"], "not_granted")

    def test_system_health_route_requires_metrics_scope(self):
        route = next(item for item in system.router.routes if item.path == "/health")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/system/health").scope, "system:metrics.read")


if __name__ == "__main__":
    unittest.main()
