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

    def all(self):
        return self.row if isinstance(self.row, list) else []


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, _params=None):
        self.sql.append(str(statement))
        self.params.append(_params or {})
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
                f"{operation} " in statement.upper()
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

    def test_system_alerts_keep_risk_events_out_and_use_server_pagination(self):
        db = _Db(
            _Result(
                {
                    "total": 2,
                    "system_operation": 1,
                    "data_qualification": 1,
                    "latest_event_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
                }
            ),
            _Result(
                [
                    {
                        "category": "data_qualification",
                        "alert_id": "data-blocker:review-1",
                        "severity": "warning",
                        "alert_type": "data_blocker:unresolved",
                        "source": "market.data_blocker_reviews",
                    }
                ]
            ),
        )
        with patch("app.api.system.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                system.list_system_alerts(category="data_qualification", page=2, page_size=1)
            )

        payload = response.data
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["summary"]["data_qualification"], 1)
        self.assertFalse(payload["risk_alerts_included"])
        self.assertFalse(payload["tradable"])
        self.assertEqual(payload["items"][0]["category"], "data_qualification")
        self.assertEqual(db.params[0]["category"], "data_qualification")
        self.assertIn("audit.async_jobs", db.sql[0])
        self.assertIn("market.research_date_reviews", db.sql[1])
        self.assertNotIn("risk.risk_events", db.sql[1])
        self.assertIn("ORDER BY event_time DESC NULLS LAST, alert_id DESC", db.sql[1])
        self.assertFalse(
            any(
                f"{operation} " in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_system_alerts_route_requires_metrics_scope(self):
        route = next(item for item in system.router.routes if item.path == "/alerts")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/system/alerts").scope, "system:metrics.read")

    def test_system_jobs_are_read_only_and_use_server_pagination(self):
        db = _Db(
            _Result(
                {
                    "total": 2,
                    "pending": 1,
                    "running": 0,
                    "failed_or_blocked": 1,
                    "latest_updated_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
                }
            ),
            _Result(
                [
                    {
                        "job_id": "job-1",
                        "job_type": "backtest",
                        "status": "failed",
                        "progress": 80,
                    }
                ]
            ),
        )
        with patch("app.api.system.get_db", return_value=_DbContext(db)):
            response = asyncio.run(system.list_system_jobs(page=2, page_size=1))

        payload = response.data
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["summary"]["failed_or_blocked"], 1)
        self.assertEqual(payload["items"][0]["job_id"], "job-1")
        self.assertEqual(payload["scheduler"]["registration_status"], "not_observed")
        self.assertEqual(payload["scheduler"]["runtime_status"], "not_observed")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])
        self.assertIn("audit.async_jobs", db.sql[0])
        self.assertIn("ORDER BY updated_at DESC, job_id DESC", db.sql[1])
        self.assertEqual(db.params[1], {"limit": 1, "offset": 1})
        self.assertFalse(
            any(
                f"{operation} " in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_system_jobs_route_requires_metrics_scope(self):
        route = next(item for item in system.router.routes if item.path == "/jobs")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/system/jobs").scope, "system:metrics.read")


if __name__ == "__main__":
    unittest.main()
