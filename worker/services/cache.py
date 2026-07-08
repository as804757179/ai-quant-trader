from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from config import get_redis_url


class CacheManager:
    """Redis 缓存与 Pub/Sub（与 backend CacheManager 行为对齐）。"""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or get_redis_url()
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
            )
        return self._client

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        client = await self._get_client()
        await client.setex(
            key, ttl, json.dumps(value, ensure_ascii=False, default=str)
        )

    async def publish(self, channel: str, data: dict) -> None:
        client = await self._get_client()
        await client.publish(
            channel, json.dumps(data, ensure_ascii=False, default=str)
        )

    async def set_lock(self, key: str, ttl: int = 300) -> bool:
        """分布式锁（SET NX EX），获取成功返回 True。"""
        client = await self._get_client()
        try:
            return bool(await client.set(key, "1", ex=ttl, nx=True))
        except Exception:
            return False

    async def release_lock(self, key: str) -> None:
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception:
            pass

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None