from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from app.data.kline_contract import KlineContract
from app.data.research_readiness import ResearchReadinessService
from app.data.research_profiles import ResearchDataRequirementProfile
from app.db import get_db


class CertifiedKlineRepository:
    """Read-only access to the isolated certified K-line store."""

    @staticmethod
    def _validate_adjustment(adjustment: str) -> str:
        if adjustment not in {"raw", "qfq", "hfq"}:
            raise ValueError("adjustment must be explicitly raw, qfq, or hfq")
        return adjustment

    async def get_bars(
        self,
        stock_codes: list[str],
        *,
        period: str,
        adjustment: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        adjustment = self._validate_adjustment(adjustment)
        symbols = [KlineContract.canonical_symbol(code)[0] for code in stock_codes]
        if not symbols:
            raise ValueError("stock_codes cannot be empty")
        filters = [
            "stock_code = ANY(:codes)",
            "period = :period",
            "adjustment = :adjustment",
            "quality_status = 'pass'",
            "certification_status = 'certified'",
        ]
        params: dict[str, Any] = {
            "codes": symbols,
            "period": period,
            "adjustment": adjustment,
        }
        if start_date is not None:
            filters.append("trading_date >= :start_date")
            params["start_date"] = start_date
        if end_date is not None:
            filters.append("trading_date <= :end_date")
            params["end_date"] = end_date
        async with get_db() as db:
            result = await db.execute(
                text(
                    "SELECT * FROM market.certified_klines WHERE "
                    + " AND ".join(filters)
                    + " ORDER BY stock_code, trading_date"
                ),
                params,
            )
            return [dict(row) for row in result.mappings().all()]

    async def list_lineage(
        self,
        *,
        stock_code: str | None,
        date_from: date | None,
        date_to: date | None,
        period: str,
        adjustment: str,
        batch_id: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        adjustment = self._validate_adjustment(adjustment)
        filters = [
            "period = :period",
            "adjustment = :adjustment",
            "quality_status = 'pass'",
            "certification_status = 'certified'",
        ]
        params: dict[str, Any] = {
            "period": period,
            "adjustment": adjustment,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if stock_code:
            filters.append("stock_code = :stock_code")
            params["stock_code"] = KlineContract.canonical_symbol(stock_code)[0]
        if date_from is not None:
            filters.append("trading_date >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            filters.append("trading_date <= :date_to")
            params["date_to"] = date_to
        if batch_id:
            filters.append("batch_id = :batch_id")
            params["batch_id"] = batch_id
        where_clause = " AND ".join(filters)
        async with get_db() as db:
            summary_result = await db.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS total,
                           COUNT(DISTINCT stock_code) AS stock_count,
                           MIN(trading_date) AS date_from,
                           MAX(trading_date) AS date_to,
                           ARRAY_AGG(DISTINCT provider ORDER BY provider) AS providers
                    FROM market.certified_klines
                    WHERE {where_clause}
                    """
                ),
                params,
            )
            summary = dict(summary_result.mappings().one())
            result = await db.execute(
                text(
                    f"""
                    SELECT stock_code, trading_date, period, adjustment,
                           provider, source, batch_id, raw_hash, quality_status,
                           certification_status, certification_time,
                           importer_version, normalizer_version, schema_version,
                           research_readiness_status, review_reason
                    FROM market.certified_klines
                    WHERE {where_clause}
                    ORDER BY trading_date DESC, stock_code, batch_id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            items = [dict(row) for row in result.mappings().all()]
        total = int(summary["total"] or 0)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items) < total,
            "summary": {
                "stock_count": int(summary["stock_count"] or 0),
                "date_from": summary["date_from"],
                "date_to": summary["date_to"],
                "providers": summary["providers"] or [],
            },
        }

    async def get_bars_for_profile(
        self,
        stock_codes: list[str],
        *,
        period: str,
        adjustment: str,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        profile = ResearchDataRequirementProfile.get(requirement_profile)
        profile.validate_declaration(
            research_use_scope=research_use_scope, required_fields=required_fields
        )
        if profile.name not in {"OHLCV_RETURN_V1", "OHLCV_TOTAL_RETURN_GROSS_V1"}:
            raise ValueError("field-limited bar reader only supports OHLCV profiles")
        adjustment = self._validate_adjustment(adjustment)
        symbols = [KlineContract.canonical_symbol(code)[0] for code in stock_codes]
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT stock_code, period, trading_date, open, high, low, close,
                           volume, adjustment, provider, source, batch_id, raw_hash,
                           quality_status, certification_status
                    FROM market.certified_klines
                    WHERE stock_code=ANY(:codes) AND period=:period
                      AND adjustment=:adjustment
                      AND trading_date BETWEEN :start_date AND :end_date
                      AND quality_status='pass' AND certification_status='certified'
                    ORDER BY stock_code, trading_date
                    """
                ),
                {
                    "codes": symbols,
                    "period": period,
                    "adjustment": adjustment,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            return [dict(row) for row in result.mappings().all()]

    async def get_latest_bar(
        self,
        stock_code: str,
        *,
        period: str,
        adjustment: str,
    ) -> dict[str, Any]:
        adjustment = self._validate_adjustment(adjustment)
        symbol = KlineContract.canonical_symbol(stock_code)[0]
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT * FROM market.certified_klines
                    WHERE stock_code=:code AND period=:period AND adjustment=:adjustment
                      AND quality_status='pass' AND certification_status='certified'
                    ORDER BY trading_date DESC LIMIT 1
                    """
                ),
                {"code": symbol, "period": period, "adjustment": adjustment},
            )
            row = result.mappings().first()
        if not row:
            raise ValueError("no certified K-line is available")
        return dict(row)

    async def get_available_range(
        self,
        stock_code: str,
        *,
        period: str,
        adjustment: str,
    ) -> dict[str, Any]:
        adjustment = self._validate_adjustment(adjustment)
        symbol = KlineContract.canonical_symbol(stock_code)[0]
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT MIN(trading_date) AS start_date, MAX(trading_date) AS end_date,
                           COUNT(*) AS row_count
                    FROM market.certified_klines
                    WHERE stock_code=:code AND period=:period AND adjustment=:adjustment
                      AND quality_status='pass' AND certification_status='certified'
                    """
                ),
                {"code": symbol, "period": period, "adjustment": adjustment},
            )
            row = dict(result.mappings().one())
        if not row["row_count"]:
            raise ValueError("no certified K-line range is available")
        return row

    async def get_certified_universe(
        self,
        *,
        period: str,
        adjustment: str,
    ) -> list[str]:
        adjustment = self._validate_adjustment(adjustment)
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT DISTINCT stock_code FROM market.certified_klines
                    WHERE period=:period AND adjustment=:adjustment
                      AND quality_status='pass' AND certification_status='certified'
                    ORDER BY stock_code
                    """
                ),
                {"period": period, "adjustment": adjustment},
            )
            return [row[0] for row in result.fetchall()]

    async def assert_dataset_ready(
        self,
        stock_codes: list[str],
        *,
        period: str,
        adjustment: str,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
        start_date: date,
        end_date: date,
    ) -> None:
        adjustment = self._validate_adjustment(adjustment)
        symbols = [KlineContract.canonical_symbol(code)[0] for code in stock_codes]
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT DISTINCT stock_code FROM market.certified_klines
                    WHERE stock_code=ANY(:codes) AND period=:period
                      AND adjustment=:adjustment
                      AND trading_date BETWEEN :start_date AND :end_date
                      AND quality_status='pass' AND certification_status='certified'
                    """
                ),
                {
                    "codes": symbols,
                    "period": period,
                    "adjustment": adjustment,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            present = {row[0] for row in result.fetchall()}
        if any(symbol not in present for symbol in symbols):
            raise ValueError("certified dataset is incomplete")
        await ResearchReadinessService().assert_ready(
            symbols,
            period=period,
            adjustment=adjustment,
            research_use_scope=research_use_scope,
            requirement_profile=requirement_profile,
            required_fields=required_fields,
            start_date=start_date,
            end_date=end_date,
        )
