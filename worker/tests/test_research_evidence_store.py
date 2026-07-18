import asyncio
import hashlib
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from services.research_evidence_store import ResearchEvidenceStore


class ResearchEvidenceStoreTests(unittest.TestCase):
    def test_observed_evidence_stays_running_until_rows_are_written(self):
        store = ResearchEvidenceStore.__new__(ResearchEvidenceStore)
        store._insert_batch = AsyncMock()
        store._insert_evidence = AsyncMock()
        store._finalize_batch = AsyncMock()

        result = asyncio.run(
            store.persist_batch(
                ["000001.SZ"],
                [
                    {
                        "evidence_type": "announcement",
                        "stock_code": "000001.SZ",
                        "source_document_id": "1225406051",
                        "publisher_name": "平安银行",
                        "title": "董事会决议公告",
                        "document_url": "https://static.cninfo.com.cn/finalpage/2026-07-03/1225406051.PDF",
                        "source_published_date": "2026-07-03",
                        "source_timestamp_raw": "1783008000000",
                        "publication_time_precision": "date",
                        "raw_hash": "a" * 64,
                        "document_bytes": 128,
                        "quality_status": "observed",
                        "reject_reason": None,
                    }
                ],
                {
                    "provider": "cninfo",
                    "source": "cninfo_listed_company_disclosure",
                    "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                    "fallback_used": False,
                    "status": "success",
                    "raw_response_hash": "b" * 64,
                    "collector_version": "test-collector",
                    "normalizer_version": "test-normalizer",
                    "usage_status": "review_required",
                },
                datetime.now(timezone.utc),
            )
        )

        inserted_batch = store._insert_batch.await_args.args[0]
        inserted_rows = store._insert_evidence.await_args.args[0]
        self.assertEqual(inserted_batch["status"], "running")
        self.assertEqual(result["status"], "success")
        self.assertEqual(inserted_rows[0]["quality_status"], "observed")
        self.assertEqual(inserted_rows[0]["availability_basis"], "system_first_observed")
        self.assertEqual(inserted_rows[0]["available_at"], inserted_rows[0]["first_observed_at"])
        store._finalize_batch.assert_awaited_once()
        self.assertEqual(store._finalize_batch.await_args.args[1], "success")

    def test_annual_report_keeps_financial_details_unresolved(self):
        store = ResearchEvidenceStore.__new__(ResearchEvidenceStore)
        store._insert_batch = AsyncMock()
        store._insert_evidence = AsyncMock()
        store._finalize_batch = AsyncMock()

        result = asyncio.run(
            store.persist_financial_report_batch(
                ["000001.SZ"],
                [
                    {
                        "evidence_type": "financial_report",
                        "stock_code": "000001.SZ",
                        "source_document_id": "1225022887",
                        "publisher_name": "平安银行",
                        "title": "2025年年度报告",
                        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-20/1225022887.PDF",
                        "source_published_date": "2026-03-20",
                        "source_timestamp_raw": "1774070400000",
                        "publication_time_precision": "date",
                        "raw_hash": "a" * 64,
                        "document_bytes": 128,
                        "quality_status": "observed",
                        "reject_reason": None,
                        "provider_category": "category_ndbg_szsh",
                        "provider_category_version": "cninfo-annual-category-v1",
                        "report_kind": "annual",
                        "report_period_label": "2025年",
                        "report_period_end": None,
                        "period_precision": "title_label",
                        "document_role": "full_report",
                        "consolidation_scope": "unresolved",
                        "currency_code": "unresolved",
                        "currency_unit": "unresolved",
                        "audit_opinion": "unresolved",
                        "revision_status": "none",
                        "supersedes_evidence_id": None,
                        "detail_parse_status": "metadata_observed",
                    }
                ],
                {
                    "provider": "cninfo",
                    "source": "cninfo_listed_company_disclosure",
                    "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                    "provider_category": "category_ndbg_szsh",
                    "fallback_used": False,
                    "status": "success",
                    "raw_response_hash": "b" * 64,
                    "collector_version": "test-collector",
                    "normalizer_version": "test-normalizer",
                    "usage_status": "review_required",
                },
                datetime.now(timezone.utc),
            )
        )

        inserted_rows = store._insert_evidence.await_args.args[0]
        detail = inserted_rows[0]["financial_detail"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(inserted_rows[0]["evidence_type"], "financial_report")
        self.assertEqual(detail["report_kind"], "annual")
        self.assertIsNone(detail["report_period_end"])
        self.assertEqual(detail["consolidation_scope"], "unresolved")
        self.assertEqual(detail["audit_opinion"], "unresolved")

    def test_news_keeps_gdelt_time_and_title_alias_semantics_in_sidecar(self):
        store = ResearchEvidenceStore.__new__(ResearchEvidenceStore)
        store._insert_batch = AsyncMock()
        store._insert_evidence = AsyncMock()
        store._finalize_batch = AsyncMock()
        document_url = "https://example.com/byd-news"
        source_document_id = (
            f"gdelt-gal:{hashlib.sha256(document_url.encode('utf-8')).hexdigest()}"
        )

        result = asyncio.run(
            store.persist_news_batch(
                ["002594.SZ"],
                [
                    {
                        "evidence_type": "news",
                        "stock_code": "002594.SZ",
                        "source_document_id": source_document_id,
                        "publisher_name": "example.com",
                        "title": "BYD announces a pilot",
                        "document_url": document_url,
                        "source_published_date": None,
                        "source_published_at": None,
                        "source_timestamp_raw": "Wed, 15 Jul 2026 08:00:00 +0000",
                        "publication_time_precision": "unresolved",
                        "raw_hash": "a" * 64,
                        "document_bytes": 128,
                        "quality_status": "observed",
                        "reject_reason": None,
                        "provider_feed_url": "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss",
                        "source_title_raw": "BYD announces a pilot",
                        "publisher_domain": "example.com",
                        "provider_reported_at": "2026-07-15T08:00:00+00:00",
                        "provider_time_semantics": "publication_or_first_seen",
                        "association_method": "title_alias_match",
                        "association_alias": "BYD",
                        "association_status": "review_required",
                        "content_scope": "title_link_only",
                        "feed_window_minutes": 15,
                        "raw_representation": "rss_item_xml_reserialized",
                        "detail_parse_status": "metadata_observed",
                    }
                ],
                {
                    "provider": "gdelt",
                    "source": "gdelt_article_list_rss",
                    "fetch_endpoint": "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss",
                    "fallback_used": False,
                    "status": "success",
                    "fetched_at": "2026-07-15T08:00:00+00:00",
                    "raw_response_hash": "b" * 64,
                    "collector_version": "test-collector",
                    "normalizer_version": "test-normalizer",
                    "usage_status": "review_required",
                    "content_scope": "title_link_only",
                    "feed_window_minutes": 15,
                },
                datetime.now(timezone.utc),
            )
        )

        inserted_rows = store._insert_evidence.await_args.args[0]
        detail = inserted_rows[0]["news_detail"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(inserted_rows[0]["evidence_type"], "news")
        self.assertIsNone(inserted_rows[0]["source_published_at"])
        self.assertEqual(inserted_rows[0]["publication_time_precision"], "unresolved")
        self.assertEqual(detail["provider_time_semantics"], "publication_or_first_seen")
        self.assertEqual(detail["association_method"], "title_alias_match")
        self.assertEqual(detail["content_scope"], "title_link_only")
        self.assertEqual(detail["feed_window_minutes"], 15)


if __name__ == "__main__":
    unittest.main()
