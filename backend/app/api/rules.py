from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.response import ok
from app.db import get_db


router = APIRouter()


@router.get("/trading-calendar")
async def list_trading_calendar(
    exchange: str | None = Query(None, pattern="^(SH|SZ)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    status: str | None = Query(None, pattern="^(confirmed|unresolved)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params = {"limit": page_size, "offset": (page - 1) * page_size}
    if exchange:
        filters.append("calendar.exchange = :exchange")
        params["exchange"] = exchange
    if date_from:
        filters.append("calendar.trading_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("calendar.trading_date <= :date_to")
        params["date_to"] = date_to
    if status:
        filters.append("calendar.status = :status")
        params["status"] = status
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(text(f"""
            SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE calendar.status = 'confirmed') AS confirmed,
                   COUNT(*) FILTER (WHERE calendar.status = 'unresolved') AS unresolved,
                   MIN(calendar.trading_date) AS coverage_from, MAX(calendar.trading_date) AS coverage_to
            FROM market.trading_calendar AS calendar WHERE {where_clause}
        """), params)
        summary = dict(summary_result.mappings().one())
        result = await db.execute(text(f"""
            SELECT calendar.exchange, calendar.trading_date, calendar.is_trading_day,
                   calendar.session_open_time, calendar.session_close_time, calendar.timezone,
                   calendar.source, calendar.source_reference, calendar.status, calendar.created_at
            FROM market.trading_calendar AS calendar WHERE {where_clause}
            ORDER BY calendar.trading_date DESC, calendar.exchange LIMIT :limit OFFSET :offset
        """), params)
        items = [dict(row) for row in result.mappings().all()]
    total = int(summary["total"] or 0)
    return ok({"items": items, "total": total, "page": page, "page_size": page_size,
               "has_more": (page - 1) * page_size + len(items) < total,
               "summary": {"confirmed": int(summary["confirmed"] or 0), "unresolved": int(summary["unresolved"] or 0), "coverage_from": summary["coverage_from"], "coverage_to": summary["coverage_to"]},
               "research_readiness": "not_granted", "tradable": False, "order_created": False,
               "source": "market.trading_calendar", "source_version": "trading-calendar-v1"})
