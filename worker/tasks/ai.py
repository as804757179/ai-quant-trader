"""AI 信号扫描与晨间选股任务。"""

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
def run_ai_analysis(self, stock_code: str, force_refresh: bool = False) -> dict:
    import asyncio

    from services.backend_client import create_backend_client

    logger.info(
        "task_start",
        task="run_ai_analysis",
        task_id=self.request.id,
        stock_code=stock_code,
    )

    async def _run() -> dict:
        client = create_backend_client()
        try:
            data = await client.analyze(stock_code, force_refresh=force_refresh)
            signal = data.get("signal") or {}
            return {
                "status": "ok",
                "task": "run_ai_analysis",
                "stock_code": stock_code,
                "action": signal.get("action"),
                "confidence": signal.get("confidence"),
                "signal_id": data.get("signal_id") or signal.get("id"),
            }
        finally:
            await client.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "run_ai_analysis_error",
            stock_code=stock_code,
            error=str(exc),
            exc_info=True,
        )
        raise


@app.task(
    name="tasks.morning_screening",
    bind=True,
    base=LoggingTask,
    queue="normal",
)
def morning_screening(self, preset_id: str = "ai_momentum") -> dict:
    """晨间选股：调用 backend screener 预设。"""
    import asyncio
    import os

    import httpx

    from services.backend_client import worker_api_headers

    logger.info("task_start", task="morning_screening", task_id=self.request.id)

    async def _run() -> dict:
        base = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
        headers = worker_api_headers()
        async with httpx.AsyncClient(base_url=base, timeout=60.0, headers=headers) as client:
            # 尝试预设；失败则 theme=AI
            try:
                resp = await client.post(
                    "/api/v1/screener/screen",
                    json={"preset_id": preset_id, "limit": 30},
                )
                if resp.status_code >= 400:
                    resp = await client.post(
                        "/api/v1/screener/theme",
                        json={"theme": "AI", "limit": 30},
                    )
                resp.raise_for_status()
                body = resp.json()
                data = body.get("data") or {}
                items = data.get("items") or []
                return {
                    "status": "ok",
                    "task": "morning_screening",
                    "preset_id": preset_id,
                    "count": len(items),
                    "top_codes": [i.get("code") for i in items[:10] if isinstance(i, dict)],
                }
            except Exception as exc:
                logger.warning("morning_screening_http_failed", error=str(exc))
                return {
                    "status": "degraded",
                    "task": "morning_screening",
                    "error": str(exc),
                    "count": 0,
                }

    return asyncio.run(_run())


@app.task(
    name="tasks.run_backtest_task",
    bind=True,
    base=LoggingTask,
    queue="low",
)
def run_backtest_task(self, payload: dict) -> dict:
    """Fail closed until a provisioned worker executes a persisted Job by ID."""
    del payload
    error_code = "worker_backtest_task_retired"
    logger.error(
        "run_backtest_task_retired",
        task_id=self.request.id,
        error_code=error_code,
        message="旧 Worker 回测任务已退役，禁止通过兼容路径创建或执行回测",
    )
    raise RuntimeError(error_code)
