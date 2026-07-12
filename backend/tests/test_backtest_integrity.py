from datetime import date
from decimal import Decimal

import pytest

from app.backtest.engine import BacktestEngine
from app.backtest.accounting_validation import validate_accounting_scenarios
from app.backtest.integrity_validation import (
    _bars_from_rows,
    _canonical_dataset_records,
    _hash,
)
from app.backtest.market_rules import (
    AshareMarketRuleRegistry,
    MarketRuleError,
    SecurityStatusSnapshot,
)
from app.backtest.metrics import profit_factor, win_rate
from app.backtest.schemas import BacktestConfig, BacktestSignal, DailyBar, TradeRecord
from app.strategy.signals import make_signal_generator


def _trade(side: str, amount: float, commission: float, stamp: float = 0.0) -> TradeRecord:
    return TradeRecord(
        stock_code="300308.SZ",
        side=side,
        signal_date=date(2026, 6, 1),
        execution_date=date(2026, 6, 2),
        quantity=100,
        fill_price=amount / 100,
        amount=amount,
        commission=commission,
        stamp_tax=stamp,
        slippage_cost=0.0,
        status="FILLED",
    )


def test_profile_rows_reject_unauthorized_amount_field() -> None:
    row = {
        "stock_code": "300308.SZ",
        "trading_date": date(2026, 6, 1),
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10,
        "volume": 1000,
        "amount": 10000,
    }
    with pytest.raises(ValueError, match="unauthorized"):
        _bars_from_rows([row])


def test_signal_executes_on_next_trading_day_open() -> None:
    days = [date(2026, 6, 1), date(2026, 6, 2)]
    bars = {
        "300308.SZ": {
            day: DailyBar(day, 10.0, 10.5, 9.5, 10.0, volume=1000, prev_close=10.0)
            for day in days
        }
    }
    config = BacktestConfig(days[0], days[-1], ["300308.SZ"], initial_cash=100000)
    result = BacktestEngine().run(
        config,
        bars,
        signals=[BacktestSignal("300308.SZ", "BUY", 150, days[0])],
    )
    trade = result.trades[0]
    assert trade.signal_date == days[0]
    assert trade.execution_date == days[1]
    assert trade.quantity == 100
    assert result.metadata["signal_audit"][0]["information_cutoff"] == "2026-06-01"
    assert result.metadata["execution_audit"][0]["execution_price_source"] == "next_trading_day_open"


def test_board_limit_uses_stock_code_semantics() -> None:
    engine = BacktestEngine()
    bar = DailyBar(date(2026, 6, 1), 10, 10, 10, 10, volume=1000)
    assert engine._limit_pct("300308.SZ", bar) == 0.20
    assert engine._limit_pct("603986.SH", bar) == 0.10


def test_metrics_include_fees_and_handle_no_loss_case() -> None:
    winning = [_trade("BUY", 1000, 5), _trade("SELL", 1200, 5, 0.6)]
    assert win_rate(winning) == 1.0
    assert profit_factor(winning) is None
    no_trades: list[TradeRecord] = []
    assert win_rate(no_trades) == 0.0
    assert profit_factor(no_trades) == 0.0


def test_metrics_count_losing_round_trip() -> None:
    losing = [_trade("BUY", 1200, 5), _trade("SELL", 1000, 5, 0.5)]
    assert win_rate(losing) == 0.0
    assert profit_factor(losing) == 0.0


def test_dual_ma_signal_is_unchanged_by_future_bar() -> None:
    days = [date(2026, 6, day) for day in range(1, 7)]
    closes = [10.0, 9.0, 8.0, 9.0, 11.0, 12.0]
    bars = {
        "300308.SZ": {
            day: DailyBar(day, close, close, close, close, volume=1000)
            for day, close in zip(days, closes)
        }
    }
    generator = make_signal_generator(
        "dual_ma",
        ["300308.SZ"],
        {"fast_period": 3, "slow_period": 5, "position_pct": 0.2},
    )
    original = generator(days[4], {}, bars)
    bars["300308.SZ"][days[5]].close = 9999.0
    changed_future = generator(days[4], {}, bars)
    assert original == changed_future


def test_market_rules_resolve_by_date_and_security_status() -> None:
    registry = AshareMarketRuleRegistry()
    status = SecurityStatusSnapshot(
        "603986.SH", "SH", "MAIN", "NORMAL",
        date(2026, 6, 1), date(2026, 6, 30),
        False, False, True, "SSE", registry.SSE_RULES_2023, "status-v1",
    )
    rules = registry.resolve(date(2026, 6, 2), status)
    assert rules.transfer_fee_rate == 0.00001
    assert rules.price_limit_rate == 0.10
    assert rules.commission_rate == 0.003


def test_unknown_security_status_fails_closed() -> None:
    registry = AshareMarketRuleRegistry()
    status = SecurityStatusSnapshot(
        "603986.SH", "SH", "MAIN", "UNKNOWN",
        date(2026, 6, 1), date(2026, 6, 30),
        False, False, True, "SSE", registry.SSE_RULES_2023, "status-v1",
    )
    with pytest.raises(MarketRuleError, match="unsupported"):
        registry.resolve(date(2026, 6, 2), status)


def test_trusted_backtest_requires_certified_calendar() -> None:
    config = BacktestConfig(
        date(2026, 6, 1), date(2026, 6, 2), ["300308.SZ"], trusted_mode=True
    )
    with pytest.raises(ValueError, match="certified trading calendar"):
        BacktestEngine().run(config, {})


def test_all_accounting_scenarios_match_independent_reference() -> None:
    result = validate_accounting_scenarios()
    assert len(result["scenarios"]) == 19
    assert result["differences"] == []


def test_odd_lot_sell_boundaries_and_buy_audit() -> None:
    scenarios = validate_accounting_scenarios()["scenarios"]
    assert scenarios["odd_lot_140_full_sell"]["final_position"] == {}
    assert scenarios["odd_lot_140_sell_round_lot"]["final_position"]["total_qty"] == 40
    assert scenarios["odd_lot_40_full_sell"]["final_position"] == {}
    assert scenarios["odd_lot_40_partial_rejected"]["failed_reasons"] == [
        "INVALID_ODD_LOT_SELL"
    ]
    assert scenarios["odd_lot_split_rejected"]["failed_reasons"] == [
        "INVALID_ODD_LOT_SELL",
        "INVALID_ODD_LOT_SELL",
    ]
    assert scenarios["buy_odd_lot_40_rejected"]["failed_reasons"] == [
        "INVALID_QUANTITY"
    ]
    assert scenarios["buy_140_normalized_to_100"]["final_position"]["total_qty"] == 100


def test_price_limits_round_half_up_to_tick_for_main_and_gem() -> None:
    registry = AshareMarketRuleRegistry()
    main = SecurityStatusSnapshot(
        "603986.SH", "SH", "MAIN", "NORMAL",
        date(2026, 6, 1), date(2026, 6, 30),
        False, False, True, "SSE", registry.SSE_RULES_2023, "main-v1",
    )
    gem = SecurityStatusSnapshot(
        "300308.SZ", "SZ", "GEM", "NORMAL",
        date(2026, 6, 1), date(2026, 6, 30),
        False, False, True, "SZSE", registry.SZSE_RULES, "gem-v1",
    )
    main_rules = registry.resolve(date(2026, 6, 2), main)
    gem_rules = registry.resolve(date(2026, 6, 2), gem)
    assert registry.price_limits(10.03, 0.10, main_rules) == (
        Decimal("11.03"), Decimal("9.03")
    )
    assert registry.price_limits(10.03, 0.20, gem_rules) == (
        Decimal("12.04"), Decimal("8.02")
    )


def test_exact_limit_prices_reject_without_fuzzy_tolerance() -> None:
    registry = AshareMarketRuleRegistry(slippage_rate=0.0)
    status = SecurityStatusSnapshot(
        "603986.SH", "SH", "MAIN", "NORMAL",
        date(2026, 6, 1), date(2026, 6, 2),
        False, False, True, "SSE", registry.SSE_RULES_2023, "main-v1",
    )

    def run(open_price: float, side: str):
        bars = {
            "603986.SH": {
                date(2026, 6, 1): DailyBar(date(2026, 6, 1), 10.03, 10.03, 10.03, 10.03, 1000, prev_close=10.03),
                date(2026, 6, 2): DailyBar(date(2026, 6, 2), open_price, open_price, open_price, open_price, 1000, prev_close=10.03),
            }
        }
        config = BacktestConfig(
            date(2026, 6, 1), date(2026, 6, 2), ["603986.SH"],
            trusted_mode=True, trusted_calendar=[date(2026, 6, 1), date(2026, 6, 2)],
        )
        initial = (
            {"603986.SH": {"total_qty": 100, "available_qty": 100, "total_cost": 1003.0}}
            if side == "SELL" else None
        )
        return BacktestEngine(
            rule_registry=registry, security_statuses={"603986.SH": status}
        ).run(
            config,
            bars,
            signals=[BacktestSignal("603986.SH", side, 100, date(2026, 6, 1))],
            initial_positions=initial,
        ).trades[0]

    assert run(11.03, "BUY").fail_reason == "LIMIT_UP"
    assert run(11.02, "BUY").status == "FILLED"
    assert run(9.03, "SELL").fail_reason == "LIMIT_DOWN"
    assert run(9.04, "SELL").status == "FILLED"


def test_dataset_hash_is_independent_of_database_order() -> None:
    rows = [
        {
            "stock_code": code,
            "trading_date": date(2026, 6, day),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
            "adjustment": "raw",
            "batch_id": f"batch-{code}",
            "raw_hash": f"hash-{code}-{day}",
        }
        for code, day in (("603986.SH", 2), ("300308.SZ", 1))
    ]
    assert _hash(_canonical_dataset_records(rows)) == _hash(
        _canonical_dataset_records(list(reversed(rows)))
    )


def test_rule_version_change_changes_hash() -> None:
    assert _hash({"rules": ["fee-v1"]}) != _hash({"rules": ["fee-v2"]})
