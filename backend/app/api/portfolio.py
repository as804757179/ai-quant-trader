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