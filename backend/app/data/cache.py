import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings


class CacheManager:
    TTL_QUOTE = 5
    TTL_KLINE_MIN = 30
    TTL_KLINE_DAILY = 300
    TTL_FUND_FLOW = 60
    TTL_NEWS = 300
    TTL_FUNDAMENTAL = 3600
    TTL_SIGNAL = 300

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
            )
        return self._client

    async def get(self, key: str) -> Any | None:
        client = await self._get_client()
        try:
            value = await client.get(key)
            if value:
                return json.loads(value)
        except Exception:
            pass
        return None

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        client = await self._get_client()
        try:
            await client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception:
            pass

    async def delete_pattern(self, pattern: str) -> None:
        client = await self._get_client()
        try:
            keys = await client.keys(pattern)
            if keys:
                await client.delete(*keys)
        except Exception:
            pass

    async def publish(self, channel: str, data: dict) -> None:
        client = await self._get_client()
        try:
            await client.publish(channel, json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            pass

    async def set_lock(self, key: str, ttl: int = 10) -> bool:
        client = await self._get_client()
        try:
            return bool(await client.set(f"lock:{key}", "1", ex=ttl, nx=True))
        except Exception:
            return False

    async def release_lock(self, key: str) -> None:
        await self.delete(f"lock:{key}")

    async def get_raw(self, key: str) -> str | None:
        client = await self._get_client()
        try:
            return await client.get(key)
        except Exception:
            return None

    async def set_raw(self, key: str, value: str, ttl: int | None = None) -> None:
        client = await self._get_client()
        try:
            if ttl:
                await client.setex(key, ttl, value)
            else:
                await client.set(key, value)
        except Exception:
            pass

    async def delete_raw(self, key: str) -> None:
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception:
            pass