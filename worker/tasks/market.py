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
    logger.info("task_start", task="sync_portfolio_value", task_id=self.request.id)
    return {"status": "stub", "task": "sync_portfolio_value"}


@app.task(
    name="tasks.sync_fund_flow",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def sync_fund_flow(self) -> dict:
    logger.info("task_start", task="sync_fund_flow", task_id=self.request.id)
    return {"status": "stub", "task": "sync_fund_flow"}


@app.task(
    name="tasks.update_available_quantity",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def update_available_quantity(self) -> dict:
    logger.info("task_start", task="update_available_quantity", task_id=self.request.id)
    return {"status": "stub", "task": "update_available_quantity"}


@app.task(
    name="tasks.archive_daily_data",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def archive_daily_data(self) -> dict:
    logger.info("task_start", task="archive_daily_data", task_id=self.request.id)
    return {"status": "stub", "task": "archive_daily_data"}


@app.task(
    name="tasks.sync_live_positions_from_broker",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def sync_live_positions_from_broker(self) -> dict:
    logger.info(
        "task_start",
        task="sync_live_positions_from_broker",
        task_id=self.request.id,
    )
    return {"status": "stub", "task": "sync_live_positions_from_broker"}