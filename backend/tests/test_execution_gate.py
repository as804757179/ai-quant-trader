import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader"
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.core.config import settings
from app.trade.base_trader import OrderRequest
from app.trade.execution_gate import ExecutionDecision, ExecutionGate
from app.trade.order_manager import OrderManager


def _request(**kwargs) -> OrderRequest:
    values = {
        "stock_code": "000001",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": 100,
        "limit_price": 10.0,
        "trigger_source": "manual_order",
        "caller": "manual_api",
        "approval_id": "approval-1",
    }
    values.update(kwargs)
    return OrderRequest(**values)


def test_default_configuration_rejects_execution() -> None:
    settings.TRADING_EXECUTION_ENABLED = False
    assert ExecutionGate().evaluate(_request(), "paper").reason == "TRADING_EXECUTION_DISABLED"


def test_ai_and_scheduled_sources_are_rejected() -> None:
    settings.TRADING_EXECUTION_ENABLED = True
    settings.REQUIRE_HUMAN_APPROVAL = False
    settings.ALLOW_SCHEDULED_ORDER = False
    gate = ExecutionGate()
    assert gate.evaluate(_request(trigger_source="ai_signal"), "paper").reason == "AI_ORDER_DISABLED"
    assert gate.evaluate(_request(trigger_source="scheduled_order"), "paper").reason == "SCHEDULED_ORDER_DISABLED"


def test_live_requires_global_live_flag() -> None:
    settings.TRADING_EXECUTION_ENABLED = True
    settings.REQUIRE_HUMAN_APPROVAL = False
    settings.LIVE_TRADING_ENABLED = False
    assert ExecutionGate().evaluate(_request(), "live").reason == "LIVE_TRADING_DISABLED"


def test_manager_rejects_before_risk_or_trader() -> None:
    async def _run() -> None:
        settings.TRADING_EXECUTION_ENABLED = False
        risk = MagicMock()
        trader = MagicMock()
        manager = OrderManager(AsyncMock(), risk, MagicMock(), {"paper": trader})
        result = await manager.create_order(_request(), "paper")
        assert result["error_code"] == "ORDER_REJECTED_BY_EXECUTION_GATE"
        assert result["rejection_reason"] == "TRADING_EXECUTION_DISABLED"
        assert not risk.check.called
        assert not trader.submit_order.called

    asyncio.run(_run())


def test_gate_pass_still_runs_risk_check() -> None:
    async def _run() -> None:
        db = AsyncMock()
        existing = MagicMock()
        existing.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=existing)
        fuse = MagicMock()
        fuse.is_fused = AsyncMock(return_value=False)
        report = MagicMock(passed=False, blocked_by=["MAX_POSITION"], warnings=[], checks=[])
        risk = MagicMock()
        risk.check = AsyncMock(return_value=report)
        gate = MagicMock()
        gate.evaluate.return_value = ExecutionDecision(True)
        manager = OrderManager(db, risk, fuse, {}, execution_gate=gate)
        result = await manager.create_order(_request(), "paper")
        assert result["success"] is False
        gate.evaluate.assert_called_once()
        risk.check.assert_awaited_once()

    asyncio.run(_run())
