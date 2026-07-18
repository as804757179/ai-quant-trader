"""Explicit read-only collection for Sprint14.3 research evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from services.data_client import DataClient
from services.research_evidence_store import ResearchEvidenceStore

logger = structlog.get_logger(__name__)


class ResearchEvidenceSyncService:
    """Collect fixed observed research evidence only when explicitly invoked."""

    def __init__(
        self,
        data_client: DataClient | None = None,
        evidence_store: ResearchEvidenceStore | None = None,
        data_service_url: str | None = None,
    ) -> None:
        self.data_client = data_client or DataClient(base_url=data_service_url)
        self.evidence_store = evidence_store or ResearchEvidenceStore()

    async def close(self) -> None:
        await self.data_client.close()
        await self.evidence_store.close()

    async def sync_symbols(self, stock_codes: list[str], limit: int = 1) -> dict[str, Any]:
        requested = list(
            dict.fromkeys(str(code).strip().upper() for code in stock_codes if str(code).strip())
        )
        results: list[dict[str, Any]] = []
        try:
            for stock_code in requested:
                started_at = datetime.now(timezone.utc)
                try:
                    items, metadata = await self.data_client.fetch_announcements_with_provenance(
                        stock_code, limit=limit
                    )
                except Exception as exc:
                    items = []
                    metadata = {
                        "provider": "cninfo",
                        "source": "cninfo_listed_company_disclosure",
                        "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                        "fallback_used": False,
                        "requested_symbols": 1,
                        "returned_items": 0,
                        "status": "fetch_failed",
                        "failure_reason": f"公告采集请求异常: {exc}",
                        "collector_version": "cninfo-announcement-collector-v1",
                        "normalizer_version": "cninfo-announcement-normalizer-v1",
                        "usage_status": "review_required",
                    }
                result = await self.evidence_store.persist_batch(
                    [stock_code], items, metadata, started_at
                )
                results.append({"stock_code": stock_code, **result})
                logger.info(
                    "research_evidence_sync_done",
                    stock_code=stock_code,
                    status=result["status"],
                    accepted_items=result["accepted_items"],
                    rejected_items=result["rejected_items"],
                )
        finally:
            await self.close()
        return {
            "requested_symbols": len(requested),
            "results": results,
            "observed_only": True,
            "tradable": False,
            "order_created": False,
        }

    async def sync_annual_reports(self, stock_codes: list[str], limit: int = 1) -> dict[str, Any]:
        requested = list(
            dict.fromkeys(str(code).strip().upper() for code in stock_codes if str(code).strip())
        )
        results: list[dict[str, Any]] = []
        try:
            for stock_code in requested:
                started_at = datetime.now(timezone.utc)
                try:
                    items, metadata = await self.data_client.fetch_annual_reports_with_provenance(
                        stock_code, limit=max(1, min(limit, 1))
                    )
                except Exception as exc:
                    items = []
                    metadata = {
                        "provider": "cninfo",
                        "source": "cninfo_listed_company_disclosure",
                        "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                        "provider_category": "category_ndbg_szsh",
                        "fallback_used": False,
                        "requested_symbols": 1,
                        "returned_items": 0,
                        "status": "fetch_failed",
                        "failure_reason": f"年报采集请求异常: {exc}",
                        "collector_version": "cninfo-annual-report-collector-v1",
                        "normalizer_version": "cninfo-annual-report-normalizer-v1",
                        "usage_status": "review_required",
                    }
                result = await self.evidence_store.persist_financial_report_batch(
                    [stock_code], items, metadata, started_at
                )
                results.append({"stock_code": stock_code, **result})
                logger.info(
                    "financial_report_evidence_sync_done",
                    stock_code=stock_code,
                    status=result["status"],
                    accepted_items=result["accepted_items"],
                    rejected_items=result["rejected_items"],
                )
        finally:
            await self.close()
        return {
            "requested_symbols": len(requested),
            "results": results,
            "observed_only": True,
            "tradable": False,
            "order_created": False,
        }

    async def sync_news_evidence(self, stock_codes: list[str], limit: int = 1) -> dict[str, Any]:
        requested = list(
            dict.fromkeys(str(code).strip().upper() for code in stock_codes if str(code).strip())
        )
        results: list[dict[str, Any]] = []
        try:
            for stock_code in requested:
                started_at = datetime.now(timezone.utc)
                try:
                    items, metadata = await self.data_client.fetch_news_evidence_with_provenance(
                        stock_code, limit=max(1, min(limit, 1))
                    )
                except Exception as exc:
                    items = []
                    metadata = {
                        "provider": "gdelt",
                        "source": "gdelt_article_list_rss",
                        "fetch_endpoint": "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss",
                        "fallback_used": False,
                        "requested_symbols": 1,
                        "returned_items": 0,
                        "status": "fetch_failed",
                        "failure_reason": f"新闻证据采集请求异常: {exc}",
                        "collector_version": "gdelt-gal-rss-news-collector-v1",
                        "normalizer_version": "gdelt-gal-rss-news-normalizer-v1",
                        "usage_status": "review_required",
                        "content_scope": "title_link_only",
                        "feed_window_minutes": 15,
                    }
                result = await self.evidence_store.persist_news_batch(
                    [stock_code], items, metadata, started_at
                )
                results.append({"stock_code": stock_code, **result})
                logger.info(
                    "news_evidence_sync_done",
                    stock_code=stock_code,
                    status=result["status"],
                    accepted_items=result["accepted_items"],
                    rejected_items=result["rejected_items"],
                )
        finally:
            await self.close()
        return {
            "requested_symbols": len(requested),
            "results": results,
            "observed_only": True,
            "tradable": False,
            "order_created": False,
        }
