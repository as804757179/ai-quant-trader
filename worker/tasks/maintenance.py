"""维护与数据归档任务。"""

from __future__ import annotations

import structlog

from celery_app import app
from tasks.base import LoggingTask

logger = structlog.get_logger(__name__)


def _run_async(coro_factory):
    import asyncio

    return asyncio.run(coro_factory())


@app.task(
    name="tasks.index_new_announcements",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def index_new_announcements(self) -> dict:
    """公告索引：尝试写入 Chroma；失败则 degraded。"""
    logger.info("task_start", task="index_new_announcements", task_id=self.request.id)

    async def _run() -> dict:
        try:
            from app.rag.indexer import index_new_announcements as _impl

            result = await _impl(limit=50)
            result["task"] = "index_new_announcements"
            return result
        except ImportError as exc:
            return {
                "status": "degraded",
                "task": "index_new_announcements",
                "indexed": 0,
                "error": str(exc),
                "message": "backend RAG not on PYTHONPATH",
            }

    try:
        return _run_async(_run)
    except Exception as exc:
        logger.error("index_announcements_error", error=str(exc), exc_info=True)
        return {
            "status": "error",
            "task": "index_new_announcements",
            "indexed": 0,
            "error": str(exc),
        }


@app.task(
    name="tasks.take_eod_snapshot",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def take_eod_snapshot(self) -> dict:
    from services.maintenance_ops import take_eod_snapshot as _impl

    logger.info("task_start", task="take_eod_snapshot", task_id=self.request.id)
    try:
        result = _run_async(_impl)
        result["task"] = "take_eod_snapshot"
        return result
    except Exception as exc:
        logger.error("eod_snapshot_error", error=str(exc), exc_info=True)
        raise


@app.task(
    name="tasks.weekly_full_data_sync",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def weekly_full_data_sync(self) -> dict:
    """周全量：触发持仓池行情同步 + 完整性检查。"""
    import asyncio

    from services.maintenance_ops import check_kline_completeness
    from services.portfolio_sync import PortfolioSyncService

    logger.info("task_start", task="weekly_full_data_sync", task_id=self.request.id)

    async def _run() -> dict:
        sync = PortfolioSyncService()
        try:
            portfolio = await sync.sync_all()
        finally:
            await sync.close()
        completeness = await check_kline_completeness(lookback_days=30)
        return {
            "status": "ok",
            "task": "weekly_full_data_sync",
            "portfolio": portfolio,
            "kline_check": completeness,
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("weekly_sync_error", error=str(exc), exc_info=True)
        raise


@app.task(
    name="tasks.check_kline_completeness",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def check_kline_completeness(self) -> dict:
    from services.maintenance_ops import check_kline_completeness as _impl

    logger.info("task_start", task="check_kline_completeness", task_id=self.request.id)
    try:
        result = _run_async(_impl)
        result["task"] = "check_kline_completeness"
        return result
    except Exception as exc:
        logger.error("kline_check_error", error=str(exc), exc_info=True)
        raise


@app.task(
    name="tasks.reconcile_accounts",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def reconcile_accounts(self) -> dict:
    from services.maintenance_ops import reconcile_with_broker

    logger.info("task_start", task="reconcile_accounts", task_id=self.request.id)
    try:
        result = _run_async(reconcile_with_broker)
        result["task"] = "reconcile_accounts"
        return result
    except Exception as exc:
        logger.error("reconcile_error", error=str(exc), exc_info=True)
        raise
