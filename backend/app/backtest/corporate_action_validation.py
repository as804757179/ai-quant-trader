from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.backtest.corporate_actions import CorporateActionEvent, CorporateActionProcessor
from app.backtest.engine import BacktestEngine
from app.backtest.schemas import BacktestConfig, BacktestSignal, DailyBar


@dataclass
class ReferencePosition:
    total_qty: int
    available_qty: int
    total_cost: Decimal
    realized_pnl: Decimal = Decimal("0")

    @property
    def avg_cost(self) -> Decimal:
        return self.total_cost / self.total_qty if self.total_qty else Decimal("0")


def reference_entitlement(event: CorporateActionEvent, eligible_quantity: int) -> tuple[int, Decimal]:
    share_value = Decimal(eligible_quantity) * event.share_increase_per_10 / Decimal("10")
    if share_value != share_value.to_integral_value():
        raise ValueError("reference cannot allocate fractional shares")
    return int(share_value), Decimal(eligible_quantity) * event.cash_dividend_per_10 / Decimal("10")


def reference_daily_states(
    event: CorporateActionEvent,
    trading_days: list[date],
    closes: dict[date, Decimal],
    *,
    initial_quantity: int,
    initial_cost: Decimal,
    initial_cash: Decimal,
) -> list[dict[str, Any]]:
    position = ReferencePosition(initial_quantity, initial_quantity, initial_cost)
    cash = initial_cash
    income = Decimal("0")
    entitlement: tuple[int, Decimal] | None = None
    states: list[dict[str, Any]] = []
    for day in trading_days:
        if entitlement and day == event.share_credit_date:
            position.total_qty += entitlement[0]
            position.available_qty = position.total_qty
        if entitlement and day == event.cash_payment_date:
            cash += entitlement[1]
            income += entitlement[1]
        position.available_qty = position.total_qty
        if day == event.record_date:
            entitlement = reference_entitlement(event, position.total_qty)
        market_value = Decimal(position.total_qty) * closes[day]
        states.append(
            {
                "trade_date": day.isoformat(),
                "total_qty": position.total_qty,
                "available_qty": position.available_qty,
                "avg_cost": position.avg_cost,
                "total_cost": position.total_cost,
                "cash": cash,
                "corporate_action_income": income,
                "realized_pnl": position.realized_pnl,
                "unrealized_pnl": market_value - position.total_cost,
                "market_value": market_value,
                "total_assets": cash + market_value,
            }
        )
    return states


def corporate_action_lineage_hash(event: CorporateActionEvent, processor_version: str = CorporateActionProcessor.VERSION) -> str:
    payload = {
        "event": {
            key: value.isoformat() if hasattr(value, "isoformat") else str(value)
            for key, value in sorted(asdict(event).items())
        },
        "processor_version": processor_version,
        "policy": CorporateActionProcessor.POLICY,
        "daily_order": list(CorporateActionProcessor.DAILY_ORDER),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


_VALIDATION_DAYS = (
    date(2026, 6, 8),
    date(2026, 6, 9),
    date(2026, 6, 10),
    date(2026, 6, 11),
    date(2026, 6, 12),
    date(2026, 6, 15),
)


def _run_scenario(
    event: CorporateActionEvent,
    *,
    initial_quantity: int = 0,
    signals: list[BacktestSignal] | None = None,
):
    bars = {
        event.stock_code: {
            day: DailyBar(day, 10, 10, 10, 10, 100_000)
            for day in _VALIDATION_DAYS
        }
    }
    initial_positions = None
    if initial_quantity:
        initial_positions = {
            event.stock_code: {
                "total_qty": initial_quantity,
                "available_qty": initial_quantity,
                "total_cost": float(initial_quantity * 10),
            }
        }
    return BacktestEngine().run(
        BacktestConfig(
            _VALIDATION_DAYS[0],
            _VALIDATION_DAYS[-1],
            [event.stock_code],
            initial_cash=100_000,
            trusted_calendar=list(_VALIDATION_DAYS),
        ),
        bars,
        signals=signals or [],
        initial_positions=initial_positions,
        corporate_actions=[event],
        corporate_action_policy=CorporateActionProcessor.POLICY,
    )


def _audit_on(result, day: date) -> dict[str, Any]:
    return next(item for item in result.metadata["daily_audit"] if item["trade_date"] == day.isoformat())


def validate_fixed_scenarios(event: CorporateActionEvent) -> dict[str, bool]:
    no_holding = _run_scenario(event)
    holding_100 = _run_scenario(event, initial_quantity=100)
    partial = _run_scenario(event, initial_quantity=50)
    sold_before = _run_scenario(
        event,
        initial_quantity=100,
        signals=[BacktestSignal(event.stock_code, "SELL", 100, date(2026, 6, 8))],
    )
    bought_after = _run_scenario(
        event,
        signals=[BacktestSignal(event.stock_code, "BUY", 100, date(2026, 6, 10))],
    )
    sell_140 = _run_scenario(
        event,
        initial_quantity=100,
        signals=[BacktestSignal(event.stock_code, "SELL", 140, date(2026, 6, 11))],
    )
    split_clear = _run_scenario(
        event,
        initial_quantity=100,
        signals=[
            BacktestSignal(event.stock_code, "SELL", 100, date(2026, 6, 11)),
            BacktestSignal(event.stock_code, "SELL", 40, date(2026, 6, 12)),
        ],
    )
    delayed = CorporateActionEvent(
        **{
            **asdict(event),
            "cash_payment_date": date(2026, 6, 12),
            "share_credit_date": date(2026, 6, 12),
            "event_version": event.event_version + "-delayed-validation",
        }
    )
    delayed_result = _run_scenario(delayed, initial_quantity=100)
    version_changed = CorporateActionEvent(
        **{**asdict(event), "event_version": event.event_version + "-revision"}
    )
    ratio_changed = CorporateActionEvent(
        **{**asdict(event), "cash_dividend_per_10": event.cash_dividend_per_10 + Decimal("1")}
    )
    hold_state = _audit_on(holding_100, event.share_credit_date)
    partial_state = _audit_on(partial, event.share_credit_date)
    delayed_ex_state = _audit_on(delayed_result, event.ex_date)
    delayed_credit_state = _audit_on(delayed_result, delayed.share_credit_date)
    return {
        "no_holding_no_entitlement": Decimal(no_holding.metadata["corporate_action_income"]) == 0 and not _audit_on(no_holding, event.share_credit_date)["positions_after"],
        "record_date_100_shares": hold_state["positions_after"][event.stock_code]["total_qty"] == 140 and Decimal(holding_100.metadata["corporate_action_income"]) == 100,
        "sold_before_record_no_entitlement": Decimal(sold_before.metadata["corporate_action_income"]) == 0 and not _audit_on(sold_before, event.share_credit_date)["positions_after"],
        "bought_after_record_no_entitlement": Decimal(bought_after.metadata["corporate_action_income"]) == 0 and _audit_on(bought_after, event.share_credit_date)["positions_after"][event.stock_code]["total_qty"] == 100,
        "partial_holding": partial_state["positions_after"][event.stock_code]["total_qty"] == 70 and Decimal(partial.metadata["corporate_action_income"]) == 50,
        "one_hundred_becomes_140": hold_state["positions_after"][event.stock_code]["total_qty"] == 140,
        "sell_140_supported": not _audit_on(sell_140, date(2026, 6, 12))["positions_after"] and sell_140.filled_trades == 1,
        "sell_100_then_odd_lot_40_supported": not _audit_on(split_clear, date(2026, 6, 15))["positions_after"] and split_clear.filled_trades == 2,
        "cash_not_before_payment_date": Decimal(delayed_ex_state["corporate_action_income"]) == 0 and Decimal(delayed_credit_state["corporate_action_income"]) == 100,
        "shares_not_before_credit_date": delayed_ex_state["positions_after"][event.stock_code]["total_qty"] == 100 and delayed_credit_state["positions_after"][event.stock_code]["total_qty"] == 140,
        "pre_announcement_hidden": event.announcement_date > date(2026, 6, 3),
        "event_version_changes_hash": corporate_action_lineage_hash(event) != corporate_action_lineage_hash(version_changed) and corporate_action_lineage_hash(event) != corporate_action_lineage_hash(ratio_changed),
    }
