from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.backtest.engine import BacktestEngine
from app.backtest.accounting_validation import validate_accounting_scenarios
from app.backtest.market_rules import AshareMarketRuleRegistry, SecurityStatusSnapshot
from app.backtest.metrics import summarize_result
from app.backtest.schemas import BacktestConfig, BacktestSignal, DailyBar
from app.backtest.trusted_calendar import TrustedTradingCalendar
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.data.research_profiles import ResearchDataRequirementProfile
from app.data.research_readiness import ResearchReadinessService
from app.strategy.signals import make_signal_generator


ALLOWED_CODES = ("300308.SZ", "603986.SH")
DATE_FROM = date(2026, 6, 1)
DATE_TO = date(2026, 6, 30)
PROFILE = "OHLCV_RETURN_V1"
SCOPE = "return_backtest"
ADJUSTMENT = "raw"
PARAMS = {"fast_period": 3, "slow_period": 5, "position_pct": 0.2}
INITIAL_CASH = 1_000_000.0
MONEY_QUANT = Decimal("0.00000001")


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _money(value: Decimal | float) -> float:
    return float(Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _canonical_dataset_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [
        {
            key: row[key]
            for key in (
                "stock_code",
                "trading_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "adjustment",
                "batch_id",
                "raw_hash",
            )
        }
        for row in rows
    ]
    return sorted(
        records,
        key=lambda item: (
            item["stock_code"],
            item["trading_date"],
            item["adjustment"],
            item["raw_hash"],
        ),
    )


def _cost_config() -> dict[str, Any]:
    return {
        "commission_rate": 0.003,
        "stamp_duty_rate_sell": 0.0005,
        "transfer_fee_rate": 0.00001,
        "transfer_fee_implemented": True,
        "slippage_rate": 0.002,
        "minimum_commission": 5.0,
        "lot_size": 100,
        "execution_model": "next_trading_day_open",
    }


def _bars_from_rows(rows: list[dict[str, Any]]) -> dict[str, dict[date, DailyBar]]:
    output: dict[str, dict[date, DailyBar]] = {}
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if "amount" in row or "turnover_rate" in row:
            raise ValueError("unauthorized amount/turnover field was read")
        by_code.setdefault(row["stock_code"], []).append(row)
    for code, items in by_code.items():
        previous = None
        for row in sorted(items, key=lambda item: item["trading_date"]):
            bar = DailyBar(
                trade_date=row["trading_date"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                prev_close=previous,
            )
            output.setdefault(code, {})[bar.trade_date] = bar
            previous = bar.close
    return output


def _config(codes: list[str], trading_days: list[date]) -> BacktestConfig:
    costs = _cost_config()
    return BacktestConfig(
        start_date=DATE_FROM,
        end_date=DATE_TO,
        universe=codes,
        initial_cash=INITIAL_CASH,
        commission_rate=costs["commission_rate"],
        stamp_tax_rate=costs["stamp_duty_rate_sell"],
        slippage_rate=costs["slippage_rate"],
        min_commission=costs["minimum_commission"],
        execution_mode="open_auction",
        lot_size=costs["lot_size"],
        trusted_mode=True,
        trusted_calendar=trading_days,
    )


def _security_statuses() -> dict[str, SecurityStatusSnapshot]:
    return {
        "300308.SZ": SecurityStatusSnapshot(
            "300308.SZ", "SZ", "GEM", "NORMAL", DATE_FROM, DATE_TO,
            False, False, True, "Shenzhen Stock Exchange filing",
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-17/9d49a477-951e-4995-bba4-4acaf6c10aba.PDF",
            "300308-status-202606-v1",
        ),
        "603986.SH": SecurityStatusSnapshot(
            "603986.SH", "SH", "MAIN", "NORMAL", DATE_FROM, DATE_TO,
            False, False, True, "Shanghai Stock Exchange official security list",
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/specific/margin/c/c_20260417_10815527.shtml",
            "603986-status-202606-v1",
        ),
    }


def _baseline_signals(codes: list[str], trading_days: list[date]) -> list[BacktestSignal]:
    signals: list[BacktestSignal] = []
    for code in codes:
        signals.append(BacktestSignal(code, "BUY", 100, trading_days[0], reason="integrity_baseline_entry"))
        signals.append(BacktestSignal(code, "SELL", 100, trading_days[-2], reason="integrity_baseline_exit"))
    return signals


def _serialize_engine(result: Any) -> dict[str, Any]:
    trades = sorted(
        result.trades,
        key=lambda trade: (
            trade.execution_date,
            trade.stock_code,
            trade.side,
            trade.signal_date,
        ),
    )
    return {
        "trades": [
            {
                "stock_code": trade.stock_code,
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
            for trade in trades
        ],
        "equity": [
            {
                "trade_date": point.trade_date.isoformat(),
                "cash": _money(point.cash),
                "market_value": _money(point.market_value),
                "total_assets": _money(point.total_assets),
                "daily_return": round(point.daily_return, 12),
            }
            for point in sorted(result.equity_curve, key=lambda point: point.trade_date)
        ],
        "final_assets": _money(result.final_cash + result.final_market_value),
        "metrics": summarize_result(result),
        "signal_audit": sorted(
            result.metadata["signal_audit"],
            key=lambda row: (row["signal_date"], row["stock_code"], row["signal"]),
        ),
        "execution_audit": sorted(
            result.metadata["execution_audit"],
            key=lambda row: (row["execution_date"], row["signal_date"], row["signal"]),
        ),
        "daily_audit": sorted(
            result.metadata["daily_audit"], key=lambda row: row["trade_date"]
        ),
    }


def _reference_metrics(
    trades: list[dict[str, Any]], equity: list[dict[str, Any]], initial_cash: float
) -> dict[str, Any]:
    assets = [Decimal(str(row["total_assets"])) for row in equity]
    returns = [Decimal(str(row["daily_return"])) for row in equity[1:]]
    total_return = float(assets[-1] / Decimal(str(initial_cash)) - 1) if assets else 0.0
    peak = Decimal("0")
    max_dd = Decimal("0")
    for value in assets:
        peak = max(peak, value)
        if peak:
            max_dd = min(max_dd, value / peak - 1)
    if returns:
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / len(returns)
        std = variance.sqrt()
        sharpe = float(mean / std * Decimal(str(math.sqrt(242)))) if std else 0.0
    else:
        sharpe = 0.0
    buys: dict[str, tuple[int, Decimal]] = {}
    pnls: list[Decimal] = []
    for trade in trades:
        if trade["status"] != "FILLED":
            continue
        if trade["side"] == "BUY":
            buys[trade["stock_code"]] = (
                trade["quantity"],
                Decimal(str(trade["amount"] + trade["commission"] + trade["transfer_fee"])),
            )
        elif trade["stock_code"] in buys:
            _, cost = buys.pop(trade["stock_code"])
            proceeds = Decimal(
                str(trade["amount"] - trade["commission"] - trade["stamp_duty"] - trade["transfer_fee"])
            )
            pnls.append(proceeds - cost)
    profits = sum((pnl for pnl in pnls if pnl > 0), Decimal("0"))
    losses = abs(sum((pnl for pnl in pnls if pnl < 0), Decimal("0")))
    average_assets = sum(assets) / len(assets) if assets else Decimal("0")
    turnover = (
        sum(Decimal(str(t["amount"])) for t in trades if t["status"] == "FILLED")
        / average_assets
        if average_assets
        else Decimal("0")
    )
    commissions = sum(Decimal(str(t["commission"])) for t in trades if t["status"] == "FILLED")
    stamp = sum(Decimal(str(t["stamp_duty"])) for t in trades if t["status"] == "FILLED")
    slippage = sum(Decimal(str(t["slippage"])) for t in trades if t["status"] == "FILLED")
    transfer = sum(Decimal(str(t["transfer_fee"])) for t in trades if t["status"] == "FILLED")
    return {
        "total_return": round(total_return, 6),
        "max_drawdown": round(abs(float(max_dd)), 6),
        "sharpe_ratio": round(sharpe, 4),
        "win_rate": round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": round(float(profits / losses), 4) if losses else (None if profits else 0.0),
        "turnover": round(float(turnover), 6),
        "total_trades": sum(1 for trade in trades if trade["status"] == "FILLED"),
        "fees": {
            "commission": round(float(commissions), 2),
            "stamp_duty": round(float(stamp), 2),
            "transfer_fee": round(float(transfer), 2),
            "slippage": round(float(slippage), 2),
            "explicit_fees": round(float(commissions + stamp + transfer), 2),
        },
    }


def _reference_baseline(
    rows: list[dict[str, Any]], codes: list[str], trading_days: list[date]
) -> dict[str, Any]:
    costs = _cost_config()
    bars = {(row["stock_code"], row["trading_date"]): row for row in rows}
    signals = _baseline_signals(codes, trading_days)
    scheduled: dict[date, list[BacktestSignal]] = {}
    for signal in signals:
        index = trading_days.index(signal.signal_date)
        scheduled.setdefault(trading_days[index + 1], []).append(signal)
    cash = Decimal(str(INITIAL_CASH))
    positions: dict[str, int] = {}
    position_costs: dict[str, Decimal] = {}
    available: dict[str, int] = {}
    trades: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    previous_assets = cash
    for day in trading_days:
        available = dict(positions)
        for signal in scheduled.get(day, []):
            bar = bars[(signal.stock_code, day)]
            side = signal.side
            reference = Decimal(str(bar["open"]))
            rate = Decimal(str(costs["slippage_rate"]))
            fill = reference * (Decimal("1") + rate if side == "BUY" else Decimal("1") - rate)
            quantity = signal.quantity // costs["lot_size"] * costs["lot_size"]
            amount = fill * quantity
            commission = max(amount * Decimal(str(costs["commission_rate"])), Decimal(str(costs["minimum_commission"])))
            stamp = amount * Decimal(str(costs["stamp_duty_rate_sell"])) if side == "SELL" else Decimal("0")
            transfer = amount * Decimal(str(costs["transfer_fee_rate"]))
            status = "FILLED"
            realized_pnl = Decimal("0")
            if side == "BUY":
                if cash < amount + commission + transfer:
                    status = "FAILED"
                else:
                    cash -= amount + commission + transfer
                    positions[signal.stock_code] = positions.get(signal.stock_code, 0) + quantity
                    position_costs[signal.stock_code] = position_costs.get(signal.stock_code, Decimal("0")) + amount + commission + transfer
            else:
                if available.get(signal.stock_code, 0) < quantity:
                    status = "FAILED"
                else:
                    average_cost = position_costs[signal.stock_code] / positions[signal.stock_code]
                    allocated_cost = average_cost * quantity
                    proceeds = amount - commission - stamp - transfer
                    realized_pnl = proceeds - allocated_cost
                    cash += proceeds
                    positions[signal.stock_code] -= quantity
                    position_costs[signal.stock_code] -= allocated_cost
                    available[signal.stock_code] -= quantity
                    if positions[signal.stock_code] == 0:
                        positions.pop(signal.stock_code)
                        position_costs.pop(signal.stock_code)
            trades.append(
                {
                    "stock_code": signal.stock_code,
                    "side": side,
                    "signal_date": signal.signal_date.isoformat(),
                    "execution_date": day.isoformat(),
                    "quantity": quantity,
                    "fill_price": round(float(fill), 4),
                    "amount": round(float(amount), 2),
                    "commission": round(float(commission), 2),
                    "stamp_duty": round(float(stamp), 2),
                    "transfer_fee": round(float(transfer), 2),
                    "slippage": round(float(abs(fill - reference) * quantity), 2),
                    "realized_pnl": round(float(realized_pnl), 8),
                    "status": status,
                    "fail_reason": None,
                }
            )
        market_value = sum(
            Decimal(str(bars[(code, day)]["close"])) * quantity
            for code, quantity in positions.items()
        )
        assets = cash + market_value
        daily_return = assets / previous_assets - 1 if previous_assets else Decimal("0")
        equity.append(
            {
                "trade_date": day.isoformat(),
                "cash": _money(cash),
                "market_value": _money(market_value),
                "total_assets": _money(assets),
                "daily_return": round(float(daily_return), 12),
                "positions": dict(sorted(positions.items())),
            }
        )
        previous_assets = assets
    return {
        "signals": [
            {
                "stock_code": signal.stock_code,
                "signal_date": signal.signal_date.isoformat(),
                "execution_date": trading_days[trading_days.index(signal.signal_date) + 1].isoformat(),
                "side": signal.side,
                "quantity": signal.quantity,
            }
            for signal in signals
        ],
        "trades": trades,
        "equity": equity,
        "final_assets": equity[-1]["total_assets"],
        "metrics": _reference_metrics(trades, equity, INITIAL_CASH),
    }


def _compare_engine_reference(engine: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    engine_signals = [
        {
            "stock_code": row["stock_code"],
            "signal_date": row["signal_date"],
            "execution_date": row["execution_date"],
            "side": row["signal"],
            "quantity": row["quantity"],
        }
        for row in engine["signal_audit"]
    ]
    signal_key = lambda row: (
        row["signal_date"],
        row["execution_date"],
        row["stock_code"],
        row["side"],
    )
    if sorted(engine_signals, key=signal_key) != sorted(reference["signals"], key=signal_key):
        differences.append("signal or execution dates differ")
    if engine["trades"] != reference["trades"]:
        differences.append("trade records differ")
    engine_equity = [
        {key: row[key] for key in ("trade_date", "cash", "market_value", "total_assets", "daily_return")}
        for row in engine["equity"]
    ]
    reference_equity = [
        {key: row[key] for key in ("trade_date", "cash", "market_value", "total_assets", "daily_return")}
        for row in reference["equity"]
    ]
    if engine_equity != reference_equity:
        differences.append("daily cash/assets differ")
    engine_positions = [
        {
            code: state["total_qty"]
            for code, state in row["positions_after"].items()
        }
        for row in engine["daily_audit"]
    ]
    reference_positions = [row["positions"] for row in reference["equity"]]
    if engine_positions != reference_positions:
        differences.append("daily positions differ")
    if engine["final_assets"] != reference["final_assets"]:
        differences.append("final assets differ")
    for key in (
        "total_return",
        "max_drawdown",
        "sharpe_ratio",
        "win_rate",
        "profit_factor",
        "turnover",
        "total_trades",
        "fees",
    ):
        if engine["metrics"].get(key) != reference["metrics"].get(key):
            differences.append(f"metric differs: {key}")
    return differences


async def validate_backtest_integrity(stock_codes: list[str] | None = None) -> dict[str, Any]:
    requested = stock_codes or list(ALLOWED_CODES)
    if set(requested) != set(ALLOWED_CODES) or len(requested) != len(ALLOWED_CODES):
        raise ValueError("integrity validation is restricted to 300308.SZ and 603986.SH")
    codes = sorted(ALLOWED_CODES)
    required_fields = list(ResearchDataRequirementProfile.get(PROFILE).required_fields)
    repository = CertifiedKlineRepository()
    await repository.assert_dataset_ready(
        codes,
        period="1d",
        adjustment=ADJUSTMENT,
        research_use_scope=SCOPE,
        requirement_profile=PROFILE,
        required_fields=required_fields,
        start_date=DATE_FROM,
        end_date=DATE_TO,
    )
    rows = await repository.get_bars_for_profile(
        codes,
        period="1d",
        adjustment=ADJUSTMENT,
        research_use_scope=SCOPE,
        requirement_profile=PROFILE,
        required_fields=required_fields,
        start_date=DATE_FROM,
        end_date=DATE_TO,
    )
    if len(rows) != 42:
        raise ValueError(f"expected 42 OHLCV rows, got {len(rows)}")
    bars = _bars_from_rows(rows)
    trading_days, calendar_lineage = await TrustedTradingCalendar().get_days(
        ["SH", "SZ"], DATE_FROM, DATE_TO
    )
    if sorted({row["trading_date"] for row in rows}) != trading_days:
        raise ValueError("certified Klines do not match certified trading calendar")
    config = _config(codes, trading_days)
    registry = AshareMarketRuleRegistry(slippage_rate=_cost_config()["slippage_rate"])
    statuses = _security_statuses()
    engine = BacktestEngine(rule_registry=registry, security_statuses=statuses)
    baseline = engine.run(config, bars, signals=_baseline_signals(codes, trading_days))
    engine_baseline = _serialize_engine(baseline)
    reference = _reference_baseline(rows, codes, trading_days)
    differences = _compare_engine_reference(engine_baseline, reference)
    generator = make_signal_generator(
        "dual_ma", codes, PARAMS, initial_cash=INITIAL_CASH
    )
    dual_ma = _serialize_engine(engine.run(config, bars, signal_generator=generator))
    accounting_scenarios = validate_accounting_scenarios()
    readiness = ResearchReadinessService()
    review_ids = []
    for code in codes:
        review = await readiness.get_review(
            code,
            period="1d",
            adjustment=ADJUSTMENT,
            research_use_scope=SCOPE,
            requirement_profile=PROFILE,
            required_fields=required_fields,
            start_date=DATE_FROM,
            end_date=DATE_TO,
        )
        if not review:
            raise ValueError(f"missing readiness review for {code}")
        review_ids.append(review["review_id"])
    dataset_records = _canonical_dataset_records(rows)
    rule_versions = sorted(
        {
            version
            for code in codes
            for version in registry.resolve(DATE_TO, statuses[code]).rule_versions
        }
    )
    sample_rules = registry.resolve(DATE_TO, statuses[codes[0]])
    lineage = {
        "stock_codes": codes,
        "date_from": DATE_FROM.isoformat(),
        "date_to": DATE_TO.isoformat(),
        "adjustment": ADJUSTMENT,
        "research_use_scope": SCOPE,
        "requirement_profile": PROFILE,
        "required_fields": required_fields,
        "readiness_review_ids": sorted(review_ids),
        "certified_batch_ids": sorted({row["batch_id"] for row in rows}),
        "raw_hashes": sorted({row["raw_hash"] for row in rows}),
        "dataset_hash": _hash(dataset_records),
        "calendar": sorted(calendar_lineage, key=lambda item: item["exchange"]),
        "market_rule_registry_version": registry.VERSION,
        "market_rule_versions": rule_versions,
        "market_microstructure": {
            "buy_lot_size": sample_rules.buy_lot_size,
            "sell_lot_size": sample_rules.sell_lot_size,
            "odd_lot_sell_policy": sample_rules.odd_lot_sell_policy,
            "price_tick": str(sample_rules.price_tick),
            "price_rounding_mode": sample_rules.price_rounding_mode,
            "price_limit_formula_version": sample_rules.price_limit_formula_version,
        },
        "security_status_versions": sorted(status.status_version for status in statuses.values()),
        "strategy_id": "dual_ma",
        "strategy_version": "builtin-dual-ma-v1",
        "parameters": PARAMS,
        "parameter_hash": _hash(PARAMS),
        "engine_version": BacktestEngine.VERSION,
        "execution_model": "next_trading_day_open",
        "cost_config": _cost_config(),
        "cost_hash": _hash(_cost_config()),
    }
    stable_result = {
        "lineage": lineage,
        "dual_ma_validation": dual_ma,
        "accounting_baseline_engine": engine_baseline,
        "accounting_baseline_reference": reference,
        "accounting_scenarios": accounting_scenarios,
        "engine_reference_differences": differences,
        "validation_only": True,
        "not_for_investment": True,
        "sample_size_insufficient": True,
    }
    return {
        **stable_result,
        "result_hash": _hash(stable_result),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
