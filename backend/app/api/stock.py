from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.logging import FEATURE_STOCK, get_logger
from app.core.response import error, ok
from app.core.auth import get_request_principal
from app.services.stock_service import StockService
from app.core.config import settings
from app.db import get_db
from app.jobs.dispatch import OperationJobDispatchError
from app.jobs.operations import OperationJobService
from app.jobs.service import AsyncJobError

logger = get_logger(__name__, feature=FEATURE_STOCK)
router = APIRouter()


def get_stock_service() -> StockService:
    return StockService()


def set_data_status_headers(response: Response, result: Any) -> None:
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    def header_value(value: Any, fallback: str, limit: int) -> str:
        return str(value or fallback).replace("\r", "").replace("\n", "")[:limit]

    response.headers["X-Data-Status"] = header_value(result.status, "unknown", 64)
    response.headers["X-Data-Source"] = header_value(
        provenance.get("source"), "not_recorded", 128
    )
    response.headers["X-Data-Quality"] = header_value(
        provenance.get("quality_status"), "not_recorded", 64
    )
    response.headers["X-Data-Usage"] = header_value(
        provenance.get("usage_status"), "not_recorded", 64
    )
    response.headers["X-Data-Error-Code"] = header_value(
        result.error_code, "none", 64
    )
    response.headers["X-Data-Retryable"] = "true" if result.retryable else "false"


class KlineBackfillRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=200)
    period: str = "1d"
    limit: int = Field(default=250, ge=10, le=1000)
    allow_synthetic: bool = False
    start_date: date | None = None
    end_date: date | None = None
    concurrency: int = Field(default=5, ge=1, le=20)


def classify_quote_status(
    latest_at: datetime | None,
    now: datetime,
    threshold_seconds: int,
    market_session: str,
) -> tuple[str, int | None]:
    if latest_at is None:
        return "empty", None
    lag_seconds = max(0, int((now - latest_at.astimezone(now.tzinfo)).total_seconds()))
    if market_session == "closed":
        return "market_closed", lag_seconds
    if market_session != "open":
        return "calendar_unresolved", lag_seconds
    return ("fresh" if lag_seconds <= threshold_seconds else "stale"), lag_seconds


@router.get("/market/status")
async def get_market_data_status():
    """只读返回行情库时效、日历覆盖和来源元数据完整性。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    threshold_seconds = max(
        60,
        int(settings.DATA_CACHE_TTL_QUOTE) * 3,
        int(settings.DATA_SYNC_INTERVAL_REALTIME) * 3,
    )
    async with get_db() as db:
        latest_at = await db.scalar(text("SELECT MAX(time) FROM market.quotes"))
        recent_count = int(
            await db.scalar(
                text(
                    """
                    SELECT COUNT(DISTINCT stock_code)
                    FROM market.quotes
                    WHERE time >= :cutoff
                    """
                ),
                {"cutoff": now - timedelta(seconds=threshold_seconds)},
            )
            or 0
        )
        active_stock_count = int(
            await db.scalar(
                text("SELECT COUNT(*) FROM fundamental.stocks WHERE is_active = TRUE")
            )
            or 0
        )
        calendar_result = await db.execute(
            text(
                """
                SELECT COUNT(*) AS row_count,
                       BOOL_AND(status = 'confirmed') AS confirmed,
                       BOOL_AND(is_trading_day) AS trading_day,
                       ARRAY_AGG(DISTINCT source ORDER BY source) AS sources
                FROM market.trading_calendar
                WHERE trading_date = :today
                  AND exchange IN ('SH', 'SZ')
                """
            ),
            {"today": now.date()},
        )
        calendar = dict(calendar_result.mappings().one())
        provenance_result = await db.execute(
            text(
                """
                SELECT p.provider, p.source, p.fetch_endpoint, p.batch_id::text AS batch_id,
                       p.fallback_used, p.received_at, p.collector_version,
                       p.normalizer_version, b.status AS batch_status
                FROM market.quote_provenance p
                JOIN market.quote_batches b ON b.batch_id = p.batch_id
                ORDER BY p.received_at DESC
                LIMIT 1
                """
            )
        )
        latest_provenance = provenance_result.mappings().first()
        batch_result = await db.execute(
            text(
                """
                SELECT batch_id::text AS batch_id, provider, source, fetch_endpoint,
                       requested_symbols, returned_symbols, accepted_symbols,
                       rejected_symbols, status, failure_reason, raw_response_hash,
                       collector_version, normalizer_version, started_at, fetched_at,
                       received_at
                FROM market.quote_batches
                ORDER BY received_at DESC
                LIMIT 1
                """
            )
        )
        latest_batch = batch_result.mappings().first()

    if int(calendar.get("row_count") or 0) != 2:
        market_session = "calendar_not_covered"
    elif not calendar.get("confirmed"):
        market_session = "calendar_unresolved"
    elif not calendar.get("trading_day"):
        market_session = "closed"
    elif time(9, 30) <= now.time() <= time(11, 30) or time(13, 0) <= now.time() <= time(15, 0):
        market_session = "open"
    else:
        market_session = "closed"

    status, lag_seconds = classify_quote_status(
        latest_at, now, threshold_seconds, market_session
    )
    return ok(
        {
            "status": status,
            "market_session": market_session,
            "latest_quote_at": latest_at.isoformat() if latest_at else None,
            "lag_seconds": lag_seconds,
            "freshness_threshold_seconds": threshold_seconds,
            "recent_symbol_count": recent_count,
            "active_stock_count": active_stock_count,
            "calendar_sources": calendar.get("sources") or [],
            "source": "market.quotes",
            "provider": latest_provenance["provider"] if latest_provenance else None,
            "provider_metadata_status": "recorded" if latest_provenance else "not_recorded",
            "fallback_status": (
                "not_used"
                if latest_provenance and not latest_provenance["fallback_used"]
                else "not_recorded"
            ),
            "source_version": (
                latest_provenance["collector_version"]
                if latest_provenance
                else "market-quote-status-v1"
            ),
            "latest_batch": dict(latest_batch) if latest_batch else None,
        }
    )


@router.get("/market/batches")
async def get_market_quote_batches(
    limit: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
):
    """只读返回实时行情批次血缘；不提供重试或数据修复操作。"""
    resolved_page_size = page_size or limit
    offset = (page - 1) * resolved_page_size
    async with get_db() as db:
        total_result = await db.execute(
            text("SELECT COUNT(*) FROM market.quote_batches")
        )
        total = int(total_result.scalar() or 0)
        result = await db.execute(
            text(
                """
                SELECT batch.batch_id::text AS batch_id, batch.provider, batch.source,
                       batch.fetch_endpoint, batch.requested_symbols,
                       batch.returned_symbols, batch.accepted_symbols,
                       batch.rejected_symbols, batch.status, batch.failure_reason,
                       batch.raw_response_hash, batch.collector_version,
                       batch.normalizer_version, batch.started_at, batch.fetched_at,
                       batch.received_at,
                       (
                           SELECT BOOL_OR(provenance.fallback_used)
                           FROM market.quote_provenance AS provenance
                           WHERE provenance.batch_id = batch.batch_id
                       ) AS fallback_used
                FROM market.quote_batches AS batch
                ORDER BY batch.received_at DESC, batch.batch_id DESC
                LIMIT :limit
                OFFSET :offset
                """
            ),
            {"limit": resolved_page_size, "offset": offset},
        )
        batches = [dict(row) for row in result.mappings().all()]
    return ok(
        {
            "items": batches,
            "total": total,
            "page": page,
            "page_size": resolved_page_size,
            "has_more": offset + len(batches) < total,
            "source": "market.quote_batches",
            "source_version": "market-quote-batches-v2",
        }
    )


@router.post("/sync-universe", status_code=202)
async def sync_stock_universe(
    request: Request,
    response: Response,
    backfill_top_n: int = Query(50, ge=0, le=200, description="同步后为前 N 只回填K线(0=不回填)"),
    allow_synthetic: bool = Query(False, description="仅 Smoke Test 可写合成数据"),
):
    """创建股票池同步 Job；HTTP 请求不执行全市场同步。"""
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)
    try:
        job, created = await OperationJobService().submit(
            job_type="market.sync_universe",
            principal=get_request_principal(request),
            idempotency_key=idempotency_key,
            payload={
                "backfill_top_n": backfill_top_n,
                "allow_synthetic": allow_synthetic,
            },
        )
    except OperationJobDispatchError:
        error("同步任务未能投递到 Worker", "OPERATION_JOB_DISPATCH_UNAVAILABLE", 503)
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
    location = f"/api/v1/jobs/{job['job_id']}"
    response.headers["Location"] = location
    logger.info(
        "stock_sync_universe_accepted",
        job_id=job["job_id"],
        created=created,
        backfill_top_n=backfill_top_n,
    )
    return ok(
        {"job": job, "location": location, "idempotent_replay": not created},
        message="股票池同步 Job 已受理",
    )


@router.get("/list")
async def get_stock_list(
    market: str | None = Query(None, description="SH/SZ/BJ"),
    sector: str | None = Query(None, description="行业筛选"),
    board: str | None = Query(None, description="主板/创业板/科创板"),
    keyword: str | None = Query(None, description="名称/代码搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    svc: StockService = Depends(get_stock_service),
):
    logger.debug(
        "stock_list_query",
        market=market,
        sector=sector,
        board=board,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    try:
        result = await svc.get_stock_list(
            market=market,
            sector=sector,
            board=board,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        logger.error("stock_list_failed", error=str(exc), exc_info=True)
        error(f"加载股票列表失败: {exc}", "STOCK_LIST_FAILED", 500)
    logger.debug("stock_list_result", total=result.get("total"), page=page)
    return ok(result)


@router.post("/backfill-kline", status_code=202)
async def backfill_kline(
    body: KlineBackfillRequest,
    request: Request,
    response: Response,
):
    """创建 K 线回填 Job；HTTP 请求不执行远程抓取或数据库回填。"""
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)
    try:
        job, created = await OperationJobService().submit(
            job_type="market.backfill_kline",
            principal=get_request_principal(request),
            idempotency_key=idempotency_key,
            payload=body.model_dump(mode="json"),
        )
    except OperationJobDispatchError:
        error("回填任务未能投递到 Worker", "OPERATION_JOB_DISPATCH_UNAVAILABLE", 503)
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
    location = f"/api/v1/jobs/{job['job_id']}"
    response.headers["Location"] = location
    logger.info(
        "stock_kline_backfill_accepted",
        job_id=job["job_id"],
        created=created,
        codes_count=len(body.codes),
    )
    return ok(
        {"job": job, "location": location, "idempotent_replay": not created},
        message="K 线回填 Job 已受理",
    )


@router.get("/{code}/profile")
async def get_stock_profile(code: str, svc: StockService = Depends(get_stock_service)):
    logger.debug("stock_profile_query", stock_code=code)
    profile = await svc.get_profile(code)
    return ok(profile)


@router.get("/{code}/quote")
async def get_realtime_quote(
    code: str,
    response: Response,
    svc: StockService = Depends(get_stock_service),
):
    result = await svc.get_quote_result(code)
    set_data_status_headers(response, result)
    return ok(result.data if result.success else None)


@router.get("/{code}/kline")
async def get_kline(
    code: str,
    period: str = Query("1d"),
    limit: int = Query(200, le=1000),
    adj: str = Query("qfq"),
    svc: StockService = Depends(get_stock_service),
):
    if adj not in {"raw", "qfq"}:
        error(
            "不支持的 K 线复权方式，仅支持 raw 或 qfq",
            "UNSUPPORTED_KLINE_ADJUSTMENT",
            422,
            field_errors=[
                {
                    "field": "adj",
                    "message": "supported values are raw and qfq",
                    "type": "value_error",
                }
            ],
        )
    logger.debug("stock_kline_query", stock_code=code, period=period, limit=limit, adj=adj)
    return ok(await svc.get_kline(code, period, limit, adj))


@router.get("/{code}/fund-flow")
async def get_fund_flow(
    code: str,
    response: Response,
    days: int = Query(10, le=90),
    svc: StockService = Depends(get_stock_service),
):
    result = await svc.get_fund_flow_result(code, days)
    set_data_status_headers(response, result)
    return ok(result.data if result.success else [])


@router.get("/{code}/news")
async def get_news(
    code: str,
    response: Response,
    limit: int = Query(20, le=100),
    svc: StockService = Depends(get_stock_service),
):
    result = await svc.get_news_result(code, limit)
    set_data_status_headers(response, result)
    response.headers["X-Data-Content-Scope"] = str(
        result.provenance.get("content_scope") or "not_recorded"
    )[:64]
    return ok(result.data if result.success else [])
