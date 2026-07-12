from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog

from services.backend_client import AIAnalyzer, SIGNAL_MIN_CONFIDENCE, create_backend_client
from services.cache import CacheManager
from services.strategy_pool import (
    get_active_strategies,
    get_strategy_stock_codes,
    has_valid_signal,
)

logger = structlog.get_logger(__name__)

CHANNEL_SIGNALS = "channel:signals"
SCAN_CONCURRENCY = int(os.getenv("SIGNAL_SCAN_CONCURRENCY", "5"))
SCAN_STOCK_LIMIT = int(os.getenv("SIGNAL_SCAN_STOCK_LIMIT", "20"))
SCAN_LOCK_TTL = int(os.getenv("SIGNAL_SCAN_LOCK_TTL", "300"))


def _lock_key(code: str, strategy_id: int | None) -> str:
    sid = strategy_id if strategy_id is not None else 0
    return f"signal_scan_lock:{code}:{sid}"


class SignalScanService:
    """AI 信号扫描只生成待复核建议，永不创建订单。"""

    def __init__(
        self,
        *,
        ai_analyzer: AIAnalyzer | None = None,
        cache: CacheManager | None = None,
        min_confidence: float = SIGNAL_MIN_CONFIDENCE,
        concurrency: int = SCAN_CONCURRENCY,
        stock_limit: int = SCAN_STOCK_LIMIT,
        lock_ttl: int = SCAN_LOCK_TTL,
    ) -> None:
        backend = create_backend_client()
        self.ai = ai_analyzer or backend
        self._owns_backend = ai_analyzer is None
        self.cache = cache or CacheManager()
        self.min_confidence = min_confidence
        self.concurrency = concurrency
        self.stock_limit = stock_limit
        self.lock_ttl = lock_ttl

    async def close(self) -> None:
        await self.cache.close()
        if self._owns_backend and hasattr(self.ai, "close"):
            await self.ai.close()

    async def scan_all(self, *, force_refresh: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        strategies = await get_active_strategies()
        stats: dict[str, Any] = {
            "strategies": len(strategies),
            "stocks_scanned": 0,
            "signals_generated": 0,
            "signals_actionable": 0,
            "recommendations_created": 0,
            "skipped_cached": 0,
            "skipped_locked": 0,
            "skipped_hold": 0,
            "errors": 0,
        }
        logger.info(
            "signal_scan_start",
            strategy_count=len(strategies),
            concurrency=self.concurrency,
            stock_limit=self.stock_limit,
            force_refresh=force_refresh,
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        tasks: list[asyncio.Task] = []
        for strategy in strategies:
            strategy_id = strategy.get("id")
            codes = await get_strategy_stock_codes(strategy_id, limit=self.stock_limit)
            for code in codes:
                tasks.append(
                    asyncio.create_task(
                        self._scan_one(
                            code=code,
                            strategy=strategy,
                            force_refresh=force_refresh,
                            semaphore=semaphore,
                            stats=stats,
                        )
                    )
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        stats["latency_ms"] = int((time.perf_counter() - start) * 1000)
        logger.info("signal_scan_done", **stats)
        return stats

    async def _scan_one(
        self,
        *,
        code: str,
        strategy: dict[str, Any],
        force_refresh: bool,
        semaphore: asyncio.Semaphore,
        stats: dict[str, Any],
    ) -> None:
        async with semaphore:
            strategy_id = strategy.get("id")
            lock_key = _lock_key(code, strategy_id)
            locked = False
            try:
                if not await self.cache.set_lock(lock_key, ttl=self.lock_ttl):
                    stats["skipped_locked"] += 1
                    return
                locked = True
                stats["stocks_scanned"] += 1
                if not force_refresh and await has_valid_signal(code):
                    stats["skipped_cached"] += 1
                    return

                strategy_id_param = strategy_id if strategy_id and strategy_id > 0 else None
                analysis = await self.ai.analyze(
                    code,
                    force_refresh=force_refresh,
                    strategy_id=strategy_id_param,
                )
                stats["signals_generated"] += 1
                signal = analysis.get("signal") or {}
                action = str(signal.get("action", "HOLD")).upper()
                confidence = float(signal.get("confidence") or 0)
                if action == "HOLD" or confidence < self.min_confidence:
                    stats["skipped_hold"] += 1
                    return

                stats["signals_actionable"] += 1
                await self._publish_recommendation(code, signal, analysis)
                stats["recommendations_created"] += 1
                logger.info(
                    "signal_scan_recommendation_created",
                    stock_code=code,
                    strategy_id=strategy_id,
                    action=action,
                    confidence=confidence,
                    review_required=True,
                )
            except Exception as exc:
                stats["errors"] += 1
                logger.error(
                    "signal_scan_stock_error",
                    stock_code=code,
                    strategy_id=strategy_id,
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                if locked:
                    await self.cache.release_lock(lock_key)

    async def _publish_recommendation(
        self,
        code: str,
        signal: dict[str, Any],
        analysis: dict[str, Any],
    ) -> None:
        await self.cache.publish(
            CHANNEL_SIGNALS,
            {
                "type": "signal_recommendation",
                "stock_code": code,
                "action": signal.get("action"),
                "confidence": signal.get("confidence"),
                "risk_level": signal.get("risk_level"),
                "price_at": signal.get("price_at"),
                "reason": signal.get("reason") or analysis.get("reason"),
                "signal_id": analysis.get("signal_id") or signal.get("id"),
                "signal_time": signal.get("signal_time"),
                "review_required": True,
                "order_created": False,
            },
        )
