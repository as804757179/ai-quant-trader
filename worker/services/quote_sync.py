from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog

from services.cache import CacheManager
from services.data_client import DataClient, validate_quote
from services.stock_pool import get_active_stock_codes

logger = structlog.get_logger(__name__)

QUOTE_TTL = int(os.getenv("QUOTE_CACHE_TTL", "8"))
QUOTE_SYNC_LIMIT = int(os.getenv("QUOTE_SYNC_STOCK_LIMIT", "100"))
QUOTE_CONCURRENCY = int(os.getenv("QUOTE_SYNC_CONCURRENCY", "20"))
CHANNEL_QUOTES = "channel:quotes"


class QuoteSyncService:
    """实时行情同步服务（对齐 DataService.get_quote 数据格式）。"""

    def __init__(
        self,
        data_client: DataClient | None = None,
        cache: CacheManager | None = None,
        stock_limit: int = QUOTE_SYNC_LIMIT,
        quote_ttl: int = QUOTE_TTL,
        concurrency: int = QUOTE_CONCURRENCY,
    ) -> None:
        self.data_client = data_client or DataClient()
        self.cache = cache or CacheManager()
        self.stock_limit = stock_limit
        self.quote_ttl = quote_ttl
        self.concurrency = concurrency

    async def sync_all(self) -> dict[str, Any]:
        start = time.perf_counter()
        codes = await get_active_stock_codes(limit=self.stock_limit)
        if not codes:
            logger.warning("quote_sync_no_active_stocks")
            return {"synced": 0, "failed": 0, "total": 0, "latency_ms": 0}

        logger.info(
            "quote_sync_start",
            stock_count=len(codes),
            concurrency=self.concurrency,
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        results = await asyncio.gather(
            *[self._sync_one(code, semaphore) for code in codes],
            return_exceptions=True,
        )

        synced = sum(1 for r in results if r is True)
        failed = len(results) - synced
        latency_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "quote_sync_done",
            synced=synced,
            failed=failed,
            total=len(codes),
            latency_ms=latency_ms,
        )
        return {
            "synced": synced,
            "failed": failed,
            "total": len(codes),
            "latency_ms": latency_ms,
        }

    async def _sync_one(self, code: str, semaphore: asyncio.Semaphore) -> bool:
        async with semaphore:
            try:
                quote = await self.data_client.fetch_quote(code)
                if not validate_quote(quote):
                    logger.warning("quote_sync_invalid", stock_code=code)
                    return False

                quote["stock_code"] = code
                cache_key = f"quote:{code}"
                await self.cache.set(cache_key, quote, ttl=self.quote_ttl)

                payload = {"type": "quote", "stock_code": code, **quote}
                await self.cache.publish(CHANNEL_QUOTES, payload)
                await self.cache.publish(f"channel:quotes:{code}", payload)
                return True
            except Exception as exc:
                logger.warning(
                    "quote_sync_failed",
                    stock_code=code,
                    error=str(exc),
                )
                return False

    async def close(self) -> None:
        await self.data_client.close()
        await self.cache.close()