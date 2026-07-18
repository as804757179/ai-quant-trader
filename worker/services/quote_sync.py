from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from services.cache import CacheManager
from services.data_client import DataClient
from services.quote_store import QuoteStore
from services.stock_pool import get_active_stock_codes

logger = structlog.get_logger(__name__)

QUOTE_TTL = int(os.getenv("QUOTE_CACHE_TTL", "8"))
QUOTE_SYNC_LIMIT = int(os.getenv("QUOTE_SYNC_STOCK_LIMIT", "100"))
QUOTE_BATCH_SIZE = min(40, max(1, int(os.getenv("QUOTE_SYNC_BATCH_SIZE", "40"))))
CHANNEL_QUOTES = "channel:quotes"


class QuoteSyncService:
    """实时行情同步服务（对齐 DataService.get_quote 数据格式）。"""

    def __init__(
        self,
        data_client: DataClient | None = None,
        cache: CacheManager | None = None,
        quote_store: QuoteStore | None = None,
        stock_limit: int = QUOTE_SYNC_LIMIT,
        quote_ttl: int = QUOTE_TTL,
        batch_size: int = QUOTE_BATCH_SIZE,
    ) -> None:
        self.data_client = data_client or DataClient()
        self.cache = cache or CacheManager()
        self.quote_store = quote_store or QuoteStore()
        self.stock_limit = stock_limit
        self.quote_ttl = quote_ttl
        self.batch_size = batch_size

    async def sync_all(self) -> dict[str, Any]:
        start = time.perf_counter()
        codes = await get_active_stock_codes(limit=self.stock_limit)
        if not codes:
            logger.warning("quote_sync_no_active_stocks")
            return {"synced": 0, "failed": 0, "total": 0, "latency_ms": 0}

        logger.info("quote_sync_start", stock_count=len(codes), batch_size=self.batch_size)

        synced = 0
        failed = 0
        batches = 0
        partial_batches = 0
        batch_results: list[dict[str, Any]] = []
        for index in range(0, len(codes), self.batch_size):
            requested_codes = codes[index : index + self.batch_size]
            batches += 1
            batch_started_at = datetime.now(timezone.utc)
            try:
                quotes, metadata = await self.data_client.fetch_quotes_with_provenance(
                    requested_codes
                )
            except Exception as exc:
                logger.warning("quote_sync_fetch_failed", error=str(exc))
                quotes = {}
                metadata = {
                    "provider": "tencent",
                    "source": "tencent_qt_gtimg_l1",
                    "fetch_endpoint": "https://qt.gtimg.cn/q",
                    "fallback_used": False,
                    "requested_symbols": len(requested_codes),
                    "returned_symbols": 0,
                    "status": "fetch_failed",
                    "failure_reason": f"固定 Provider 请求异常: {exc}",
                    "collector_version": "realtime-quote-collector-v1",
                    "normalizer_version": "tencent-l1-normalizer-v1",
                }

            persisted = await self.quote_store.persist_batch(
                requested_codes, quotes, metadata, batch_started_at
            )
            batch_results.append(persisted)
            accepted_codes = persisted["accepted_codes"]
            synced += len(accepted_codes)
            failed += len(requested_codes) - len(accepted_codes)
            if persisted["status"] != "success":
                partial_batches += 1

            for code in accepted_codes:
                try:
                    quote = quotes[code]
                    quote["stock_code"] = code
                    quote["provenance"] = {
                        "batch_id": persisted["batch_id"],
                        "provider": metadata["provider"],
                        "source": metadata["source"],
                        "fallback_used": False,
                    }
                    cache_key = f"quote:{code}"
                    await self.cache.set(cache_key, quote, ttl=self.quote_ttl)
                    payload = {"type": "quote", "stock_code": code, **quote}
                    await self.cache.publish(CHANNEL_QUOTES, payload)
                    await self.cache.publish(f"channel:quotes:{code}", payload)
                except Exception as exc:
                    logger.warning("quote_sync_cache_publish_failed", stock_code=code, error=str(exc))

        latency_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "quote_sync_done",
            synced=synced,
            failed=failed,
            total=len(codes),
            batches=batches,
            partial_batches=partial_batches,
            latency_ms=latency_ms,
        )
        return {
            "synced": synced,
            "failed": failed,
            "total": len(codes),
            "batches": batches,
            "partial_batches": partial_batches,
            "batch_results": batch_results,
            "latency_ms": latency_ms,
        }

    async def close(self) -> None:
        await self.data_client.close()
        await self.cache.close()
        await self.quote_store.close()
