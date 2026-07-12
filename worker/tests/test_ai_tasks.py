import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", os.environ["REDIS_URL"])
os.environ.setdefault("CELERY_RESULT_BACKEND", os.environ["REDIS_URL"])
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)

from services.signal_scan import SignalScanService


def _make_analysis(action: str = "BUY", confidence: float = 0.8) -> dict:
    return {
        "code": "000001",
        "signal_id": "sig-001",
        "signal": {
            "id": "sig-001",
            "action": action,
            "confidence": confidence,
            "risk_level": "MEDIUM",
            "price_at": 10.0,
            "reason": "test signal",
        },
    }


def test_normal_scan_creates_recommendation_only() -> None:
    async def _run() -> None:
        ai = MagicMock()
        ai.analyze = AsyncMock(return_value=_make_analysis())
        cache = MagicMock()
        cache.set_lock = AsyncMock(return_value=True)
        cache.release_lock = AsyncMock()
        cache.publish = AsyncMock()
        cache.close = AsyncMock()
        service = SignalScanService(ai_analyzer=ai, cache=cache, concurrency=1)

        with (
            patch("services.signal_scan.get_active_strategies", AsyncMock(return_value=[{"id": 1}])),
            patch("services.signal_scan.get_strategy_stock_codes", AsyncMock(return_value=["000001"])),
            patch("services.signal_scan.has_valid_signal", AsyncMock(return_value=False)),
        ):
            result = await service.scan_all()

        assert result["recommendations_created"] == 1
        payload = cache.publish.await_args.args[1]
        assert payload["type"] == "signal_recommendation"
        assert payload["review_required"] is True
        assert payload["order_created"] is False

    asyncio.run(_run())


def test_hold_signal_does_not_create_recommendation() -> None:
    async def _run() -> None:
        ai = MagicMock()
        ai.analyze = AsyncMock(return_value=_make_analysis(action="HOLD"))
        cache = MagicMock()
        cache.set_lock = AsyncMock(return_value=True)
        cache.release_lock = AsyncMock()
        cache.publish = AsyncMock()
        cache.close = AsyncMock()
        service = SignalScanService(ai_analyzer=ai, cache=cache, concurrency=1)
        with (
            patch("services.signal_scan.get_active_strategies", AsyncMock(return_value=[{"id": 1}])),
            patch("services.signal_scan.get_strategy_stock_codes", AsyncMock(return_value=["000001"])),
            patch("services.signal_scan.has_valid_signal", AsyncMock(return_value=False)),
        ):
            result = await service.scan_all()
        assert result["recommendations_created"] == 0
        cache.publish.assert_not_awaited()

    asyncio.run(_run())


def test_run_signal_scan_task_runs() -> None:
    from celery_app import app

    service = MagicMock()
    service.scan_all = AsyncMock(return_value={"stocks_scanned": 5})
    service.close = AsyncMock()
    with patch("services.signal_scan.SignalScanService", return_value=service):
        result = app.tasks["tasks.run_signal_scan"].run()

    assert result["status"] == "ok"
    assert result["task"] == "run_signal_scan"
