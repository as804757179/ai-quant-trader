"""Realtime quote persistence with provider provenance."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from services.data_client import validate_quote


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_provider_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
    except ValueError:
        return None


def _row_hash(quote: dict[str, Any]) -> str:
    payload = json.dumps(quote, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _number(quote: dict[str, Any], field: str) -> float | None:
    value = quote.get(field)
    return float(value) if value not in (None, "") else None


class QuoteStore:
    """Write observed L1 quotes and their immutable batch provenance."""

    def __init__(self) -> None:
        database_url = os.getenv("DATABASE_URL", "")
        self._engine = create_async_engine(database_url, poolclass=NullPool)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def persist_batch(
        self,
        requested_codes: list[str],
        quotes: dict[str, dict[str, Any]],
        metadata: dict[str, Any],
        started_at: datetime,
    ) -> dict[str, Any]:
        """Persist one fixed-provider collection attempt without any fallback."""
        requested = list(dict.fromkeys(str(code) for code in requested_codes))
        batch_id = uuid4()
        received_at = datetime.now(timezone.utc)
        provider = str(metadata.get("provider") or "unknown")
        source = str(metadata.get("source") or "unknown")
        endpoint = str(metadata.get("fetch_endpoint") or "")
        fetched_at = _parse_iso(metadata.get("fetched_at"))
        collector_version = str(metadata.get("collector_version") or "unknown")
        normalizer_version = str(metadata.get("normalizer_version") or "unknown")
        fallback_used = bool(metadata.get("fallback_used"))
        supplied_status = str(metadata.get("status") or "fetch_failed")
        failure_reason = metadata.get("failure_reason")

        safe_source = (
            provider not in {"", "unknown", "synthetic"}
            and source not in {"", "unknown", "synthetic"}
            and bool(endpoint)
            and not fallback_used
        )
        if not safe_source:
            supplied_status = "validation_failed"
            quotes = {}
            failure_reason = "固定 Provider 血缘元数据无效或检测到 fallback"

        valid_rows: list[tuple[str, dict[str, Any]]] = []
        invalid_codes: list[str] = []
        for code, quote in quotes.items():
            normalized_code = str(code)
            if normalized_code not in requested or not validate_quote(quote):
                invalid_codes.append(normalized_code)
                continue
            valid_rows.append((normalized_code, quote))

        if supplied_status == "fetch_failed":
            valid_rows = []
        elif not valid_rows and requested:
            supplied_status = "validation_failed"
            failure_reason = failure_reason or "没有通过基础质量校验的行情记录"

        expected_rejected = max(0, len(requested) - len(valid_rows))
        if supplied_status not in {"fetch_failed", "validation_failed"}:
            supplied_status = "partial" if expected_rejected else "success"
        initial_status = (
            supplied_status
            if supplied_status in {"fetch_failed", "validation_failed"}
            else "running"
        )

        batch = {
            "batch_id": batch_id,
            "provider": provider if safe_source else "tencent",
            "source": source if safe_source else "tencent_qt_gtimg_l1",
            "fetch_endpoint": endpoint or "https://qt.gtimg.cn/q",
            "requested_symbols": len(requested),
            "returned_symbols": len(quotes),
            "accepted_symbols": 0,
            "rejected_symbols": len(requested),
            "status": initial_status,
            "failure_reason": failure_reason,
            "raw_response_hash": metadata.get("raw_response_hash"),
            "collector_version": collector_version,
            "normalizer_version": normalizer_version,
            "started_at": started_at,
            "fetched_at": fetched_at,
            "received_at": received_at,
        }
        await self._insert_batch(batch)

        if initial_status in {"fetch_failed", "validation_failed"}:
            return {
                "batch_id": str(batch_id),
                "status": initial_status,
                "accepted_codes": [],
                "rejected_symbols": len(requested),
                "failure_reason": failure_reason,
            }

        try:
            inserted_codes = await self._insert_quotes_and_provenance(
                batch_id=batch_id,
                rows=valid_rows,
                metadata=metadata,
                received_at=received_at,
                provider=provider,
                source=source,
                endpoint=endpoint,
                fetched_at=fetched_at,
                collector_version=collector_version,
                normalizer_version=normalizer_version,
            )
        except Exception as exc:
            failure_reason = f"行情与血缘写入失败: {exc}"
            await self._finalize_batch(
                batch_id, "write_failed", 0, len(requested), failure_reason
            )
            return {
                "batch_id": str(batch_id),
                "status": "write_failed",
                "accepted_codes": [],
                "rejected_symbols": len(requested),
                "failure_reason": failure_reason,
            }

        rejected = max(0, len(requested) - len(inserted_codes))
        status = "success" if not rejected else "partial"
        if invalid_codes:
            failure_reason = failure_reason or "存在未通过基础行情质量校验的记录"
        await self._finalize_batch(batch_id, status, len(inserted_codes), rejected, failure_reason)
        return {
            "batch_id": str(batch_id),
            "status": status,
            "accepted_codes": inserted_codes,
            "rejected_symbols": rejected,
            "failure_reason": failure_reason,
        }

    async def _insert_batch(self, batch: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO market.quote_batches (
                        batch_id, provider, source, fetch_endpoint,
                        requested_symbols, returned_symbols, accepted_symbols,
                        rejected_symbols, status, failure_reason, raw_response_hash,
                        collector_version, normalizer_version, started_at, fetched_at,
                        received_at
                    ) VALUES (
                        :batch_id, :provider, :source, :fetch_endpoint,
                        :requested_symbols, :returned_symbols, :accepted_symbols,
                        :rejected_symbols, :status, :failure_reason, :raw_response_hash,
                        :collector_version, :normalizer_version, :started_at, :fetched_at,
                        :received_at
                    )
                    """
                ),
                batch,
            )
            await session.commit()

    async def _insert_quotes_and_provenance(
        self,
        *,
        batch_id: UUID,
        rows: list[tuple[str, dict[str, Any]]],
        metadata: dict[str, Any],
        received_at: datetime,
        provider: str,
        source: str,
        endpoint: str,
        fetched_at: datetime | None,
        collector_version: str,
        normalizer_version: str,
    ) -> list[str]:
        raw_hashes = metadata.get("quote_raw_hashes") or {}
        inserted_codes: list[str] = []
        async with self._session_factory() as session:
            for stock_code, quote in rows:
                quote_result = await session.execute(
                    text(
                        """
                        INSERT INTO market.quotes (
                            time, stock_code, price, open, high, low, prev_close,
                            change, change_pct, volume, amount,
                            bid1_price, bid1_vol, bid2_price, bid2_vol, bid3_price, bid3_vol,
                            ask1_price, ask1_vol, ask2_price, ask2_vol, ask3_price, ask3_vol
                        ) VALUES (
                            :quote_time, :stock_code, :price, :open, :high, :low, :prev_close,
                            :change, :change_pct, :volume, :amount,
                            :bid1_price, :bid1_vol, :bid2_price, :bid2_vol, :bid3_price, :bid3_vol,
                            :ask1_price, :ask1_vol, :ask2_price, :ask2_vol, :ask3_price, :ask3_vol
                        ) ON CONFLICT (time, stock_code) DO NOTHING
                        """
                    ),
                    {
                        "quote_time": received_at,
                        "stock_code": stock_code,
                        "price": _number(quote, "price"),
                        "open": _number(quote, "open"),
                        "high": _number(quote, "high"),
                        "low": _number(quote, "low"),
                        "prev_close": _number(quote, "prev_close"),
                        "change": _number(quote, "change"),
                        "change_pct": _number(quote, "change_pct"),
                        "volume": int(quote.get("volume_shares") or quote.get("volume") or 0),
                        "amount": _number(quote, "amount"),
                        "bid1_price": _number(quote, "bid1_price"),
                        "bid1_vol": quote.get("bid1_vol"),
                        "bid2_price": _number(quote, "bid2_price"),
                        "bid2_vol": quote.get("bid2_vol"),
                        "bid3_price": _number(quote, "bid3_price"),
                        "bid3_vol": quote.get("bid3_vol"),
                        "ask1_price": _number(quote, "ask1_price"),
                        "ask1_vol": quote.get("ask1_vol"),
                        "ask2_price": _number(quote, "ask2_price"),
                        "ask2_vol": quote.get("ask2_vol"),
                        "ask3_price": _number(quote, "ask3_price"),
                        "ask3_vol": quote.get("ask3_vol"),
                    },
                )
                if quote_result.rowcount != 1:
                    continue
                await session.execute(
                    text(
                        """
                        INSERT INTO market.quote_provenance (
                            quote_time, stock_code, batch_id, provider, source, fetch_endpoint,
                            provider_time, fetched_at, received_at, raw_hash, quality_status,
                            reject_reason, fallback_used, collector_version, normalizer_version
                        ) VALUES (
                            :quote_time, :stock_code, :batch_id, :provider, :source, :fetch_endpoint,
                            :provider_time, :fetched_at, :received_at, :raw_hash, 'pass',
                            NULL, FALSE, :collector_version, :normalizer_version
                        )
                        """
                    ),
                    {
                        "quote_time": received_at,
                        "stock_code": stock_code,
                        "batch_id": batch_id,
                        "provider": provider,
                        "source": source,
                        "fetch_endpoint": endpoint,
                        "provider_time": _parse_provider_time(quote.get("trade_time")),
                        "fetched_at": fetched_at,
                        "received_at": received_at,
                        "raw_hash": str(raw_hashes.get(stock_code) or _row_hash(quote)),
                        "collector_version": collector_version,
                        "normalizer_version": normalizer_version,
                    },
                )
                inserted_codes.append(stock_code)
            await session.commit()
        return inserted_codes

    async def _finalize_batch(
        self,
        batch_id: UUID,
        status: str,
        accepted_symbols: int,
        rejected_symbols: int,
        failure_reason: str | None,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE market.quote_batches
                    SET status = :status,
                        accepted_symbols = :accepted_symbols,
                        rejected_symbols = :rejected_symbols,
                        failure_reason = :failure_reason
                    WHERE batch_id = :batch_id
                    """
                ),
                {
                    "batch_id": batch_id,
                    "status": status,
                    "accepted_symbols": accepted_symbols,
                    "rejected_symbols": rejected_symbols,
                    "failure_reason": failure_reason,
                },
            )
            await session.commit()
