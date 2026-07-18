import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import httpx

from app.core.config import settings
from app.core.logging import FEATURE_DATA, get_logger

logger = get_logger(__name__, feature=FEATURE_DATA)

DataResultStatus = Literal[
    "success",
    "no_data",
    "timeout",
    "fetch_failed",
    "malformed_response",
    "validation_failed",
]


@dataclass(frozen=True)
class DataFetchResult:
    """Stable result contract for internal a-stock-data reads."""

    status: DataResultStatus
    data: Any | None = None
    error_code: str | None = None
    retryable: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == "success"

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

    @staticmethod
    def _provenance(path: str, payload: Any | None = None) -> dict[str, Any]:
        provenance: dict[str, Any] = {"service": "a-stock-data", "path": path}
        if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
            provenance.update(payload["meta"])
        return provenance

    @staticmethod
    def _retryable_http_status(status_code: int) -> bool:
        return status_code in {408, 425, 429} or status_code >= 500

    @staticmethod
    def _collection_has_only_dicts(payload: Any) -> bool:
        return isinstance(payload, list) and all(isinstance(item, dict) for item in payload)

    @staticmethod
    def _quote_map_is_valid(payload: Any) -> bool:
        return isinstance(payload, dict) and all(
            isinstance(code, str) and isinstance(quote, dict)
            for code, quote in payload.items()
        )

    @staticmethod
    def _validation_result(
        error_code: str, provenance: dict[str, Any]
    ) -> DataFetchResult:
        return DataFetchResult(
            status="validation_failed",
            error_code=error_code,
            retryable=False,
            provenance=provenance,
        )

    async def _request_typed(
        self, method: str, path: str, **kwargs: Any
    ) -> DataFetchResult:
        client = await self._client()
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError:
                    logger.warning("data_client_malformed_response", path=path)
                    return DataFetchResult(
                        status="malformed_response",
                        error_code="MALFORMED_RESPONSE",
                        retryable=False,
                        provenance=self._provenance(path),
                    )
                if not isinstance(payload, (dict, list)):
                    logger.warning("data_client_malformed_response", path=path)
                    return DataFetchResult(
                        status="malformed_response",
                        error_code="MALFORMED_RESPONSE",
                        retryable=False,
                        provenance=self._provenance(path),
                    )
                provenance = self._provenance(path, payload)
                if isinstance(payload, dict) and payload.get("success") is False:
                    return DataFetchResult(
                        status="fetch_failed",
                        error_code=str(payload.get("error_code") or "UPSTREAM_REJECTED"),
                        retryable=bool(payload.get("retryable", False)),
                        provenance=provenance,
                    )
                return DataFetchResult(data=payload, provenance=provenance, status="success")
            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                logger.warning("data_client_timeout", path=path, attempts=attempt + 1)
                return DataFetchResult(
                    status="timeout",
                    error_code="UPSTREAM_TIMEOUT",
                    retryable=True,
                    provenance=self._provenance(path),
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                logger.error("data_client_http_error", path=path, status=status_code)
                if status_code in {400, 422}:
                    return self._validation_result(
                        f"UPSTREAM_HTTP_{status_code}", self._provenance(path)
                    )
                return DataFetchResult(
                    status="fetch_failed",
                    error_code=f"UPSTREAM_HTTP_{status_code}",
                    retryable=self._retryable_http_status(status_code),
                    provenance=self._provenance(path),
                )
            except httpx.RequestError as exc:
                logger.error("data_client_request_error", path=path, error=str(exc))
                return DataFetchResult(
                    status="fetch_failed",
                    error_code="UPSTREAM_REQUEST_FAILED",
                    retryable=True,
                    provenance=self._provenance(path),
                )
            except Exception as exc:
                logger.error("data_client_error", path=path, error=str(exc))
                return DataFetchResult(
                    status="fetch_failed",
                    error_code="DATA_CLIENT_ERROR",
                    retryable=False,
                    provenance=self._provenance(path),
                )
        return DataFetchResult(
            status="fetch_failed",
            error_code="DATA_CLIENT_RETRY_EXHAUSTED",
            retryable=True,
            provenance=self._provenance(path),
        )

    def _payload_result(
        self,
        result: DataFetchResult,
        expected_type: type | tuple[type, ...],
        *,
        validator: Callable[[Any], bool] | None = None,
    ) -> DataFetchResult:
        if not result.success:
            return result

        response = result.data
        provenance = dict(result.provenance)
        payload = response
        if isinstance(response, dict):
            if isinstance(response.get("meta"), dict):
                provenance.update(response["meta"])
            if "success" in response:
                if response.get("success") is False:
                    return DataFetchResult(
                        status="fetch_failed",
                        error_code=str(response.get("error_code") or "UPSTREAM_REJECTED"),
                        retryable=bool(response.get("retryable", False)),
                        provenance=provenance,
                    )
                if "data" not in response:
                    return DataFetchResult(
                        status="malformed_response",
                        error_code="MALFORMED_ENVELOPE",
                        retryable=False,
                        provenance=provenance,
                    )
                payload = response["data"]
            elif "data" in response and "price" not in response:
                payload = response["data"]
            elif "items" in response and expected_type is list:
                payload = response["items"]

        if payload is None:
            return DataFetchResult(
                status="no_data",
                error_code="NO_DATA",
                retryable=False,
                provenance=provenance,
            )
        if not isinstance(payload, expected_type):
            return DataFetchResult(
                status="malformed_response",
                error_code="MALFORMED_RESPONSE",
                retryable=False,
                provenance=provenance,
            )
        if not payload:
            return DataFetchResult(
                status="no_data",
                error_code="NO_DATA",
                retryable=False,
                provenance=provenance,
            )
        if validator is not None and not validator(payload):
            return self._validation_result("DATA_VALIDATION_FAILED", provenance)
        return DataFetchResult(data=payload, provenance=provenance, status="success")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict | None:
        """Legacy compatibility request path; new callers should use typed methods."""
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

    async def fetch_quote_result(self, code: str) -> DataFetchResult:
        return self._payload_result(
            await self._request_typed("GET", f"/quote/{code}"), dict
        )

    async def fetch_quotes_batch_result(self, codes: list[str]) -> DataFetchResult:
        clean_codes = [str(code).strip() for code in codes if str(code).strip()]
        provenance = self._provenance("/quotes")
        if not clean_codes:
            return self._validation_result("CODES_REQUIRED", provenance)
        result = await self._request_typed(
            "GET", "/quotes", params={"codes": ",".join(clean_codes)}
        )
        return self._payload_result(result, dict, validator=self._quote_map_is_valid)

    async def fetch_kline_result(
        self, code: str, period: str, limit: int
    ) -> DataFetchResult:
        result = await self._request_typed(
            "GET",
            f"/kline/{code}",
            params={"period": period, "limit": limit, "adjustment": "raw"},
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_fund_flow_result(self, code: str, days: int) -> DataFetchResult:
        result = await self._request_typed(
            "GET", f"/fund-flow/{code}", params={"days": days}
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_news_result(self, code: str, limit: int = 20) -> DataFetchResult:
        result = await self._request_typed("GET", f"/news/{code}", params={"limit": limit})
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_financial_report_result(self, code: str) -> DataFetchResult:
        return self._payload_result(
            await self._request_typed("GET", f"/financial/{code}"), dict
        )

    async def fetch_stock_list_result(self) -> DataFetchResult:
        result = await self._request_typed("GET", "/stock/list")
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def refresh_stock_list_result(self) -> DataFetchResult:
        token = settings.A_STOCK_DATA_COMMAND_TOKEN.strip()
        if (
            len(token) < 32
            or token.lower().startswith("replace-with-")
            or "change_me" in token.lower()
        ):
            return self._validation_result(
                "DATA_COMMAND_TOKEN_REQUIRED",
                self._provenance("/internal/stock-list/refresh"),
            )
        result = await self._request_typed(
            "POST",
            "/internal/stock-list/refresh",
            headers={"X-Stock-Refresh-Token": token},
            timeout=120.0,
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

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

    async def fetch_stock_list(self) -> list[dict] | None:
        # 全市场列表较大，单独放宽超时（缓存命中时很快）
        client = await self._client()
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(
                    "/stock/list",
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

    async def refresh_stock_list(self) -> list[dict] | None:
        result = await self.refresh_stock_list_result()
        return result.data if result.success and isinstance(result.data, list) else None
