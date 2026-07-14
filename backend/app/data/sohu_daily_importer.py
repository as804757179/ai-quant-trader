from __future__ import annotations

import asyncio
import hashlib
import json
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.certification import DataCertificationService
from app.data.kline_contract import KlineContract
from app.db import get_db

CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ProviderFetchResult:
    stock_code: str
    provider: str
    source: str
    provider_priority: int
    fallback_used: bool
    fetch_url_or_endpoint: str
    fetch_time: datetime
    raw_hash: str
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ImportResult:
    stock_code: str
    batch_id: str
    status: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    reject_reason: str | None = None


class SohuDailyKlineImporter:
    PROVIDER = "sohu"
    SOURCE = "sohu_daily_kline"
    IMPORTER_VERSION = "sprint06-sohu-daily-v1"
    ENDPOINT = "https://q.stock.sohu.com/hisHq"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        certification: DataCertificationService | None = None,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.client = client or httpx.AsyncClient(
            timeout=30.0,
            trust_env=False,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://q.stock.sohu.com/"},
        )
        self._owns_client = client is None
        self.certification = certification or DataCertificationService()
        self.max_attempts = max_attempts
        self._last_request = 0.0

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def fetch(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> ProviderFetchResult:
        code = self._normalize_symbol(stock_code)
        provider_code = code.split(".", 1)[0]
        params = {
            "code": f"cn_{provider_code}",
            "start": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
            "stat": "1",
            "order": "D",
            "period": "d",
            "rt": "json",
        }
        response = None
        for attempt in range(self.max_attempts):
            elapsed = time_module.monotonic() - self._last_request
            if elapsed < 2.0:
                await asyncio.sleep(2.0 - elapsed)
            try:
                response = await self.client.get(self.ENDPOINT, params=params)
                self._last_request = time_module.monotonic()
                response.raise_for_status()
                break
            except (httpx.HTTPError, httpx.TransportError):
                if attempt == self.max_attempts - 1:
                    raise
                await asyncio.sleep(2.0 * (attempt + 1))
        if response is None:
            raise ValueError("sohu request produced no response")
        payload = json.loads(response.content.decode("gb18030"))
        item = payload[0] if isinstance(payload, list) and payload else None
        raw_rows = item.get("hq") if isinstance(item, dict) else None
        if not raw_rows:
            raise ValueError("sohu returned no daily kline rows")
        rows = self.normalize_rows(code, raw_rows, start_date, end_date)
        if not rows:
            raise ValueError("sohu rows are empty after normalization")
        return ProviderFetchResult(
            stock_code=code,
            provider=self.PROVIDER,
            source=self.SOURCE,
            provider_priority=1,
            fallback_used=False,
            fetch_url_or_endpoint=str(response.request.url),
            fetch_time=datetime.now(timezone.utc),
            raw_hash=hashlib.sha256(response.content).hexdigest(),
            rows=rows,
        )

    @staticmethod
    def normalize_rows(
        code: str,
        raw_rows: list[list[str]],
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for fields in raw_rows:
            if len(fields) < 10:
                continue
            trade_date = date.fromisoformat(str(fields[0]))
            if trade_date < start_date or trade_date > end_date:
                continue
            rows.append(KlineContract.normalize_sohu_row(code, fields))
        rows.sort(key=lambda row: row["time"])
        return rows

    async def ingest(self, db: AsyncSession, fetched: ProviderFetchResult) -> ImportResult:
        rows = fetched.rows
        legacy_code = fetched.stock_code.split(".", 1)[0]
        legacy_rows = [{**row, "stock_code": legacy_code} for row in rows]
        batch_id, quality = await self.certification.create_batch(
            db,
            legacy_rows,
            provider=fetched.provider,
            source=fetched.source,
            period="1d",
            is_synthetic=False,
            fetch_time=fetched.fetch_time,
            importer_version=self.IMPORTER_VERSION,
            provider_priority=fetched.provider_priority,
            fallback_used=fetched.fallback_used,
            fetch_endpoint=fetched.fetch_url_or_endpoint,
            raw_hash=fetched.raw_hash,
            stock_code=fetched.stock_code,
        )
        if not quality.passed:
            return ImportResult(
                fetched.stock_code,
                batch_id,
                "rejected",
                len(rows),
                0,
                len(rows),
                "; ".join(quality.reasons),
            )

        collision = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM market.klines
                WHERE stock_code = :stock_code AND period = '1d'
                  AND time::date BETWEEN :start_date AND :end_date
                """
            ),
            {
                "stock_code": legacy_code,
                "start_date": rows[0]["time"].date(),
                "end_date": rows[-1]["time"].date(),
            },
        )
        collision_count = int(collision.scalar() or 0)
        if collision_count:
            reason = f"existing natural-day kline collision ({collision_count}); legacy data preserved"
            await db.execute(
                text(
                    """
                    UPDATE market.data_batches
                    SET accepted_rows = 0, rejected_rows = total_rows,
                        status = 'rejected', reject_reason = :reason
                    WHERE batch_id = :batch_id
                    """
                ),
                {"batch_id": batch_id, "reason": reason},
            )
            return ImportResult(
                fetched.stock_code,
                batch_id,
                "rejected",
                len(rows),
                0,
                len(rows),
                reason,
            )

        await db.execute(
            text(
                """
                INSERT INTO market.klines
                (time, stock_code, period, open, high, low, close, volume, amount, turnover_rate)
                VALUES
                (:time, :stock_code, :period, :open, :high, :low, :close,
                 :volume, :amount, :turnover_rate)
                """
            ),
            legacy_rows,
        )
        await self.certification.record_provenance(
            db,
            legacy_rows,
            batch_id=batch_id,
            provider=fetched.provider,
            source=fetched.source,
            quality=quality,
            is_synthetic=False,
            fetch_time=fetched.fetch_time,
            importer_version=self.IMPORTER_VERSION,
        )
        await self.certification.certify_kline_batch(db, batch_id)
        return ImportResult(
            fetched.stock_code,
            batch_id,
            "certified",
            len(rows),
            len(rows),
            0,
        )

    async def import_code(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> ImportResult:
        try:
            fetched = await self.fetch(stock_code, start_date, end_date)
        except Exception as exc:
            code = self._normalize_symbol(stock_code)
            async with get_db() as db:
                batch_id, _ = await self.certification.create_batch(
                    db,
                    [],
                    provider=self.PROVIDER,
                    source=self.SOURCE,
                    period="1d",
                    importer_version=self.IMPORTER_VERSION,
                    provider_priority=1,
                    fallback_used=False,
                    fetch_endpoint=self.ENDPOINT,
                    stock_code=code,
                )
                reason = f"provider fetch failed: {exc}"
                await db.execute(
                    text(
                        "UPDATE market.data_batches SET status='failed', reject_reason=:reason "
                        "WHERE batch_id=:batch_id"
                    ),
                    {"batch_id": batch_id, "reason": reason},
                )
            return ImportResult(code, batch_id, "failed", 0, 0, 0, reason)

        async with get_db() as db:
            return await self.ingest(db, fetched)

    @staticmethod
    def _normalize_symbol(stock_code: str) -> str:
        return KlineContract.canonical_symbol(stock_code)[0]
