from fastapi import APIRouter, Depends, Query

from app.core.logging import FEATURE_PORTFOLIO, get_logger
from app.core.response import ok
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__, feature=FEATURE_PORTFOLIO)
router = APIRouter()


def get_portfolio_service() -> PortfolioService:
    return PortfolioService()


@router.get("/summary")
async def get_portfolio_summary(
    mode: str = Query("simulation"),
    svc: PortfolioService = Depends(get_portfolio_service),
):
    logger.info("portfolio_summary_query", mode=mode)
    data = await svc.get_summary(mode)
    logger.debug(
        "portfolio_summary_result",
        mode=mode,
        total_assets=data.get("total_assets"),
        position_count=data.get("position_count"),
        is_fused=data.get("is_fused"),
    )
    return ok(data)


@router.get("/positions")
async def get_positions(
    mode: str = Query("simulation"),
    svc: PortfolioService = Depends(get_portfolio_service),
):
    logger.info("portfolio_positions_query", mode=mode)
    positions = await svc.get_positions(mode)
    logger.debug("portfolio_positions_result", mode=mode, count=len(positions or []))
    return ok(positions)


@router.get("/equity-curve")
async def get_equity_curve(
    mode: str = Query("simulation"),
    days: int = Query(30, ge=1, le=365),
    svc: PortfolioService = Depends(get_portfolio_service),
):
    """只读返回账户每日最新资产快照。"""
    logger.info("portfolio_equity_curve_query", mode=mode, days=days)
    return ok(await svc.get_equity_curve(mode, days))
