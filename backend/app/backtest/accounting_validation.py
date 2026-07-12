from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.backtest.engine import BacktestEngine
from app.backtest.market_rules import (
    AshareMarketRuleRegistry,
    MarketRuleError,
    SecurityStatusSnapshot,
)
from app.backtest.schemas import BacktestConfig, BacktestSignal, DailyBar


DAYS = [date(2026, 6, day) for day in (1, 2, 3, 4, 5, 8, 9)]
CODE = "603986.SH"


def _status(start: date = DAYS[0], end: date = DAYS[-1]) -> SecurityStatusSnapshot:
    return SecurityStatusSnapshot(
        CODE,
        "SH",
        "MAIN",
        "NORMAL",
        start,
        end,
        False,
        False,
        True,
        "official validation fixture",
        AshareMarketRuleRegistry.SSE_RULES_2023,
        "603986-accounting-fixture-v1",
    )


def _bars(*, suspended_day: date | None = None, limit_up_day: date | None = None, limit_down_day: date | None = None, price: float = 10.0) -> dict[str, dict[date, DailyBar]]:
    output: dict[date, DailyBar] = {}
    previous = price
    for day in DAYS:
        current = price
        if day == limit_up_day:
            current = round(previous * 1.10, 2)
        elif day == limit_down_day:
            current = round(previous * 0.90, 2)
        output[day] = DailyBar(
            day,
            current,
            current,
            current,
            current,
            volume=0 if day == suspended_day else 1_000_000,
            prev_close=previous,
            is_suspended=day == suspended_day,
        )
        previous = current
    return {CODE: output}


def _config(initial_cash: float = 100_000.0) -> BacktestConfig:
    return BacktestConfig(
        DAYS[0],
        DAYS[-1],
        [CODE],
        initial_cash=initial_cash,
        trusted_mode=True,
        trusted_calendar=DAYS,
    )


def _trade_view(trade: Any) -> dict[str, Any]:
    return {
        "side": trade.side,
        "signal_date": trade.signal_date.isoformat(),
        "execution_date": trade.execution_date.isoformat(),
        "quantity": trade.quantity,
        "fill_price": trade.fill_price,
        "amount": trade.amount,
        "commission": trade.commission,
        "stamp_duty": trade.stamp_tax,
        "transfer_fee": trade.transfer_fee,
        "slippage": trade.slippage_cost,
        "realized_pnl": trade.realized_pnl,
        "status": trade.status,
        "fail_reason": trade.fail_reason,
    }


def _reference(
    signals: list[BacktestSignal],
    bars: dict[str, dict[date, DailyBar]],
    initial_cash: float,
    registry: AshareMarketRuleRegistry,
    status: SecurityStatusSnapshot,
    initial_position: dict[str, float | int] | None = None,
) -> dict[str, Any]:
    scheduled: dict[date, list[BacktestSignal]] = {}
    for signal in signals:
        index = DAYS.index(signal.signal_date)
        if index + 1 < len(DAYS):
            scheduled.setdefault(DAYS[index + 1], []).append(signal)
    cash = Decimal(str(initial_cash))
    quantity = int((initial_position or {}).get("total_qty", 0))
    available = int((initial_position or {}).get("available_qty", quantity))
    total_cost = Decimal(str((initial_position or {}).get("total_cost", 0)))
    realized_total = Decimal(str((initial_position or {}).get("realized_pnl", 0)))
    trades: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    for day in DAYS:
        positions_before = _position_view(
            quantity, available, total_cost, realized_total, bars[CODE][day].close
        )
        positions_before.pop("market_value", None)
        positions_before.pop("unrealized_pnl", None)
        available = quantity
        for signal in scheduled.get(day, []):
            rules = registry.resolve(day, status)
            bar = bars[CODE][day]
            if signal.side == "SELL":
                normalized = signal.quantity
            elif signal.quantity < rules.buy_lot_size:
                normalized = signal.quantity
            else:
                normalized = signal.quantity // rules.buy_lot_size * rules.buy_lot_size
            record = {
                "side": signal.side,
                "signal_date": signal.signal_date.isoformat(),
                "execution_date": day.isoformat(),
                "quantity": normalized,
                "fill_price": 0.0,
                "amount": 0.0,
                "commission": 0.0,
                "stamp_duty": 0.0,
                "transfer_fee": 0.0,
                "slippage": 0.0,
                "realized_pnl": 0.0,
                "status": "FAILED",
                "fail_reason": None,
            }
            if normalized <= 0 or (
                signal.side == "BUY" and normalized % rules.buy_lot_size != 0
            ):
                record["fail_reason"] = "INVALID_QUANTITY"
                trades.append(record)
                continue
            if signal.side == "SELL":
                if available < normalized:
                    record["fail_reason"] = "INSUFFICIENT_POSITION"
                    trades.append(record)
                    continue
                if not _reference_valid_sell_quantity(
                    normalized,
                    available,
                    rules.sell_lot_size,
                    rules.odd_lot_sell_policy,
                ):
                    record["fail_reason"] = "INVALID_ODD_LOT_SELL"
                    trades.append(record)
                    continue
            if bar.is_suspended or bar.volume <= 0:
                record["fail_reason"] = "SUSPENDED"
                trades.append(record)
                continue
            limit_up, limit_down = registry.price_limits(
                bar.prev_close, rules.price_limit_rate, rules
            )
            if signal.side == "BUY" and Decimal(str(bar.open)) >= limit_up:
                record["fail_reason"] = "LIMIT_UP"
                trades.append(record)
                continue
            if signal.side == "SELL" and Decimal(str(bar.open)) <= limit_down:
                record["fail_reason"] = "LIMIT_DOWN"
                trades.append(record)
                continue
            reference = Decimal(str(bar.open))
            rate = Decimal(str(rules.slippage_rate))
            raw_fill = reference * (Decimal("1") + rate if signal.side == "BUY" else Decimal("1") - rate)
            fill = min(raw_fill, limit_up) if signal.side == "BUY" else max(raw_fill, limit_down)
            amount = fill * normalized
            commission = max(amount * Decimal(str(rules.commission_rate)), Decimal(str(rules.minimum_commission)))
            stamp = amount * Decimal(str(rules.stamp_duty_rate)) if signal.side == "SELL" else Decimal("0")
            transfer = amount * Decimal(str(rules.transfer_fee_rate))
            record.update(
                {
                    "fill_price": round(float(fill), 4),
                    "amount": round(float(amount), 2),
                    "commission": round(float(commission), 2),
                    "stamp_duty": round(float(stamp), 2),
                    "transfer_fee": round(float(transfer), 2),
                    "slippage": round(float(abs(fill - reference) * normalized), 2),
                }
            )
            if signal.side == "BUY":
                debit = amount + commission + transfer
                if cash < debit:
                    record["fail_reason"] = "INSUFFICIENT_CASH"
                    _clear_unfilled_amounts(record)
                else:
                    cash -= debit
                    quantity += normalized
                    total_cost += debit
                    record["status"] = "FILLED"
            else:
                if available < normalized:
                    record["fail_reason"] = "INSUFFICIENT_POSITION"
                    _clear_unfilled_amounts(record)
                else:
                    average_cost = total_cost / quantity
                    allocated = average_cost * normalized
                    proceeds = amount - commission - stamp - transfer
                    realized = proceeds - allocated
                    cash += proceeds
                    quantity -= normalized
                    available -= normalized
                    total_cost -= allocated
                    realized_total += realized
                    if quantity == 0:
                        total_cost = Decimal("0")
                    record["realized_pnl"] = round(float(realized), 8)
                    record["status"] = "FILLED"
            trades.append(record)
        position = _position_view(quantity, available, total_cost, realized_total, bars[CODE][day].close)
        market_value = Decimal(str(bars[CODE][day].close)) * quantity
        daily.append(
            {
                "trade_date": day.isoformat(),
                "cash": round(float(cash), 8),
                "position": position,
                "market_value": round(float(market_value), 8),
                "total_assets": round(float(cash + market_value), 8),
                "position_before": positions_before,
            }
        )
    return {"trades": trades, "daily": daily}


def _reference_valid_sell_quantity(
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
    return (
        available_quantity % sell_lot_size > 0
        and quantity % sell_lot_size == available_quantity % sell_lot_size
    )


def _clear_unfilled_amounts(record: dict[str, Any]) -> None:
    for key in (
        "fill_price",
        "amount",
        "commission",
        "stamp_duty",
        "transfer_fee",
        "slippage",
        "realized_pnl",
    ):
        record[key] = 0.0


def _position_view(
    quantity: int,
    available: int,
    total_cost: Decimal,
    realized: Decimal,
    close: float,
) -> dict[str, Any]:
    if not quantity:
        return {}
    market_value = Decimal(str(close)) * quantity
    return {
        "total_qty": quantity,
        "available_qty": available,
        "avg_cost": round(float(total_cost / quantity), 8),
        "total_cost": round(float(total_cost), 8),
        "realized_pnl": round(float(realized), 8),
        "market_value": round(float(market_value), 8),
        "unrealized_pnl": round(float(market_value - total_cost), 8),
    }


def _engine_view(result: Any) -> dict[str, Any]:
    return {
        "trades": [_trade_view(trade) for trade in result.trades],
        "daily": [
            {
                "trade_date": point.trade_date.isoformat(),
                "cash": round(point.cash, 8),
                "position": audit["positions_after"].get(CODE, {}),
                "market_value": round(point.market_value, 8),
                "total_assets": round(point.total_assets, 8),
                "position_before": audit["positions_before"].get(CODE, {}),
            }
            for point, audit in zip(result.equity_curve, result.metadata["daily_audit"])
        ],
    }


def validate_accounting_scenarios() -> dict[str, Any]:
    registry = AshareMarketRuleRegistry()
    status = _status()
    scenarios = {
        "single_buy_full_sell": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "SELL", 100, DAYS[2])], _bars(), 100_000.0),
        "multiple_buys_full_sell": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "BUY", 100, DAYS[1]), BacktestSignal(CODE, "SELL", 200, DAYS[3])], _bars(), 100_000.0),
        "multiple_buys_partial_sell": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "BUY", 100, DAYS[1]), BacktestSignal(CODE, "SELL", 100, DAYS[3])], _bars(), 100_000.0),
        "partial_sell_then_buy": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "BUY", 100, DAYS[1]), BacktestSignal(CODE, "SELL", 100, DAYS[2]), BacktestSignal(CODE, "BUY", 100, DAYS[4])], _bars(), 100_000.0),
        "minimum_commission": ([BacktestSignal(CODE, "BUY", 100, DAYS[0])], _bars(price=1.0), 100_000.0),
        "insufficient_cash": ([BacktestSignal(CODE, "BUY", 100, DAYS[0])], _bars(), 500.0),
        "oversell": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "SELL", 200, DAYS[2])], _bars(), 100_000.0),
        "t_plus_one_same_execution_day": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "SELL", 100, DAYS[0])], _bars(), 100_000.0),
        "suspended": ([BacktestSignal(CODE, "BUY", 100, DAYS[0])], _bars(suspended_day=DAYS[1]), 100_000.0),
        "limit_up_buy": ([BacktestSignal(CODE, "BUY", 100, DAYS[0])], _bars(limit_up_day=DAYS[1]), 100_000.0),
        "limit_down_sell": ([BacktestSignal(CODE, "BUY", 100, DAYS[0]), BacktestSignal(CODE, "SELL", 100, DAYS[1])], _bars(limit_down_day=DAYS[2]), 100_000.0),
        "odd_lot_140_full_sell": ([BacktestSignal(CODE, "SELL", 140, DAYS[0])], _bars(), 100_000.0, {"total_qty": 140, "available_qty": 140, "total_cost": 1400.0}),
        "odd_lot_140_sell_round_lot": ([BacktestSignal(CODE, "SELL", 100, DAYS[0])], _bars(), 100_000.0, {"total_qty": 140, "available_qty": 140, "total_cost": 1400.0}),
        "odd_lot_40_full_sell": ([BacktestSignal(CODE, "SELL", 40, DAYS[0])], _bars(), 100_000.0, {"total_qty": 40, "available_qty": 40, "total_cost": 400.0}),
        "odd_lot_40_partial_rejected": ([BacktestSignal(CODE, "SELL", 20, DAYS[0])], _bars(), 100_000.0, {"total_qty": 40, "available_qty": 40, "total_cost": 400.0}),
        "odd_lot_split_rejected": ([BacktestSignal(CODE, "SELL", 20, DAYS[0]), BacktestSignal(CODE, "SELL", 20, DAYS[1])], _bars(), 100_000.0, {"total_qty": 140, "available_qty": 140, "total_cost": 1400.0}),
        "buy_odd_lot_40_rejected": ([BacktestSignal(CODE, "BUY", 40, DAYS[0])], _bars(), 100_000.0),
        "buy_140_normalized_to_100": ([BacktestSignal(CODE, "BUY", 140, DAYS[0])], _bars(), 100_000.0),
    }
    results: dict[str, Any] = {}
    for name, values in scenarios.items():
        signals, bars, initial_cash = values[:3]
        initial_position = values[3] if len(values) == 4 else None
        engine = BacktestEngine(rule_registry=registry, security_statuses={CODE: status})
        actual = _engine_view(
            engine.run(
                _config(initial_cash),
                bars,
                signals=signals,
                initial_positions={CODE: initial_position} if initial_position else None,
            )
        )
        expected = _reference(
            signals, bars, initial_cash, registry, status, initial_position
        )
        results[name] = {
            "differences": [] if actual == expected else ["engine/reference mismatch"],
            "filled_trades": sum(1 for trade in actual["trades"] if trade["status"] == "FILLED"),
            "failed_reasons": [
                trade["fail_reason"]
                for trade in actual["trades"]
                if trade["status"] == "FAILED"
            ],
            "final_position": actual["daily"][-1]["position"],
        }
    boundary_status = _status(date(2022, 4, 28), date(2022, 4, 29))
    try:
        registry.resolve_rule("transfer_fee", date(2022, 4, 28), boundary_status)
        before = "unexpected_rule"
    except MarketRuleError:
        before = "blocked"
    on_date = registry.resolve_rule("transfer_fee", date(2022, 4, 29), boundary_status)
    results["transfer_fee_effective_boundary"] = {
        "before_effective_date": before,
        "on_effective_date_rate": on_date.value,
        "differences": [] if before == "blocked" and on_date.value == 0.00001 else ["boundary mismatch"],
    }
    return {
        "scenarios": results,
        "differences": [name for name, result in results.items() if result["differences"]],
    }
