"""订单幂等：IntegrityError 回退已有订单。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from sqlalchemy.exc import IntegrityError

from app.trade.base_trader import OrderRequest, OrderResult
from app.trade.execution_gate import ExecutionDecision
from app.trade.order_manager import OrderManager


def _allowed_gate() -> MagicMock:
    gate = MagicMock()
    gate.evaluate.return_value = ExecutionDecision(True)
    return gate


def test_idempotent_hit_before_submit() -> None:
    async def _run() -> None:
        db = AsyncMock()
        existing = MagicMock()
        existing.mappings.return_value.first.return_value = {
            "id": "11111111-1111-1111-1111-111111111111",
            "status": "FILLED",
        }
        db.execute = AsyncMock(return_value=existing)

        manager = OrderManager(db, MagicMock(), MagicMock(), {}, _allowed_gate())
        req = OrderRequest(
            stock_code="000001",
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            limit_price=10.0,
            signal_id="manual",
        )
        result = await manager.create_order(req, "simulation")
        assert result["idempotent"] is True
        assert result["order_id"] == "11111111-1111-1111-1111-111111111111"

    asyncio.run(_run())


def test_integrity_error_returns_existing() -> None:
    async def _run() -> None:
        db = AsyncMock()
        # first find: none
        empty = MagicMock()
        empty.mappings.return_value.first.return_value = None
        # after IntegrityError: found
        found = MagicMock()
        found.mappings.return_value.first.return_value = {
            "id": "22222222-2222-2222-2222-222222222222",
            "status": "FILLED",
        }
        db.execute = AsyncMock(side_effect=[empty, found])
        db.rollback = AsyncMock()

        fuse = MagicMock()
        fuse.is_fused = AsyncMock(return_value=False)
        risk = MagicMock()
        risk_report = MagicMock()
        risk_report.passed = True
        risk_report.warnings = []
        risk.check = AsyncMock(return_value=risk_report)

        trader = MagicMock()
        trader.submit_order = AsyncMock(
            side_effect=IntegrityError("dup", {}, Exception("unique"))
        )

        manager = OrderManager(db, risk, fuse, {"simulation": trader}, _allowed_gate())
        req = OrderRequest(
            stock_code="000001",
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            limit_price=10.0,
            signal_id="sig-1",
        )
        result = await manager.create_order(req, "simulation")
        assert result["idempotent"] is True
        assert result["order_id"] == "22222222-2222-2222-2222-222222222222"
        db.rollback.assert_awaited()

    asyncio.run(_run())


def test_fuse_blocks_order() -> None:
    async def _run() -> None:
        db = AsyncMock()
        empty = MagicMock()
        empty.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=empty)

        fuse = MagicMock()
        fuse.is_fused = AsyncMock(return_value=True)
        manager = OrderManager(db, MagicMock(), fuse, {}, _allowed_gate())
        req = OrderRequest(
            stock_code="000001",
            side="BUY",
            order_type="MARKET",
            quantity=100,
        )
        result = await manager.create_order(req, "simulation")
        assert result["success"] is False
        assert "熔断" in result["message"]

    asyncio.run(_run())
