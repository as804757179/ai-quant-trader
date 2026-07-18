from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.backtest.market_rules import AshareMarketRuleRegistry
from app.core.response import ok
from app.db import get_db


router = APIRouter()


def _list_rule_records(
    rule_types: set[str],
    *,
    exchange: str | None,
    board: str | None,
    security_status: str | None,
    date_from: date | None,
    date_to: date | None,
    rule_version: str | None,
    page: int,
    page_size: int,
):
    records = AshareMarketRuleRegistry().records()
    filtered = [
        record
        for record in records
        if record["rule_type"] in rule_types
        and (exchange is None or record["exchange"] == exchange)
        and (board is None or record["board"] == board)
        and (security_status is None or record["security_status"] == security_status)
        and (date_from is None or record["effective_to"] is None or record["effective_to"] >= date_from)
        and (date_to is None or record["effective_from"] <= date_to)
        and (rule_version is None or record["rule_version"] == rule_version)
    ]
    filtered.sort(key=lambda record: (record["effective_from"], record["exchange"], record["board"], record["rule_type"], record["rule_version"]), reverse=True)
    total = len(filtered)
    start = (page - 1) * page_size
    items = [
        {
            **record,
            "source_hash": None,
            "source_hash_status": "not_recorded",
            "parse_status": "not_recorded",
        }
        for record in filtered[start:start + page_size]
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + len(items) < total,
        "registry_version": AshareMarketRuleRegistry.VERSION,
        "research_readiness": "not_granted",
        "tradable": False,
        "order_created": False,
        "source": "app.backtest.market_rules",
    }


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


@router.get("/trading")
async def list_trading_rules(
    exchange: str | None = Query(None, pattern="^(SH|SZ)$"),
    board: str | None = Query(None, pattern="^(MAIN|GEM|STAR|\\*)$"),
    security_status: str | None = Query(None, pattern="^(NORMAL|ST)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    rule_version: str | None = Query(None, min_length=1, max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    return ok(_list_rule_records(
        {"buy_lot_size", "sell_lot_size", "odd_lot_sell_policy", "minimum_price_tick", "price_rounding_mode", "price_limit_formula_version", "t_plus_one", "price_limit"},
        exchange=exchange, board=board, security_status=security_status,
        date_from=date_from, date_to=date_to, rule_version=rule_version,
        page=page, page_size=page_size,
    ))
