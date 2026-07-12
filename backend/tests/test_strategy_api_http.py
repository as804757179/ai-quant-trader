"""策略 API HTTP 级测试（无需 DB）。"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("WS_REDIS_ENABLED", "false")
os.environ.setdefault("API_KEY", "")

from app.main import app
from app.strategy.config_store import StrategyConfigStore


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_strategy_list_and_update() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as td:
            store = StrategyConfigStore(Path(td) / "s.json")
            with patch("app.api.strategy._store", store):
                async with await _client() as client:
                    r = await client.get("/api/v1/strategy/list")
                    assert r.status_code == 200
                    body = r.json()
                    assert body["success"] is True
                    assert body["data"]["total"] == 4

                    r2 = await client.post(
                        "/api/v1/strategy/dual_ma/update",
                        json={"enabled": False, "params": {"fast_period": 8}},
                    )
                    assert r2.status_code == 200
                    data = r2.json()["data"]
                    assert data["enabled"] is False
                    assert data["params"]["fast_period"] == 8

                    r3 = await client.get("/api/v1/strategy/unknown_xx")
                    # error() raises HTTPException
                    assert r3.status_code == 404

    asyncio.run(_run())
