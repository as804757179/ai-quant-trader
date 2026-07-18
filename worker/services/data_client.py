from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import httpx
import structlog

logger = structlog.get_logger(__name__)

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
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.request(method, path, **kwargs)
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
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.warning("data_client_timeout", path=path)
                return DataFetchResult(
                    status="timeout",
                    error_code="UPSTREAM_TIMEOUT",
                    retryable=True,
                    provenance=self._provenance(path),
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                logger.warning(
                    "data_client_http_error",
                    path=path,
                    status=status_code,
                )
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
                logger.warning("data_client_request_error", path=path, error=str(exc))
                return DataFetchResult(
                    status="fetch_failed",
                    error_code="UPSTREAM_REQUEST_FAILED",
                    retryable=True,
                    provenance=self._provenance(path),
                )
            except Exception as exc:
                logger.warning("data_client_error", path=path, error=str(exc))
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

    async def fetch_quote_result(self, code: str) -> DataFetchResult:
        return self._payload_result(
            await self._request_typed("GET", f"/quote/{code}"), dict
        )

    async def fetch_announcements_with_provenance_result(
        self, code: str, limit: int = 1
    ) -> DataFetchResult:
        clean_code = str(code).strip().upper()
        result = await self._request_typed(
            "GET",
            f"/announcements/{clean_code}",
            params={"limit": max(1, min(int(limit), 5)), "fresh": "true"},
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_annual_reports_with_provenance_result(
        self, code: str, limit: int = 1
    ) -> DataFetchResult:
        clean_code = str(code).strip().upper()
        result = await self._request_typed(
            "GET",
            f"/financial-reports/{clean_code}",
            params={"limit": max(1, min(int(limit), 1)), "fresh": "true"},
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_news_evidence_with_provenance_result(
        self, code: str, limit: int = 1
    ) -> DataFetchResult:
        clean_code = str(code).strip().upper()
        result = await self._request_typed(
            "GET",
            f"/news-evidence/{clean_code}",
            params={"limit": max(1, min(int(limit), 1)), "fresh": "true"},
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_quotes_with_provenance_result(
        self, codes: list[str]
    ) -> DataFetchResult:
        clean_codes = [str(code).strip() for code in codes if str(code).strip()]
        provenance = self._provenance("/quotes")
        if not clean_codes:
            return self._validation_result("CODES_REQUIRED", provenance)
        result = await self._request_typed(
            "GET",
            "/quotes",
            params={"codes": ",".join(clean_codes), "fresh": "true"},
        )
        return self._payload_result(result, dict, validator=self._quote_map_is_valid)

    async def fetch_fund_flow_result(
        self, code: str, days: int = 5
    ) -> DataFetchResult:
        result = await self._request_typed(
            "GET", f"/fund-flow/{code}", params={"days": days}
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_kline_result(
        self, code: str, period: str = "1d", limit: int = 200
    ) -> DataFetchResult:
        result = await self._request_typed(
            "GET",
            f"/kline/{code}",
            params={"period": period, "limit": limit, "adjustment": "raw"},
        )
        return self._payload_result(
            result, list, validator=self._collection_has_only_dicts
        )

    async def fetch_quote(self, code: str) -> dict | None:
        return await self._request("GET", f"/quote/{code}")

    async def fetch_announcements_with_provenance(
        self, code: str, limit: int = 1
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch one fixed-provider announcement batch without fallback."""
        clean_code = str(code).strip().upper()
        response = await self._request(
            "GET",
            f"/announcements/{clean_code}",
            params={"limit": max(1, min(int(limit), 5)), "fresh": "true"},
        )
        default_metadata = {
            "provider": "cninfo",
            "source": "cninfo_listed_company_disclosure",
            "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            "fallback_used": False,
            "requested_symbols": 1,
            "returned_items": 0,
            "status": "fetch_failed",
            "failure_reason": "a-stock-data 公告请求失败",
            "collector_version": "cninfo-announcement-collector-v1",
            "normalizer_version": "cninfo-announcement-normalizer-v1",
            "usage_status": "review_required",
        }
        if not isinstance(response, dict):
            return [], default_metadata
        metadata = response.get("meta") or {}
        items = response.get("data") or []
        if not isinstance(metadata, dict):
            metadata = {}
        if not isinstance(items, list):
            items = []
        if not metadata:
            return [], {
                **default_metadata,
                "failure_reason": "a-stock-data 未返回公告血缘元数据",
            }
        return [item for item in items if isinstance(item, dict)], metadata

    async def fetch_annual_reports_with_provenance(
        self, code: str, limit: int = 1
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch one fixed-provider annual-report batch without fallback."""
        clean_code = str(code).strip().upper()
        response = await self._request(
            "GET",
            f"/financial-reports/{clean_code}",
            params={"limit": max(1, min(int(limit), 1)), "fresh": "true"},
        )
        default_metadata = {
            "provider": "cninfo",
            "source": "cninfo_listed_company_disclosure",
            "fetch_endpoint": "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            "provider_category": "category_ndbg_szsh",
            "fallback_used": False,
            "requested_symbols": 1,
            "returned_items": 0,
            "status": "fetch_failed",
            "failure_reason": "a-stock-data 年报请求失败",
            "collector_version": "cninfo-annual-report-collector-v1",
            "normalizer_version": "cninfo-annual-report-normalizer-v1",
            "usage_status": "review_required",
        }
        if not isinstance(response, dict):
            return [], default_metadata
        metadata = response.get("meta") or {}
        items = response.get("data") or []
        if not isinstance(metadata, dict):
            metadata = {}
        if not isinstance(items, list):
            items = []
        if not metadata:
            return [], {
                **default_metadata,
                "failure_reason": "a-stock-data 未返回年报血缘元数据",
            }
        return [item for item in items if isinstance(item, dict)], metadata

    async def fetch_news_evidence_with_provenance(
        self, code: str, limit: int = 1
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch one fixed GDELT RSS news-evidence batch without fallback."""
        clean_code = str(code).strip().upper()
        response = await self._request(
            "GET",
            f"/news-evidence/{clean_code}",
            params={"limit": max(1, min(int(limit), 1)), "fresh": "true"},
        )
        default_metadata = {
            "provider": "gdelt",
            "source": "gdelt_article_list_rss",
            "fetch_endpoint": "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss",
            "fallback_used": False,
            "requested_symbols": 1,
            "returned_items": 0,
            "status": "fetch_failed",
            "failure_reason": "a-stock-data 新闻证据请求失败",
            "collector_version": "gdelt-gal-rss-news-collector-v1",
            "normalizer_version": "gdelt-gal-rss-news-normalizer-v1",
            "usage_status": "review_required",
            "content_scope": "title_link_only",
            "feed_window_minutes": 15,
        }
        if not isinstance(response, dict):
            return [], default_metadata
        metadata = response.get("meta") or {}
        items = response.get("data") or []
        if not isinstance(metadata, dict):
            metadata = {}
        if not isinstance(items, list):
            items = []
        if not metadata:
            return [], {
                **default_metadata,
                "failure_reason": "a-stock-data 未返回新闻证据血缘元数据",
            }
        return [item for item in items if isinstance(item, dict)], metadata

    async def fetch_quotes_with_provenance(
        self, codes: list[str]
    ) -> tuple[dict[str, dict], dict[str, Any]]:
        """获取固定 Provider 批量行情；失败时绝不降级到单标的接口。"""
        clean_codes = [str(code).strip() for code in codes if str(code).strip()]
        response = await self._request(
            "GET",
            "/quotes",
            params={"codes": ",".join(clean_codes), "fresh": "true"},
        )
        if not isinstance(response, dict):
            return {}, {
                "provider": "tencent",
                "source": "tencent_qt_gtimg_l1",
                "fetch_endpoint": "https://qt.gtimg.cn/q",
                "fallback_used": False,
                "requested_symbols": len(clean_codes),
                "returned_symbols": 0,
                "status": "fetch_failed",
                "failure_reason": "a-stock-data 请求失败",
                "collector_version": "realtime-quote-collector-v1",
                "normalizer_version": "tencent-l1-normalizer-v1",
            }

        metadata = response.get("meta") or {}
        quotes = response.get("data") or {}
        if not isinstance(quotes, dict):
            quotes = {}
        if not metadata:
            metadata = {
                "provider": "tencent",
                "source": "tencent_qt_gtimg_l1",
                "fetch_endpoint": "https://qt.gtimg.cn/q",
                "fallback_used": False,
                "requested_symbols": len(clean_codes),
                "returned_symbols": 0,
                "status": "fetch_failed",
                "failure_reason": "a-stock-data 未返回固定 Provider 血缘元数据",
                "collector_version": "realtime-quote-collector-v1",
                "normalizer_version": "tencent-l1-normalizer-v1",
            }
            quotes = {}
        return quotes, metadata

    async def fetch_fund_flow(self, code: str, days: int = 5) -> list | None:
        data = await self._request(
            "GET", f"/fund-flow/{code}", params={"days": days}
        )
        if data is None:
            return None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return items
            payload = data.get("data")
            if isinstance(payload, list):
                return payload
            return [data]
        return None

    async def fetch_kline(
        self, code: str, period: str = "1d", limit: int = 200
    ) -> list | None:
        data = await self._request(
            "GET",
            f"/kline/{code}",
            params={"period": period, "limit": limit},
        )
        if data is None:
            return None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items") or data.get("data")
        return None


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
