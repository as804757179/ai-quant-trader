import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "p2-research-aggregation-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import research
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

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        self.params.append(params or {})
        return self.results.pop(0)


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class ResearchAggregationContractTests(unittest.TestCase):
    def test_deep_analysis_preserves_available_time_and_source_without_conclusion(self):
        available_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        db = _Db(
            _Result(
                {
                    "total": 2,
                    "observed": 1,
                    "rejected": 1,
                    "latest_available_at": available_at,
                }
            ),
            _Result(
                [
                    {
                        "evidence_id": "evidence-1",
                        "stock_code": "600000.SH",
                        "evidence_type": "announcement",
                        "provider": "cninfo",
                        "source": "cninfo_listed_company_disclosure",
                        "available_at": available_at,
                        "quality_status": "observed",
                        "usage_status": "review_required",
                    }
                ]
            ),
        )
        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_deep_analysis(
                    stock_code="600000.sh",
                    evidence_type="announcement",
                    page=2,
                    page_size=1,
                )
            )

        payload = response.data
        self.assertEqual(payload["items"][0]["available_at"], available_at.isoformat())
        self.assertEqual(payload["summary"]["observed"], 1)
        self.assertEqual(payload["analysis_conclusion"], "not_generated")
        self.assertTrue(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])
        self.assertEqual(db.params[0]["stock_code"], "600000.SH")
        self.assertEqual(db.params[1]["evidence_type"], "announcement")
        self.assertIn("market.research_evidence", db.sql[0])
        self.assertIn("market.research_evidence_batches", db.sql[1])
        self.assertIn("ORDER BY evidence.available_at DESC, evidence.evidence_id DESC", db.sql[1])
        self.assertFalse(
            any(
                f"{operation} " in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_deep_analysis_route_requires_research_read_scope(self):
        route = next(item for item in research.router.routes if item.path == "/deep-analysis")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/research/deep-analysis").scope, "research:read")

    def test_research_exclusions_preserve_field_level_review_facts(self):
        reviewed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        db = _Db(
            _Result(
                {
                    "total": 2,
                    "review_required": 1,
                    "rejected": 1,
                    "latest_reviewed_at": reviewed_at,
                }
            ),
            _Result(
                [
                    {
                        "review_id": "review-1",
                        "stock_code": "600000.SH",
                        "readiness_status": "rejected",
                        "research_use_scope": "return_backtest",
                        "unresolved_fields": ["close"],
                        "rejected_fields": ["amount"],
                        "reviewed_at": reviewed_at,
                    }
                ]
            ),
        )
        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_research_exclusions(
                    stock_code="600000.sh",
                    readiness_status="rejected",
                    research_use_scope="return_backtest",
                    page=2,
                    page_size=1,
                )
            )

        payload = response.data
        self.assertEqual(payload["items"][0]["rejected_fields"], ["amount"])
        self.assertEqual(payload["summary"]["rejected"], 1)
        self.assertFalse(payload["risk_events_included"])
        self.assertTrue(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertEqual(db.params[0]["stock_code"], "600000.SH")
        self.assertEqual(db.params[1]["research_use_scope"], "return_backtest")
        self.assertIn("market.research_readiness_reviews", db.sql[0])
        self.assertIn("ORDER BY review.reviewed_at DESC, review.review_id DESC", db.sql[1])
        self.assertNotIn("risk.risk_events", db.sql[1])
        self.assertFalse(
            any(
                f"{operation} " in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_research_exclusions_route_requires_research_read_scope(self):
        route = next(item for item in research.router.routes if item.path == "/exclusions")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/research/exclusions").scope, "research:read")

    def test_holdings_review_preserves_position_and_readiness_without_risk_inference(self):
        reviewed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        db = _Db(
            _Result({"total": 2, "readiness_recorded": 1, "readiness_not_recorded": 1}),
            _Result(
                [
                    {
                        "stock_code": "600000.SH",
                        "total_qty": 100,
                        "available_qty": 0,
                        "frozen_qty": 0,
                        "review_id": "review-1",
                        "readiness_status": "review_required",
                        "reviewed_at": reviewed_at,
                    }
                ]
            ),
        )
        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(research.list_holdings_review(mode="simulation", page=2, page_size=1))

        payload = response.data
        self.assertEqual(payload["items"][0]["stock_code"], "600000.SH")
        self.assertEqual(payload["items"][0]["risk_association_status"], "not_recorded")
        self.assertEqual(payload["items"][0]["action_boundary"], "not_generated")
        self.assertEqual(payload["summary"]["readiness_recorded"], 1)
        self.assertEqual(payload["risk_association"]["status"], "not_recorded")
        self.assertEqual(payload["reassessment_status"], "not_evaluated")
        self.assertTrue(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])
        self.assertEqual(db.params[0]["mode"], "simulation")
        self.assertIn("trade.positions", db.sql[0])
        self.assertIn("market.research_readiness_reviews", db.sql[1])
        self.assertIn("ORDER BY p.updated_at DESC NULLS LAST, p.id DESC", db.sql[1])
        self.assertNotIn("risk.risk_events", db.sql[1])
        self.assertFalse(
            any(
                f"{operation} " in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_holdings_review_route_requires_research_read_scope(self):
        route = next(item for item in research.router.routes if item.path == "/holdings-review")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/research/holdings-review").scope, "research:read")


if __name__ == "__main__":
    unittest.main()
