"""内存 Mock 券商 — 无 miniQMT 时用于 paper / 联调。"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.trade.qmt.adapter import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    QmtAdapter,
)

logger = structlog.get_logger(__name__)


class MockQmtAdapter(QmtAdapter):
    name = "mock"

    def __init__(
        self,
        *,
        initial_cash: float = 1_000_000.0,
        fill_slippage: float = 0.001,
        deferred_fill: bool = False,
    ) -> None:
        super().__init__()
        self.initial_cash = initial_cash
        self.fill_slippage = fill_slippage
        # True 时先返回 SUBMITTED，需 force_fill 才成交（测状态同步）
        self.deferred_fill = deferred_fill
        self._connected = False
        self._cash = initial_cash
        self._positions: dict[str, dict[str, Any]] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._pending_fills: dict[str, dict[str, Any]] = {}

    async def connect(self) -> bool:
        self._connected = True
        logger.info("mock_qmt_connected", cash=self._cash)
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    async def get_account(self) -> BrokerAccount:
        mv = sum(
            float(p.get("market_value") or p["total_qty"] * p["avg_cost"])
            for p in self._positions.values()
        )
        return BrokerAccount(
            total_assets=self._cash + mv,
            cash=self._cash,
            market_value=mv,
        )

    async def get_positions(self) -> list[BrokerPosition]:
        out: list[BrokerPosition] = []
        for code, p in self._positions.items():
            out.append(
                BrokerPosition(
                    stock_code=code,
                    total_qty=int(p["total_qty"]),
                    available_qty=int(p["available_qty"]),
                    avg_cost=float(p["avg_cost"]),
                    market_value=float(
                        p.get("market_value") or p["total_qty"] * p["avg_cost"]
                    ),
                )
            )
        return out

    async def submit_order(
        self,
        *,
        stock_code: str,
        side: str,
        quantity: int,
        order_type: str = "LIMIT",
        limit_price: float | None = None,
    ) -> BrokerOrder:
        if not self._connected:
            await self.connect()

        oid = f"MOCK-{uuid.uuid4().hex[:12].upper()}"
        if quantity <= 0 or quantity % 100 != 0:
            order = BrokerOrder(
                broker_order_id=oid,
                stock_code=stock_code,
                side=side,
                quantity=quantity,
                status="FAILED",
                message="数量非法",
            )
            self._orders[oid] = order
            return order

        price = float(limit_price or 0)
        if price <= 0:
            order = BrokerOrder(
                broker_order_id=oid,
                stock_code=stock_code,
                side=side,
                quantity=quantity,
                status="FAILED",
                message="Mock 需要有效价格",
            )
            self._orders[oid] = order
            return order

        fill = (
            price * (1 + self.fill_slippage)
            if side == "BUY"
            else price * (1 - self.fill_slippage)
        )

        if self.deferred_fill:
            # 挂单：资金/持仓预检但不立即成交
            if side == "BUY":
                cost = fill * quantity
                if self._cash < cost:
                    order = BrokerOrder(
                        broker_order_id=oid,
                        stock_code=stock_code,
                        side=side,
                        quantity=quantity,
                        status="FAILED",
                        message="Mock 资金不足",
                    )
                    self._orders[oid] = order
                    return order
            else:
                pos = self._positions.get(stock_code)
                if not pos or pos["available_qty"] < quantity:
                    order = BrokerOrder(
                        broker_order_id=oid,
                        stock_code=stock_code,
                        side=side,
                        quantity=quantity,
                        status="FAILED",
                        message="Mock 可卖不足",
                    )
                    self._orders[oid] = order
                    return order
            order = BrokerOrder(
                broker_order_id=oid,
                stock_code=stock_code,
                side=side,
                quantity=quantity,
                status="SUBMITTED",
                filled_quantity=0,
                avg_fill_price=0.0,
                message="Mock 挂单等待成交",
            )
            self._orders[oid] = order
            self._pending_fills[oid] = {
                "stock_code": stock_code,
                "side": side,
                "quantity": quantity,
                "fill": fill,
            }
            return order

        apply_err = self._apply_fill(stock_code, side, quantity, fill)
        if apply_err:
            order = BrokerOrder(
                broker_order_id=oid,
                stock_code=stock_code,
                side=side,
                quantity=quantity,
                status="FAILED",
                message=apply_err,
            )
            self._orders[oid] = order
            return order

        order = BrokerOrder(
            broker_order_id=oid,
            stock_code=stock_code,
            side=side,
            quantity=quantity,
            status="FILLED",
            filled_quantity=quantity,
            avg_fill_price=round(fill, 4),
            message=f"Mock 成交 @{fill:.4f}",
        )
        self._orders[oid] = order
        # 不在此处 emit：本地订单尚未 INSERT，由 LiveTrader 落库后再 emit_order_event
        return order

    def _apply_fill(
        self, stock_code: str, side: str, quantity: int, fill: float
    ) -> str | None:
        if side == "BUY":
            cost = fill * quantity
            if self._cash < cost:
                return "Mock 资金不足"
            self._cash -= cost
            pos = self._positions.get(stock_code)
            if pos:
                new_qty = pos["total_qty"] + quantity
                pos["avg_cost"] = (pos["avg_cost"] * pos["total_qty"] + cost) / new_qty
                pos["total_qty"] = new_qty
                pos["market_value"] = new_qty * fill
            else:
                self._positions[stock_code] = {
                    "total_qty": quantity,
                    "available_qty": 0,
                    "avg_cost": fill,
                    "market_value": quantity * fill,
                }
        else:
            pos = self._positions.get(stock_code)
            if not pos or pos["available_qty"] < quantity:
                return "Mock 可卖不足"
            proceeds = fill * quantity
            self._cash += proceeds
            pos["available_qty"] -= quantity
            pos["total_qty"] -= quantity
            if pos["total_qty"] <= 0:
                del self._positions[stock_code]
            else:
                pos["market_value"] = pos["total_qty"] * fill
        return None

    def force_fill(self, broker_order_id: str) -> BrokerOrder | None:
        """测试/联调：将挂单强制成交。"""
        pending = self._pending_fills.pop(broker_order_id, None)
        order = self._orders.get(broker_order_id)
        if not pending or not order:
            return order
        err = self._apply_fill(
            pending["stock_code"],
            pending["side"],
            pending["quantity"],
            pending["fill"],
        )
        if err:
            order.status = "FAILED"
            order.message = err
            return order
        order.status = "FILLED"
        order.filled_quantity = pending["quantity"]
        order.avg_fill_price = round(pending["fill"], 4)
        order.message = f"Mock 延迟成交 @{order.avg_fill_price:.4f}"
        self.emit_order_event(order)
        return order

    async def cancel_order(self, broker_order_id: str) -> bool:
        order = self._orders.get(broker_order_id)
        if not order or order.status not in ("PENDING", "SUBMITTED"):
            return False
        order.status = "CANCELLED"
        return True

    async def query_order(self, broker_order_id: str) -> BrokerOrder | None:
        return self._orders.get(broker_order_id)

    def release_t1(self) -> None:
        """测试辅助：释放 T+1 可卖。"""
        for p in self._positions.values():
            p["available_qty"] = p["total_qty"]
