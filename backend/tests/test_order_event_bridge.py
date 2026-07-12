"""订单回调桥与告警历史。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.trade.order_event_bridge import OrderEventBridge
from app.trade.qmt.adapter import BrokerOrder
from app.trade.qmt.mock_adapter import MockQmtAdapter
from app.ws import publisher


def test_mock_emits_on_force_fill() -> None:
    async def _run() -> None:
        events: list[BrokerOrder] = []
        m = MockQmtAdapter(initial_cash=100_000, deferred_fill=True)
        m.register_order_callback(lambda o: events.append(o))
        await m.connect()
        o = await m.submit_order(
            stock_code="000001", side="BUY", quantity=100, limit_price=10.0
        )
        assert o.status == "SUBMITTED"
        assert len(events) == 0
        m.force_fill(o.broker_order_id)
        assert len(events) == 1
        assert events[0].status == "FILLED"

    asyncio.run(_run())


def test_bridge_handle_missing_local() -> None:
    async def _run() -> None:
        bridge = OrderEventBridge()
        db_cm = MagicMock()
        session = AsyncMock()
        empty = MagicMock()
        empty.mappings.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=empty)
        db_cm.__aenter__ = AsyncMock(return_value=session)
        db_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.trade.order_event_bridge.get_db", return_value=db_cm):
            out = await bridge.handle_broker_order(
                "paper",
                BrokerOrder(
                    broker_order_id="NOPE",
                    stock_code="000001",
                    side="BUY",
                    quantity=100,
                    status="FILLED",
                    filled_quantity=100,
                    avg_fill_price=10.0,
                ),
            )
        assert out["ok"] is False
        assert out["reason"] == "local_not_found"

    asyncio.run(_run())


def test_bridge_attach_and_sync() -> None:
    async def _run() -> None:
        bridge = OrderEventBridge()
        adapter = MockQmtAdapter(deferred_fill=True)
        await adapter.connect()
        bridge.attach(adapter, "paper")

        order_id = "11111111-1111-1111-1111-111111111111"
        session = AsyncMock()
        found = MagicMock()
        found.mappings.return_value.first.return_value = {
            "id": order_id,
            "status": "SUBMITTED",
        }
        session.execute = AsyncMock(return_value=found)
        db_cm = MagicMock()
        db_cm.__aenter__ = AsyncMock(return_value=session)
        db_cm.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.trade.order_event_bridge.get_db", return_value=db_cm),
            patch(
                "app.trade.order_event_bridge.OrderSyncService"
            ) as SyncCls,
            patch.object(bridge, "_auto_reconcile", new_callable=AsyncMock),
        ):
            sync_inst = MagicMock()
            sync_inst.sync_order_by_id = AsyncMock(
                return_value={
                    "changed": True,
                    "new_status": "FILLED",
                    "order_id": order_id,
                }
            )
            SyncCls.return_value = sync_inst

            bo = BrokerOrder(
                broker_order_id="MOCK-1",
                stock_code="000001",
                side="BUY",
                quantity=100,
                status="FILLED",
                filled_quantity=100,
                avg_fill_price=10.0,
            )
            out = await bridge.handle_broker_order("paper", bo)
            assert out["ok"] is True
            sync_inst.sync_order_by_id.assert_awaited()
            bridge._auto_reconcile.assert_awaited_with("paper")

    asyncio.run(_run())


def test_publish_alert_and_history() -> None:
    async def _run() -> None:
        mock_client = AsyncMock()
        mock_client.lpush = AsyncMock()
        mock_client.ltrim = AsyncMock()
        mock_client.lrange = AsyncMock(
            return_value=[
                '{"type":"t","level":"INFO","message":"hello","ts":"1","detail":{}}'
            ]
        )

        cache = MagicMock()
        cache.publish = AsyncMock()
        cache._get_client = AsyncMock(return_value=mock_client)

        with patch("app.ws.publisher.CacheManager", return_value=cache):
            await publisher.publish_alert("test", "INFO", "hello", {"a": 1})
            items = await publisher.get_recent_alerts(10)

        mock_client.lpush.assert_awaited()
        assert len(items) == 1
        assert items[0]["message"] == "hello"

    asyncio.run(_run())
