from sqlalchemy import text

from app.core.config import settings
from app.core.logging import FEATURE_TRADE, get_logger
from app.data.cache import CacheManager
from app.data.service import DataService
from app.db import get_db
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.schemas.trade import OrderCreateRequest
from app.trade.base_trader import OrderRequest
from app.trade.live_trader import LiveTrader
from app.trade.order_manager import OrderManager
from app.trade.order_sync import OrderSyncService
from app.trade.qmt.factory import create_qmt_adapter, probe_broker_environment
from app.trade.simulation_trader import SimulationTrader

logger = get_logger(__name__, feature=FEATURE_TRADE)


class TradeService:
    async def _build_order_manager(self, db) -> OrderManager:
        cache = CacheManager()
        monitor = RiskMonitor(db)
        risk_checker = PreTradeRiskChecker(db, monitor)
        fuse_manager = FuseManager(db, cache)
        data_service = DataService()

        traders: dict = {
            "simulation": SimulationTrader(db, data_service),
        }

        paper_adapter = create_qmt_adapter("paper")
        traders["paper"] = LiveTrader(db, paper_adapter, mode="paper")

        try:
            live_adapter = create_qmt_adapter("live")
            traders["live"] = LiveTrader(db, live_adapter, mode="live")
        except Exception as exc:
            logger.warning("live_trader_unavailable", reason=str(exc))

        return OrderManager(db, risk_checker, fuse_manager, traders)

    async def create_manual_order(self, payload: dict) -> dict:
        request = OrderCreateRequest(**payload)
        logger.info(
            "trade_api_create_order",
            mode=request.mode,
            stock_code=request.stock_code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
        )
        order_req = OrderRequest(
            stock_code=request.stock_code,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            limit_price=request.limit_price,
            signal_id=request.signal_id,
            trigger_source="manual_order",
            operator="user",
            order_reason=request.order_reason or "manual order submitted by API",
            caller="manual_api",
            approval_id=request.approval_id,
            approval_status="approved" if request.approval_id else "pending",
            data_certification_status=request.data_certification_status,
        )
        async with get_db() as db:
            manager = await self._build_order_manager(db)
            return await manager.create_order(
                order_req,
                request.mode,
                live_confirm=request.live_confirm,
            )

    async def cancel_order(self, order_id: str, mode: str = "simulation") -> dict:
        logger.info("trade_api_cancel_order", order_id=order_id, mode=mode)
        async with get_db() as db:
            manager = await self._build_order_manager(db)
            return await manager.cancel_order(order_id, mode)

    async def list_orders(
        self,
        mode: str = "simulation",
        status: str | None = None,
        days: int = 7,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        # asyncpg 下 int 不能直接 || text，使用 make_interval
        filters = ["mode = :mode", "created_at >= NOW() - make_interval(days => :days)"]
        params: dict = {"mode": mode, "days": int(days)}
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
                           filled_quantity, avg_fill_price, status, created_at, filled_at,
                           broker_order_id, order_source, order_reason, caller,
                           approval_status, approval_id, risk_check_id,
                           data_certification_status, created_by, created_from_task
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
        broker = probe_broker_environment()
        return {
            "mode": settings.TRADE_MODE,
            "available_modes": ["simulation", "paper", "live"],
            "live_confirm_required": bool(settings.LIVE_CONFIRM_TOKEN)
            or settings.TRADE_MODE == "live",
            "live_max_order_value": settings.LIVE_MAX_ORDER_VALUE,
            "broker": broker,
            "adapters": {
                "simulation": "local_db",
                "paper": "mock_qmt",
                "live": broker.get("selected_adapter") or "unavailable",
            },
        }

    async def get_broker_status(self) -> dict:
        return probe_broker_environment()

    async def sync_open_orders(self, mode: str = "paper") -> dict:
        """轮询券商，更新挂单/成交状态并推送 WS。"""
        logger.info("trade_sync_open_orders_start", mode=mode)
        if mode == "simulation":
            return {
                "mode": mode,
                "checked": 0,
                "updated": 0,
                "message": "simulation 本地即时成交，无需同步",
            }
        adapter = create_qmt_adapter("live" if mode == "live" else "paper")
        async with get_db() as db:
            syncer = OrderSyncService(db, adapter, mode=mode)
            result = await syncer.sync_open_orders()
        logger.info("trade_sync_open_orders_done", mode=mode, **{
            k: result.get(k) for k in ("checked", "updated", "errors") if k in result
        })
        return result

    async def sync_order(self, order_id: str, mode: str = "paper") -> dict:
        logger.info("trade_sync_one_order", order_id=order_id, mode=mode)
        if mode == "simulation":
            return {"changed": False, "message": "simulation 无需同步"}
        adapter = create_qmt_adapter("live" if mode == "live" else "paper")
        async with get_db() as db:
            syncer = OrderSyncService(db, adapter, mode=mode)
            return await syncer.sync_order_by_id(order_id)

    async def get_order(self, order_id: str) -> dict | None:
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT id, stock_code, side, order_type, quantity, limit_price,
                           filled_quantity, avg_fill_price, status, mode,
                           broker_order_id, created_at, filled_at, cancelled_at,
                           reject_reason, commission, order_source, order_reason,
                           caller, approval_status, approval_id, risk_check_id,
                           data_certification_status, created_by, created_from_task
                    FROM trade.orders WHERE id = :id
                    """
                ),
                {"id": order_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            item = dict(row)
            item["id"] = str(item["id"])
            for k in ("created_at", "filled_at", "cancelled_at"):
                if item.get(k):
                    item[k] = item[k].isoformat()
            return item

    async def reconcile_with_broker(self, mode: str = "paper") -> dict:
        """对比本地持仓与适配器持仓。"""
        logger.info("trade_reconcile_start", mode=mode)
        if mode == "simulation":
            return {
                "status": "skipped",
                "message": "simulation 无外部券商",
                "issues": [],
            }
        adapter = create_qmt_adapter("live" if mode == "live" else "paper")
        await adapter.connect()
        try:
            remote = await adapter.get_positions()
            remote_map = {p.stock_code: p for p in remote}
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT stock_code, total_qty, available_qty, avg_cost
                        FROM trade.positions WHERE mode = :mode AND total_qty > 0
                        """
                    ),
                    {"mode": mode},
                )
                local_rows = list(result.mappings().all())
            local_map = {r["stock_code"]: r for r in local_rows}
            issues = []
            all_codes = set(local_map) | set(remote_map)
            for code in sorted(all_codes):
                loc = local_map.get(code)
                rem = remote_map.get(code)
                lq = int(loc["total_qty"]) if loc else 0
                rq = rem.total_qty if rem else 0
                if lq != rq:
                    issues.append(
                        {
                            "stock_code": code,
                            "local_qty": lq,
                            "broker_qty": rq,
                            "severity": "CRITICAL" if abs(lq - rq) >= 100 else "WARNING",
                        }
                    )
            result = {
                "status": "ok" if not issues else "mismatch",
                "mode": mode,
                "adapter": adapter.name,
                "local_count": len(local_map),
                "broker_count": len(remote_map),
                "issues": issues,
            }
            if issues:
                logger.warning(
                    "trade_reconcile_mismatch",
                    mode=mode,
                    issue_count=len(issues),
                    issues=issues[:20],
                )
            else:
                logger.info(
                    "trade_reconcile_ok",
                    mode=mode,
                    local_count=len(local_map),
                    broker_count=len(remote_map),
                )
            return result
        finally:
            await adapter.disconnect()
