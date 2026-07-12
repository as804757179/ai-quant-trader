"""订单状态同步服务测试。"""

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.trade.order_sync import OrderSyncService
from app.trade.qmt.adapter import BrokerOrder
from app.trade.qmt.mock_adapter import MockQmtAdapter


def test_mock_deferred_fill_and_force() -> None:
    async def _run() -> None:
        m = MockQmtAdapter(initial_cash=100_000, deferred_fill=True)
        await m.connect()
        o = await m.submit_order(
            stock_code="000001", side="BUY", quantity=100, limit_price=10.0
        )
        assert o.status == "SUBMITTED"
        assert o.filled_quantity == 0
        filled = m.force_fill(o.broker_order_id)
        assert filled is not None
        assert filled.status == "FILLED"
        assert filled.filled_quantity == 100
        q = await m.query_order(o.broker_order_id)
        assert q is not None
        assert q.status == "FILLED"

    asyncio.run(_run())


def test_order_sync_transitions_to_filled() -> None:
    async def _run() -> None:
        order_id = str(uuid.uuid4())
        broker_id = "MOCK-ABC"

        db = AsyncMock()
        # open orders select
        open_result = MagicMock()
        open_result.mappings.return_value.all.return_value = [
            {
                "id": order_id,
                "stock_code": "000001",
                "side": "BUY",
                "quantity": 100,
                "limit_price": 10.0,
                "status": "SUBMITTED",
                "filled_quantity": 0,
                "avg_fill_price": None,
                "broker_order_id": broker_id,
            }
        ]
        # subsequent executes for update / history / position / account
        db.execute = AsyncMock(return_value=open_result)

        adapter = MagicMock()
        adapter.connect = AsyncMock(return_value=True)
        adapter.query_order = AsyncMock(
            return_value=BrokerOrder(
                broker_order_id=broker_id,
                stock_code="000001",
                side="BUY",
                quantity=100,
                status="FILLED",
                filled_quantity=100,
                avg_fill_price=10.05,
                message="filled",
            )
        )

        with (
            patch(
                "app.trade.order_sync.publish_portfolio_update",
                new_callable=AsyncMock,
            ) as pub,
            patch(
                "app.trade.order_sync.publish_alert",
                new_callable=AsyncMock,
            ) as alert,
            patch(
                "app.trade.order_sync.recompute_account_assets",
                new_callable=AsyncMock,
            ),
            patch.object(
                OrderSyncService,
                "_sync_one",
                new_callable=AsyncMock,
            ) as sync_one,
        ):
            # 用真实 _sync_one 测一次
            pass

        # 直接测 _sync_one
        syncer = OrderSyncService(db, adapter, mode="paper")
        # LiveTrader._ensure_connected
        syncer._trader._connected = True
        syncer._trader._sync_fill_to_local = AsyncMock()

        with (
            patch(
                "app.trade.order_sync.publish_portfolio_update",
                new_callable=AsyncMock,
            ) as pub,
            patch(
                "app.trade.order_sync.publish_alert",
                new_callable=AsyncMock,
            ) as alert,
            patch(
                "app.trade.order_sync.recompute_account_assets",
                new_callable=AsyncMock,
            ),
        ):
            detail = await syncer._sync_one(
                {
                    "id": order_id,
                    "stock_code": "000001",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": 10.0,
                    "status": "SUBMITTED",
                    "filled_quantity": 0,
                    "avg_fill_price": None,
                    "broker_order_id": broker_id,
                }
            )

        assert detail["changed"] is True
        assert detail["new_status"] == "FILLED"
        pub.assert_awaited()
        alert.assert_awaited()
        syncer._trader._sync_fill_to_local.assert_awaited()

    asyncio.run(_run())


def test_order_sync_unchanged() -> None:
    async def _run() -> None:
        db = AsyncMock()
        adapter = MagicMock()
        adapter.query_order = AsyncMock(
            return_value=BrokerOrder(
                broker_order_id="X",
                stock_code="000001",
                side="BUY",
                quantity=100,
                status="SUBMITTED",
                filled_quantity=0,
            )
        )
        syncer = OrderSyncService(db, adapter, mode="paper")
        syncer._trader._connected = True
        detail = await syncer._sync_one(
            {
                "id": str(uuid.uuid4()),
                "stock_code": "000001",
                "side": "BUY",
                "quantity": 100,
                "status": "SUBMITTED",
                "filled_quantity": 0,
                "broker_order_id": "X",
            }
        )
        assert detail["changed"] is False

    asyncio.run(_run())
