import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import research  # noqa: E402
from app.core.auth import route_access  # noqa: E402
from app.core.response import APIProblem  # noqa: E402


class _Result:
    def __init__(self, *, one=None, rows=None, first=None):
        self._one = one
        self._rows = rows or []
        self._first = first

    def mappings(self):
        return self

    def one(self):
        return self._one

    def one_or_none(self):
        return self._one

    def first(self):
        return self._first

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


def request_with_idempotency_key(key: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/research/evidence/example/financial-location-reviews",
            "raw_path": b"/api/v1/research/evidence/example/financial-location-reviews",
            "query_string": b"",
            "headers": [(b"idempotency-key", key.encode("ascii"))],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


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


def reviewable_location():
    return {
        "location_id": "00000000-0000-0000-0000-000000000004",
        "parse_run_id": "00000000-0000-0000-0000-000000000003",
        "page_evidence_id": "00000000-0000-0000-0000-000000000005",
        "field_name": "statement_currency_unit",
        "location_status": "located",
        "locator_version": "v1",
        "snapshot_id": "00000000-0000-0000-0000-000000000002",
        "raw_hash": "a" * 64,
        "page_number": 3,
        "extraction_status": "text_observed",
    }


class FinancialLocationReviewAppendTests(unittest.TestCase):
    evidence_id = UUID("00000000-0000-0000-0000-000000000001")
    location_id = UUID("00000000-0000-0000-0000-000000000004")
    principal = SimpleNamespace(
        principal_id="00000000-0000-0000-0000-000000000006",
        display_name="reviewer",
    )

    def test_route_requires_append_scope(self):
        route = next(
            item
            for item in research.router.routes
            if item.path == "/evidence/{evidence_id}/financial-location-reviews"
            and item.methods == {"POST"}
        )
        self.assertEqual(route.methods, {"POST"})
        self.assertEqual(
            route_access(
                "POST",
                "/api/v1/research/evidence/example/financial-location-reviews",
            ).scope,
            "research:review.append",
        )

    def test_append_binds_current_location_and_returns_closed_review_result(self):
        body = research.FinancialLocationReviewRequest(
            location_id=self.location_id,
            conclusion="confirmed",
            reason="页内锚点与表头一致。",
        )
        inserted = {
            "review_id": "00000000-0000-0000-0000-000000000007",
            "evidence_id": str(self.evidence_id),
            "location_id": str(self.location_id),
            "snapshot_id": observed_evidence()["snapshot_id"],
            "parse_run_id": observed_evidence()["parse_run_id"],
            "page_evidence_id": reviewable_location()["page_evidence_id"],
            "raw_hash": "a" * 64,
            "locator_version": "v1",
            "reviewer_label": "reviewer",
            "reviewer_principal_id": self.principal.principal_id,
            "idempotency_key": "review-key-0001",
            "request_hash": "b" * 64,
            "conclusion": "confirmed",
            "reason": body.reason,
            "reviewed_at": None,
        }
        db = _Db(
            [
                _Result(one=observed_evidence()),
                _Result(one=reviewable_location()),
                _Result(first=inserted),
            ]
        )

        with (
            patch("app.api.research.get_db", return_value=_DbContext(db)),
            patch("app.api.research.get_request_principal", return_value=self.principal),
        ):
            response = asyncio.run(
                research.append_financial_location_review(
                    self.evidence_id,
                    body,
                    request_with_idempotency_key("review-key-0001"),
                )
            )

        payload = response.data
        self.assertEqual(payload["item"]["review_id"], inserted["review_id"])
        self.assertEqual(payload["location"]["location_id"], str(self.location_id))
        self.assertEqual(payload["review_scope"], "financial_location_only")
        self.assertEqual(db.params[2]["reviewer_principal_id"], self.principal.principal_id)
        self.assertIn("INSERT INTO market.research_financial_metadata_location_reviews", db.sql[2])
        self.assertTrue(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])

    def test_reused_idempotency_key_with_changed_payload_is_rejected(self):
        body = research.FinancialLocationReviewRequest(
            location_id=self.location_id,
            conclusion="confirmed",
            reason="页内锚点与表头一致。",
        )
        existing = {
            "review_id": "00000000-0000-0000-0000-000000000007",
            "request_hash": "different-request-hash",
        }
        db = _Db(
            [
                _Result(one=observed_evidence()),
                _Result(one=reviewable_location()),
                _Result(first=None),
                _Result(one=existing),
            ]
        )

        with (
            patch("app.api.research.get_db", return_value=_DbContext(db)),
            patch("app.api.research.get_request_principal", return_value=self.principal),
            self.assertRaises(APIProblem) as raised,
        ):
            asyncio.run(
                research.append_financial_location_review(
                    self.evidence_id,
                    body,
                    request_with_idempotency_key("review-key-0001"),
                )
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_PAYLOAD_CONFLICT")


if __name__ == "__main__":
    unittest.main()
