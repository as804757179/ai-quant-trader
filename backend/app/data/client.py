import asyncio
from typing import Any

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class DataClient:
    TIMEOUT = 10.0
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.A_STOCK_DATA_URL,
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
                logger.warning("data_client_timeout", path=path, attempts=attempt + 1)
                return None
            except httpx.HTTPStatusError as exc:
                logger.error("data_client_http_error", path=path, status=exc.response.status_code)
                return None
            except Exception as exc:
                logger.error("data_client_error", path=path, error=str(exc))
                return None
        return None

    async def fetch_quote(self, code: str) -> dict | None:
        return await self._request("GET", f"/quote/{code}")

    async def fetch_kline(self, code: str, period: str, limit: int) -> list[dict] | None:
        data = await self._request(
            "GET", f"/kline/{code}", params={"period": period, "limit": limit}
        )
        return data.get("data") if data else None

    async def fetch_fund_flow(self, code: str, days: int) -> list[dict] | None:
        data = await self._request(
            "GET", f"/fund-flow/{code}", params={"days": days}
        )
        return data.get("data") if data else None

    async def fetch_news(self, code: str, limit: int = 20) -> list[dict] | None:
        data = await self._request("GET", f"/news/{code}", params={"limit": limit})
        return data.get("data") if data else None

    async def fetch_financial_report(self, code: str) -> dict | None:
        data = await self._request("GET", f"/financial/{code}")
        return data.get("data") if data else None

    async def fetch_stock_list(self) -> list[dict] | None:
        data = await self._request("GET", "/stock/list")
        return data.get("data") if data else None