import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.service import DataService
from app.trade.base_trader import (
    AccountInfo,
    BaseTrader,
    FillResult,
    OrderRequest,
    OrderResult,
    Position,
)

logger = structlog.get_logger()


class SimulationTrader(BaseTrader):
    COMMISSION_RATE = 0.0003
    STAMP_TAX_RATE = 0.0005
    SLIPPAGE_RATE = 0.001
    MIN_COMMISSION = 5.0

    def __init__(self, db: AsyncSession, data_service: DataService) -> None:
        self.db = db
        self.data = data_service
        self.mode = "simulation"

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        order_id = str(uuid.uuid4())
        quote = await self.data.get_quote(request.stock_code)
        if quote is None:
            return OrderResult(order_id=order_id, status="FAILED", message="无法获取行情")

        current_price = float(quote["price"])
        prev_close = float(quote.get("prev_close") or current_price)
        limit_up = float(quote.get("limit_up") or prev_close * 1.10)
        limit_down = float(quote.get("limit_down") or prev_close * 0.90)

        if request.side == "BUY" and current_price >= limit_up * 0.999:
            return OrderResult(order_id=order_id, status="FAILED", message="涨停板，无法买入")
        if request.side == "SELL" and current_price <= limit_down * 1.001:
            return OrderResult(order_id=order_id, status="FAILED", message="跌停板，无法卖出")

        if request.order_type == "MARKET":
            fill_price = (
                min(current_price * (1 + self.SLIPPAGE_RATE), limit_up)
                if request.side == "BUY"
                else max(current_price * (1 - self.SLIPPAGE_RATE), limit_down)
            )
        else:
            if request.limit_price is None:
                return OrderResult(order_id=order_id, status="FAILED", message="限价单缺少价格")
            if request.side == "BUY" and current_price > request.limit_price:
                return OrderResult(order_id=order_id, status="SUBMITTED", message="限价单等待成交")
            if request.side == "SELL" and current_price < request.limit_price:
                return OrderResult(order_id=order_id, status="SUBMITTED", message="限价单等待成交")
            fill_price = request.limit_price

        amount = fill_price * request.quantity
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_tax = amount * self.STAMP_TAX_RATE if request.side == "SELL" else 0.0
        total_cost = amount + commission + stamp_tax

        if request.side == "BUY":
            account = await self.get_account_info()
            if account.cash < total_cost:
                return OrderResult(
                    order_id=order_id,
                    status="FAILED",
                    message=f"资金不足，需要¥{total_cost:.2f}，可用¥{account.cash:.2f}",
                )
        else:
            position = await self._get_position(request.stock_code)
            available = position.available_qty if position else 0
            if available < request.quantity:
                return OrderResult(
                    order_id=order_id,
                    status="FAILED",
                    message=f"可卖数量不足，需要{request.quantity}股，可用{available}股",
                )

        signal_id = request.signal_id or "manual"
        idempotency_key = f"{signal_id}:{request.stock_code}:{request.side}:{request.quantity}"

        await self._execute_fill_transaction(
            order_id=order_id,
            request=request,
            idempotency_key=idempotency_key,
            fill_price=fill_price,
            quantity=request.quantity,
            commission=commission,
            stamp_tax=stamp_tax,
            amount=amount,
        )

        return OrderResult(
            order_id=order_id,
            status="FILLED",
            message=f"模拟成交：{request.side} {request.quantity}股 @{fill_price:.2f}",
        )

    async def _execute_fill_transaction(
        self,
        order_id: str,
        request: OrderRequest,
        idempotency_key: str,
        fill_price: float,
        quantity: int,
        commission: float,
        stamp_tax: float,
        amount: float,
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO trade.orders
                (id, idempotency_key, stock_code, signal_id, strategy_id,
                 side, order_type, quantity, limit_price, filled_quantity,
                 avg_fill_price, commission, status, mode,
                 trigger_source, operator, submitted_at, filled_at)
                VALUES
                (:id, :idempotency_key, :stock_code, NULLIF(:signal_id, 'manual')::uuid,
                 :strategy_id, :side, :order_type, :quantity, :limit_price, :filled_quantity,
                 :avg_fill_price, :commission, 'FILLED', :mode,
                 :trigger_source, :operator, NOW(), NOW())
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
                "quantity": quantity,
                "limit_price": request.limit_price,
                "filled_quantity": quantity,
                "avg_fill_price": fill_price,
                "commission": commission,
                "mode": self.mode,
                "trigger_source": request.trigger_source,
                "operator": request.operator,
            },
        )

        if request.side == "BUY":
            await self._update_position_buy(request.stock_code, quantity, fill_price, amount)
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = cash - :cost,
                        market_value = market_value + :amount,
                        record_time = NOW()
                    WHERE mode = :mode
                    """
                ),
                {"cost": amount + commission, "amount": amount, "mode": self.mode},
            )
        else:
            await self._update_position_sell(request.stock_code, quantity, fill_price)
            net_proceeds = amount - commission - stamp_tax
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = cash + :proceeds,
                        market_value = market_value - :amount,
                        record_time = NOW()
                    WHERE mode = :mode
                    """
                ),
                {"proceeds": net_proceeds, "amount": amount, "mode": self.mode},
            )

        await self.db.execute(
            text(
                """
                INSERT INTO trade.order_history (order_id, from_status, to_status, changed_by)
                VALUES (:order_id, 'PENDING', 'FILLED', 'simulation_engine')
                """
            ),
            {"order_id": order_id},
        )

    async def _update_position_buy(
        self, stock_code: str, quantity: int, fill_price: float, amount: float
    ) -> None:
        existing = await self._get_position(stock_code)
        if existing:
            new_qty = existing.total_qty + quantity
            new_cost = (existing.total_qty * existing.avg_cost + amount) / new_qty
            await self.db.execute(
                text(
                    """
                    UPDATE trade.positions
                    SET total_qty = :total_qty,
                        avg_cost = :avg_cost,
                        total_cost = total_cost + :amount,
                        current_price = :price,
                        market_value = :total_qty * :price,
                        updated_at = NOW()
                    WHERE stock_code = :code AND mode = :mode
                    """
                ),
                {
                    "total_qty": new_qty,
                    "avg_cost": new_cost,
                    "amount": amount,
                    "price": fill_price,
                    "code": stock_code,
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
                    VALUES (:code, :mode, :qty, 0, :avg_cost, :amount, :price, :market_value)
                    """
                ),
                {
                    "code": stock_code,
                    "mode": self.mode,
                    "qty": quantity,
                    "avg_cost": fill_price,
                    "amount": amount,
                    "price": fill_price,
                    "market_value": fill_price * quantity,
                },
            )

    async def _update_position_sell(
        self, stock_code: str, quantity: int, fill_price: float
    ) -> None:
        existing = await self._get_position(stock_code)
        if not existing:
            raise ValueError(f"持仓不存在：{stock_code}")
        realized_pnl = (fill_price - existing.avg_cost) * quantity
        new_qty = existing.total_qty - quantity
        new_available = existing.available_qty - quantity
        if new_qty <= 0:
            await self.db.execute(
                text("DELETE FROM trade.positions WHERE stock_code = :code AND mode = :mode"),
                {"code": stock_code, "mode": self.mode},
            )
        else:
            await self.db.execute(
                text(
                    """
                    UPDATE trade.positions
                    SET total_qty = :total_qty,
                        available_qty = :available_qty,
                        total_cost = avg_cost * :total_qty,
                        realized_pnl = realized_pnl + :realized_pnl,
                        current_price = :price,
                        market_value = :total_qty * :price,
                        updated_at = NOW()
                    WHERE stock_code = :code AND mode = :mode
                    """
                ),
                {
                    "total_qty": new_qty,
                    "available_qty": new_available,
                    "realized_pnl": realized_pnl,
                    "price": fill_price,
                    "code": stock_code,
                    "mode": self.mode,
                },
            )

    async def _get_position(self, stock_code: str) -> Position | None:
        result = await self.db.execute(
            text("SELECT * FROM trade.positions WHERE stock_code = :code AND mode = :mode"),
            {"code": stock_code, "mode": self.mode},
        )
        row = result.mappings().first()
        if not row:
            return None
        return Position(
            stock_code=row["stock_code"],
            total_qty=row["total_qty"],
            available_qty=row["available_qty"],
            avg_cost=float(row["avg_cost"] or 0),
            current_price=float(row["current_price"] or 0),
            market_value=float(row["market_value"] or 0),
            unrealized_pnl=float(row["unrealized_pnl"] or 0),
            unrealized_pnl_pct=float(row["unrealized_pnl_pct"] or 0),
        )

    async def cancel_order(self, order_id: str) -> bool:
        result = await self.db.execute(
            text(
                """
                UPDATE trade.orders
                SET status = 'CANCELLED', cancelled_at = NOW()
                WHERE id = :id AND status IN ('PENDING', 'SUBMITTED')
                """
            ),
            {"id": order_id},
        )
        return result.rowcount > 0

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
                WHERE mode = :mode
                ORDER BY record_time DESC
                LIMIT 1
                """
            ),
            {"mode": self.mode},
        )
        row = result.mappings().first()
        if not row:
            return AccountInfo(total_assets=0, cash=0, market_value=0)
        return AccountInfo(
            total_assets=float(row["total_assets"]),
            cash=float(row["cash"]),
            market_value=float(row["market_value"]),
            frozen_cash=float(row["frozen_cash"] or 0),
            daily_pnl=float(row["daily_pnl"] or 0),
            total_pnl=float(row["total_pnl"] or 0),
        )

    async def sync_positions(self) -> None:
        positions = await self.get_positions()
        for pos in positions:
            quote = await self.data.get_quote(pos.stock_code)
            if not quote:
                continue
            price = float(quote["price"])
            market_value = price * pos.total_qty
            unrealized_pnl = (price - pos.avg_cost) * pos.total_qty
            unrealized_pnl_pct = (
                (price / pos.avg_cost - 1) * 100 if pos.avg_cost > 0 else 0
            )
            await self.db.execute(
                text(
                    """
                    UPDATE trade.positions
                    SET current_price = :price,
                        market_value = :market_value,
                        unrealized_pnl = :unrealized_pnl,
                        unrealized_pnl_pct = :unrealized_pnl_pct,
                        updated_at = NOW()
                    WHERE stock_code = :code AND mode = :mode
                    """
                ),
                {
                    "price": price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "code": pos.stock_code,
                    "mode": self.mode,
                },
            )