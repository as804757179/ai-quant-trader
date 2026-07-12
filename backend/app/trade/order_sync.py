"""挂单/成交状态同步：券商 → 本地订单表 → WS 推送。"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.trade.account_ledger import recompute_account_assets
from app.trade.live_trader import LiveTrader
from app.trade.qmt.adapter import BrokerOrder, QmtAdapter
from app.ws.publisher import publish_alert, publish_portfolio_update

logger = structlog.get_logger(__name__)

OPEN_STATUSES = ("PENDING", "SUBMITTED", "PARTIAL")
TERMINAL = frozenset({"FILLED", "CANCELLED", "FAILED"})


class OrderSyncService:
    def __init__(
        self,
        db: AsyncSession,
        adapter: QmtAdapter,
        *,
        mode: str,
    ) -> None:
        self.db = db
        self.adapter = adapter
        self.mode = mode
        self._trader = LiveTrader(db, adapter, mode=mode)

    async def sync_open_orders(self) -> dict[str, Any]:
        """同步本 mode 下未终态订单。"""
        await self._trader._ensure_connected()
        rows = await self.db.execute(
            text(
                """
                SELECT id, stock_code, side, quantity, limit_price, status,
                       filled_quantity, avg_fill_price, broker_order_id
                FROM trade.orders
                WHERE mode = :mode
                  AND status IN ('PENDING', 'SUBMITTED', 'PARTIAL')
                ORDER BY created_at
                LIMIT 200
                """
            ),
            {"mode": self.mode},
        )
        orders = list(rows.mappings().all())
        stats = {
            "mode": self.mode,
            "checked": len(orders),
            "updated": 0,
            "filled": 0,
            "cancelled": 0,
            "failed": 0,
            "unchanged": 0,
            "errors": 0,
            "details": [],
        }

        for order in orders:
            try:
                detail = await self._sync_one(dict(order))
                stats["details"].append(detail)
                if detail.get("changed"):
                    stats["updated"] += 1
                    new_st = detail.get("new_status")
                    if new_st == "FILLED":
                        stats["filled"] += 1
                    elif new_st == "CANCELLED":
                        stats["cancelled"] += 1
                    elif new_st == "FAILED":
                        stats["failed"] += 1
                else:
                    stats["unchanged"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.error(
                    "order_sync_one_error",
                    order_id=str(order["id"]),
                    error=str(exc),
                    exc_info=True,
                )
                stats["details"].append(
                    {
                        "order_id": str(order["id"]),
                        "changed": False,
                        "error": str(exc),
                    }
                )

        logger.info(
            "order_sync_done",
            mode=self.mode,
            checked=stats["checked"],
            updated=stats["updated"],
            filled=stats["filled"],
        )
        return stats

    async def sync_order_by_id(self, order_id: str) -> dict[str, Any]:
        row = await self.db.execute(
            text(
                """
                SELECT id, stock_code, side, quantity, limit_price, status,
                       filled_quantity, avg_fill_price, broker_order_id, mode
                FROM trade.orders WHERE id = :id
                """
            ),
            {"id": order_id},
        )
        order = row.mappings().first()
        if not order:
            return {"changed": False, "error": "订单不存在"}
        if order["mode"] != self.mode:
            return {"changed": False, "error": "mode 不匹配"}
        await self._trader._ensure_connected()
        return await self._sync_one(dict(order))

    async def _sync_one(self, order: dict[str, Any]) -> dict[str, Any]:
        order_id = str(order["id"])
        old_status = order["status"]
        broker_id = order.get("broker_order_id")

        if not broker_id:
            return {
                "order_id": order_id,
                "changed": False,
                "old_status": old_status,
                "reason": "no_broker_order_id",
            }

        if old_status in TERMINAL:
            return {
                "order_id": order_id,
                "changed": False,
                "old_status": old_status,
                "reason": "already_terminal",
            }

        remote: BrokerOrder | None = await self.adapter.query_order(str(broker_id))
        if remote is None:
            return {
                "order_id": order_id,
                "changed": False,
                "old_status": old_status,
                "reason": "broker_not_found",
            }
        return await self.apply_broker_snapshot(order_id, order, remote)

    async def apply_broker_snapshot(
        self,
        order_id: str,
        order: dict[str, Any],
        remote: BrokerOrder,
    ) -> dict[str, Any]:
        """用券商快照更新本地订单（轮询与回调共用）。"""
        old_status = order["status"]
        broker_id = order.get("broker_order_id") or remote.broker_order_id

        if old_status in TERMINAL:
            return {
                "order_id": order_id,
                "changed": False,
                "old_status": old_status,
                "reason": "already_terminal",
            }

        new_status = remote.status if remote.status in (
            "PENDING", "SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "FAILED"
        ) else old_status

        filled_qty = int(remote.filled_quantity or 0)
        avg_price = float(remote.avg_fill_price or 0)
        old_filled = int(order.get("filled_quantity") or 0)

        if new_status == old_status and filled_qty == old_filled:
            return {
                "order_id": order_id,
                "changed": False,
                "old_status": old_status,
                "new_status": new_status,
            }

        commission = 0.0
        if avg_price > 0 and filled_qty > 0:
            commission = max(avg_price * filled_qty * 0.0003, 5.0)

        await self.db.execute(
            text(
                """
                UPDATE trade.orders
                SET status = :status,
                    filled_quantity = :filled_quantity,
                    avg_fill_price = COALESCE(NULLIF(:avg_fill_price, 0), avg_fill_price),
                    commission = CASE WHEN :status = 'FILLED' THEN :commission ELSE commission END,
                    filled_at = CASE
                        WHEN :status = 'FILLED' AND filled_at IS NULL THEN NOW()
                        ELSE filled_at
                    END,
                    cancelled_at = CASE
                        WHEN :status = 'CANCELLED' AND cancelled_at IS NULL THEN NOW()
                        ELSE cancelled_at
                    END,
                    reject_reason = CASE
                        WHEN :status = 'FAILED' THEN :reject_reason
                        ELSE reject_reason
                    END
                WHERE id = :id
                """
            ),
            {
                "id": order_id,
                "status": new_status,
                "filled_quantity": filled_qty,
                "avg_fill_price": avg_price,
                "commission": commission,
                "reject_reason": remote.message or None,
            },
        )

        await self.db.execute(
            text(
                """
                INSERT INTO trade.order_history (order_id, from_status, to_status, changed_by, detail)
                VALUES (
                    :order_id, :from_status, :to_status, 'order_sync',
                    CAST(:detail AS jsonb)
                )
                """
            ),
            {
                "order_id": order_id,
                "from_status": old_status,
                "to_status": new_status,
                "detail": __import__("json").dumps(
                    {
                        "broker_order_id": broker_id,
                        "filled_quantity": filled_qty,
                        "avg_fill_price": avg_price,
                        "message": remote.message,
                        "source": "callback_or_poll",
                    },
                    ensure_ascii=False,
                ),
            },
        )

        if new_status == "FILLED" and old_status != "FILLED":
            if avg_price > 0 and filled_qty > 0:
                from app.trade.base_trader import OrderRequest

                req = OrderRequest(
                    stock_code=order["stock_code"],
                    side=order["side"],
                    order_type="LIMIT",
                    quantity=filled_qty,
                    limit_price=avg_price,
                )
                await self._trader._sync_fill_to_local(
                    req,
                    fill_price=avg_price,
                    quantity=filled_qty,
                    commission=commission,
                )
                await recompute_account_assets(self.db, self.mode)

            await publish_portfolio_update(
                self.mode,
                {
                    "type": "order_filled",
                    "order_id": order_id,
                    "stock_code": order["stock_code"],
                    "side": order["side"],
                    "status": new_status,
                    "filled_quantity": filled_qty,
                    "avg_fill_price": avg_price,
                },
            )
            await publish_alert(
                alert_type="order_filled",
                level="INFO",
                message=f"订单成交 {order['stock_code']} {order['side']} {filled_qty}@{avg_price}",
                detail={
                    "order_id": order_id,
                    "mode": self.mode,
                    "broker_order_id": broker_id,
                },
            )
            # 轮询路径成交后也可触发对账（与回调路径一致）
            try:
                from app.core.config import settings

                if getattr(settings, "AUTO_RECONCILE_ON_FILL", True):
                    from app.trade.order_event_bridge import order_event_bridge

                    await order_event_bridge._auto_reconcile(self.mode)
            except Exception as exc:
                logger.warning("auto_reconcile_from_sync_failed", error=str(exc))
        else:
            await publish_portfolio_update(
                self.mode,
                {
                    "type": "order_status",
                    "order_id": order_id,
                    "stock_code": order["stock_code"],
                    "status": new_status,
                    "filled_quantity": filled_qty,
                    "old_status": old_status,
                },
            )

        return {
            "order_id": order_id,
            "changed": True,
            "old_status": old_status,
            "new_status": new_status,
            "filled_quantity": filled_qty,
            "avg_fill_price": avg_price,
        }
