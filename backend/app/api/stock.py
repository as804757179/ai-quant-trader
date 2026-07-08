from fastapi import APIRouter, Depends, Query

from app.core.response import ok
from app.services.stock_service import StockService

router = APIRouter()


def get_stock_service() -> StockService:
    return StockService()


@router.get("/list")
async def get_stock_list(
    market: str | None = Query(None, description="SH/SZ/BJ"),
    sector: str | None = Query(None, description="行业筛选"),
    board: str | None = Query(None, description="主板/创业板/科创板"),
    keyword: str | None = Query(None, description="名称/代码搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    svc: StockService = Depends(get_stock_service),
):
    result = await svc.get_stock_list(
        market=market,
        sector=sector,
        board=board,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ok(result)


@router.get("/{code}/profile")
async def get_stock_profile(code: str, svc: StockService = Depends(get_stock_service)):
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