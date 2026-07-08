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

from services.backend_client import RiskCheckResult
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
        "from_cache": False,
    }


def test_normal_scan_flow_creates_order() -> None:
    async def _run() -> None:
        mock_ai = MagicMock()
        mock_ai.analyze = AsyncMock(return_value=_make_analysis())

        mock_risk = MagicMock()
        mock_risk.check_before_trade = AsyncMock(
            return_value=RiskCheckResult(passed=True)
        )

        mock_trade = MagicMock()
        mock_trade.submit_order = AsyncMock(
            return_value={"success": True, "order_id": "ord-1", "status": "FILLED"}
        )

        mock_cache = MagicMock()
        mock_cache.set_lock = AsyncMock(return_value=True)
        mock_cache.release_lock = AsyncMock()
        mock_cache.publish = AsyncMock()
        mock_cache.close = AsyncMock()

        service = SignalScanService(
            ai_analyzer=mock_ai,
            risk_checker=mock_risk,
            trade_submitter=mock_trade,
            cache=mock_cache,
            concurrency=1,
            stock_limit=2,
        )

        with (
            patch(
                "services.signal_scan.get_active_strategies",
                AsyncMock(
                    return_value=[
                        {
                            "id": 1,
                            "name": "test",
                            "trade_mode": "simulation",
                        }
                    ]
                ),
            ),
            patch(
                "services.signal_scan.get_strategy_stock_codes",
                AsyncMock(return_value=["000001"]),
            ),
            patch("services.signal_scan.has_valid_signal", AsyncMock(return_value=False)),
        ):
            result = await service.scan_all()

        assert result["stocks_scanned"] == 1
        assert result["signals_generated"] == 1
        assert result["signals_actionable"] == 1
        assert result["orders_created"] == 1
        assert result["risk_blocked"] == 0
        mock_risk.check_before_trade.assert_awaited_once()
        mock_trade.submit_order.assert_awaited_once()
        mock_cache.publish.assert_awaited_once()

    asyncio.run(_run())


def test_risk_blocked_skips_order() -> None:
    async def _run() -> None:
        mock_ai = MagicMock()
        mock_ai.analyze = AsyncMock(return_value=_make_analysis())

        mock_risk = MagicMock()
        mock_risk.check_before_trade = AsyncMock(
            return_value=RiskCheckResult(
                passed=False,
                blocked_by=["MAX_SINGLE_POSITION"],
            )
        )

        mock_trade = MagicMock()
        mock_trade.submit_order = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.set_lock = AsyncMock(return_value=True)
        mock_cache.release_lock = AsyncMock()
        mock_cache.publish = AsyncMock()
        mock_cache.close = AsyncMock()

        service = SignalScanService(
            ai_analyzer=mock_ai,
            risk_checker=mock_risk,
            trade_submitter=mock_trade,
            cache=mock_cache,
            concurrency=1,
        )

        with (
            patch(
                "services.signal_scan.get_active_strategies",
                AsyncMock(return_value=[{"id": 1, "trade_mode": "simulation"}]),
            ),
            patch(
                "services.signal_scan.get_strategy_stock_codes",
                AsyncMock(return_value=["000001"]),
            ),
            patch("services.signal_scan.has_valid_signal", AsyncMock(return_value=False)),
        ):
            result = await service.scan_all()

        assert result["signals_actionable"] == 1
        assert result["risk_blocked"] == 1
        assert result["orders_created"] == 0
        mock_trade.submit_order.assert_not_awaited()

    asyncio.run(_run())


def test_distributed_lock_prevents_duplicate_scan() -> None:
    async def _run() -> None:
        mock_ai = MagicMock()
        mock_ai.analyze = AsyncMock(return_value=_make_analysis())

        mock_cache = MagicMock()
        mock_cache.set_lock = AsyncMock(return_value=False)
        mock_cache.release_lock = AsyncMock()
        mock_cache.close = AsyncMock()

        service = SignalScanService(
            ai_analyzer=mock_ai,
            risk_checker=MagicMock(),
            trade_submitter=MagicMock(),
            cache=mock_cache,
            concurrency=1,
        )

        with (
            patch(
                "services.signal_scan.get_active_strategies",
                AsyncMock(return_value=[{"id": 2, "trade_mode": "simulation"}]),
            ),
            patch(
                "services.signal_scan.get_strategy_stock_codes",
                AsyncMock(return_value=["000001"]),
            ),
        ):
            result = await service.scan_all()

        assert result["skipped_locked"] == 1
        assert result["stocks_scanned"] == 0
        mock_ai.analyze.assert_not_awaited()

    asyncio.run(_run())


def test_cache_set_lock_key_format() -> None:
    async def _run() -> None:
        mock_cache = MagicMock()
        mock_cache.set_lock = AsyncMock(return_value=True)
        mock_cache.release_lock = AsyncMock()
        mock_cache.publish = AsyncMock()
        mock_cache.close = AsyncMock()

        mock_ai = MagicMock()
        mock_ai.analyze = AsyncMock(return_value=_make_analysis(action="HOLD"))

        service = SignalScanService(
            ai_analyzer=mock_ai,
            risk_checker=MagicMock(),
            trade_submitter=MagicMock(),
            cache=mock_cache,
            concurrency=1,
        )

        with (
            patch(
                "services.signal_scan.get_active_strategies",
                AsyncMock(return_value=[{"id": 3, "trade_mode": "simulation"}]),
            ),
            patch(
                "services.signal_scan.get_strategy_stock_codes",
                AsyncMock(return_value=["000002"]),
            ),
            patch("services.signal_scan.has_valid_signal", AsyncMock(return_value=False)),
        ):
            await service.scan_all()

        lock_call = mock_cache.set_lock.await_args
        assert lock_call.args[0] == "signal_scan_lock:000002:3"

    asyncio.run(_run())


def test_run_signal_scan_task_runs() -> None:
    from celery_app import app

    with patch(
        "asyncio.run",
        return_value={
            "strategies": 1,
            "stocks_scanned": 5,
            "signals_generated": 5,
            "orders_created": 1,
            "latency_ms": 200,
        },
    ):
        task = app.tasks["tasks.run_signal_scan"]
        result = task.run()

    assert result["status"] == "ok"
    assert result["task"] == "run_signal_scan"
    assert result["stocks_scanned"] == 5