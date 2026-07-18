"""订单事件桥：适配器回调 → 本地同步 → 可选对账。"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import text

from app.core.config import settings
from app.db import get_db
from app.trade.order_sync import OrderSyncService
from app.trade.qmt.adapter import BrokerOrder, QmtAdapter
from app.trade.qmt.factory import create_qmt_adapter
from app.ws.publisher import publish_alert

logger = structlog.get_logger(__name__)


class OrderEventBridge:
    """
    将券商回调接到 OrderSyncService。

    - attach(adapter, mode) 注册回调
    - 收到 FILLED/CANCELLED/FAILED/PARTIAL 时按 broker_order_id 同步本地单
    - 成交后可选自动对账
    """

    def __init__(self) -> None:
        self._attached: dict[str, QmtAdapter] = {}
        self._lock = asyncio.Lock()

    def attach(self, adapter: QmtAdapter, mode: str) -> None:
        key = f"{mode}:{id(adapter)}"
        if key in self._attached:
            return
        try:
            loop = asyncio.get_running_loop()
            adapter.set_event_loop(loop)
        except RuntimeError:
            pass

        def _cb(order: BrokerOrder) -> Any:
            return self.handle_broker_order(mode, order)

        adapter.register_order_callback(_cb)
        self._attached[key] = adapter
        logger.info("order_event_bridge_attached", mode=mode, adapter=adapter.name)

    async def handle_broker_order(self, mode: str, broker_order: BrokerOrder) -> dict[str, Any]:
        if not broker_order.broker_order_id:
            return {"ok": False, "reason": "empty_broker_id"}

        logger.info(
            "order_event_received",
            mode=mode,
            broker_order_id=broker_order.broker_order_id,
            status=broker_order.status,
            stock=broker_order.stock_code,
        )

        async with self._lock:
            async with get_db() as db:
                # 找到本地订单
                row = await db.execute(
                    text(
                        """
                        SELECT id, stock_code, side, quantity, status,
                               filled_quantity, avg_fill_price, commission, broker_order_id
                        FROM trade.orders
                        WHERE broker_order_id = :bid AND mode = :mode
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"bid": broker_order.broker_order_id, "mode": mode},
                )
                local = row.mappings().first()
                if not local:
                    logger.warning(
                        "order_event_no_local",
                        broker_order_id=broker_order.broker_order_id,
                        mode=mode,
                    )
                    return {"ok": False, "reason": "local_not_found"}

                adapter = self._adapter_for_mode(mode)
                syncer = OrderSyncService(db, adapter, mode=mode)
                # 用 query 路径统一更新；只有累计订单快照可直接作为兜底。
                detail = await syncer.sync_order_by_id(str(local["id"]))
                callback_filled_quantity = int(broker_order.filled_quantity or 0)
                local_filled_quantity = int(local["filled_quantity"] or 0)
                callback_differs = (
                    broker_order.status != local["status"]
                    or callback_filled_quantity != local_filled_quantity
                )
                if not detail.get("changed") and callback_differs:
                    if (broker_order.raw or {}).get("source") == "on_stock_trade":
                        logger.warning(
                            "order_event_non_cumulative_trade_callback",
                            broker_order_id=broker_order.broker_order_id,
                            mode=mode,
                        )
                        return {
                            "ok": False,
                            "reason": "non_cumulative_trade_callback",
                        }
                    # query 可能仍返回旧状态，使用订单状态回调的累计快照兜底。
                    detail = await syncer.apply_broker_snapshot(
                        str(local["id"]),
                        {
                            "id": str(local["id"]),
                            "stock_code": local["stock_code"],
                            "side": local["side"],
                            "quantity": local["quantity"],
                            "status": local["status"],
                            "filled_quantity": local_filled_quantity,
                            "avg_fill_price": local["avg_fill_price"],
                            "commission": local["commission"],
                            "broker_order_id": local["broker_order_id"],
                        },
                        broker_order,
                    )

        if detail.get("fully_filled") and getattr(
            settings, "AUTO_RECONCILE_ON_FILL", True
        ):
            await self._auto_reconcile(mode)

        return {"ok": True, "detail": detail}

    def _adapter_for_mode(self, mode: str) -> QmtAdapter:
        for key, ad in self._attached.items():
            if key.startswith(f"{mode}:"):
                return ad
        return create_qmt_adapter("live" if mode == "live" else "paper")

    async def _auto_reconcile(self, mode: str) -> None:
        try:
            from app.services.trade_service import TradeService

            svc = TradeService()
            result = await svc.reconcile_with_broker(
                "live" if mode == "live" else "paper"
            )
            issues = result.get("issues") or []
            if issues:
                await publish_alert(
                    alert_type="reconcile_mismatch",
                    level="WARNING",
                    message=f"成交后对账发现 {len(issues)} 项差异 ({mode})",
                    detail=result,
                )
            else:
                logger.info("auto_reconcile_ok", mode=mode)
        except Exception as exc:
            logger.warning("auto_reconcile_failed", mode=mode, error=str(exc))


# 进程内单例
order_event_bridge = OrderEventBridge()
