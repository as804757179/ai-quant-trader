import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:password@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:password@localhost:6379/0")
os.environ.setdefault("WS_REDIS_ENABLED", "false")

from app.ws.manager import WebSocketManager


class FakeWebSocket:
    """轻量 WebSocket 替身，用于测试连接与消息推送。"""

    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[str] = []
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


def test_ws_connect_and_receive_broadcast() -> None:
    async def _run() -> None:
        manager = WebSocketManager()
        manager._running = True
        ws = FakeWebSocket()

        await manager.connect(ws, "signals")
        assert ws.accepted is True
        assert manager.connection_count == 1

        handled = await manager.handle_client_message(ws, "ping")
        assert handled is True
        assert ws.sent[-1] == "pong"

        sent = await manager.broadcast(
            "signals",
            {"type": "signal", "stock_code": "000001", "action": "BUY"},
        )
        assert sent == 1

        payload = json.loads(ws.sent[-1])
        assert payload["type"] == "signal"
        assert payload["stock_code"] == "000001"
        assert payload["_channel"] == "signals"
        assert "_ts" in payload

    asyncio.run(_run())


def test_ws_multiple_clients_receive_broadcast() -> None:
    async def _run() -> None:
        manager = WebSocketManager()
        manager._running = True
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        await manager.connect(ws1, "signals")
        await manager.connect(ws2, "signals")

        sent = await manager.broadcast("signals", {"type": "signal", "action": "SELL"})
        assert sent == 2

        msg1 = json.loads(ws1.sent[-1])
        msg2 = json.loads(ws2.sent[-1])
        assert msg1["action"] == "SELL"
        assert msg2["action"] == "SELL"

    asyncio.run(_run())


def test_ws_ping_updates_heartbeat() -> None:
    async def _run() -> None:
        manager = WebSocketManager()
        manager._running = True
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        await manager.connect(mock_ws, "signals")
        assert manager.connection_count == 1

        handled = await manager.handle_client_message(mock_ws, "ping")
        assert handled is True
        mock_ws.send_text.assert_awaited_once_with("pong")

        await manager.disconnect(mock_ws)
        assert manager.connection_count == 0

    asyncio.run(_run())


def test_ws_redis_channel_mapping() -> None:
    manager = WebSocketManager()
    assert manager._redis_channel_to_ws("channel:quotes:000001") == "quotes:000001"
    assert manager._redis_channel_to_ws("channel:signals") == "signals"
    assert manager._redis_channel_to_ws("channel:portfolio:simulation") == "portfolio:simulation"


def test_ws_dispatch_redis_message() -> None:
    async def _run() -> None:
        manager = WebSocketManager()
        manager._running = True
        ws = FakeWebSocket()
        await manager.connect(ws, "quotes:000001")

        await manager.dispatch_redis_message(
            "channel:quotes:000001",
            json.dumps({"type": "quote", "price": 10.5}),
        )
        assert len(ws.sent) == 1
        sent = json.loads(ws.sent[0])
        assert sent["price"] == 10.5
        assert sent["_channel"] == "quotes:000001"

    asyncio.run(_run())


def test_ws_stale_client_disconnect() -> None:
    """心跳超时后自动清理僵死连接（断线重连机制的服务端部分）。"""

    async def _heartbeat_once() -> None:
        manager = WebSocketManager()
        manager._running = True
        manager.HEARTBEAT_INTERVAL = 0.01
        manager.HEARTBEAT_TIMEOUT = 0

        ws = FakeWebSocket()
        await manager.connect(ws, "alerts")
        manager._client_last_ping[ws] = 0

        task = asyncio.create_task(manager._heartbeat_loop())
        await asyncio.sleep(0.05)
        manager._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert manager.connection_count == 0

    asyncio.run(_heartbeat_once())


def test_ws_routes_registered() -> None:
    from app.main import app

    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/ws/quotes/{stock_code}" in paths
    assert "/ws/signals" in paths
    assert "/ws/alerts" in paths
    assert "/ws/portfolio" in paths