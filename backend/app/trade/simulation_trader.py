"""模拟交易：真实行情优先 + A 股规则本地撮合（非券商实盘）。"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import FEATURE_TRADE, get_logger
from app.core.timeutil import today_cn
from app.data.service import DataService
from app.data.research_profiles import ResearchDataRequirementProfile
from app.trade.account_ledger import recompute_account_assets, release_t1_available_qty
from app.trade.ashare_rules import (
    MarketSnapshot,
    build_snapshot_from_kline,
    build_snapshot_from_quote,
    check_limit_board,
    fees,
    is_continuous_auction,
    is_order_accept_time,
    resolve_fill_price,
    validate_lot,
    validate_price_tick,
)
from app.trade.base_trader import (
    AccountInfo,
    BaseTrader,
    FillResult,
    OrderRequest,
    OrderResult,
    Position,
)
from app.trade.idempotency import build_idempotency_key

logger = get_logger(__name__, feature=FEATURE_TRADE)


class SimulationTrader(BaseTrader):
    def __init__(self, db: AsyncSession, data_service: DataService) -> None:
        self.db = db
        self.data = data_service
        self.mode = "simulation"

    async def _maybe_release_t1(self) -> dict:
        """
        T+1 释放：仅释放「今日无买入成交」的标的可卖数量。
        避免把当日新买的仓位错误放开。
        """
        today = today_cn()  # date 对象，避免 asyncpg 把 str 绑成 date 失败
        result = await self.db.execute(
            text(
                """
                UPDATE trade.positions p
                SET available_qty = total_qty,
                    updated_at = NOW()
                WHERE p.mode = :mode
                  AND p.total_qty > 0
                  AND p.available_qty < p.total_qty
                  AND NOT EXISTS (
                    SELECT 1 FROM trade.orders o
                    WHERE o.stock_code = p.stock_code
                      AND o.mode = p.mode
                      AND o.side = 'BUY'
                      AND o.status = 'FILLED'
                      AND (timezone('Asia/Shanghai', o.filled_at))::date = :today
                  )
                """
            ),
            {"mode": self.mode, "today": today},
        )
        n = int(result.rowcount or 0)
        if n:
            logger.info("simulation_t1_released", released_rows=n, today=str(today))
        return {"released_rows": n, "today": str(today)}

    async def _resolve_market(self, code: str) -> MarketSnapshot | None:
        """优先真实行情；失败再用日 K 收盘价。"""
        code = str(code).zfill(6)
        # 1) 实时/近实时行情（腾讯/通达信等，经 a-stock-data）
        try:
            quote = await self.data.get_quote(code)
            if quote:
                snap = build_snapshot_from_quote(code, quote)
                if snap:
                    return snap
        except Exception as exc:
            logger.warning("simulation_quote_failed", code=code, error=str(exc))

        # 2) 远程/本地日 K
        try:
            klines = await self.data.get_certified_kline(
                code,
                "1d",
                5,
                "raw",
                "execution_reference",
                "EXECUTION_REFERENCE_V1",
                list(
                    ResearchDataRequirementProfile.get(
                        "EXECUTION_REFERENCE_V1"
                    ).required_fields
                ),
            )
            if klines:
                snap = build_snapshot_from_kline(code, klines)
                if snap:
                    return snap
        except Exception as exc:
            logger.warning("simulation_kline_failed", code=code, error=str(exc))
        return None

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        order_id = str(uuid.uuid4())
        code = str(request.stock_code).zfill(6)
        logger.info(
            "simulation_submit_start",
            order_id=order_id,
            stock_code=code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )

        await self._maybe_release_t1()

        # —— 交易时段 ——
        allow_off = bool(getattr(settings, "SIM_ALLOW_OFF_HOURS", True))
        in_session = is_order_accept_time()
        if not in_session and not allow_off:
            return OrderResult(
                order_id=order_id,
                status="FAILED",
                message="非 A 股交易时段（工作日 09:15-11:30、13:00-15:00，北京时间）",
            )

        # —— 手数 ——
        lot_err = validate_lot(code, int(request.quantity), request.side)
        # 卖出清仓允许零股：若持仓不足一手
        if lot_err and request.side == "SELL":
            pos = await self._get_position(code)
            if pos and pos.available_qty == request.quantity and request.quantity % 100 != 0:
                lot_err = None
        if lot_err:
            return OrderResult(order_id=order_id, status="FAILED", message=lot_err)

        # 限价自动规范到 0.01 元
        if request.order_type == "LIMIT" and request.limit_price is not None:
            from app.trade.ashare_rules import normalize_limit_price

            request.limit_price = normalize_limit_price(float(request.limit_price))
            pe = validate_price_tick(request.limit_price)
            if pe:
                return OrderResult(order_id=order_id, status="FAILED", message=pe)

        # —— 真实行情 ——
        snap = await self._resolve_market(code)
        if snap is None:
            return OrderResult(
                order_id=order_id,
                status="FAILED",
                message="无法获取真实行情，请检查 a-stock-data 或网络后重试",
            )

        logger.info(
            "simulation_price_resolved",
            order_id=order_id,
            stock_code=code,
            price=snap.price,
            prev_close=snap.prev_close,
            limit_up=snap.limit_up,
            limit_down=snap.limit_down,
            source=snap.source,
            in_session=in_session,
            continuous=is_continuous_auction(),
        )

        board_err = check_limit_board(request.side, snap)
        if board_err:
            return OrderResult(order_id=order_id, status="FAILED", message=board_err)

        fill_price, fill_note, fill_status = resolve_fill_price(
            request.side,
            request.order_type,
            float(request.limit_price) if request.limit_price is not None else None,
            snap,
        )
        if fill_status == "FAILED":
            return OrderResult(
                order_id=order_id,
                status="FAILED",
                message=fill_note or "无法成交",
            )
        if fill_status == "SUBMITTED":
            await self._insert_pending_order(order_id, request, code)
            return OrderResult(
                order_id=order_id,
                status="SUBMITTED",
                message=fill_note or "限价单已挂出，等待触及成交",
            )

        assert fill_price is not None
        amount = fill_price * request.quantity
        commission, stamp_tax, _ = fees(request.side, amount)
        total_buy_cost = amount + commission

        if request.side == "BUY":
            account = await self.get_account_info()
            if account.cash < total_buy_cost:
                return OrderResult(
                    order_id=order_id,
                    status="FAILED",
                    message=f"资金不足：需要¥{total_buy_cost:.2f}，可用¥{account.cash:.2f}",
                )
        else:
            position = await self._get_position(code)
            available = position.available_qty if position else 0
            if available < request.quantity:
                return OrderResult(
                    order_id=order_id,
                    status="FAILED",
                    message=(
                        f"可卖数量不足（T+1）：需要 {request.quantity} 股，可卖 {available} 股。"
                        "当日买入次一交易日才可卖出。"
                    ),
                )

        signal_id = request.signal_id or "manual"
        idempotency_key = build_idempotency_key(
            mode=self.mode,
            signal_id=signal_id,
            stock_code=code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )

        await self._execute_fill_transaction(
            order_id=order_id,
            request=request,
            stock_code=code,
            idempotency_key=idempotency_key,
            fill_price=fill_price,
            quantity=request.quantity,
            commission=commission,
            stamp_tax=stamp_tax,
            amount=amount,
        )

        src_note = "真实行情" if snap.source == "quote" else "日K收盘(行情暂不可用)"
        session_note = "" if in_session else "；非交易时段按最近行情模拟"
        note_extra = f"；{fill_note}" if fill_note else ""
        logger.info(
            "simulation_submit_filled",
            order_id=order_id,
            stock_code=code,
            side=request.side,
            quantity=request.quantity,
            fill_price=fill_price,
            commission=commission,
            stamp_tax=stamp_tax,
            price_source=snap.source,
        )
        return OrderResult(
            order_id=order_id,
            status="FILLED",
            message=(
                f"模拟成交[{src_note}]：{request.side} {request.quantity}股 "
                f"@{fill_price:.2f} 佣金¥{commission:.2f}"
                f"{' 印花税¥' + f'{stamp_tax:.2f}' if stamp_tax else ''}"
                f"{session_note}{note_extra}"
            ),
        )

    async def _insert_pending_order(
        self, order_id: str, request: OrderRequest, code: str
    ) -> None:
        signal_id = request.signal_id or "manual"
        idempotency_key = build_idempotency_key(
            mode=self.mode,
            signal_id=signal_id,
            stock_code=code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )
        await self.db.execute(
            text(
                """
                INSERT INTO trade.orders
                (id, idempotency_key, stock_code, signal_id, strategy_id,
                 side, order_type, quantity, limit_price, filled_quantity,
                 avg_fill_price, commission, status, mode,
                 trigger_source, operator, order_source, order_reason, caller,
                 approval_status, approval_id, risk_check_id, data_certification_status,
                 created_by, created_from_task, submitted_at)
                VALUES
                (:id, :idempotency_key, :stock_code, NULLIF(:signal_id, 'manual')::uuid,
                 :strategy_id, :side, :order_type, :quantity, :limit_price, 0,
                 NULL, 0, 'SUBMITTED', :mode,
                 :trigger_source, :operator, :order_source, :order_reason, :caller,
                 :approval_status, :approval_id, :risk_check_id, :data_certification_status,
                 :created_by, :created_from_task, NOW())
                """
            ),
            {
                "id": order_id,
                "idempotency_key": idempotency_key,
                "stock_code": code,
                "signal_id": signal_id,
                "strategy_id": request.strategy_id,
                "side": request.side,
                "order_type": request.order_type,
                "quantity": request.quantity,
                "limit_price": request.limit_price,
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
            },
        )
        await self.db.execute(
            text(
                """
                INSERT INTO trade.order_history (order_id, from_status, to_status, changed_by)
                VALUES (:order_id, 'PENDING', 'SUBMITTED', 'simulation_engine')
                """
            ),
            {"order_id": order_id},
        )

    async def _execute_fill_transaction(
        self,
        order_id: str,
        request: OrderRequest,
        stock_code: str,
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
                 trigger_source, operator, order_source, order_reason, caller,
                 approval_status, approval_id, risk_check_id, data_certification_status,
                 created_by, created_from_task, submitted_at, filled_at)
                VALUES
                (:id, :idempotency_key, :stock_code, NULLIF(:signal_id, 'manual')::uuid,
                 :strategy_id, :side, :order_type, :quantity, :limit_price, :filled_quantity,
                 :avg_fill_price, :commission, 'FILLED', :mode,
                 :trigger_source, :operator, :order_source, :order_reason, :caller,
                 :approval_status, :approval_id, :risk_check_id, :data_certification_status,
                 :created_by, :created_from_task, NOW(), NOW())
                """
            ),
            {
                "id": order_id,
                "idempotency_key": idempotency_key,
                "stock_code": stock_code,
                "signal_id": request.signal_id or "manual",
                "strategy_id": request.strategy_id,
                "side": request.side,
                "order_type": request.order_type,
                "quantity": quantity,
                "limit_price": request.limit_price,
                "filled_quantity": quantity,
                "avg_fill_price": fill_price,
                "commission": commission + stamp_tax,
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
            },
        )

        if request.side == "BUY":
            await self._update_position_buy(stock_code, quantity, fill_price, amount)
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = cash - :cost, record_time = NOW()
                    WHERE id = (
                        SELECT id FROM trade.account_records
                        WHERE mode = :mode
                        ORDER BY record_time DESC LIMIT 1
                    )
                    """
                ),
                {"cost": amount + commission, "mode": self.mode},
            )
        else:
            await self._update_position_sell(stock_code, quantity, fill_price)
            net_proceeds = amount - commission - stamp_tax
            await self.db.execute(
                text(
                    """
                    UPDATE trade.account_records
                    SET cash = cash + :proceeds, record_time = NOW()
                    WHERE id = (
                        SELECT id FROM trade.account_records
                        WHERE mode = :mode
                        ORDER BY record_time DESC LIMIT 1
                    )
                    """
                ),
                {"proceeds": net_proceeds, "mode": self.mode},
            )

        await recompute_account_assets(self.db, self.mode)
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
            # T+1：当日新买不可卖，available 保持原可卖
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
                    "available_qty": max(new_available, 0),
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
        await self._maybe_release_t1()
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
        """用真实行情刷新持仓市值。"""
        await self._maybe_release_t1()
        positions = await self.get_positions()
        for pos in positions:
            snap = await self._resolve_market(pos.stock_code)
            if not snap:
                continue
            price = snap.price
            market_value = price * pos.total_qty
            unrealized_pnl = (price - pos.avg_cost) * pos.total_qty
            unrealized_pnl_pct = (price / pos.avg_cost - 1) * 100 if pos.avg_cost > 0 else 0
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
        await recompute_account_assets(self.db, self.mode)
