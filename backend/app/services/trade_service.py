from sqlalchemy import text

from app.core.config import settings
from app.data.cache import CacheManager
from app.data.service import DataService
from app.db import get_db
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.schemas.trade import OrderCreateRequest
from app.trade.base_trader import OrderRequest
from app.trade.order_manager import OrderManager
from app.trade.simulation_trader import SimulationTrader


class TradeService:
    async def _build_order_manager(self, db) -> OrderManager:
        cache = CacheManager()
        monitor = RiskMonitor(db)
        risk_checker = PreTradeRiskChecker(db, monitor)
        fuse_manager = FuseManager(db, cache)
        data_service = DataService()
        traders = {
            "simulation": SimulationTrader(db, data_service),
        }
        return OrderManager(db, risk_checker, fuse_manager, traders)

    async def create_manual_order(self, payload: dict) -> dict:
        request = OrderCreateRequest(**payload)
        order_req = OrderRequest(
            stock_code=request.stock_code,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            limit_price=request.limit_price,
            signal_id=request.signal_id,
            trigger_source="manual",
            operator="user",
        )
        async with get_db() as db:
            manager = await self._build_order_manager(db)
            return await manager.create_order(order_req, request.mode)

    async def list_orders(
        self,
        mode: str = "simulation",
        status: str | None = None,
        days: int = 7,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        filters = ["mode = :mode", "created_at >= NOW() - (:days || ' days')::interval"]
        params: dict = {"mode": mode, "days": days}
        if status:
            filters.append("status = :status")
            params["status"] = status
        where_clause = " AND ".join(filters)
        offset = (page - 1) * page_size
        params.update({"limit": page_size, "offset": offset})

        async with get_db() as db:
            result = await db.execute(
                text(
                    f"""
                    SELECT id, stock_code, side, order_type, quantity, limit_price,
                           filled_quantity, avg_fill_price, status, created_at, filled_at
                    FROM trade.orders
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            items = [dict(r._mapping) for r in result.fetchall()]
            for item in items:
                item["id"] = str(item["id"])
                if item.get("created_at"):
                    item["created_at"] = item["created_at"].isoformat()
                if item.get("filled_at"):
                    item["filled_at"] = item["filled_at"].isoformat()
        return {"items": items, "page": page, "page_size": page_size}

    async def get_current_mode(self) -> dict:
        return {"mode": settings.TRADE_MODE}