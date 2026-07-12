"""熔断 DB 优先 + API Key 鉴权。"""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("WS_REDIS_ENABLED", "false")
os.environ.setdefault("API_KEY", "")  # 默认关闭

from app.core.auth import extract_api_key, is_public_path
from app.risk.fuse import FuseManager


def test_public_paths() -> None:
    assert is_public_path("/api/v1/health") is True
    assert is_public_path("/api/docs") is True
    assert is_public_path("/ws/quotes") is True
    assert is_public_path("/api/v1/trade/order") is False


def test_extract_api_key_from_headers() -> None:
    req = MagicMock()
    req.headers = {"X-API-Key": "secret-123"}
    assert extract_api_key(req) == "secret-123"

    req2 = MagicMock()
    req2.headers = {"Authorization": "Bearer token-xyz"}
    assert extract_api_key(req2) == "token-xyz"


def test_is_fused_uses_db_not_only_cache() -> None:
    async def _run() -> None:
        db = AsyncMock()
        # DB says active
        db_result = MagicMock()
        db_result.scalar.return_value = 1
        db.execute = AsyncMock(return_value=db_result)

        cache = MagicMock()
        cache.get_raw = AsyncMock(return_value=None)  # Redis 空
        cache.set_raw = AsyncMock()
        cache.delete_raw = AsyncMock()

        fuse = FuseManager(db, cache)
        assert await fuse.is_fused("simulation") is True
        cache.set_raw.assert_awaited()  # 回写缓存

    asyncio.run(_run())


def test_is_fused_false_clears_cache() -> None:
    async def _run() -> None:
        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar.return_value = None
        db.execute = AsyncMock(return_value=db_result)

        cache = MagicMock()
        cache.get_raw = AsyncMock(
            return_value=json.dumps({"active": True})  # 脏缓存
        )
        cache.delete_raw = AsyncMock()
        cache.set_raw = AsyncMock()

        fuse = FuseManager(db, cache)
        assert await fuse.is_fused("simulation") is False
        cache.delete_raw.assert_awaited_with("fuse:simulation")

    asyncio.run(_run())


def test_api_key_middleware_blocks_when_configured() -> None:
    async def _run() -> None:
        # 临时开启 API_KEY
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.API_KEY = "test-api-key-xyz"
            from app.core.auth import api_key_middleware

            request = MagicMock()
            request.url.path = "/api/v1/trade/order"
            request.headers = {}

            async def call_next(_req):
                return httpx.Response(200, json={"ok": True})

            # 无 key
            resp = await api_key_middleware(request, call_next)
            assert resp.status_code == 401

            # 错误 key
            request.headers = {"X-API-Key": "wrong"}
            resp2 = await api_key_middleware(request, call_next)
            assert resp2.status_code == 401

            # 正确 key
            request.headers = {"X-API-Key": "test-api-key-xyz"}
            resp3 = await api_key_middleware(request, call_next)
            assert resp3.status_code == 200

            # health 放行
            request.url.path = "/api/v1/health"
            request.headers = {}
            resp4 = await api_key_middleware(request, call_next)
            assert resp4.status_code == 200

    asyncio.run(_run())
