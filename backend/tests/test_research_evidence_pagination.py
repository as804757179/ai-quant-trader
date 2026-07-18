import asyncio
import os
import unittest
from uuid import UUID
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import research
from app.core.response import APIProblem


class _Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one(self):
        return self.value

    def one_or_none(self):
        return self.value

    def all(self):
        return self.value


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


class ResearchEvidencePaginationTests(unittest.TestCase):
    def test_evidence_returns_real_total_and_stable_server_page(self):
        db = _Db(
            {
                "total": 3,
                "observed": 3,
                "rejected": 0,
                "stock_count": 2,
                "latest_available_at": None,
                "usage_statuses": ["review_required"],
            },
            [{"evidence_id": "news-2"}],
        )
        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_research_evidence(
                    stock_code=None,
                    evidence_type="news",
                    quality_status="observed",
                    page=2,
                    page_size=1,
                )
            )

        payload = response.data
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 1)
        self.assertEqual(payload["items"][0]["evidence_id"], "news-2")
        self.assertEqual(db.params[1]["offset"], 1)
        self.assertIn("COUNT(*) AS total", db.sql[0])
        self.assertIn(
            "ORDER BY evidence.available_at DESC, evidence.evidence_id DESC",
            db.sql[1],
        )
        self.assertIn("LIMIT :limit OFFSET :offset", db.sql[1])
        self.assertNotIn("financial_report_snapshot_location", db.sql[1])
        self.assertNotIn("financial_report_detail", db.sql[1])
        self.assertNotIn("association_alias", db.sql[1])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_evidence_detail_returns_sidecar_data_separately_from_list(self):
        db = _Db(
            {
                "evidence_id": "00000000-0000-0000-0000-000000000001",
                "evidence_type": "news",
                "stock_code": "002594.SZ",
            },
            {"detail": {"content_scope": "title_link_only"}},
            {"review": {"conclusion": "needs_more_evidence"}},
        )
        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.get_research_evidence(
                    UUID("00000000-0000-0000-0000-000000000001")
                )
            )

        item = response.data["item"]
        self.assertEqual(item["news_detail"]["content_scope"], "title_link_only")
        self.assertEqual(item["manual_review"]["conclusion"], "needs_more_evidence")
        self.assertIsNone(item["financial_report_detail"])
        self.assertTrue(any("market.research_news_details" in sql for sql in db.sql))
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_evidence_detail_rejects_unknown_identifier(self):
        db = _Db(None)
        with patch("app.api.research.get_db", return_value=_DbContext(db)), self.assertRaises(
            APIProblem
        ) as raised:
            asyncio.run(
                research.get_research_evidence(
                    UUID("00000000-0000-0000-0000-000000000009")
                )
            )

        self.assertEqual(raised.exception.code, "RESEARCH_EVIDENCE_NOT_FOUND")
        self.assertEqual(raised.exception.status_code, 404)

    def test_evidence_batches_return_real_total_and_stable_server_page(self):
        db = _Db(
            {"total": 3},
            [{"batch_id": "batch-2", "received_at": None}],
        )
        with patch("app.api.research.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                research.list_research_evidence_batches(
                    limit=None,
                    page=2,
                    page_size=1,
                )
            )

        payload = response.data
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 1)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["items"][0]["batch_id"], "batch-2")
        self.assertEqual(db.params[1]["offset"], 1)
        self.assertIn("COUNT(*) AS total", db.sql[0])
        self.assertIn("ORDER BY received_at DESC, batch_id DESC", db.sql[1])
        self.assertIn("LIMIT :limit", db.sql[1])
        self.assertIn("OFFSET :offset", db.sql[1])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )


if __name__ == "__main__":
    unittest.main()
