"""基于 QmtAdapter 的 paper/live 交易器（本地订单落库 + 券商/Mock 成交）。"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import FEATURE_TRADE, get_logger
from app.trade.account_ledger import recompute_account_assets
from app.trade.base_trader import (
    AccountInfo,
    BaseTrader,
    FillResult,
    OrderRequest,
    OrderResult,
    Position,
)
from app.trade.idempotency import build_idempotency_key
from app.trade.qmt.adapter import QmtAdapter

logger = get_logger(__name__, feature=FEATURE_TRADE)


class LiveTrader(BaseTrader):
    """
    mode=paper → Mock 适配器
    mode=live  → XtQuant 或 Mock 降级
    """

    def __init__(
        self,
        db: AsyncSession,
        adapter: QmtAdapter,
        *,
        mode: str = "paper",
    ) -> None:
        self.db = db
        self.adapter = adapter
        self.mode = mode
        self._connected = False

    async def _ensure_connected(self) -> None:
        if not self._connected:
            ok = await self.adapter.connect()
            if not ok:
                raise RuntimeError(f"{self.adapter.name} 连接失败")
            self._connected = True
            # 注册成交回调 → 本地同步
            try:
                from app.trade.order_event_bridge import order_event_bridge

                order_event_bridge.attach(self.adapter, self.mode)
            except Exception as exc:
                logger.warning("order_event_bridge_attach_failed", error=str(exc))

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        await self._ensure_connected()
        order_id = str(uuid.uuid4())
        logger.info(
            "live_submit_start",
            mode=self.mode,
            order_id=order_id,
            adapter=getattr(self.adapter, "name", type(self.adapter).__name__),
            stock_code=request.stock_code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )
        idempotency_key = build_idempotency_key(
            mode=self.mode,
            signal_id=request.signal_id,
            stock_code=request.stock_code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )

        try:
            broker_order = await self.adapter.submit_order(
                stock_code=request.stock_code,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
                limit_price=request.limit_price,
            )
        except Exception as exc:
            logger.error(
                "live_submit_failed",
                error=str(exc),
                mode=self.mode,
                order_id=order_id,
                stock_code=request.stock_code,
                exc_info=True,
            )
            return OrderResult(
                order_id=order_id,
                status="FAILED",
                message=f"券商下单失败: {exc}",
            )

        status = broker_order.status
        commission = 0.0
        if status == "FILLED" and broker_order.avg_fill_price > 0:
            amount = broker_order.avg_fill_price * broker_order.filled_quantity
            commission = max(amount * 0.0003, 5.0)

        await self.db.execute(
            text(
                """
                INSERT INTO trade.orders
                (id, idempotency_key, stock_code, signal_id, strategy_id,
                 side, order_type, quantity, limit_price, filled_quantity,
                 avg_fill_price, commission, status, mode,
                 trigger_source, operator, order_source, order_reason, caller,
                 approval_status, approval_id, risk_check_id, data_certification_status,
                 created_by, created_from_task, submitted_at, filled_at, broker_order_id, reject_reason)
                VALUES
                (:id, :idempotency_key, :stock_code, NULLIF(:signal_id, 'manual')::uuid,
                 :strategy_id, :side, :order_type, :quantity, :limit_price, :filled_quantity,
                 :avg_fill_price, :commission, :status, :mode,
                 :trigger_source, :operator, :order_source, :order_reason, :caller,
                 :approval_status, :approval_id, :risk_check_id, :data_certification_status,
                 :created_by, :created_from_task, NOW(),
                 CASE WHEN :status = 'FILLED' THEN NOW() ELSE NULL END,
                 :broker_order_id, :reject_reason)
                """
            ),
            {
                "id": order_id,
                "idempotency_key": idempotency_key,
                "stock_code": request.stock_code,
                "signal_id": request.signal_id or "manual",
                "strategy_id": request.strategy_id,
                "side": request.side,
                "order_type": request.order_type,
                "quantity": request.quantity,
                "limit_price": request.limit_price,
                "filled_quantity": broker_order.filled_quantity,
                "avg_fill_price": broker_order.avg_fill_price or None,
                "commission": commission,
                "status": status if status in (
                    "PENDING", "SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "FAILED"
                ) else "FAILED",
                "mode": self.mode,
                "trigger_source": request.trigger_source,
                "operator": request.operator,
                "order_source": request.trigger_source,
                "order_reason": request.order_reason,
                "caller": request.caller,
                "approval_status": request.approval_status,
                "approval_id": request.approval_id,
                "risk_check_id": request.risk_check_id,
                "data_certification_status": request.data_certification_status,
                "created_by": request.operator,
                "created_from_task": request.created_from_task,
                "broker_order_id": broker_order.broker_order_id,
                "reject_reason": broker_order.message if status == "FAILED" else None,
            },
        )

        if status == "FILLED":
            # Mock：以适配器账本为源镜像到 DB，避免双套现金/佣金算法漂移
            if getattr(self.adapter, "name", "") == "mock":
                await self._mirror_broker_state_to_local()
            else:
                await self._sync_fill_to_local(
                    request,
                    fill_price=broker_order.avg_fill_price,
                    quantity=broker_order.filled_quantity,
                    commission=commission,
                )
                await recompute_account_assets(self.db, self.mode)

        # 本地订单已落库后再推送事件，避免回调找不到本地单
        if broker_order.broker_order_id:
            try:
                self.adapter.emit_order_event(broker_order)
            except Exception as exc:
                logger.warning("post_insert_emit_failed", error=str(exc))

        return OrderResult(
            order_id=order_id,
            status=status,
            broker_order_id=broker_order.broker_order_id,
            message=broker_order.message or f"{self.adapter.name}:{status}",
        )

    async def _mirror_broker_state_to_local(self) -> None:
        """将适配器账户/持仓全量镜像到本地表（paper/Mock 专用）。"""
        await self._ensure_connected()
        remote_pos = await self.adapter.get_positions()
        remote_codes = {p.stock_code for p in remote_pos}
        for rp in remote_pos:
            await self.db.execute(
                text(
                    """
                    INSERT INTO trade.positions
                    (stock_code, mode, total_qty, available_qty, avg_cost, total_cost,
                     current_price, market_value)
                    VALUES (:code, :mode, :qty, :avail, :avg, :cost, :price, :mv)
                    ON CONFLICT (stock_code, mode) DO UPDATE SET
                        total_qty = EXCLUDED.total_qty,
                        available_qty = EXCLUDED.available_qty,
                        avg_cost = EXCLUDED.avg_cost,
                        total_cost = EXCLUDED.total_cost,
                        market_value = EXCLUDED.market_value,
                        current_price = EXCLUDED.current_price,
                        updated_at = NOW()
                    """
                ),
                {
                    "code": rp.stock_code,
                    "mode": self.mode,
                    "qty": rp.total_qty,
                    "avail": rp.available_qty,
                    "avg": rp.avg_cost,
                    "cost": rp.avg_cost * rp.total_qty,
                    "price": rp.avg_cost,
                    "mv": rp.market_value or rp.avg_cost * rp.total_qty,
                },
            )
        # 删除适配器已无的本地持仓
        if remote_codes:
            from sqlalchemy import bindparam

            stmt = text(
                """
                DELETE FROM trade.positions
                WHERE mode = :mode AND stock_code NOT IN :codes
                """
            ).bindparams(bindparam("codes", expanding=True))
            await self.db.execute(
                stmt, {"mode": self.mode, "codes": list(remote_codes)}
            )
        else:
            await self.db.execute(
                text("DELETE FROM trade.positions WHERE mode = :mode"),
                {"mode": self.mode},
            )

        acc = await self.adapter.get_account()
        # 更新或插入账户快照
        existing = await self.db.execute(
            text(
                """
                SELECT id FROM trade.account_records
                WHERE mode = :mode ORDER BY record_time DESC LIMIT 1
                """
            ),
            {"mode": self.mode},
        )
        row = existing.mappings().first()
        if row:
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = :cash,
                        market_value = :mv,
                        total_assets = :total,
                        frozen_cash = :frozen,
                        position_count = :pcnt,
                        record_time = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": row["id"],
                    "cash": acc.cash,
                    "mv": acc.market_value,
                    "total": acc.total_assets,
                    "frozen": acc.frozen_cash,
                    "pcnt": len(remote_pos),
                },
            )
        else:
            await self.db.execute(
                text(
                    """
                    INSERT INTO trade.account_records
                    (mode, total_assets, cash, market_value, frozen_cash, position_count, data_type)
                    VALUES (:mode, :total, :cash, :mv, :frozen, :pcnt, 'snapshot')
                    """
                ),
                {
                    "mode": self.mode,
                    "total": acc.total_assets,
                    "cash": acc.cash,
                    "mv": acc.market_value,
                    "frozen": acc.frozen_cash,
                    "pcnt": len(remote_pos),
                },
            )

    async def _sync_fill_to_local(
        self,
        request: OrderRequest,
        *,
        fill_price: float,
        quantity: int,
        commission: float,
    ) -> None:
        """将 Mock/券商成交镜像到本地 positions/account（便于统一风控展示）。"""
        amount = fill_price * quantity
        stamp = amount * 0.0005 if request.side == "SELL" else 0.0

        if request.side == "BUY":
            existing = await self._get_position_row(request.stock_code)
            if existing:
                new_qty = existing["total_qty"] + quantity
                new_cost = (
                    float(existing["avg_cost"]) * existing["total_qty"] + amount
                ) / new_qty
                await self.db.execute(
                    text(
                        """
                        UPDATE trade.positions
                        SET total_qty = :qty, avg_cost = :avg_cost,
                            total_cost = total_cost + :amount,
                            current_price = :price,
                            market_value = :qty * :price,
                            updated_at = NOW()
                        WHERE stock_code = :code AND mode = :mode
                        """
                    ),
                    {
                        "qty": new_qty,
                        "avg_cost": new_cost,
                        "amount": amount,
                        "price": fill_price,
                        "code": request.stock_code,
                        "mode": self.mode,
                    },
                )
            else:
                await self.db.execute(
                    text(
                        """
                        INSERT INTO trade.positions
                        (stock_code, mode, total_qty, available_qty, avg_cost, total_cost,
                         current_price, market_value)
                        VALUES (:code, :mode, :qty, 0, :avg, :amount, :price, :mv)
                        """
                    ),
                    {
                        "code": request.stock_code,
                        "mode": self.mode,
                        "qty": quantity,
                        "avg": fill_price,
                        "amount": amount,
                        "price": fill_price,
                        "mv": amount,
                    },
                )
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = cash - :cost, record_time = NOW()
                    WHERE id = (
                        SELECT id FROM trade.account_records
                        WHERE mode = :mode ORDER BY record_time DESC LIMIT 1
                    )
                    """
                ),
                {"cost": amount + commission, "mode": self.mode},
            )
        else:
            existing = await self._get_position_row(request.stock_code)
            if not existing:
                return
            new_qty = existing["total_qty"] - quantity
            new_avail = max(0, existing["available_qty"] - quantity)
            if new_qty <= 0:
                await self.db.execute(
                    text(
                        "DELETE FROM trade.positions WHERE stock_code = :code AND mode = :mode"
                    ),
                    {"code": request.stock_code, "mode": self.mode},
                )
            else:
                await self.db.execute(
                    text(
                        """
                        UPDATE trade.positions
                        SET total_qty = :qty, available_qty = :avail,
                            total_cost = avg_cost * :qty,
                            current_price = :price,
                            market_value = :qty * :price,
                            updated_at = NOW()
                        WHERE stock_code = :code AND mode = :mode
                        """
                    ),
                    {
                        "qty": new_qty,
                        "avail": new_avail,
                        "price": fill_price,
                        "code": request.stock_code,
                        "mode": self.mode,
                    },
                )
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = cash + :proceeds, record_time = NOW()
                    WHERE id = (
                        SELECT id FROM trade.account_records
                        WHERE mode = :mode ORDER BY record_time DESC LIMIT 1
                    )
                    """
                ),
                {"proceeds": amount - commission - stamp, "mode": self.mode},
            )

    async def _get_position_row(self, code: str) -> dict | None:
        result = await self.db.execute(
            text(
                "SELECT * FROM trade.positions WHERE stock_code = :code AND mode = :mode"
            ),
            {"code": code, "mode": self.mode},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def cancel_order(self, order_id: str) -> bool:
        await self._ensure_connected()
        result = await self.db.execute(
            text("SELECT broker_order_id FROM trade.orders WHERE id = :id"),
            {"id": order_id},
        )
        row = result.mappings().first()
        if not row or not row["broker_order_id"]:
            return False
        ok = await self.adapter.cancel_order(row["broker_order_id"])
        if ok:
            await self.db.execute(
                text(
                    """
                    UPDATE trade.orders
                    SET status = 'CANCELLED', cancelled_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": order_id},
            )
        return ok

    async def get_order_status(self, order_id: str) -> FillResult:
        result = await self.db.execute(
            text("SELECT * FROM trade.orders WHERE id = :id"),
            {"id": order_id},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"Order not found: {order_id}")
        return FillResult(
            order_id=order_id,
            status=row["status"],
            filled_quantity=row["filled_quantity"] or 0,
            avg_fill_price=float(row["avg_fill_price"] or 0),
            commission=float(row["commission"] or 0),
            filled_at=row["filled_at"],
        )

    async def get_positions(self) -> list[Position]:
        result = await self.db.execute(
            text("SELECT * FROM trade.positions WHERE mode = :mode"),
            {"mode": self.mode},
        )
        return [
            Position(
                stock_code=row["stock_code"],
                total_qty=row["total_qty"],
                available_qty=row["available_qty"],
                avg_cost=float(row["avg_cost"] or 0),
                current_price=float(row["current_price"] or 0),
                market_value=float(row["market_value"] or 0),
                unrealized_pnl=float(row["unrealized_pnl"] or 0),
                unrealized_pnl_pct=float(row["unrealized_pnl_pct"] or 0),
            )
            for row in result.mappings().all()
        ]

    async def get_account_info(self) -> AccountInfo:
        result = await self.db.execute(
            text(
                """
                SELECT * FROM trade.account_records
                WHERE mode = :mode ORDER BY record_time DESC LIMIT 1
                """
            ),
            {"mode": self.mode},
        )
        row = result.mappings().first()
        if not row:
            await self._ensure_connected()
            acc = await self.adapter.get_account()
            return AccountInfo(
                total_assets=acc.total_assets,
                cash=acc.cash,
                market_value=acc.market_value,
                frozen_cash=acc.frozen_cash,
            )
        return AccountInfo(
            total_assets=float(row["total_assets"]),
            cash=float(row["cash"]),
            market_value=float(row["market_value"]),
            frozen_cash=float(row["frozen_cash"] or 0),
            daily_pnl=float(row["daily_pnl"] or 0),
            total_pnl=float(row["total_pnl"] or 0),
        )

    async def sync_positions(self) -> None:
        await self._ensure_connected()
        remote = await self.adapter.get_positions()
        for rp in remote:
            await self.db.execute(
                text(
                    """
                    INSERT INTO trade.positions
                    (stock_code, mode, total_qty, available_qty, avg_cost, total_cost,
                     current_price, market_value)
                    VALUES (:code, :mode, :qty, :avail, :avg, :cost, :price, :mv)
                    ON CONFLICT (stock_code, mode) DO UPDATE SET
                        total_qty = EXCLUDED.total_qty,
                        available_qty = EXCLUDED.available_qty,
                        avg_cost = EXCLUDED.avg_cost,
                        market_value = EXCLUDED.market_value,
                        updated_at = NOW()
                    """
                ),
                {
                    "code": rp.stock_code,
                    "mode": self.mode,
                    "qty": rp.total_qty,
                    "avail": rp.available_qty,
                    "avg": rp.avg_cost,
                    "cost": rp.avg_cost * rp.total_qty,
                    "price": rp.avg_cost,
                    "mv": rp.market_value or rp.avg_cost * rp.total_qty,
                },
            )
        await recompute_account_assets(self.db, self.mode)
