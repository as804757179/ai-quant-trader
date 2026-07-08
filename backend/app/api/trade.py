from fastapi import APIRouter, Depends, Query

from app.core.response import error, ok
from app.schemas.trade import OrderCreateRequest
from app.services.trade_service import TradeService

router = APIRouter()


def get_trade_service() -> TradeService:
    return TradeService()


@router.post("/order")
async def create_order(
    request: OrderCreateRequest,
    svc: TradeService = Depends(get_trade_service),
):
    if request.quantity % 100 != 0:
        error("买入数量必须是100的整数倍", "INVALID_QUANTITY")
    if request.order_type == "LIMIT" and request.limit_price is None:
        error("限价单必须提供limit_price", "MISSING_PRICE")

    result = await svc.create_manual_order(request.model_dump())
    return ok(result)


@router.get("/orders")
async def list_orders(
    mode: str = Query("simulation"),
    status: str | None = Query(None),
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    svc: TradeService = Depends(get_trade_service),
):
    return ok(await svc.list_orders(mode, status, days, page, page_size))


@router.get("/mode")
async def get_trade_mode(svc: TradeService = Depends(get_trade_service)):
    return ok(await svc.get_current_mode())