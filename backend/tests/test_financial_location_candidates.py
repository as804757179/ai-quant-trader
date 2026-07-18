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
from app.core.response import APIProblem  # noqa: E402


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


class FinancialLocationCandidateTests(unittest.TestCase):
    evidence_id = UUID("00000000-0000-0000-0000-000000000001")

    def test_route_is_read_only_and_uses_research_read_scope(self):
        route = next(
            item
            for item in research.router.routes
            if item.path == "/evidence/{evidence_id}/financial-location-candidates"
        )
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(
            route_access(
                "GET",
                "/api/v1/research/evidence/example/financial-location-candidates",
            ).scope,
            "research:read",
        )

    def test_candidates_use_latest_parse_run_with_stable_server_pagination(self):
        evidence = {
            "evidence_id": str(self.evidence_id),
            "stock_code": "000001.SZ",
            "title": "年度报告",
            "raw_hash": "a" * 64,
            "available_at": None,
            "usage_status": "review_required",
            "snapshot_id": "snapshot-1",
            "observed_raw_hash": "a" * 64,
            "observed_bytes": 1024,
            "parse_run_id": "00000000-0000-0000-0000-000000000002",
            "parser_name": "pypdf",
            "parser_version": "3.17.4",
            "normalization_version": "v1",
            "parse_status": "success",
            "page_count": 10,
            "text_page_count": 10,
            "completed_at": None,
        }
        summary = {
            "total": 2,
            "located": 1,
            "ambiguous": 1,
            "unresolved": 0,
            "rejected": 0,
        }
        row = {
            "location_id": "location-2",
            "parse_run_id": evidence["parse_run_id"],
            "page_evidence_id": "page-2",
            "field_name": "statement_currency_unit",
            "raw_value": "人民币元",
            "normalized_value": "CNY",
            "match_start": 12,
            "match_end": 16,
            "anchor_hash": "b" * 64,
            "statement_scope": "consolidated",
            "status": "located",
            "reason": None,
            "locator_version": "v1",
            "created_at": None,
            "page_number": 3,
            "extraction_status": "text_observed",
            "text_hash": "c" * 64,
            "character_count": 200,
            "failure_reason": None,
        }
        db = _Db([_Result(one=evidence), _Result(one=summary), _Result(rows=[row])])

        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_financial_location_candidates(
                    self.evidence_id,
                    field_name=None,
                    status=None,
                    page=2,
                    page_size=1,
                )
            )

        payload = response.data
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["page"], 2)
        self.assertFalse(payload["has_more"])
        self.assertEqual(payload["items"][0]["location_id"], "location-2")
        self.assertEqual(db.params[1]["parse_run_id"], evidence["parse_run_id"])
        self.assertEqual(db.params[2]["offset"], 1)
        self.assertIn("ORDER BY location.field_name", db.sql[2])
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

    def test_missing_parse_run_returns_real_empty_result(self):
        evidence = {
            "evidence_id": str(self.evidence_id),
            "stock_code": "000001.SZ",
            "title": "年度报告",
            "raw_hash": "a" * 64,
            "available_at": None,
            "usage_status": "review_required",
            "snapshot_id": None,
            "observed_raw_hash": None,
            "observed_bytes": None,
            "parse_run_id": None,
            "parser_name": None,
            "parser_version": None,
            "normalization_version": None,
            "parse_status": None,
            "page_count": None,
            "text_page_count": None,
            "completed_at": None,
        }
        db = _Db([_Result(one=evidence)])

        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_financial_location_candidates(
                    self.evidence_id,
                    field_name=None,
                    status=None,
                    page=1,
                    page_size=50,
                )
            )

        self.assertEqual(response.data["items"], [])
        self.assertEqual(response.data["location_status"], "parse_run_unavailable")
        self.assertEqual(len(db.sql), 1)

    def test_unknown_or_non_reviewable_evidence_is_rejected(self):
        db = _Db([_Result(one=None)])

        with (
            patch("app.api.research.get_db", return_value=_DbContext(db)),
            self.assertRaises(APIProblem) as raised,
        ):
            asyncio.run(
                research.list_financial_location_candidates(
                    self.evidence_id,
                    field_name=None,
                    status=None,
                    page=1,
                    page_size=50,
                )
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.code,
            "FINANCIAL_LOCATION_EVIDENCE_NOT_FOUND",
        )


if __name__ == "__main__":
    unittest.main()
