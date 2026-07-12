from fastapi import APIRouter, Depends, Query

from app.core.response import error, ok
from app.schemas.trade import OrderCancelRequest, OrderCreateRequest
from app.services.trade_service import TradeService

router = APIRouter()


def get_trade_service() -> TradeService:
    return TradeService()


@router.post("/order")
async def create_order(
    request: OrderCreateRequest,
    svc: TradeService = Depends(get_trade_service),
):
    code = str(request.stock_code).zfill(6)
    # 科创板买入 ≥200 且可为 1 股递增；其它板买入须 100 整数倍（卖出零股由撮合层校验）
    if request.side == "BUY":
        if code.startswith("688"):
            if request.quantity < 200:
                error("科创板买入不少于 200 股", "INVALID_QUANTITY")
        elif request.quantity % 100 != 0:
            error("买入数量必须是 100 的整数倍（1 手）", "INVALID_QUANTITY")
    elif request.quantity % 100 != 0 and request.quantity > 0:
        # 卖出非整手：允许（清仓零股），撮合层再校验可卖
        pass
    if request.order_type == "LIMIT":
        if request.limit_price is None:
            error("限价单必须提供 limit_price", "MISSING_PRICE")
        else:
            # 统一到分，避免浮点导致「最小变动单位」误拒
            request.limit_price = round(float(request.limit_price) + 1e-8, 2)

    result = await svc.create_manual_order(request.model_dump())
    return ok(result)


@router.post("/simulation/release-t1")
async def simulation_release_t1(
    force_all: bool = Query(
        True,
        description="true=模拟跳到下一交易日，全部可卖；false=仅释放非当日买入",
    ),
):
    """模拟盘：释放 T+1 可卖数量（学习辅助，非实盘）。"""
    from app.data.service import DataService
    from app.db import get_db
    from app.trade.account_ledger import release_t1_available_qty
    from app.trade.simulation_trader import SimulationTrader

    data = DataService()
    try:
        async with get_db() as db:
            if force_all:
                out = await release_t1_available_qty(db, "simulation")
                out["force_all"] = True
            else:
                trader = SimulationTrader(db, data)
                out = await trader._maybe_release_t1()
                out["force_all"] = False
        return ok(
            out,
            message=(
                f"已释放可卖 {out.get('released_rows', 0)} 条持仓"
                + ("（模拟下一交易日，含当日买入）" if force_all else "（仅非当日买入）")
            ),
        )
    finally:
        await data.close()


@router.post("/order/cancel")
async def cancel_order(
    body: OrderCancelRequest,
    svc: TradeService = Depends(get_trade_service),
):
    result = await svc.cancel_order(body.order_id, body.mode)
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


@router.get("/orders/{order_id}")
async def get_order(order_id: str, svc: TradeService = Depends(get_trade_service)):
    data = await svc.get_order(order_id)
    if not data:
        error("订单不存在", "ORDER_NOT_FOUND", 404)
    return ok(data)


@router.post("/orders/sync")
async def sync_open_orders(
    mode: str = Query("paper", pattern="^(paper|live)$"),
    svc: TradeService = Depends(get_trade_service),
):
    """同步未终态订单状态（券商轮询 → 本地 + WS）。"""
    return ok(await svc.sync_open_orders(mode), message="订单同步完成")


@router.post("/orders/{order_id}/sync")
async def sync_one_order(
    order_id: str,
    mode: str = Query("paper", pattern="^(paper|live|simulation)$"),
    svc: TradeService = Depends(get_trade_service),
):
    return ok(await svc.sync_order(order_id, mode))


@router.get("/mode")
async def get_trade_mode(svc: TradeService = Depends(get_trade_service)):
    return ok(await svc.get_current_mode())


@router.get("/broker-status")
async def broker_status(svc: TradeService = Depends(get_trade_service)):
    """QMT / Mock 环境探测（不强制连接）。"""
    return ok(await svc.get_broker_status())


@router.post("/reconcile")
async def reconcile_broker(
    mode: str = Query("paper", pattern="^(paper|live)$"),
    svc: TradeService = Depends(get_trade_service),
):
    """本地持仓 vs 券商/Mock 持仓交叉验证。"""
    return ok(await svc.reconcile_with_broker(mode))
