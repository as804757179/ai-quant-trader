import asyncio
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from services.research_evidence_sync import ResearchEvidenceSyncService


class FakeDataClient:
    def __init__(self):
        self.requests = []
        self.annual_requests = []
        self.news_requests = []
        self.closed = False

    async def fetch_announcements_with_provenance(self, code, limit):
        self.requests.append((code, limit))
        return [], {
            "provider": "cninfo",
            "source": "cninfo_listed_company_disclosure",
            "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            "fallback_used": False,
            "status": "fetch_failed",
            "failure_reason": "测试请求失败",
            "collector_version": "test-collector",
            "normalizer_version": "test-normalizer",
            "usage_status": "review_required",
        }

    async def fetch_annual_reports_with_provenance(self, code, limit):
        self.annual_requests.append((code, limit))
        return [], {
            "provider": "cninfo",
            "source": "cninfo_listed_company_disclosure",
            "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            "provider_category": "category_ndbg_szsh",
            "fallback_used": False,
            "status": "fetch_failed",
            "failure_reason": "测试年报请求失败",
            "collector_version": "test-collector",
            "normalizer_version": "test-normalizer",
            "usage_status": "review_required",
        }

    async def fetch_news_evidence_with_provenance(self, code, limit):
        self.news_requests.append((code, limit))
        return [], {
            "provider": "gdelt",
            "source": "gdelt_article_list_rss",
            "fetch_endpoint": "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss",
            "fallback_used": False,
            "status": "fetch_failed",
            "failure_reason": "测试新闻请求失败",
            "collector_version": "test-collector",
            "normalizer_version": "test-normalizer",
            "usage_status": "review_required",
            "content_scope": "title_link_only",
            "feed_window_minutes": 15,
        }

    async def close(self):
        self.closed = True


class FakeEvidenceStore:
    def __init__(self):
        self.batches = []
        self.financial_batches = []
        self.news_batches = []
        self.closed = False

    async def persist_batch(self, requested_codes, items, metadata, started_at):
        self.batches.append((requested_codes, items, metadata))
        return {
            "batch_id": "batch-1",
            "status": "fetch_failed",
            "accepted_items": 0,
            "rejected_items": 0,
            "failure_reason": metadata["failure_reason"],
        }

    async def persist_financial_report_batch(self, requested_codes, items, metadata, started_at):
        self.financial_batches.append((requested_codes, items, metadata))
        return {
            "batch_id": "financial-batch-1",
            "status": "fetch_failed",
            "accepted_items": 0,
            "rejected_items": 0,
            "failure_reason": metadata["failure_reason"],
        }

    async def persist_news_batch(self, requested_codes, items, metadata, started_at):
        self.news_batches.append((requested_codes, items, metadata))
        return {
            "batch_id": "news-batch-1",
            "status": "fetch_failed",
            "accepted_items": 0,
            "rejected_items": 0,
            "failure_reason": metadata["failure_reason"],
        }

    async def close(self):
        self.closed = True


class ResearchEvidenceSyncTests(unittest.TestCase):
    def test_sync_is_explicit_and_returns_non_trading_status(self):
        client = FakeDataClient()
        store = FakeEvidenceStore()
        service = ResearchEvidenceSyncService(data_client=client, evidence_store=store)

        result = asyncio.run(service.sync_symbols(["000001.sz"], limit=1))

        self.assertEqual(client.requests, [("000001.SZ", 1)])
        self.assertEqual(len(store.batches), 1)
        self.assertFalse(store.batches[0][2]["fallback_used"])
        self.assertTrue(result["observed_only"])
        self.assertFalse(result["tradable"])
        self.assertFalse(result["order_created"])
        self.assertTrue(client.closed)
        self.assertTrue(store.closed)

    def test_annual_report_sync_is_explicit_and_returns_non_trading_status(self):
        client = FakeDataClient()
        store = FakeEvidenceStore()
        service = ResearchEvidenceSyncService(data_client=client, evidence_store=store)

        result = asyncio.run(service.sync_annual_reports(["000001.sz"], limit=5))

        self.assertEqual(client.annual_requests, [("000001.SZ", 1)])
        self.assertEqual(len(store.financial_batches), 1)
        self.assertEqual(store.financial_batches[0][2]["provider_category"], "category_ndbg_szsh")
        self.assertTrue(result["observed_only"])
        self.assertFalse(result["tradable"])
        self.assertFalse(result["order_created"])
        self.assertTrue(client.closed)
        self.assertTrue(store.closed)

    def test_news_sync_is_explicit_and_returns_non_trading_status(self):
        client = FakeDataClient()
        store = FakeEvidenceStore()
        service = ResearchEvidenceSyncService(data_client=client, evidence_store=store)

        result = asyncio.run(service.sync_news_evidence(["002594.sz"], limit=5))

        self.assertEqual(client.news_requests, [("002594.SZ", 1)])
        self.assertEqual(len(store.news_batches), 1)
        self.assertEqual(store.news_batches[0][2]["provider"], "gdelt")
        self.assertEqual(store.news_batches[0][2]["content_scope"], "title_link_only")
        self.assertTrue(result["observed_only"])
        self.assertFalse(result["tradable"])
        self.assertFalse(result["order_created"])
        self.assertTrue(client.closed)
        self.assertTrue(store.closed)


if __name__ == "__main__":
    unittest.main()
