from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog

from app.backtest.calendar import build_trading_days, next_trading_day
from app.backtest.schemas import (
    BacktestConfig,
    BacktestResult,
    BacktestSignal,
    DailyBar,
    EquityPoint,
    PositionSnapshot,
    SignalGenerator,
    TradeRecord,
)

logger = structlog.get_logger(__name__)


@dataclass
class _Position:
    stock_code: str
    total_qty: int = 0
    available_qty: int = 0
    avg_cost: float = 0.0
    total_cost: float = 0.0


@dataclass
class _PendingOrder:
    stock_code: str
    side: str
    quantity: int
    signal_date: date
    execution_date: date
    order_type: str = "MARKET"
    limit_price: float | None = None
    reason: str = ""


class BacktestEngine:
    """
    A 股回测撮合引擎。

    规则：
    - 信号基于 T 日收盘后数据产生，T+1 日开盘执行（连续竞价简化版）
    - T+1 持仓限制：当日买入次日才可卖
    - 涨跌停、停牌无法成交
    - 手续费 + 印花税 + 滑点
    """

    BOARD_LIMIT_PCT = {
        "主板": 0.10,
        "创业板": 0.20,
        "科创板": 0.20,
        "北交所": 0.30,
    }

    def __init__(self, stock_meta: dict[str, dict[str, Any]] | None = None) -> None:
        self.stock_meta = stock_meta or {}

    def run(
        self,
        config: BacktestConfig,
        bars_by_stock: dict[str, dict[date, DailyBar]],
        signal_generator: SignalGenerator | None = None,
        signals: list[BacktestSignal] | None = None,
        *,
        strategy_code: str | None = None,
        financial_data_used: bool = True,
        skip_lookahead_check: bool = False,
    ) -> BacktestResult:
        lookahead_warnings: list[dict[str, str]] = []
        if strategy_code and not skip_lookahead_check:
            from app.backtest.lookahead_checker import LookaheadChecker, LookaheadError

            check_result = LookaheadChecker().check(
                strategy_code,
                financial_data_used=financial_data_used,
            )
            if not check_result.passed:
                raise LookaheadError(check_result)
            lookahead_warnings = [
                i for i in check_result.issues if i.get("severity") == "WARNING"
            ]
            logger.info(
                "lookahead_check_passed",
                warnings=check_result.warning_count,
            )

        trading_days = build_trading_days(config.start_date, config.end_date, bars_by_stock)
        if not trading_days:
            raise ValueError("回测区间内无有效交易日")

        cash = float(config.initial_cash)
        positions: dict[str, _Position] = {}
        pending_orders: list[_PendingOrder] = []
        trades: list[TradeRecord] = []
        equity_curve: list[EquityPoint] = []
        prev_total_assets = cash

        preset_signals = self._group_signals_by_date(signals or [])

        for trade_date in trading_days:
            self._release_t1_holdings(positions)

            day_orders = [o for o in pending_orders if o.execution_date == trade_date]
            pending_orders = [o for o in pending_orders if o.execution_date != trade_date]

            for order in day_orders:
                record, cash_delta = self._execute_order(order, trade_date, bars_by_stock, config, positions, cash)
                trades.append(record)
                if record.status == "FILLED":
                    cash += cash_delta

            market_value = self._mark_to_market(trade_date, positions, bars_by_stock)
            total_assets = cash + market_value
            daily_return = (total_assets / prev_total_assets - 1) if prev_total_assets > 0 else 0.0
            equity_curve.append(
                EquityPoint(
                    trade_date=trade_date,
                    cash=cash,
                    market_value=market_value,
                    total_assets=total_assets,
                    daily_return=daily_return,
                )
            )
            prev_total_assets = total_assets

            day_signals: list[BacktestSignal] = []
            if signal_generator:
                snapshots = self._position_snapshots(positions, bars_by_stock, trade_date)
                day_signals = signal_generator(trade_date, snapshots, bars_by_stock)
            day_signals.extend(preset_signals.get(trade_date, []))

            for sig in day_signals:
                if sig.stock_code not in config.universe:
                    continue
                exec_date = next_trading_day(sig.signal_date, trading_days)
                if exec_date is None:
                    continue
                pending_orders.append(
                    _PendingOrder(
                        stock_code=sig.stock_code,
                        side=sig.side.upper(),
                        quantity=self._normalize_quantity(sig.quantity, config.lot_size),
                        signal_date=sig.signal_date,
                        execution_date=exec_date,
                        order_type=sig.order_type,
                        limit_price=sig.limit_price,
                        reason=sig.reason,
                    )
                )

        final_mv = equity_curve[-1].market_value if equity_curve else 0.0
        filled = sum(1 for t in trades if t.status == "FILLED")
        failed = len(trades) - filled
        total_return = (
            (equity_curve[-1].total_assets / config.initial_cash - 1) if equity_curve else 0.0
        )

        logger.info(
            "backtest_done",
            trading_days=len(trading_days),
            filled_trades=filled,
            failed_trades=failed,
            total_return=round(total_return, 4),
        )

        metadata: dict[str, Any] = {}
        if lookahead_warnings:
            metadata["lookahead_warnings"] = lookahead_warnings

        return BacktestResult(
            config=config,
            trades=trades,
            equity_curve=equity_curve,
            final_cash=cash,
            final_market_value=final_mv,
            total_return=total_return,
            trading_days=len(trading_days),
            filled_trades=filled,
            failed_trades=failed,
            metadata=metadata,
        )

    def _execute_order(
        self,
        order: _PendingOrder,
        execution_date: date,
        bars_by_stock: dict[str, dict[date, DailyBar]],
        config: BacktestConfig,
        positions: dict[str, _Position],
        cash: float,
    ) -> tuple[TradeRecord, float]:
        bar = bars_by_stock.get(order.stock_code, {}).get(execution_date)
        base_record = TradeRecord(
            stock_code=order.stock_code,
            side=order.side,
            signal_date=order.signal_date,
            execution_date=execution_date,
            quantity=order.quantity,
            fill_price=0.0,
            amount=0.0,
            commission=0.0,
            stamp_tax=0.0,
            slippage_cost=0.0,
            status="FAILED",
        )

        if bar is None or bar.is_suspended or bar.volume <= 0:
            base_record.fail_reason = "SUSPENDED"
            return base_record, 0.0

        if order.quantity <= 0 or order.quantity % config.lot_size != 0:
            base_record.fail_reason = "INVALID_QUANTITY"
            return base_record, 0.0

        limit_pct = self._limit_pct(order.stock_code, bar)
        prev_close = bar.prev_close or bar.open
        limit_up = prev_close * (1 + limit_pct)
        limit_down = prev_close * (1 - limit_pct)

        if order.side == "BUY" and self._is_limit_up(bar, limit_up):
            base_record.fail_reason = "LIMIT_UP"
            return base_record, 0.0
        if order.side == "SELL" and self._is_limit_down(bar, limit_down):
            base_record.fail_reason = "LIMIT_DOWN"
            return base_record, 0.0

        ref_price = bar.open if config.execution_mode == "open_auction" else bar.close
        fill_price, slippage_per_share = self._apply_slippage(
            ref_price, order.side, config.slippage_rate, limit_up, limit_down
        )
        slippage_cost = slippage_per_share * order.quantity

        if order.order_type == "LIMIT" and order.limit_price is not None:
            if order.side == "BUY" and fill_price > order.limit_price:
                base_record.fail_reason = "LIMIT_NOT_REACHED"
                return base_record, 0.0
            if order.side == "SELL" and fill_price < order.limit_price:
                base_record.fail_reason = "LIMIT_NOT_REACHED"
                return base_record, 0.0
            fill_price = order.limit_price

        amount = fill_price * order.quantity
        commission = max(amount * config.commission_rate, config.min_commission)
        stamp_tax = amount * config.stamp_tax_rate if order.side == "SELL" else 0.0
        cash_delta = 0.0

        if order.side == "BUY":
            total_cost = amount + commission
            if cash < total_cost:
                base_record.fail_reason = "INSUFFICIENT_CASH"
                return base_record, 0.0
            pos = positions.setdefault(order.stock_code, _Position(stock_code=order.stock_code))
            new_total = pos.total_qty + order.quantity
            pos.avg_cost = (pos.total_cost + amount) / new_total if new_total > 0 else 0.0
            pos.total_cost += amount
            pos.total_qty = new_total
            cash_delta = -total_cost
        else:
            pos = positions.get(order.stock_code)
            if not pos or pos.available_qty < order.quantity:
                base_record.fail_reason = "INSUFFICIENT_POSITION"
                return base_record, 0.0
            proceeds = amount - commission - stamp_tax
            pos.available_qty -= order.quantity
            pos.total_qty -= order.quantity
            pos.total_cost = pos.avg_cost * pos.total_qty
            if pos.total_qty <= 0:
                positions.pop(order.stock_code, None)
            cash_delta = proceeds

        return (
            TradeRecord(
                stock_code=order.stock_code,
                side=order.side,
                signal_date=order.signal_date,
                execution_date=execution_date,
                quantity=order.quantity,
                fill_price=round(fill_price, 4),
                amount=round(amount, 2),
                commission=round(commission, 2),
                stamp_tax=round(stamp_tax, 2),
                slippage_cost=round(slippage_cost, 2),
                status="FILLED",
            ),
            cash_delta,
        )

    @staticmethod
    def _release_t1_holdings(positions: dict[str, _Position]) -> None:
        for pos in positions.values():
            pos.available_qty = pos.total_qty

    def _mark_to_market(
        self,
        trade_date: date,
        positions: dict[str, _Position],
        bars_by_stock: dict[str, dict[date, DailyBar]],
    ) -> float:
        total = 0.0
        for code, pos in positions.items():
            bar = bars_by_stock.get(code, {}).get(trade_date)
            price = bar.close if bar else pos.avg_cost
            total += price * pos.total_qty
        return total

    @staticmethod
    def _apply_slippage(
        price: float,
        side: str,
        slippage_rate: float,
        limit_up: float,
        limit_down: float,
    ) -> tuple[float, float]:
        if side == "BUY":
            raw = price * (1 + slippage_rate)
            fill = min(raw, limit_up)
        else:
            raw = price * (1 - slippage_rate)
            fill = max(raw, limit_down)
        return fill, abs(fill - price)

    @staticmethod
    def _is_limit_up(bar: DailyBar, limit_up: float) -> bool:
        return bar.open >= limit_up * 0.999 or (bar.high == bar.low and bar.close >= limit_up * 0.999)

    @staticmethod
    def _is_limit_down(bar: DailyBar, limit_down: float) -> bool:
        return bar.open <= limit_down * 1.001 or (bar.high == bar.low and bar.close <= limit_down * 1.001)

    def _limit_pct(self, stock_code: str, bar: DailyBar) -> float:
        if bar.is_st:
            return 0.05
        board = self.stock_meta.get(stock_code, {}).get("board", "主板")
        return self.BOARD_LIMIT_PCT.get(board, 0.10)

    @staticmethod
    def _normalize_quantity(quantity: int, lot_size: int) -> int:
        if quantity <= 0:
            return 0
        return max((quantity // lot_size) * lot_size, lot_size)

    @staticmethod
    def _group_signals_by_date(signals: list[BacktestSignal]) -> dict[date, list[BacktestSignal]]:
        grouped: dict[date, list[BacktestSignal]] = {}
        for sig in signals:
            grouped.setdefault(sig.signal_date, []).append(sig)
        return grouped

    @staticmethod
    def _position_snapshots(
        positions: dict[str, _Position],
        bars_by_stock: dict[str, dict[date, DailyBar]],
        trade_date: date,
    ) -> dict[str, PositionSnapshot]:
        snapshots: dict[str, PositionSnapshot] = {}
        for code, pos in positions.items():
            bar = bars_by_stock.get(code, {}).get(trade_date)
            price = bar.close if bar else pos.avg_cost
            snapshots[code] = PositionSnapshot(
                stock_code=code,
                total_qty=pos.total_qty,
                available_qty=pos.available_qty,
                avg_cost=pos.avg_cost,
                market_price=price,
                market_value=price * pos.total_qty,
            )
        return snapshots

    @staticmethod
    def bars_from_rows(rows: list[dict[str, Any]]) -> dict[str, dict[date, DailyBar]]:
        """将 K 线记录列表转为引擎输入格式。"""
        result: dict[str, dict[date, DailyBar]] = {}
        for row in rows:
            code = row["stock_code"]
            trade_date = row["trade_date"]
            if isinstance(trade_date, str):
                trade_date = date.fromisoformat(trade_date[:10])

            suspended = bool(row.get("is_suspended")) or int(row.get("volume") or 0) <= 0
            result.setdefault(code, {})[trade_date] = DailyBar(
                trade_date=trade_date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row.get("volume") or 0),
                amount=float(row.get("amount") or 0),
                prev_close=float(row["prev_close"]) if row.get("prev_close") else None,
                turnover_rate=float(row["turnover_rate"]) if row.get("turnover_rate") else None,
                is_suspended=suspended,
                is_st=bool(row.get("is_st")),
            )
        return result