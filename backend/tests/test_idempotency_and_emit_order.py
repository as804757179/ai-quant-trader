"""幂等键与落库后再 emit。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.trade.base_trader import OrderRequest
from app.trade.idempotency import build_idempotency_key
from app.trade.live_trader import LiveTrader
from app.trade.qmt.adapter import BrokerOrder
from app.trade.qmt.mock_adapter import MockQmtAdapter


def test_idempotency_includes_mode_and_price() -> None:
    a = build_idempotency_key(
        mode="simulation",
        signal_id="manual",
        stock_code="000001",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        limit_price=10.0,
    )
    b = build_idempotency_key(
        mode="paper",
        signal_id="manual",
        stock_code="000001",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        limit_price=10.0,
    )
    c = build_idempotency_key(
        mode="simulation",
        signal_id="manual",
        stock_code="000001",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        limit_price=11.0,
    )
    assert a != b
    assert a != c
    assert len(a) == 64


def test_mock_immediate_fill_does_not_emit_before_return() -> None:
    async def _run() -> None:
        events: list = []
        m = MockQmtAdapter(initial_cash=100_000, deferred_fill=False)
        m.register_order_callback(lambda o: events.append(o))
        await m.connect()
        o = await m.submit_order(
            stock_code="000001", side="BUY", quantity=100, limit_price=10.0
        )
        assert o.status == "FILLED"
        # 即时成交不再自动 emit
        assert len(events) == 0

    asyncio.run(_run())


def test_live_trader_emits_after_insert() -> None:
    async def _run() -> None:
        events: list = []
        adapter = MockQmtAdapter(initial_cash=100_000)
        adapter.register_order_callback(lambda o: events.append(o))
        await adapter.connect()

        db = AsyncMock()
        db.execute = AsyncMock()

        trader = LiveTrader(db, adapter, mode="paper")
        trader._connected = True
        trader._mirror_broker_state_to_local = AsyncMock()

        with patch(
            "app.trade.live_trader.order_event_bridge",
            create=True,
        ):
            req = OrderRequest(
                stock_code="000001",
                side="BUY",
                order_type="LIMIT",
                quantity=100,
                limit_price=10.0,
            )
            result = await trader.submit_order(req)

        assert result.status == "FILLED"
        # INSERT 之后才 emit
        assert len(events) == 1
        assert events[0].status == "FILLED"
        # 应已执行镜像
        trader._mirror_broker_state_to_local.assert_awaited()
        assert db.execute.await_count >= 1

    asyncio.run(_run())


def test_force_fill_still_emits() -> None:
    async def _run() -> None:
        events: list = []
        m = MockQmtAdapter(initial_cash=100_000, deferred_fill=True)
        m.register_order_callback(lambda o: events.append(o))
        await m.connect()
        o = await m.submit_order(
            stock_code="000001", side="BUY", quantity=100, limit_price=10.0
        )
        assert len(events) == 0
        m.force_fill(o.broker_order_id)
        assert len(events) == 1
        assert events[0].status == "FILLED"

    asyncio.run(_run())
