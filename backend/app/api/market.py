from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.response import ok
from app.db import get_db


router = APIRouter()


@router.get("/industry-classifications")
async def list_industry_classifications(
    sector: str | None = Query(None, min_length=1, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """只读展示 legacy 行业当前快照，不提供 PIT 或历史研究资格。"""
    filters = ["stock.sector IS NOT NULL", "BTRIM(stock.sector) <> ''"]
    params = {"limit": page_size, "offset": (page - 1) * page_size}
    if sector:
        filters.append("stock.sector = :sector")
        params["sector"] = sector
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT stock.sector) AS total,
                       COUNT(*) AS stock_count,
                       MAX(stock.updated_at) AS latest_snapshot_updated_at
                FROM fundamental.stocks AS stock
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT stock.sector AS classification_name,
                       COUNT(*) AS stock_count,
                       MAX(stock.updated_at) AS snapshot_updated_at
                FROM fundamental.stocks AS stock
                WHERE {where_clause}
                GROUP BY stock.sector
                ORDER BY MAX(stock.updated_at) DESC NULLS LAST, stock.sector
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    for item in items:
        item.update(
            {
                "classification_kind": "industry",
                "data_semantics": "current_snapshot",
                "provider": "legacy_internal",
                "source": "fundamental.stocks.sector",
                "dataset_version": None,
                "fetched_at": None,
                "effective_from": None,
                "effective_to": None,
                "quality_status": "unverified",
                "pit_capable": False,
                "historical_research_usable": False,
                "backtest_usable": False,
            }
        )
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": params["offset"] + len(items) < total,
            "summary": {
                "stock_count": int(summary["stock_count"] or 0),
                "latest_snapshot_updated_at": summary["latest_snapshot_updated_at"],
            },
            "data_semantics": "current_snapshot",
            "observed_only": False,
            "pit_capable": False,
            "historical_research_usable": False,
            "backtest_usable": False,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "fundamental.stocks.sector",
            "source_version": "market-industry-current-snapshot-v1",
        }
    )


@router.get("/concept-boards")
async def list_concept_boards(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """概念板块正式来源未接入时只返回不可用事实，不执行回退或推断。"""
    return ok(
        {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "has_more": False,
            "availability_status": "unavailable",
            "data_semantics": "unavailable",
            "formal_model": "market.concept_board_memberships",
            "provider": None,
            "source": None,
            "dataset_version": None,
            "fetched_at": None,
            "effective_from": None,
            "effective_to": None,
            "pit_capable": False,
            "observed_only": False,
            "historical_research_usable": False,
            "backtest_usable": False,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source_version": "market-concept-board-unavailable-v1",
        }
    )


@router.get("/exchange-boards")
async def list_exchange_boards(
    board: str | None = Query(None, min_length=1, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """只读展示 legacy 交易所板块当前快照，不提供 PIT 或历史研究资格。"""
    filters = ["stock.board IS NOT NULL", "BTRIM(stock.board) <> ''"]
    params = {"limit": page_size, "offset": (page - 1) * page_size}
    if board:
        filters.append("stock.board = :board")
        params["board"] = board
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT stock.board) AS total,
                       COUNT(*) AS stock_count,
                       MAX(stock.updated_at) AS latest_snapshot_updated_at
                FROM fundamental.stocks AS stock
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT stock.board AS classification_name,
                       COUNT(*) AS stock_count,
                       MAX(stock.updated_at) AS snapshot_updated_at
                FROM fundamental.stocks AS stock
                WHERE {where_clause}
                GROUP BY stock.board
                ORDER BY MAX(stock.updated_at) DESC NULLS LAST, stock.board
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    for item in items:
        item.update(
            {
                "classification_kind": "exchange_board",
                "data_semantics": "current_snapshot",
                "provider": "legacy_internal",
                "source": "fundamental.stocks.board",
                "dataset_version": None,
                "fetched_at": None,
                "effective_from": None,
                "effective_to": None,
                "quality_status": "unverified",
                "pit_capable": False,
                "historical_research_usable": False,
                "backtest_usable": False,
            }
        )
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": params["offset"] + len(items) < total,
            "summary": {
                "stock_count": int(summary["stock_count"] or 0),
                "latest_snapshot_updated_at": summary["latest_snapshot_updated_at"],
            },
            "data_semantics": "current_snapshot",
            "observed_only": False,
            "pit_capable": False,
            "historical_research_usable": False,
            "backtest_usable": False,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "fundamental.stocks.board",
            "source_version": "market-exchange-board-current-snapshot-v1",
        }
    )


@router.get("/security-status")
async def list_security_status(
    stock_code: str | None = Query(None, min_length=1, max_length=12),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    status: str | None = Query(None, min_length=1, max_length=24),
    evidence_version: str | None = Query(None, min_length=1, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params = {"limit": page_size, "offset": (page - 1) * page_size}
    if stock_code:
        filters.append("review.stock_code = :stock_code")
        params["stock_code"] = stock_code
    if date_from:
        filters.append("review.effective_to >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("review.effective_from <= :date_to")
        params["date_to"] = date_to
    if status:
        filters.append("review.status = :status")
        params["status"] = status
    if evidence_version:
        filters.append("review.evidence_version = :evidence_version")
        params["evidence_version"] = evidence_version
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(text(f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE review.status = 'unresolved') AS unresolved,
                   COUNT(*) FILTER (WHERE review.status = 'provider_missing') AS provider_missing,
                   MAX(review.reviewed_at) AS latest_reviewed_at
            FROM market.security_status_reviews AS review WHERE {where_clause}
        """), params)
        summary = dict(summary_result.mappings().one())
        result = await db.execute(text(f"""
            SELECT review.run_id, review.stock_code, review.effective_from, review.effective_to,
                   review.status, review.evidence_source, review.evidence_version, review.reviewed_at
            FROM market.security_status_reviews AS review WHERE {where_clause}
            ORDER BY review.effective_from DESC, review.stock_code, review.status
            LIMIT :limit OFFSET :offset
        """), params)
        items = [dict(row) for row in result.mappings().all()]
    for item in items:
        item.update({
            "price_limit_rule": None,
            "price_tick": None,
            "resolution_status": "not_recorded",
            "source_hash": None,
            "source_hash_status": "not_recorded",
            "status_execution_usable": False,
        })
    total = int(summary["total"] or 0)
    return ok({
        "items": items, "total": total, "page": page, "page_size": page_size,
        "has_more": (page - 1) * page_size + len(items) < total,
        "summary": {"unresolved": int(summary["unresolved"] or 0), "provider_missing": int(summary["provider_missing"] or 0), "latest_reviewed_at": summary["latest_reviewed_at"]},
        "research_readiness": "not_granted", "tradable": False, "order_created": False,
        "source": "market.security_status_reviews", "source_version": "security-status-reviews-v1",
    })
