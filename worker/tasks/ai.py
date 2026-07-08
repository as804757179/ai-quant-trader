"""AI 信号扫描任务（Step 3 将实现完整逻辑）。"""

from __future__ import annotations

import structlog

from celery_app import app
from tasks.base import LoggingTask

logger = structlog.get_logger(__name__)


@app.task(
    name="tasks.run_signal_scan",
    bind=True,
    base=LoggingTask,
    queue="normal",
    ignore_result=True,
    max_retries=2,
    default_retry_delay=10,
)
def run_signal_scan(self, force_refresh: bool = False) -> dict:
    import asyncio

    from services.signal_scan import SignalScanService

    logger.info(
        "task_start",
        task="run_signal_scan",
        task_id=self.request.id,
        force_refresh=force_refresh,
    )

    async def _run() -> dict:
        service = SignalScanService()
        try:
            return await service.scan_all(force_refresh=force_refresh)
        finally:
            await service.close()

    try:
        result = asyncio.run(_run())
        result["status"] = "ok"
        result["task"] = "run_signal_scan"
        return result
    except Exception as exc:
        logger.error(
            "signal_scan_task_error",
            task_id=self.request.id,
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc) from exc


@app.task(
    name="tasks.run_ai_analysis",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def run_ai_analysis(self, stock_code: str) -> dict:
    logger.info(
        "task_start",
        task="run_ai_analysis",
        task_id=self.request.id,
        stock_code=stock_code,
    )
    return {"status": "stub", "task": "run_ai_analysis", "stock_code": stock_code}


@app.task(
    name="tasks.morning_screening",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def morning_screening(self) -> dict:
    logger.info("task_start", task="morning_screening", task_id=self.request.id)
    return {"status": "stub", "task": "morning_screening"}