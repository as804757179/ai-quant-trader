from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.response import ok
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.db import get_db


router = APIRouter()


@router.get("/certified-klines")
async def list_certified_klines(
    stock_code: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    period: str = Query("1d", min_length=1, max_length=10),
    adjustment: str = Query("raw", pattern="^(raw|qfq|hfq)$"),
    batch_id: str | None = Query(None, min_length=1, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    data = await CertifiedKlineRepository().list_lineage(
        stock_code=stock_code,
        date_from=date_from,
        date_to=date_to,
        period=period,
        adjustment=adjustment,
        batch_id=batch_id,
        page=page,
        page_size=page_size,
    )
    data.update(
        {
            "certification_scope": "certified_store_observation",
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.certified_klines",
            "source_version": "certified-kline-lineage-v1",
        }
    )
    return ok(data)


@router.get("/certification-batches")
async def list_certification_batches(
    provider: str | None = Query(None, min_length=1, max_length=64),
    period: str | None = Query(None, min_length=1, max_length=10),
    stock_code: str | None = Query(None, min_length=1, max_length=12),
    status: str | None = Query(None, min_length=1, max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if provider:
        filters.append("batch.provider = :provider")
        params["provider"] = provider.strip()
    if period:
        filters.append("batch.period = :period")
        params["period"] = period.strip()
    if stock_code:
        filters.append("batch.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if status:
        filters.append("batch.status = :status")
        params["status"] = status.strip()
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE batch.status = 'certified') AS certified,
                       COUNT(*) FILTER (WHERE batch.status = 'rejected') AS rejected,
                       COUNT(*) FILTER (WHERE batch.status IN ('failed', 'fetch_failed', 'validation_failed', 'write_failed')) AS failed,
                       MAX(batch.fetch_time) AS latest_fetch_time
                FROM market.data_batches AS batch
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT batch.batch_id, batch.stock_code, batch.provider, batch.source,
                       batch.period, batch.start_date, batch.end_date, batch.fetch_time,
                       batch.importer_version, batch.total_rows, batch.accepted_rows,
                       batch.rejected_rows, batch.quality_score, batch.status,
                       batch.reject_reason, batch.provider_priority, batch.fallback_used,
                       batch.fetch_endpoint, batch.raw_hash, batch.created_at
                FROM market.data_batches AS batch
                WHERE {where_clause}
                ORDER BY batch.fetch_time DESC, batch.batch_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items) < total,
            "summary": {
                "certified": int(summary["certified"] or 0),
                "rejected": int(summary["rejected"] or 0),
                "failed": int(summary["failed"] or 0),
                "latest_fetch_time": summary["latest_fetch_time"],
            },
            "certification_scope": "batch_observation",
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.data_batches",
            "source_version": "certification-batches-v1",
        }
    )
