import json
import time
from threading import Lock
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# 进程内共享连接，避免每次 new CacheManager 都开池
_shared_client: aioredis.Redis | None = None

# L1 进程内缓存：热路径避免 Redis RTT + 序列化（报价/K线秒级命中）
_l1: dict[str, tuple[float, Any]] = {}
_l1_lock = Lock()
_L1_MAX_KEYS = 4096


class CacheManager:
    # 行情缓存略放宽：UI 轮询友好，真实行情仍由后台任务/刷新覆盖
    TTL_QUOTE = max(5, int(getattr(settings, "DATA_CACHE_TTL_QUOTE", 15) or 15))
    TTL_KLINE_MIN = 30
    TTL_KLINE_DAILY = max(60, int(getattr(settings, "DATA_CACHE_TTL_KLINE", 300) or 300))
    TTL_FUND_FLOW = 60
    TTL_NEWS = 300
    TTL_FUNDAMENTAL = 3600
    TTL_SIGNAL = 300
    TTL_STOCK_LIST = 30

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis:
        global _shared_client
        if self._client is not None:
            return self._client
        if _shared_client is None:
            _shared_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
        self._client = _shared_client
        return self._client

    def _log_error(self, op: str, error: Exception, **kwargs: Any) -> None:
        logger.warning("cache_op_failed", op=op, error=str(error), **kwargs)

    @staticmethod
    def _l1_get(key: str) -> Any | None:
        now = time.monotonic()
        with _l1_lock:
            item = _l1.get(key)
            if not item:
                return None
            exp, val = item
            if exp < now:
                _l1.pop(key, None)
                return None
            return val

    @staticmethod
    def _l1_set(key: str, value: Any, ttl: int) -> None:
        if ttl <= 0:
            return
        now = time.monotonic()
        with _l1_lock:
            if len(_l1) >= _L1_MAX_KEYS:
                # 简单淘汰：删掉已过期；仍满则清空一半
                expired = [k for k, (e, _) in _l1.items() if e < now]
                for k in expired:
                    _l1.pop(k, None)
                if len(_l1) >= _L1_MAX_KEYS:
                    for k in list(_l1.keys())[: len(_l1) // 2]:
                        _l1.pop(k, None)
            _l1[key] = (now + float(ttl), value)

    @staticmethod
    def _l1_delete(key: str) -> None:
        with _l1_lock:
            _l1.pop(key, None)

    async def get(self, key: str) -> Any | None:
        hit = self._l1_get(key)
        if hit is not None:
            return hit
        client = await self._get_client()
        try:
            value = await client.get(key)
            if value:
                data = json.loads(value)
                # 回填 L1：尽量贴近业务 TTL，避免热路径反复打 Redis
                self._l1_set(key, data, ttl=max(3, min(30, self.TTL_QUOTE)))
                return data
        except Exception as exc:
            self._log_error("get", exc, key=key)
        return None

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        self._l1_set(key, value, ttl=ttl)
        client = await self._get_client()
        try:
            await client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
        except Exception as exc:
            self._log_error("set", exc, key=key)

    async def delete(self, key: str) -> None:
        self._l1_delete(key)
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception as exc:
            self._log_error("delete", exc, key=key)

    async def delete_pattern(self, pattern: str) -> None:
        with _l1_lock:
            # 仅支持简单前缀*
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                for k in [k for k in _l1 if k.startswith(prefix)]:
                    _l1.pop(k, None)
            else:
                _l1.pop(pattern, None)
        client = await self._get_client()
        try:
            keys = await client.keys(pattern)
            if keys:
                await client.delete(*keys)
        except Exception as exc:
            self._log_error("delete_pattern", exc, pattern=pattern)

    async def publish(self, channel: str, data: dict) -> None:
        client = await self._get_client()
        try:
            await client.publish(channel, json.dumps(data, ensure_ascii=False, default=str))
        except Exception as exc:
            self._log_error("publish", exc, channel=channel)

    async def set_lock(self, key: str, ttl: int = 10) -> bool:
        client = await self._get_client()
        try:
            return bool(await client.set(f"lock:{key}", "1", ex=ttl, nx=True))
        except Exception as exc:
            self._log_error("set_lock", exc, key=key)
            return False

    async def release_lock(self, key: str) -> None:
        await self.delete(f"lock:{key}")

    async def get_raw(self, key: str) -> str | None:
        client = await self._get_client()
        try:
            return await client.get(key)
        except Exception as exc:
            self._log_error("get_raw", exc, key=key)
        return None

    async def get_raw_strict(self, key: str) -> str | None:
        """Read a safety-critical value without converting infrastructure errors to None."""
        client = await self._get_client()
        return await client.get(key)

    async def set_raw(self, key: str, value: str, ttl: int | None = None) -> None:
        client = await self._get_client()
        try:
            if ttl:
                await client.setex(key, ttl, value)
            else:
                await client.set(key, value)
        except Exception as exc:
            self._log_error("set_raw", exc, key=key)

    async def set_raw_strict(self, key: str, value: str, ttl: int | None = None) -> None:
        """Write a safety-critical value and propagate infrastructure failures."""
        client = await self._get_client()
        if ttl:
            await client.setex(key, ttl, value)
        else:
            await client.set(key, value)

    async def delete_raw(self, key: str) -> None:
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception as exc:
            self._log_error("delete_raw", exc, key=key)

    async def delete_raw_strict(self, key: str) -> None:
        """Delete a safety-critical value and propagate infrastructure failures."""
        client = await self._get_client()
        await client.delete(key)

    async def mget(self, keys: list[str]) -> list[Any | None]:
        """批量 get：先 L1，未命中再 Redis MGET。"""
        if not keys:
            return []
        results: list[Any | None] = [None] * len(keys)
        miss_idx: list[int] = []
        miss_keys: list[str] = []
        for i, k in enumerate(keys):
            hit = self._l1_get(k)
            if hit is not None:
                results[i] = hit
            else:
                miss_idx.append(i)
                miss_keys.append(k)
        if not miss_keys:
            return results
        client = await self._get_client()
        try:
            values = await client.mget(miss_keys)
            for i, raw in zip(miss_idx, values):
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                results[i] = data
                self._l1_set(keys[i], data, ttl=min(5, self.TTL_QUOTE))
        except Exception as exc:
            self._log_error("mget", exc, count=len(miss_keys))
        return results
