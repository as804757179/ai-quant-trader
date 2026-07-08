from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class DataClient:
    """a-stock-data HTTP 客户端（与 backend DataClient 对齐）。"""

    TIMEOUT = 10.0
    MAX_RETRIES = 3

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.getenv(
            "A_STOCK_DATA_URL", "http://a-stock-data:8080"
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict | None:
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.warning("data_client_timeout", path=path)
                return None
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "data_client_http_error",
                    path=path,
                    status=exc.response.status_code,
                )
                return None
            except Exception as exc:
                logger.warning("data_client_error", path=path, error=str(exc))
                return None
        return None

    async def fetch_quote(self, code: str) -> dict | None:
        return await self._request("GET", f"/quote/{code}")


def validate_quote(data: dict | None) -> bool:
    if not data:
        return False
    price = data.get("price", 0)
    if not price or price <= 0:
        return False
    high = data.get("high", 0)
    low = data.get("low", 0)
    if high and low and high < low:
        return False
    return True