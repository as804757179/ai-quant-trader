"""行情同步任务（Step 2 将实现完整逻辑）。"""

from __future__ import annotations

import structlog

from celery_app import app
from tasks.base import LoggingTask

logger = structlog.get_logger(__name__)


@app.task(
    name="tasks.sync_realtime_quotes",
    bind=True,
    base=LoggingTask,
    queue="high",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=1,
)
def sync_realtime_quotes(self) -> dict:
    import asyncio

    from services.quote_sync import QuoteSyncService

    logger.info("task_start", task="sync_realtime_quotes", task_id=self.request.id)

    async def _run() -> dict:
        service = QuoteSyncService()
        try:
            return await service.sync_all()
        finally:
            await service.close()

    try:
        result = asyncio.run(_run())
        result["status"] = "ok"
        result["task"] = "sync_realtime_quotes"
        return result
    except Exception as exc:
        logger.error(
            "quote_sync_task_error",
            task_id=self.request.id,
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc) from exc


@app.task(
    name="tasks.sync_portfolio_value",
    bind=True,
    base=LoggingTask,
    queue="high",
    ignore_result=True,
)
def sync_portfolio_value(self) -> dict:
    import asyncio

    from services.portfolio_sync import PortfolioSyncService

    logger.info("task_start", task="sync_portfolio_value", task_id=self.request.id)

    async def _run() -> dict:
        service = PortfolioSyncService()
        try:
            return await service.sync_all()
        finally:
            await service.close()

    try:
        result = asyncio.run(_run())
        result["status"] = "ok"
        result["task"] = "sync_portfolio_value"
        return result
    except Exception as exc:
        logger.error(
            "portfolio_sync_task_error",
            task_id=self.request.id,
            error=str(exc),
            exc_info=True,
        )
        raise


@app.task(
    name="tasks.sync_fund_flow",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def sync_fund_flow(self) -> dict:
    """同步持仓标的资金流到 Redis 缓存。"""
    import asyncio
    import os

    from services.cache import CacheManager
    from services.data_client import DataClient
    from services.stock_pool import get_active_stock_codes

    logger.info("task_start", task="sync_fund_flow", task_id=self.request.id)

    async def _run() -> dict:
        limit = int(os.getenv("FUND_FLOW_SYNC_LIMIT", "50"))
        codes = await get_active_stock_codes(limit=limit)
        client = DataClient()
        cache = CacheManager()
        ok_n = 0
        fail_n = 0
        try:
            for code in codes:
                try:
                    data = await client.fetch_fund_flow(code, days=5)
                    if data:
                        await cache.set(f"fund_flow:{code}:5", data, ttl=1800)
                        ok_n += 1
                    else:
                        fail_n += 1
                except Exception:
                    fail_n += 1
        finally:
            await client.close()
            await cache.close()
        return {
            "status": "ok",
            "task": "sync_fund_flow",
            "synced": ok_n,
            "failed": fail_n,
            "total": len(codes),
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("fund_flow_sync_error", error=str(exc), exc_info=True)
        raise


@app.task(
    name="tasks.update_available_quantity",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def update_available_quantity(self) -> dict:
    """T+1：开盘前将 available_qty 同步为 total_qty。"""
    import asyncio

    from services.portfolio_sync import PortfolioSyncService

    logger.info("task_start", task="update_available_quantity", task_id=self.request.id)

    async def _run() -> dict:
        service = PortfolioSyncService()
        try:
            return await service.release_available_quantity()
        finally:
            await service.close()

    try:
        result = asyncio.run(_run())
        result["task"] = "update_available_quantity"
        return result
    except Exception as exc:
        logger.error(
            "update_available_qty_error",
            task_id=self.request.id,
            error=str(exc),
            exc_info=True,
        )
        raise


@app.task(
    name="tasks.archive_daily_data",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def archive_daily_data(self) -> dict:
    import asyncio

    from services.maintenance_ops import archive_daily_data as _impl

    logger.info("task_start", task="archive_daily_data", task_id=self.request.id)
    try:
        result = asyncio.run(_impl())
        result["task"] = "archive_daily_data"
        return result
    except Exception as exc:
        logger.error("archive_daily_error", error=str(exc), exc_info=True)
        raise


@app.task(
    name="tasks.sync_open_orders",
    bind=True,
    base=LoggingTask,
    queue="high",
    ignore_result=True,
)
def sync_open_orders(self) -> dict:
    """轮询 paper/live 未终态订单，更新成交并推送 WS。"""
    import asyncio
    import os

    logger.info("task_start", task="sync_open_orders", task_id=self.request.id)

    async def _run() -> dict:
        try:
            from app.services.trade_service import TradeService
        except ImportError:
            return {
                "status": "not_configured",
                "task": "sync_open_orders",
                "reason": "backend not on PYTHONPATH",
            }

        svc = TradeService()
        trade_mode = os.getenv("TRADE_MODE", "simulation")
        modes = ["paper"]
        if trade_mode == "live":
            modes.append("live")
        results = {}
        for mode in modes:
            try:
                results[mode] = await svc.sync_open_orders(mode)
            except Exception as exc:
                results[mode] = {"status": "error", "error": str(exc)}
        return {"status": "ok", "task": "sync_open_orders", "results": results}

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("sync_open_orders_error", error=str(exc), exc_info=True)
        return {"status": "error", "task": "sync_open_orders", "error": str(exc)}


@app.task(
    name="tasks.sync_live_positions_from_broker",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def sync_live_positions_from_broker(self) -> dict:
    """从 QMT/Mock 适配器同步持仓到本地（live/paper）。"""
    import asyncio
    import os

    logger.info(
        "task_start",
        task="sync_live_positions_from_broker",
        task_id=self.request.id,
    )
    trade_mode = os.getenv("TRADE_MODE", "simulation")
    if trade_mode == "simulation":
        return {
            "status": "skipped",
            "task": "sync_live_positions_from_broker",
            "reason": "simulation mode uses local ledger only",
        }

    async def _run() -> dict:
        # 通过 HTTP 触达 backend 较重；worker 直接导入 backend 需 PYTHONPATH
        try:
            from app.db import get_db
            from app.trade.live_trader import LiveTrader
            from app.trade.qmt.factory import create_qmt_adapter
        except ImportError:
            return {
                "status": "not_configured",
                "task": "sync_live_positions_from_broker",
                "reason": "backend package not on PYTHONPATH; set WORKER_BACKEND_MODE=direct",
            }

        mode = "live" if trade_mode == "live" else "paper"
        adapter = create_qmt_adapter(mode)
        async with get_db() as db:
            trader = LiveTrader(db, adapter, mode=mode)
            await trader.sync_positions()
            positions = await trader.get_positions()
        return {
            "status": "ok",
            "task": "sync_live_positions_from_broker",
            "mode": mode,
            "adapter": adapter.name,
            "position_count": len(positions),
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("sync_live_positions_error", error=str(exc), exc_info=True)
        return {
            "status": "error",
            "task": "sync_live_positions_from_broker",
            "error": str(exc),
        }