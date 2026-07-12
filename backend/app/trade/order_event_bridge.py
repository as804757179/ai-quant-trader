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
                        SELECT id, status FROM trade.orders
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
                # 用 query 路径统一更新；若 query 不到则直接用回调数据
                detail = await syncer.sync_order_by_id(str(local["id"]))
                if not detail.get("changed") and broker_order.status != local["status"]:
                    # query 可能仍返回旧状态，强制用回调写入
                    detail = await syncer.apply_broker_snapshot(
                        str(local["id"]),
                        {
                            "id": str(local["id"]),
                            "stock_code": broker_order.stock_code,
                            "side": broker_order.side,
                            "quantity": broker_order.quantity,
                            "status": local["status"],
                            "filled_quantity": 0,
                            "broker_order_id": broker_order.broker_order_id,
                        },
                        broker_order,
                    )

        if detail.get("new_status") == "FILLED" and getattr(
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
