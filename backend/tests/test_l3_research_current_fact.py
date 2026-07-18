import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.api.research import (
    NewsEvidenceManualReviewRequest,
    _load_source_usage_context,
    _news_review_request_hash,
    _research_candidate_snapshot_hash,
    list_research_source_usage_evidence,
)
from pydantic import ValidationError
from uuid import UUID


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    async def execute(self, statement):
        self.sql = str(statement)
        return _Result(self.rows)


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class ResearchCurrentFactTests(unittest.TestCase):
    def test_only_latest_terms_evidence_is_used_for_current_review(self):
        row = {
            "terms_evidence_id": "new-terms",
            "provider": "gdelt",
            "source": "gdelt_article_list_rss",
            "source_scope": "metadata",
            "document_kind": "terms",
            "terms_url": "https://example.test/terms",
            "retrieved_at": None,
            "source_effective_at": None,
            "source_time_precision": "unknown",
            "raw_hash": "a" * 64,
            "document_bytes": 10,
            "content_type": "text/html",
            "status": "observed",
            "failure_reason": None,
            "collector_version": "test",
            "created_at": None,
            "review_id": "new-review",
            "usage_scope": "research",
            "decision_status": "rejected",
            "reason": "latest terms rejected",
            "reviewer_label": "reviewer",
            "identity_assurance": "verified",
            "policy_version": "v1",
            "reviewed_at": None,
        }

        async def run():
            db = _Db([row])
            contexts = await _load_source_usage_context(db)
            context = contexts[("gdelt", "gdelt_article_list_rss")]
            self.assertEqual(context["latest_reviews"]["research"]["terms_evidence_id"], "new-terms")
            self.assertEqual(context["precheck_status"], "rejected")
            self.assertIn("WITH latest_terms", db.sql)

        asyncio.run(run())

    def test_current_terms_keep_each_official_url_and_latest_review_is_stable(self):
        earlier = datetime(2026, 7, 16, 8, tzinfo=timezone.utc)
        later = datetime(2026, 7, 16, 9, tzinfo=timezone.utc)

        def row(
            terms_evidence_id,
            terms_url,
            review_id=None,
            decision_status=None,
            reviewed_at=None,
        ):
            return {
                "terms_evidence_id": terms_evidence_id,
                "provider": "gdelt",
                "source": "gdelt_article_list_rss",
                "source_scope": "metadata",
                "document_kind": "terms_of_use",
                "terms_url": terms_url,
                "retrieved_at": later,
                "source_effective_at": None,
                "source_time_precision": "unresolved",
                "raw_hash": "a" * 64,
                "document_bytes": 10,
                "content_type": "text/html",
                "status": "observed",
                "failure_reason": None,
                "collector_version": "test",
                "created_at": later,
                "review_id": review_id,
                "usage_scope": "automated_fetch" if review_id else None,
                "decision_status": decision_status,
                "reason": "test" if review_id else None,
                "reviewer_label": "reviewer" if review_id else None,
                "identity_assurance": "unverified" if review_id else None,
                "policy_version": "v1" if review_id else None,
                "reviewed_at": reviewed_at,
            }

        rows = [
            row(
                "product-document",
                "https://example.test/product",
                "product-rejected",
                "rejected",
                earlier,
            ),
            row(
                "terms-document",
                "https://example.test/terms",
                "earlier-review",
                "rejected",
                earlier,
            ),
            row(
                "terms-document",
                "https://example.test/terms",
                "later-review",
                "review_required",
                later,
            ),
        ]

        async def run():
            db = _Db(rows)
            contexts = await _load_source_usage_context(db)
            context = contexts[("gdelt", "gdelt_article_list_rss")]
            self.assertEqual(
                [item["terms_url"] for item in context["terms_evidence"]],
                ["https://example.test/product", "https://example.test/terms"],
            )
            self.assertEqual(
                [item["review_id"] for item in context["review_history"]],
                ["later-review", "product-rejected", "earlier-review"],
            )
            self.assertEqual(
                context["latest_reviews"]["automated_fetch"]["review_id"],
                "later-review",
            )
            self.assertEqual(
                context["latest_reviews"]["automated_fetch"]["decision_status"],
                "review_required",
            )
            self.assertEqual(context["precheck_status"], "rejected")
            self.assertIn("DISTINCT ON (provider, source, terms_url)", db.sql)
            self.assertIn("review.reviewed_at DESC NULLS LAST", db.sql)

            with patch("app.api.research.get_db", return_value=_DbContext(_Db(rows))):
                response = await list_research_source_usage_evidence(
                    provider=None,
                    source=None,
                )
            self.assertEqual(
                response.data["source_version"],
                "research-source-usage-evidence-v2",
            )
            self.assertEqual(
                len(response.data["items"][0]["terms_evidence"]),
                2,
            )

        asyncio.run(run())

    def test_manual_review_uses_authenticated_identity_and_idempotency(self):
        body = NewsEvidenceManualReviewRequest(
            conclusion="title_link_relevant", reason="关联关系可由标题和链接核验"
        )
        evidence_id = UUID("00000000-0000-0000-0000-000000000001")
        self.assertEqual(
            _news_review_request_hash(evidence_id, body),
            _news_review_request_hash(evidence_id, body),
        )
        with self.assertRaises(ValidationError):
            NewsEvidenceManualReviewRequest(
                reviewer_label="forged", conclusion="title_link_relevant", reason="x"
            )
        source = (Path(__file__).parents[1] / "app" / "api" / "research.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('request.headers.get("Idempotency-Key")', source)
        self.assertIn("principal.display_name", source)
        migration = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "026_news_review_principal_idempotency.py"
        ).read_text(encoding="utf-8")
        self.assertIn('down_revision = "025"', migration)
        self.assertIn("reviewer_principal_id", migration)
        self.assertIn("uq_news_review_principal_idempotency", migration)

    def test_candidate_snapshot_hash_is_stable_and_complete(self):
        items = [{"review_id": "review-1", "stock_code": "600000.SH"}]
        counts = {"review_required": 1}
        baseline = _research_candidate_snapshot_hash(items, counts, False)
        self.assertEqual(
            baseline,
            _research_candidate_snapshot_hash(items, counts, False),
        )
        self.assertNotEqual(
            baseline,
            _research_candidate_snapshot_hash(items, counts, True),
        )
        self.assertNotEqual(
            baseline,
            _research_candidate_snapshot_hash(items, {"review_required": 2}, False),
        )


if __name__ == "__main__":
    unittest.main()
