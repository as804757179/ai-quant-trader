from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.logging import FEATURE_STOCK, get_logger
from app.core.response import error, ok
from app.data.kline_backfill import KlineBackfillService, estimate_limit_for_range
from app.services.stock_service import StockService

logger = get_logger(__name__, feature=FEATURE_STOCK)
router = APIRouter()


def get_stock_service() -> StockService:
    return StockService()


class KlineBackfillRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=200)
    period: str = "1d"
    limit: int = Field(default=250, ge=10, le=1000)
    allow_synthetic: bool = False
    start_date: date | None = None
    end_date: date | None = None
    concurrency: int = Field(default=5, ge=1, le=20)


@router.post("/sync-universe")
async def sync_stock_universe(
    backfill_top_n: int = Query(50, ge=0, le=200, description="同步后为前 N 只回填K线(0=不回填)"),
    allow_synthetic: bool = Query(False, description="仅 Smoke Test 可写合成数据"),
):
    """从 a-stock-data 同步全市场股票到 fundamental.stocks。"""
    import importlib.util
    from pathlib import Path

    from sqlalchemy import text

    from app.db import get_db

    logger.info("stock_sync_universe_start", backfill_top_n=backfill_top_n)
    try:
        seed_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_stocks.py"
        spec = importlib.util.spec_from_file_location("seed_stocks_mod", seed_path)
        if spec is None or spec.loader is None:
            error("无法加载 seed_stocks 脚本", "STOCK_SYNC_FAILED", 500)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        await mod.seed_stocks()
    except SystemExit as exc:
        error(f"同步股票池失败: {exc}", "STOCK_SYNC_FAILED", 502)
    except Exception as exc:
        logger.error("stock_sync_universe_failed", error=str(exc), exc_info=True)
        error(f"同步股票池失败: {exc}", "STOCK_SYNC_FAILED", 500)

    async with get_db() as db:
        total = int(
            await db.scalar(text("SELECT COUNT(*) FROM fundamental.stocks WHERE is_active=TRUE"))
            or 0
        )
        rows = await db.execute(
            text(
                """
                SELECT code FROM fundamental.stocks
                WHERE is_active=TRUE ORDER BY code LIMIT :n
                """
            ),
            {"n": backfill_top_n},
        )
        codes = [r[0] for r in rows.fetchall()]

    backfill_stats = None
    if codes and backfill_top_n > 0:
        bf = KlineBackfillService()
        try:
            backfill_stats = await bf.backfill_codes(
                codes,
                period="1d",
                limit=250,
                allow_synthetic=allow_synthetic,
                concurrency=8,
            )
        finally:
            await bf.close()

    logger.info("stock_sync_universe_done", total=total, backfill=backfill_stats)
    return ok(
        {"total_active": total, "backfill": backfill_stats},
        message=f"股票池已同步，active={total}",
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


@router.post("/backfill-kline")
async def backfill_kline(body: KlineBackfillRequest):
    """
    批量回填日/分钟 K 线到 market.klines。
    远程数据源不可用时可 allow_synthetic=true 写入演示数据。
    """
    codes = [c.strip() for c in body.codes if c and c.strip()]
    if not codes:
        error("codes 不能为空", "INVALID_CODES")

    limit = body.limit
    if body.start_date and body.end_date:
        limit = max(limit, estimate_limit_for_range(body.start_date, body.end_date))

    logger.info(
        "stock_kline_backfill_start",
        codes_count=len(codes),
        period=body.period,
        limit=limit,
        allow_synthetic=body.allow_synthetic,
        start_date=str(body.start_date) if body.start_date else None,
        end_date=str(body.end_date) if body.end_date else None,
    )
    svc = KlineBackfillService()
    try:
        stats = await svc.backfill_codes(
            codes,
            period=body.period,
            limit=limit,
            concurrency=body.concurrency,
            allow_synthetic=body.allow_synthetic,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        logger.info("stock_kline_backfill_done", **{k: stats.get(k) for k in stats})
        return ok(stats, message=f"回填完成 success={stats['success']}/{stats['total']}")
    except Exception as exc:
        logger.error("stock_kline_backfill_failed", error=str(exc), exc_info=True)
        error(f"回填失败: {exc}", "BACKFILL_FAILED", 500)
    finally:
        await svc.close()


@router.get("/{code}/profile")
async def get_stock_profile(code: str, svc: StockService = Depends(get_stock_service)):
    logger.debug("stock_profile_query", stock_code=code)
    profile = await svc.get_profile(code)
    return ok(profile)


@router.get("/{code}/quote")
async def get_realtime_quote(code: str, svc: StockService = Depends(get_stock_service)):
    return ok(await svc.get_quote(code))


@router.get("/{code}/kline")
async def get_kline(
    code: str,
    period: str = Query("1d"),
    limit: int = Query(200, le=1000),
    adj: str = Query("qfq"),
    svc: StockService = Depends(get_stock_service),
):
    logger.debug("stock_kline_query", stock_code=code, period=period, limit=limit, adj=adj)
    return ok(await svc.get_kline(code, period, limit, adj))


@router.get("/{code}/fund-flow")
async def get_fund_flow(
    code: str,
    days: int = Query(10, le=90),
    svc: StockService = Depends(get_stock_service),
):
    return ok(await svc.get_fund_flow(code, days))


@router.get("/{code}/news")
async def get_news(
    code: str,
    limit: int = Query(20, le=100),
    svc: StockService = Depends(get_stock_service),
):
    return ok(await svc.get_news(code, limit))
