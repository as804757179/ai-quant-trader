import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import research  # noqa: E402
from app.core.auth import route_access  # noqa: E402


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def mappings(self):
        return self

    def one(self):
        return self._one

    def one_or_none(self):
        return self._one

    def all(self):
        return self._rows


class _Db:
    def __init__(self, results):
        self._results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params):
        self.sql.append(str(statement))
        self.params.append(params)
        return self._results.pop(0)


class _DbContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def observed_evidence():
    return {
        "evidence_id": "00000000-0000-0000-0000-000000000001",
        "stock_code": "000001.SZ",
        "title": "年度报告",
        "raw_hash": "a" * 64,
        "available_at": None,
        "usage_status": "review_required",
        "snapshot_id": "00000000-0000-0000-0000-000000000002",
        "observed_raw_hash": "a" * 64,
        "observed_bytes": 1024,
        "parse_run_id": "00000000-0000-0000-0000-000000000003",
        "parser_name": "pypdf",
        "parser_version": "3.17.4",
        "normalization_version": "v1",
        "parse_status": "success",
        "page_count": 10,
        "text_page_count": 10,
        "completed_at": None,
    }


class FinancialLocationReviewHistoryTests(unittest.TestCase):
    evidence_id = UUID("00000000-0000-0000-0000-000000000001")
    location_id = UUID("00000000-0000-0000-0000-000000000004")

    def test_route_is_read_only_and_uses_research_read_scope(self):
        route = next(
            item
            for item in research.router.routes
            if item.path == "/evidence/{evidence_id}/financial-location-reviews"
        )
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(
            route_access(
                "GET",
                "/api/v1/research/evidence/example/financial-location-reviews",
            ).scope,
            "research:read",
        )

    def test_history_is_stably_paginated_and_keeps_review_scope_closed(self):
        row = {
            "review_id": "review-2",
            "evidence_id": str(self.evidence_id),
            "location_id": str(self.location_id),
            "snapshot_id": "00000000-0000-0000-0000-000000000002",
            "parse_run_id": "00000000-0000-0000-0000-000000000003",
            "page_evidence_id": "00000000-0000-0000-0000-000000000005",
            "raw_hash": "a" * 64,
            "locator_version": "v1",
            "reviewer_label": "reviewer",
            "reviewer_principal_id": "00000000-0000-0000-0000-000000000006",
            "conclusion": "ambiguous",
            "reason": "候选上下文不足",
            "reviewed_at": None,
            "field_name": "statement_currency_unit",
            "location_status": "ambiguous",
            "page_number": 3,
        }
        db = _Db([_Result(one=observed_evidence()), _Result(one={"total": 2}), _Result(rows=[row])])

        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_financial_location_reviews(
                    self.evidence_id,
                    location_id=self.location_id,
                    page=1,
                    page_size=1,
                )
            )

        payload = response.data
        self.assertEqual(payload["total"], 2)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["items"][0]["review_id"], "review-2")
        self.assertEqual(payload["review_scope"], "financial_location_only")
        self.assertEqual(db.params[1]["location_id"], self.location_id)
        self.assertIn("ORDER BY review.reviewed_at DESC, review.review_id DESC", db.sql[2])
        self.assertIn("LIMIT :limit OFFSET :offset", db.sql[2])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )
        self.assertTrue(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])

    def test_migration_is_append_only_and_binds_review_to_current_location_evidence(self):
        migration = (
            ROOT / "backend/alembic/versions/039_financial_location_review_audit.py"
        ).read_text(encoding="utf-8")
        self.assertIn('down_revision = "038"', migration)
        self.assertIn("market.research_financial_metadata_location_reviews", migration)
        self.assertIn("reviewer_principal_id UUID NOT NULL", migration)
        self.assertIn("idempotency_key VARCHAR(128) NOT NULL", migration)
        self.assertIn("request_hash CHAR(64) NOT NULL", migration)
        self.assertIn("financial location review binding is invalid or stale", migration)
        self.assertIn("BEFORE UPDATE OR DELETE", migration)
        self.assertIn("financial location reviews are append-only", migration)


if __name__ == "__main__":
    unittest.main()
