from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.certification import DataCertificationService
from app.data.kline_contract import KlineContract
from app.data.sohu_daily_importer import ImportResult, ProviderFetchResult


class CertifiedStoreWriter:
    """Write validated provider rows directly to the isolated certified store."""

    IMPORTER_VERSION = "sprint07-sohu-certified-store-v1"

    def __init__(self, certification: DataCertificationService | None = None) -> None:
        self.certification = certification or DataCertificationService()

    async def ingest(self, db: AsyncSession, fetched: ProviderFetchResult) -> ImportResult:
        rows = fetched.rows
        batch_id, quality = await self.certification.create_batch(
            db,
            rows,
            provider=fetched.provider,
            source=fetched.source,
            period=KlineContract.PERIOD,
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

        calendar_error = await self._calendar_error(db, rows)
        if calendar_error:
            await self._reject_batch(db, batch_id, calendar_error)
            return ImportResult(
                fetched.stock_code,
                batch_id,
                "rejected",
                len(rows),
                0,
                len(rows),
                calendar_error,
            )

        duplicate = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM market.certified_klines
                WHERE stock_code=:stock_code AND period='1d' AND adjustment='raw'
                  AND trading_date BETWEEN :start_date AND :end_date
                """
            ),
            {
                "stock_code": fetched.stock_code,
                "start_date": rows[0]["trading_date"],
                "end_date": rows[-1]["trading_date"],
            },
        )
        if int(duplicate.scalar() or 0):
            reason = "certified store natural-day collision; existing certified rows preserved"
            await self._reject_batch(db, batch_id, reason)
            return ImportResult(
                fetched.stock_code,
                batch_id,
                "rejected",
                len(rows),
                0,
                len(rows),
                reason,
            )

        values = [self._store_row(row, fetched, batch_id, quality.score) for row in rows]
        await db.execute(
            text(
                """
                INSERT INTO market.certified_klines
                (stock_code, exchange, period, trading_date, market_close_time, timezone,
                 open, high, low, close, volume, amount, turnover_rate, adjustment,
                 price_currency, volume_unit, amount_unit, provider, source, batch_id,
                 raw_hash, quality_status, quality_score, certification_status,
                 certification_time, importer_version, normalizer_version, schema_version,
                 research_readiness_status, review_reason)
                VALUES
                (:stock_code, :exchange, :period, :trading_date, :market_close_time, :timezone,
                 :open, :high, :low, :close, :volume, :amount, :turnover_rate, :adjustment,
                 :price_currency, :volume_unit, :amount_unit, :provider, :source, :batch_id,
                 :raw_hash, 'pass', :quality_score, 'certified', NOW(), :importer_version,
                 :normalizer_version, :schema_version, 'review_required', :review_reason)
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                UPDATE market.data_batches
                SET accepted_rows=total_rows, rejected_rows=0, status='certified',
                    reject_reason=NULL
                WHERE batch_id=:batch_id
                """
            ),
            {"batch_id": batch_id},
        )
        return ImportResult(fetched.stock_code, batch_id, "certified", len(rows), len(rows), 0)

    @staticmethod
    async def _calendar_error(db: AsyncSession, rows: list[dict[str, Any]]) -> str | None:
        exchange = rows[0]["exchange"]
        start_date = rows[0]["trading_date"]
        end_date = rows[-1]["trading_date"]
        result = await db.execute(
            text(
                """
                SELECT trading_date FROM market.trading_calendar
                WHERE exchange=:exchange AND trading_date BETWEEN :start_date AND :end_date
                  AND is_trading_day AND status='confirmed'
                ORDER BY trading_date
                """
            ),
            {"exchange": exchange, "start_date": start_date, "end_date": end_date},
        )
        expected = {row[0] for row in result.fetchall()}
        actual = {row["trading_date"] for row in rows}
        if not expected:
            return "official trading calendar is unavailable or unresolved"
        non_trading = sorted(actual - expected)
        missing = sorted(expected - actual)
        if non_trading:
            return f"provider contains non-trading dates: {','.join(map(str, non_trading))}"
        if missing:
            return f"provider is missing confirmed trading dates: {','.join(map(str, missing))}"
        return None

    @staticmethod
    async def _reject_batch(db: AsyncSession, batch_id: str, reason: str) -> None:
        await db.execute(
            text(
                """
                UPDATE market.data_batches
                SET accepted_rows=0, rejected_rows=total_rows,
                    status='rejected', reject_reason=:reason
                WHERE batch_id=:batch_id
                """
            ),
            {"batch_id": batch_id, "reason": reason},
        )

    @classmethod
    def _store_row(
        cls,
        row: dict[str, Any],
        fetched: ProviderFetchResult,
        batch_id: str,
        quality_score: float,
    ) -> dict[str, Any]:
        raw_hash = hashlib.sha256(
            json.dumps(row, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            **row,
            "provider": fetched.provider,
            "source": fetched.source,
            "batch_id": batch_id,
            "raw_hash": raw_hash,
            "quality_score": quality_score,
            "importer_version": cls.IMPORTER_VERSION,
            "review_reason": (
                "Sohu raw adjustment was cross-verified; corporate-action review is not automated."
            ),
        }
