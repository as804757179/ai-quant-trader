from fastapi import APIRouter, Depends, Query

from app.core.response import ok
from app.services.portfolio_service import PortfolioService

router = APIRouter()


def get_portfolio_service() -> PortfolioService:
    return PortfolioService()


@router.get("/summary")
async def get_portfolio_summary(
    mode: str = Query("simulation"),
    svc: PortfolioService = Depends(get_portfolio_service),
):
    return ok(await svc.get_summary(mode))


@router.get("/positions")
async def get_positions(
    mode: str = Query("simulation"),
    svc: PortfolioService = Depends(get_portfolio_service),
):
    return ok(await svc.get_positions(mode))