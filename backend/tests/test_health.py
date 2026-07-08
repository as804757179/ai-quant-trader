import asyncio
import os

import httpx

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:password@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:password@localhost:6379/0")

from app.main import app


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_health_endpoint_returns_version() -> None:
    response = asyncio.run(_get("/api/v1/health"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "1.0.0"
    assert "status" in payload