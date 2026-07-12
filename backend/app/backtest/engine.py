from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import structlog

from app.backtest.calendar import build_trading_days, next_trading_day
from app.backtest.corporate_actions import (
    CorporateActionEntitlement,
    CorporateActionEvent,
    CorporateActionProcessor,
)
from app.backtest.market_rules import (
    AshareMarketRuleRegistry,
    MarketRuleError,
    ResolvedMarketRules,
    SecurityStatusSnapshot,
)
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
    realized_pnl: float = 0.0


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
    VERSION = "backtest-engine-v2-market-rules"
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

    def __init__(
        self,
        stock_meta: dict[str, dict[str, Any]] | None = None,
        *,
        rule_registry: AshareMarketRuleRegistry | None = None,
        security_statuses: dict[str, SecurityStatusSnapshot] | None = None,
    ) -> None:
        self.stock_meta = stock_meta or {}
        self.rule_registry = rule_registry or AshareMarketRuleRegistry()
        self.security_statuses = security_statuses or {}

    def run(
        self,
        config: BacktestConfig,
        bars_by_stock: dict[str, dict[date, DailyBar]],
        signal_generator: SignalGenerator | None = None,
        signals: list[BacktestSignal] | None = None,
        *,
        initial_positions: dict[str, dict[str, float | int]] | None = None,
        corporate_actions: list[CorporateActionEvent] | None = None,
        corporate_action_policy: str | None = None,
        strategy_code: str | None = None,
        financial_data_used: bool = True,
        skip_lookahead_check: bool = False,
    ) -> BacktestResult:
        lookahead_warnings: list[dict[str, str]] = []
        action_events = corporate_actions or []
        if action_events and corporate_action_policy != CorporateActionProcessor.POLICY:
            raise ValueError("explicit gross corporate action policy is required")
        for event in action_events:
            CorporateActionProcessor.validate_event(event)
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

        trading_days = build_trading_days(
            config.start_date,
            config.end_date,
            bars_by_stock,
            certified_calendar=config.trusted_calendar,
            require_certified=config.trusted_mode,
        )
        if not trading_days:
            raise ValueError("回测区间内无有效交易日")

        cash = float(config.initial_cash)
        positions: dict[str, _Position] = {
            code: _Position(
                stock_code=code,
                total_qty=int(state["total_qty"]),
                available_qty=int(state.get("available_qty", state["total_qty"])),
                avg_cost=float(state["total_cost"]) / int(state["total_qty"]),
                total_cost=float(state["total_cost"]),
                realized_pnl=float(state.get("realized_pnl", 0.0)),
            )
            for code, state in (initial_positions or {}).items()
            if int(state["total_qty"]) > 0
        }
        pending_orders: list[_PendingOrder] = []
        trades: list[TradeRecord] = []
        equity_curve: list[EquityPoint] = []
        signal_audit: list[dict[str, Any]] = []
        execution_audit: list[dict[str, Any]] = []
        daily_audit: list[dict[str, Any]] = []
        prev_total_assets = cash
        market_rule_versions: set[str] = set()
        action_entitlements: dict[str, CorporateActionEntitlement] = {}
        applied_share_actions: set[str] = set()
        applied_cash_actions: set[str] = set()
        corporate_action_income = Decimal("0")
        corporate_action_audit: list[dict[str, Any]] = []

        preset_signals = self._group_signals_by_date(signals or [])

        for trade_date in trading_days:
            day_cash_before = cash
            day_positions_before = self._positions_state(positions)
            day_action_audit: list[dict[str, Any]] = []
            for event in action_events:
                entitlement = action_entitlements.get(event.action_id)
                if entitlement is None:
                    continue
                position = positions.get(event.stock_code)
                if event.share_credit_date == trade_date and event.action_id not in applied_share_actions:
                    if entitlement.share_increase:
                        if position is None:
                            raise ValueError("corporate action position disappeared before share credit")
                        position.total_qty += entitlement.share_increase
                        position.avg_cost = position.total_cost / position.total_qty
                    applied_share_actions.add(event.action_id)
                    day_action_audit.append({"action_id": event.action_id, "type": "share_credit", "quantity": entitlement.share_increase})
                if event.cash_payment_date == trade_date and event.action_id not in applied_cash_actions:
                    cash_amount = entitlement.gross_cash_dividend
                    cash += float(cash_amount)
                    corporate_action_income += cash_amount
                    applied_cash_actions.add(event.action_id)
                    day_action_audit.append({"action_id": event.action_id, "type": "gross_cash_dividend", "amount": str(cash_amount)})
            self._release_t1_holdings(positions)

            day_orders = [o for o in pending_orders if o.execution_date == trade_date]
            pending_orders = [o for o in pending_orders if o.execution_date != trade_date]

            for order in day_orders:
                cash_before = cash
                position_before = self._positions_state(positions).get(
                    order.stock_code, {"total_qty": 0, "available_qty": 0}
                )
                resolved_rules = None
                if config.trusted_mode:
                    status = self.security_statuses.get(order.stock_code)
                    if status is not None:
                        try:
                            resolved_rules = self.rule_registry.resolve(trade_date, status)
                            market_rule_versions.update(resolved_rules.rule_versions)
                        except MarketRuleError:
                            resolved_rules = None
                record, cash_delta = self._execute_order(
                    order,
                    trade_date,
                    bars_by_stock,
                    config,
                    positions,
                    cash,
                    resolved_rules=resolved_rules,
                    trusted_mode=config.trusted_mode,
                    security_status=self.security_statuses.get(order.stock_code),
                )
                trades.append(record)
                if record.status == "FILLED":
                    cash += cash_delta
                execution_audit.append(
                    {
                        "signal_date": order.signal_date.isoformat(),
                        "information_cutoff": order.signal_date.isoformat(),
                        "execution_date": trade_date.isoformat(),
                        "execution_price_source": (
                            "next_trading_day_open"
                            if config.execution_mode == "open_auction"
                            else "next_trading_day_close"
                        ),
                        "signal": order.side,
                        "order": {"side": order.side, "quantity": order.quantity},
                        "fill": {
                            "status": record.status,
                            "price": record.fill_price,
                            "fail_reason": record.fail_reason,
                        },
                        "position_before": position_before,
                        "position_after": self._positions_state(positions).get(
                            order.stock_code, {"total_qty": 0, "available_qty": 0}
                        ),
                        "cash_before": round(cash_before, 8),
                        "cash_after": round(cash, 8),
                    }
                )

            for event in action_events:
                if event.record_date != trade_date or event.action_id in action_entitlements:
                    continue
                eligible_quantity = positions.get(event.stock_code, _Position(event.stock_code)).total_qty
                entitlement = CorporateActionProcessor.calculate_entitlement(event, eligible_quantity)
                action_entitlements[event.action_id] = entitlement
                day_action_audit.append({
                    "action_id": event.action_id,
                    "type": "record_date_entitlement",
                    "eligible_quantity": eligible_quantity,
                    "share_increase": entitlement.share_increase,
                    "gross_cash_dividend": str(entitlement.gross_cash_dividend),
                })

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
                buy_lot_size = config.lot_size
                if config.trusted_mode:
                    status = self.security_statuses.get(sig.stock_code)
                    if status is not None:
                        try:
                            buy_lot_size = self.rule_registry.resolve(
                                exec_date, status
                            ).buy_lot_size
                        except MarketRuleError:
                            pass
                normalized_quantity = self._normalize_order_quantity(
                    sig.side, sig.quantity, buy_lot_size
                )
                signal_audit.append(
                    {
                        "stock_code": sig.stock_code,
                        "signal_date": sig.signal_date.isoformat(),
                        "information_cutoff": trade_date.isoformat(),
                        "signal": sig.side.upper(),
                        "requested_quantity": sig.quantity,
                        "quantity": normalized_quantity,
                        "quantity_policy": (
                            "BUY_FLOOR_TO_LOT" if sig.side.upper() == "BUY" else "SELL_PRESERVE_REQUEST"
                        ),
                        "execution_date": exec_date.isoformat(),
                    }
                )
                pending_orders.append(
                    _PendingOrder(
                        stock_code=sig.stock_code,
                        side=sig.side.upper(),
                        quantity=normalized_quantity,
                        signal_date=sig.signal_date,
                        execution_date=exec_date,
                        order_type=sig.order_type,
                        limit_price=sig.limit_price,
                        reason=sig.reason,
                    )
                )
            daily_audit.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "cash_before": round(day_cash_before, 8),
                    "cash_after": round(cash, 8),
                    "positions_before": day_positions_before,
                    "positions_after": self._positions_accounting_state(
                        positions, trade_date, bars_by_stock
                    ),
                    "market_value": round(market_value, 8),
                    "total_assets": round(total_assets, 8),
                    "corporate_action_income": str(corporate_action_income),
                    "corporate_actions": day_action_audit,
                }
            )
            if not action_events:
                daily_audit[-1].pop("corporate_action_income")
                daily_audit[-1].pop("corporate_actions")
            corporate_action_audit.extend(
                {"trade_date": trade_date.isoformat(), **entry} for entry in day_action_audit
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

        metadata: dict[str, Any] = {
            "signal_audit": signal_audit,
            "execution_audit": execution_audit,
            "daily_audit": daily_audit,
            "market_rule_versions": sorted(market_rule_versions),
        }
        if action_events:
            metadata.update(
                {
                    "corporate_action_audit": corporate_action_audit,
                    "corporate_action_income": str(corporate_action_income),
                    "corporate_action_processor_version": CorporateActionProcessor.VERSION,
                    "corporate_action_policy": corporate_action_policy,
                    "corporate_action_daily_order": list(CorporateActionProcessor.DAILY_ORDER),
                    "corporate_action_versions": sorted(event.event_version for event in action_events),
                    "corporate_action_evidence_hashes": sorted(event.evidence_hash for event in action_events),
                }
            )
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
        *,
        resolved_rules: ResolvedMarketRules | None = None,
        trusted_mode: bool = False,
        security_status: SecurityStatusSnapshot | None = None,
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

        if trusted_mode and (resolved_rules is None or security_status is None):
            base_record.fail_reason = "MARKET_RULE_BLOCKED"
            return base_record, 0.0

        if (
            bar is None
            or bar.is_suspended
            or bar.volume <= 0
            or (security_status is not None and security_status.suspended)
        ):
            base_record.fail_reason = "SUSPENDED"
            return base_record, 0.0

        buy_lot_size = resolved_rules.buy_lot_size if resolved_rules else config.lot_size
        if order.quantity <= 0:
            base_record.fail_reason = "INVALID_QUANTITY"
            return base_record, 0.0
        if order.side == "BUY" and order.quantity % buy_lot_size != 0:
            base_record.fail_reason = "INVALID_QUANTITY"
            return base_record, 0.0
        if order.side == "SELL":
            pos = positions.get(order.stock_code)
            if not pos or pos.available_qty < order.quantity:
                base_record.fail_reason = "INSUFFICIENT_POSITION"
                return base_record, 0.0
            sell_lot_size = (
                resolved_rules.sell_lot_size if resolved_rules else config.lot_size
            )
            odd_lot_policy = (
                resolved_rules.odd_lot_sell_policy
                if resolved_rules
                else "FULL_ODD_LOT_ONLY"
            )
            if not self._valid_sell_quantity(
                order.quantity,
                pos.available_qty,
                sell_lot_size,
                odd_lot_policy,
            ):
                base_record.fail_reason = "INVALID_ODD_LOT_SELL"
                return base_record, 0.0

        limit_pct = (
            resolved_rules.price_limit_rate
            if resolved_rules
            else self._limit_pct(order.stock_code, bar)
        )
        prev_close = bar.prev_close or bar.open
        if resolved_rules and limit_pct is not None:
            try:
                limit_up_decimal, limit_down_decimal = self.rule_registry.price_limits(
                    prev_close, limit_pct, resolved_rules
                )
            except MarketRuleError:
                base_record.fail_reason = "MARKET_RULE_BLOCKED"
                return base_record, 0.0
            limit_up = float(limit_up_decimal)
            limit_down = float(limit_down_decimal)
        else:
            limit_up = prev_close * (1 + limit_pct) if limit_pct is not None else float("inf")
            limit_down = prev_close * (1 - limit_pct) if limit_pct is not None else 0.0

        if order.side == "BUY" and Decimal(str(bar.open)) >= Decimal(str(limit_up)):
            base_record.fail_reason = "LIMIT_UP"
            return base_record, 0.0
        if order.side == "SELL" and Decimal(str(bar.open)) <= Decimal(str(limit_down)):
            base_record.fail_reason = "LIMIT_DOWN"
            return base_record, 0.0

        ref_price = bar.open if config.execution_mode == "open_auction" else bar.close
        slippage_rate = resolved_rules.slippage_rate if resolved_rules else config.slippage_rate
        fill_price, slippage_per_share = self._apply_slippage(
            ref_price, order.side, slippage_rate, limit_up, limit_down
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
        commission_rate = resolved_rules.commission_rate if resolved_rules else config.commission_rate
        minimum_commission = resolved_rules.minimum_commission if resolved_rules else config.min_commission
        stamp_rate = resolved_rules.stamp_duty_rate if resolved_rules else config.stamp_tax_rate
        transfer_rate = resolved_rules.transfer_fee_rate if resolved_rules else 0.0
        commission = max(amount * commission_rate, minimum_commission)
        stamp_tax = amount * stamp_rate if order.side == "SELL" else 0.0
        transfer_fee = amount * transfer_rate
        cash_delta = 0.0
        realized_pnl = 0.0

        if order.side == "BUY":
            total_cost = amount + commission + transfer_fee
            if cash < total_cost:
                base_record.fail_reason = "INSUFFICIENT_CASH"
                return base_record, 0.0
            pos = positions.setdefault(order.stock_code, _Position(stock_code=order.stock_code))
            new_total = pos.total_qty + order.quantity
            pos.total_cost += total_cost
            pos.avg_cost = pos.total_cost / new_total if new_total > 0 else 0.0
            pos.total_qty = new_total
            cash_delta = -total_cost
        else:
            pos = positions[order.stock_code]
            proceeds = amount - commission - stamp_tax - transfer_fee
            allocated_cost = pos.avg_cost * order.quantity
            realized_pnl = proceeds - allocated_cost
            pos.available_qty -= order.quantity
            pos.total_qty -= order.quantity
            pos.total_cost -= allocated_cost
            pos.realized_pnl += realized_pnl
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
                transfer_fee=round(transfer_fee, 2),
                realized_pnl=round(realized_pnl, 8),
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

    def _limit_pct(self, stock_code: str, bar: DailyBar) -> float:
        if bar.is_st:
            return 0.05
        code = stock_code.split(".", 1)[0]
        if code.startswith(("300", "301", "688", "689")):
            return 0.20
        if code.startswith(("4", "8")):
            return 0.30
        board = self.stock_meta.get(stock_code, {}).get("board", "主板")
        return self.BOARD_LIMIT_PCT.get(board, 0.10)

    @staticmethod
    def _positions_state(positions: dict[str, _Position]) -> dict[str, dict[str, Any]]:
        return {
            code: {
                "total_qty": pos.total_qty,
                "available_qty": pos.available_qty,
                "avg_cost": round(pos.avg_cost, 8),
                "total_cost": round(pos.total_cost, 8),
                "realized_pnl": round(pos.realized_pnl, 8),
            }
            for code, pos in sorted(positions.items())
        }

    @staticmethod
    def _positions_accounting_state(
        positions: dict[str, _Position],
        trade_date: date,
        bars_by_stock: dict[str, dict[date, DailyBar]],
    ) -> dict[str, dict[str, Any]]:
        state = BacktestEngine._positions_state(positions)
        for code, item in state.items():
            bar = bars_by_stock.get(code, {}).get(trade_date)
            price = bar.close if bar else positions[code].avg_cost
            market_value = price * positions[code].total_qty
            item["market_value"] = round(market_value, 8)
            item["unrealized_pnl"] = round(
                market_value - positions[code].total_cost, 8
            )
        return state

    @staticmethod
    def _normalize_order_quantity(side: str, quantity: int, buy_lot_size: int) -> int:
        if quantity <= 0:
            return 0
        if side.upper() == "SELL":
            return quantity
        if quantity < buy_lot_size:
            return quantity
        return (quantity // buy_lot_size) * buy_lot_size

    @staticmethod
    def _valid_sell_quantity(
        quantity: int,
        available_quantity: int,
        sell_lot_size: int,
        odd_lot_policy: str,
    ) -> bool:
        if quantity <= 0 or quantity > available_quantity:
            return False
        if quantity % sell_lot_size == 0:
            return True
        if odd_lot_policy != "FULL_ODD_LOT_ONLY":
            return False
        available_odd_lot = available_quantity % sell_lot_size
        requested_odd_lot = quantity % sell_lot_size
        return available_odd_lot > 0 and requested_odd_lot == available_odd_lot

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
                total_cost=pos.total_cost,
                realized_pnl=pos.realized_pnl,
                unrealized_pnl=price * pos.total_qty - pos.total_cost,
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
