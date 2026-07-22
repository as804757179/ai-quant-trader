from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx


TUSHARE_PROVIDER = "tushare"
TUSHARE_SOURCE = "tushare.pro/daily"
TUSHARE_DATASET_VERSION = "daily-api-v1"
TUSHARE_TERMS_URL = "https://tushare.pro/document/1?doc_id=405"
TUSHARE_HTTP_ENDPOINT = "http://api.tushare.pro"
FREE_OBSERVATION_MODE = "free_observation"
FREE_OBSERVATION_UNIVERSE_SCOPE = "provider_response_rows_for_trade_date"


class FreeObservationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FreeObservationDailyBatch:
    provider: str
    source: str
    dataset_version: str
    terms_url: str
    data_mode: str
    data_qualification: str
    formal_use: bool
    trade_date: date
    fetched_at: datetime
    raw_payload_hash: str
    batch_hash: str
    rows: tuple[dict[str, Any], ...]
    available_at: None = None
    available_at_status: str = "unverified"
    lineage_status: str = "unverified"
    external_request_count: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source": self.source,
            "dataset_version": self.dataset_version,
            "terms_url": self.terms_url,
            "data_mode": self.data_mode,
            "data_qualification": self.data_qualification,
            "formal_use": self.formal_use,
            "trade_date": self.trade_date.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "raw_payload_hash": self.raw_payload_hash,
            "batch_hash": self.batch_hash,
            "rows": list(self.rows),
            "available_at": self.available_at,
            "available_at_status": self.available_at_status,
            "lineage_status": self.lineage_status,
            "external_request_count": self.external_request_count,
            "universe_manifest": {
                "scope": FREE_OBSERVATION_UNIVERSE_SCOPE,
                "coverage_status": "unverified",
                "returned_row_count": len(self.rows),
                "stock_code_hash": hashlib.sha256(
                    json.dumps(sorted(str(row["ts_code"]) for row in self.rows), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "not_proven": ["all_a_share_coverage", "listing_status", "tradability", "calendar_completeness"],
            },
            "blocked_from": ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"],
        }


class TushareFreeObservationClient:
    """Fetch raw local-observation batches without granting certification or execution use."""

    def __init__(
        self,
        *,
        token: str,
        client: httpx.Client | None = None,
        endpoint: str = TUSHARE_HTTP_ENDPOINT,
    ) -> None:
        if not token.strip():
            raise FreeObservationError(
                "FREE_OBSERVATION_TOKEN_REQUIRED",
                "免费观测抓取需要通过官方渠道取得的 Tushare Token",
            )
        self.token = token.strip()
        self.client = client or httpx.Client(timeout=30.0, trust_env=False)
        self.endpoint = endpoint
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def fetch_daily(self, *, trade_date: date) -> FreeObservationDailyBatch:
        request = {
            "api_name": "daily",
            "token": self.token,
            "params": {"trade_date": trade_date.strftime("%Y%m%d")},
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        }
        try:
            response = self.client.post(self.endpoint, json=request)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FreeObservationError("FREE_OBSERVATION_PROVIDER_UNAVAILABLE", "免费观测 Provider 不可用") from exc

        raw = response.content
        raw_payload_hash = hashlib.sha256(raw).hexdigest()
        try:
            payload = response.json()
        except ValueError as exc:
            raise FreeObservationError("FREE_OBSERVATION_RESPONSE_INVALID", "免费观测 Provider 返回非 JSON 响应") from exc
        code = payload.get("code") if isinstance(payload, dict) else None
        if code not in (0, None):
            raise FreeObservationError(
                "FREE_OBSERVATION_PROVIDER_REJECTED",
                f"免费观测 Provider 拒绝请求：{payload.get('msg') or code}",
            )
        data = payload.get("data") if isinstance(payload, dict) else None
        fields = data.get("fields") if isinstance(data, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(fields, list) or not isinstance(items, list):
            raise FreeObservationError("FREE_OBSERVATION_RESPONSE_INVALID", "免费观测日线响应缺少 fields 或 items")
        rows = tuple(self._row(fields, item) for item in items)
        if not rows:
            raise FreeObservationError("FREE_OBSERVATION_DATA_UNAVAILABLE", "免费观测日线响应为空")
        self._validate_daily_rows(rows, trade_date)
        batch_hash = self._hash(
            {
                "provider": TUSHARE_PROVIDER,
                "source": TUSHARE_SOURCE,
                "dataset_version": TUSHARE_DATASET_VERSION,
                "trade_date": trade_date.isoformat(),
                "raw_payload_hash": raw_payload_hash,
                "rows": rows,
            }
        )
        return FreeObservationDailyBatch(
            provider=TUSHARE_PROVIDER,
            source=TUSHARE_SOURCE,
            dataset_version=TUSHARE_DATASET_VERSION,
            terms_url=TUSHARE_TERMS_URL,
            data_mode=FREE_OBSERVATION_MODE,
            data_qualification="unverified",
            formal_use=False,
            trade_date=trade_date,
            fetched_at=datetime.now(timezone.utc),
            raw_payload_hash=raw_payload_hash,
            batch_hash=batch_hash,
            rows=rows,
        )

    @classmethod
    def _row(cls, fields: list[Any], item: Any) -> dict[str, Any]:
        if not isinstance(item, list) or len(item) != len(fields):
            raise FreeObservationError("FREE_OBSERVATION_RESPONSE_INVALID", "免费观测日线行与字段定义不一致")
        payload = {str(field): value for field, value in zip(fields, item)}
        required = ("ts_code", "trade_date", "open", "high", "low", "close")
        if any(payload.get(field) in (None, "") for field in required):
            raise FreeObservationError("FREE_OBSERVATION_RESPONSE_INVALID", "免费观测日线行缺少必要 OHLC 字段")
        payload["row_hash"] = cls._hash(payload)
        return payload

    @staticmethod
    def _validate_daily_rows(rows: tuple[dict[str, Any], ...], trade_date: date) -> None:
        expected_trade_date = trade_date.strftime("%Y%m%d")
        stock_codes: set[str] = set()
        for row in rows:
            if row["trade_date"] != expected_trade_date:
                raise FreeObservationError(
                    "FREE_OBSERVATION_TRADE_DATE_MISMATCH",
                    "免费观测日线行交易日期与请求日期不一致",
                )
            stock_code = str(row["ts_code"])
            if stock_code in stock_codes:
                raise FreeObservationError("FREE_OBSERVATION_ROW_DUPLICATE", "免费观测日线存在重复股票行")
            stock_codes.add(stock_code)

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
