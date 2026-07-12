import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import FEATURE_DATA, get_logger

logger = get_logger(__name__, feature=FEATURE_DATA)

# 进程级共享 HTTP 客户端，复用连接池
_shared_http: httpx.AsyncClient | None = None
_shared_lock = asyncio.Lock()


async def get_shared_http() -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        return _shared_http
    async with _shared_lock:
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(
                base_url=settings.A_STOCK_DATA_URL,
                timeout=httpx.Timeout(10.0, connect=3.0),
                trust_env=False,  # 禁用系统代理，避免本机 127.0.0.1 被错误代理
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=40),
                headers={"Connection": "keep-alive"},
            )
        return _shared_http


async def close_shared_http() -> None:
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        await _shared_http.aclose()
    _shared_http = None


class DataClient:
    TIMEOUT = 10.0
    MAX_RETRIES = 2  # 热路径少重试，失败快降级

    def __init__(self, *, shared: bool = True) -> None:
        self._shared = shared
        self._owned: httpx.AsyncClient | None = None
        if not shared:
            self._owned = httpx.AsyncClient(
                base_url=settings.A_STOCK_DATA_URL,
                timeout=httpx.Timeout(self.TIMEOUT, connect=3.0),
                trust_env=False,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )

    async def _client(self) -> httpx.AsyncClient:
        if self._owned is not None:
            return self._owned
        return await get_shared_http()

    async def close(self) -> None:
        # 共享客户端不在单次请求中关闭
        if self._owned is not None:
            await self._owned.aclose()
            self._owned = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict | None:
        client = await self._client()
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(0.2 * (attempt + 1))
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
        data = await self._request("GET", f"/quote/{code}")
        if not data:
            return None
        # 兼容 {success,data} 与直接行情对象
        if isinstance(data, dict) and "data" in data and (
            data.get("success") is True or "price" not in data
        ):
            inner = data.get("data")
            return inner if isinstance(inner, dict) else None
        return data if isinstance(data, dict) else None

    async def fetch_quotes_batch(self, codes: list[str]) -> dict[str, dict]:
        """批量行情：优先 /quotes?codes=，失败则并发单票。"""
        codes = [c.strip() for c in codes if c and str(c).strip()]
        if not codes:
            return {}
        if len(codes) == 1:
            q = await self.fetch_quote(codes[0])
            return {codes[0]: q} if q else {}

        joined = ",".join(codes[:80])  # 腾讯单次不宜过长
        data = await self._request("GET", "/quotes", params={"codes": joined})
        out: dict[str, dict] = {}
        if isinstance(data, dict):
            payload = data.get("data") if "data" in data else data
            if isinstance(payload, dict):
                for k, v in payload.items():
                    if isinstance(v, dict) and float(v.get("price") or 0) > 0:
                        out[str(k).zfill(6) if str(k).isdigit() else str(k)] = v
            elif isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    code = str(item.get("stock_code") or item.get("code") or "").zfill(6)
                    if code and float(item.get("price") or 0) > 0:
                        out[code] = item
        if len(out) >= max(1, len(codes) // 2):
            return out

        # 降级：有限并发单票
        sem = asyncio.Semaphore(10)

        async def _one(c: str) -> tuple[str, dict | None]:
            async with sem:
                return c, await self.fetch_quote(c)

        pairs = await asyncio.gather(*[_one(c) for c in codes if c not in out])
        for c, q in pairs:
            if q:
                out[c] = q
        return out

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

    async def fetch_stock_list(self, force_refresh: bool = False) -> list[dict] | None:
        # 全市场列表较大，单独放宽超时（缓存命中时很快）
        params = {"force_refresh": "true"} if force_refresh else None
        client = await self._client()
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(
                    "/stock/list",
                    params=params,
                    timeout=120.0,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data") if data else None
            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.warning("data_client_timeout", path="/stock/list", attempts=attempt + 1)
                return None
            except Exception as exc:
                logger.error("data_client_error", path="/stock/list", error=str(exc))
                return None
        return None
