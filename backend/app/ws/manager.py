from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import WebSocket

from app.core.config import settings
from app.core.timeutil import now_cn_iso

logger = structlog.get_logger(__name__)

REDIS_PREFIX = "channel:"


class WebSocketManager:
    """WebSocket 连接管理器 — Redis Pub/Sub 订阅 + 多频道广播。"""

    HEARTBEAT_INTERVAL = 30
    HEARTBEAT_TIMEOUT = 90

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.REDIS_URL
        self._connections: dict[str, list[WebSocket]] = {}
        self._client_channels: dict[WebSocket, set[str]] = {}
        self._client_last_ping: dict[WebSocket, float] = {}
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._subscriber_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False

    @property
    def connection_count(self) -> int:
        return len(self._client_channels)

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        redis_enabled = os.getenv("WS_REDIS_ENABLED", "true").lower() == "true"
        if redis_enabled:
            try:
                self._redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                self._subscriber_task = asyncio.create_task(self._redis_subscriber_loop())
                logger.info("ws_redis_subscriber_started")
            except Exception as exc:
                logger.warning("ws_redis_subscriber_failed", error=str(exc))
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("ws_manager_started", redis_enabled=redis_enabled)

    async def stop(self) -> None:
        self._running = False
        for task in (self._subscriber_task, self._heartbeat_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._subscriber_task = None
        self._heartbeat_task = None

        for ws in list(self._client_channels.keys()):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()
        self._client_channels.clear()
        self._client_last_ping.clear()

        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.punsubscribe()
                await self._pubsub.aclose()
            except Exception:
                pass
            self._pubsub = None

        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

        logger.info("ws_manager_stopped")

    async def connect(self, websocket: WebSocket, channel: str) -> None:
        await websocket.accept()
        self._connections.setdefault(channel, []).append(websocket)
        self._client_channels.setdefault(websocket, set()).add(channel)
        self._client_last_ping[websocket] = time.time()
        logger.info("ws_client_connected", channel=channel, total=self.connection_count)

    async def disconnect(self, websocket: WebSocket) -> None:
        channels = self._client_channels.pop(websocket, set())
        self._client_last_ping.pop(websocket, None)
        for channel in channels:
            bucket = self._connections.get(channel, [])
            if websocket in bucket:
                bucket.remove(websocket)
            if not bucket:
                self._connections.pop(channel, None)
        logger.info("ws_client_disconnected", channels=list(channels), total=self.connection_count)

    async def handle_client_message(self, websocket: WebSocket, data: str) -> bool:
        if data.strip().lower() == "ping":
            self._client_last_ping[websocket] = time.time()
            await websocket.send_text("pong")
            return True
        return False

    async def broadcast(self, channel: str, data: dict[str, Any]) -> int:
        """向订阅频道的所有客户端推送消息，返回成功发送数。"""
        clients = list(self._connections.get(channel, []))
        if not clients:
            return 0

        event = dict(data)
        event.setdefault("event_version", "1")
        payload = json.dumps(
            {
                **event,
                "_channel": channel,
                "_ts": now_cn_iso(),
            },
            ensure_ascii=False,
            default=str,
        )

        sent = 0
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead.append(ws)

        for ws in dead:
            await self.disconnect(ws)
        return sent

    async def dispatch_redis_message(self, redis_channel: str, raw_data: str) -> None:
        ws_channel = self._redis_channel_to_ws(redis_channel)
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("ws_invalid_redis_payload", channel=redis_channel)
            return
        await self.broadcast(ws_channel, data)

    @staticmethod
    def _redis_channel_to_ws(redis_channel: str) -> str:
        if redis_channel.startswith(REDIS_PREFIX):
            return redis_channel[len(REDIS_PREFIX) :]
        return redis_channel

    async def _redis_subscriber_loop(self) -> None:
        if self._redis is None:
            return

        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(f"{REDIS_PREFIX}quotes*")
        await self._pubsub.psubscribe(f"{REDIS_PREFIX}portfolio*")
        await self._pubsub.subscribe(f"{REDIS_PREFIX}signals", f"{REDIS_PREFIX}alerts")

        logger.info("ws_redis_subscribed", patterns=["quotes*", "portfolio*"], channels=["signals", "alerts"])

        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message:
                    continue
                msg_type = message.get("type")
                if msg_type not in ("message", "pmessage"):
                    continue
                redis_channel = message.get("channel")
                raw_data = message.get("data")
                if not redis_channel or raw_data is None:
                    continue
                await self.dispatch_redis_message(redis_channel, raw_data)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ws_subscriber_error", error=str(exc), exc_info=True)
                await asyncio.sleep(1)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            now = time.time()
            stale = [
                ws
                for ws, last_ping in self._client_last_ping.items()
                if now - last_ping > self.HEARTBEAT_TIMEOUT
            ]
            for ws in stale:
                logger.info("ws_client_stale_disconnect")
                await self.disconnect(ws)


ws_manager = WebSocketManager()
