from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog

from services.backend_client import (
    AIAnalyzer,
    RiskChecker,
    SIGNAL_MIN_CONFIDENCE,
    TradeSubmitter,
    create_backend_client,
)
from services.cache import CacheManager
from services.strategy_pool import (
    get_active_strategies,
    get_available_sell_quantity,
    get_strategy_stock_codes,
    has_valid_signal,
)

logger = structlog.get_logger(__name__)

CHANNEL_SIGNALS = "channel:signals"
SCAN_CONCURRENCY = int(os.getenv("SIGNAL_SCAN_CONCURRENCY", "5"))
SCAN_STOCK_LIMIT = int(os.getenv("SIGNAL_SCAN_STOCK_LIMIT", "20"))
SCAN_LOCK_TTL = int(os.getenv("SIGNAL_SCAN_LOCK_TTL", "300"))
DEFAULT_BUY_RATIO = float(os.getenv("SIGNAL_SCAN_BUY_RATIO", "0.02"))


def _lock_key(code: str, strategy_id: int | None) -> str:
    sid = strategy_id if strategy_id is not None else 0
    return f"signal_scan_lock:{code}:{sid}"


def _calculate_buy_quantity(price: float, total_assets: float = 1_000_000) -> int:
    if price <= 0:
        return 100
    target_value = total_assets * DEFAULT_BUY_RATIO
    lots = int(target_value / price / 100)
    return max(lots * 100, 100)


class SignalScanService:
    """AI 信号扫描：策略池 → 分析 → 风控 → 下单。"""

    def __init__(
        self,
        *,
        ai_analyzer: AIAnalyzer | None = None,
        risk_checker: RiskChecker | None = None,
        trade_submitter: TradeSubmitter | None = None,
        cache: CacheManager | None = None,
        min_confidence: float = SIGNAL_MIN_CONFIDENCE,
        concurrency: int = SCAN_CONCURRENCY,
        stock_limit: int = SCAN_STOCK_LIMIT,
        lock_ttl: int = SCAN_LOCK_TTL,
    ) -> None:
        backend = create_backend_client()
        self.ai = ai_analyzer or backend
        self.risk = risk_checker or backend
        self.trade = trade_submitter or backend
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
            "risk_blocked": 0,
            "orders_created": 0,
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
            trade_mode = strategy.get("trade_mode") or os.getenv("TRADE_MODE", "simulation")
            codes = await get_strategy_stock_codes(strategy_id, limit=self.stock_limit)

            for code in codes:
                tasks.append(
                    asyncio.create_task(
                        self._scan_one(
                            code=code,
                            strategy=strategy,
                            trade_mode=trade_mode,
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
        trade_mode: str,
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
                    logger.debug(
                        "signal_scan_skip_locked",
                        stock_code=code,
                        strategy_id=strategy_id,
                    )
                    return

                locked = True
                stats["stocks_scanned"] += 1

                if not force_refresh and await has_valid_signal(code):
                    stats["skipped_cached"] += 1
                    logger.debug(
                        "signal_scan_skip_cached",
                        stock_code=code,
                        strategy_id=strategy_id,
                    )
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
                signal_id = analysis.get("signal_id") or signal.get("id")

                if action == "HOLD" or confidence < self.min_confidence:
                    stats["skipped_hold"] += 1
                    return

                stats["signals_actionable"] += 1
                await self._publish_signal(code, signal, analysis)

                order_payload = await self._build_order_payload(
                    code=code,
                    action=action,
                    signal=signal,
                    signal_id=signal_id,
                    trade_mode=trade_mode,
                )
                if order_payload is None:
                    return

                risk_result = await self.risk.check_before_trade(
                    {
                        "stock_code": code,
                        "side": order_payload["side"],
                        "quantity": order_payload["quantity"],
                        "limit_price": order_payload.get("limit_price"),
                        "signal_id": signal_id,
                    },
                    trade_mode,
                )
                if not risk_result.passed:
                    stats["risk_blocked"] += 1
                    logger.info(
                        "signal_scan_risk_blocked",
                        stock_code=code,
                        strategy_id=strategy_id,
                        blocked_by=risk_result.blocked_by,
                    )
                    return

                order_result = await self.trade.submit_order(order_payload)
                if order_result.get("success"):
                    stats["orders_created"] += 1
                    logger.info(
                        "signal_scan_order_created",
                        stock_code=code,
                        strategy_id=strategy_id,
                        order_id=order_result.get("order_id"),
                        action=action,
                        confidence=confidence,
                    )
                else:
                    logger.warning(
                        "signal_scan_order_failed",
                        stock_code=code,
                        strategy_id=strategy_id,
                        message=order_result.get("message"),
                    )

            except Exception as exc:
                stats["errors"] += 1
                logger.error(
                    "signal_scan_stock_error",
                    stock_code=code,
                    strategy_id=strategy.get("id"),
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                if locked:
                    await self.cache.release_lock(lock_key)

    async def _publish_signal(
        self,
        code: str,
        signal: dict[str, Any],
        analysis: dict[str, Any],
    ) -> None:
        payload = {
            "type": "signal",
            "stock_code": code,
            "action": signal.get("action"),
            "confidence": signal.get("confidence"),
            "risk_level": signal.get("risk_level"),
            "price_at": signal.get("price_at"),
            "reason": signal.get("reason") or analysis.get("reason"),
            "signal_id": analysis.get("signal_id") or signal.get("id"),
            "signal_time": signal.get("signal_time"),
        }
        await self.cache.publish(CHANNEL_SIGNALS, payload)

    async def _build_order_payload(
        self,
        *,
        code: str,
        action: str,
        signal: dict[str, Any],
        signal_id: str | None,
        trade_mode: str,
    ) -> dict[str, Any] | None:
        price = float(signal.get("price_at") or 0)
        side = "BUY" if action == "BUY" else "SELL"

        if side == "SELL":
            quantity = await get_available_sell_quantity(code, trade_mode)
            if quantity < 100:
                logger.info(
                    "signal_scan_skip_no_position",
                    stock_code=code,
                    action=action,
                )
                return None
        else:
            quantity = _calculate_buy_quantity(price)

        return {
            "stock_code": code,
            "side": side,
            "order_type": "LIMIT",
            "quantity": quantity,
            "limit_price": price if price > 0 else None,
            "signal_id": signal_id,
            "mode": trade_mode,
        }