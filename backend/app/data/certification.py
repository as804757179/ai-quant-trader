from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.quality_validator import KlineQualityValidator, QualityResult


CERTIFIED_FILTER = """
certification_status = 'certified'
AND quality_status = 'pass'
AND is_synthetic = FALSE
AND source NOT IN ('unknown', 'synthetic')
"""


class DataCertificationService:
    IMPORTER_VERSION = "data-certification-v1"

    def __init__(self, validator: KlineQualityValidator | None = None) -> None:
        self.validator = validator or KlineQualityValidator()

    def validate_batch(self, rows: list[dict[str, Any]], *, provider: str, source: str, is_synthetic: bool) -> QualityResult:
        return self.validator.validate_rows(rows, provider=provider, source=source, is_synthetic=is_synthetic)

    async def create_batch(
        self,
        db: AsyncSession,
        rows: list[dict[str, Any]],
        *,
        provider: str,
        source: str,
        period: str,
        is_synthetic: bool = False,
        fetch_time: datetime | None = None,
        importer_version: str | None = None,
        provider_priority: int | None = None,
        fallback_used: bool = False,
        fetch_endpoint: str | None = None,
        raw_hash: str | None = None,
        stock_code: str | None = None,
    ) -> tuple[str, QualityResult]:
        result = self.validate_batch(rows, provider=provider, source=source, is_synthetic=is_synthetic)
        batch_id = uuid.uuid4().hex
        dates = [self._date_of(row.get("time")) for row in rows if self._date_of(row.get("time"))]
        await db.execute(
            text("""
                INSERT INTO market.data_batches
                (batch_id, provider, source, period, start_date, end_date, fetch_time,
                 importer_version, total_rows, accepted_rows, rejected_rows, quality_score,
                 status, reject_reason, provider_priority, fallback_used, fetch_endpoint, raw_hash,
                 stock_code)
                VALUES (:batch_id, :provider, :source, :period, :start_date, :end_date, :fetch_time,
                        :version, :total, :accepted, :rejected, :score, :status, :reason,
                        :provider_priority, :fallback_used, :fetch_endpoint, :raw_hash, :stock_code)
            """),
            {
                "batch_id": batch_id, "provider": provider or "unknown", "source": source or "unknown",
                "period": period, "start_date": min(dates) if dates else None, "end_date": max(dates) if dates else None,
                "fetch_time": fetch_time or datetime.now(timezone.utc),
                "version": importer_version or self.IMPORTER_VERSION, "total": len(rows), "accepted": len(rows) if result.passed else 0,
                "rejected": 0 if result.passed else len(rows), "score": result.score,
                "status": "validated" if result.passed else "rejected", "reason": "; ".join(result.reasons) or None,
                "provider_priority": provider_priority, "fallback_used": fallback_used,
                "fetch_endpoint": fetch_endpoint, "raw_hash": raw_hash,
                "stock_code": stock_code,
            },
        )
        return batch_id, result

    async def record_provenance(
        self, db: AsyncSession, rows: list[dict[str, Any]], *, batch_id: str, provider: str, source: str,
        quality: QualityResult, is_synthetic: bool, fetch_time: datetime | None = None,
        importer_version: str | None = None,
    ) -> None:
        status = "pass" if quality.passed else "rejected"
        certification = "uncertified"
        for row in rows:
            ts = row["time"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            raw_hash = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
            await db.execute(text("""
                INSERT INTO market.kline_provenance
                (time, stock_code, period, provider, source, fetch_time, batch_id,
                 quality_status, quality_score, is_synthetic, raw_hash, importer_version,
                 certification_status, reject_reason, updated_at)
                VALUES (:time, :stock_code, :period, :provider, :source, :fetch_time, :batch_id,
                        :quality_status, :quality_score, :is_synthetic, :raw_hash, :version,
                        :certification_status, :reason, NOW())
                ON CONFLICT (time, stock_code, period) DO UPDATE SET
                    provider = EXCLUDED.provider, source = EXCLUDED.source, fetch_time = EXCLUDED.fetch_time,
                    batch_id = EXCLUDED.batch_id, quality_status = EXCLUDED.quality_status,
                    quality_score = EXCLUDED.quality_score, is_synthetic = EXCLUDED.is_synthetic,
                    raw_hash = EXCLUDED.raw_hash, importer_version = EXCLUDED.importer_version,
                    certification_status = EXCLUDED.certification_status, reject_reason = EXCLUDED.reject_reason,
                    updated_at = NOW()
            """), {
                "time": ts, "stock_code": row["stock_code"], "period": row["period"],
                "provider": provider or "unknown", "source": source or "unknown", "batch_id": batch_id,
                "quality_status": status, "quality_score": quality.score, "is_synthetic": is_synthetic,
                "raw_hash": raw_hash, "version": importer_version or self.IMPORTER_VERSION,
                "certification_status": certification,
                "reason": "; ".join(quality.reasons) or None,
                "fetch_time": fetch_time or datetime.now(timezone.utc),
            })

    async def certify_kline_batch(self, db: AsyncSession, batch_id: str, *, threshold: float = 100.0) -> None:
        result = await db.execute(text("""
            SELECT provider, source, quality_status, quality_score, is_synthetic
            FROM market.kline_provenance WHERE batch_id = :batch_id
        """), {"batch_id": batch_id})
        rows = result.mappings().all()
        if not rows or any(
            r["provider"] == "unknown" or r["source"] in ("unknown", "synthetic")
            or r["quality_status"] != "pass" or r["is_synthetic"] or float(r["quality_score"] or 0) < threshold
            for r in rows
        ):
            raise ValueError("batch does not satisfy certification requirements")
        await db.execute(text("""
            UPDATE market.kline_provenance SET certification_status = 'certified',
                certification_time = NOW(), updated_at = NOW()
            WHERE batch_id = :batch_id
        """), {"batch_id": batch_id})
        await db.execute(text("UPDATE market.data_batches SET status = 'certified' WHERE batch_id = :batch_id"), {"batch_id": batch_id})

    async def assert_certified_dataset(self, db: AsyncSession, codes: list[str], start_date: Any, end_date: Any) -> None:
        result = await db.execute(text(f"""
            SELECT COUNT(*) FROM market.kline_provenance
            WHERE stock_code = ANY(:codes) AND period = '1d' AND time::date BETWEEN :start_date AND :end_date
              AND {CERTIFIED_FILTER}
        """), {"codes": codes, "start_date": start_date, "end_date": end_date})
        if int(result.scalar() or 0) == 0:
            raise ValueError("当前标的/时间区间无已认证历史数据，禁止真实回测。")

    @staticmethod
    def _date_of(value: Any):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        return None
