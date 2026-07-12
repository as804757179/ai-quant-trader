from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.backtest.corporate_action_validation import (
    corporate_action_lineage_hash,
    reference_daily_states,
    validate_fixed_scenarios,
)
from app.backtest.corporate_actions import CorporateActionEvent, CorporateActionProcessor
from app.backtest.engine import BacktestEngine
from app.backtest.schemas import BacktestConfig, DailyBar
from app.data.research_profiles import ResearchDataRequirementProfile


def event(**overrides):
    values = {
        "action_id": "cninfo-1225351859-v1",
        "stock_code": "300502.SZ",
        "event_type": "cash_dividend_and_capital_increase",
        "announcement_date": date(2026, 6, 4),
        "record_date": date(2026, 6, 10),
        "ex_date": date(2026, 6, 11),
        "cash_payment_date": date(2026, 6, 11),
        "share_credit_date": date(2026, 6, 11),
        "cash_dividend_per_10": Decimal("10"),
        "share_increase_per_10": Decimal("4"),
        "source_name": "cninfo",
        "source_reference": "https://static.cninfo.com.cn/finalpage/2026-06-04/1225351859.PDF",
        "evidence_hash": "b" * 64,
        "captured_at": datetime(2026, 7, 12, tzinfo=timezone.utc),
        "event_version": "cninfo-1225351859-v1",
        "verification_status": "verified",
    }
    values.update(overrides)
    return CorporateActionEvent(**values)


def test_profile_is_scoped_and_explicit():
    profile = ResearchDataRequirementProfile.get("OHLCV_TOTAL_RETURN_GROSS_V1")
    assert "cash_payment_date" in profile.required_fields
    assert "share_credit_date" in profile.required_fields
    assert profile.allowed_scopes == ("return_backtest",)


def test_event_validation_fails_closed():
    with pytest.raises(ValueError):
        CorporateActionProcessor.validate_event(event(source_name="unknown"))
    with pytest.raises(ValueError):
        CorporateActionProcessor.validate_event(event(cash_payment_date=date(2026, 6, 10)))


def test_engine_and_independent_reference_match_daily_accounting():
    days = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    bars = {"300502.SZ": {day: DailyBar(day, 10, 10, 10, 10, 10000) for day in days}}
    result = BacktestEngine().run(
        BacktestConfig(days[0], days[-1], ["300502.SZ"], initial_cash=1000, trusted_calendar=days),
        bars,
        initial_positions={"300502.SZ": {"total_qty": 100, "total_cost": 1000}},
        corporate_actions=[event()],
        corporate_action_policy=CorporateActionProcessor.POLICY,
    )
    reference = reference_daily_states(
        event(), days, {day: Decimal("10") for day in days},
        initial_quantity=100, initial_cost=Decimal("1000"), initial_cash=Decimal("1000"),
    )
    for actual, expected in zip(result.metadata["daily_audit"], reference):
        state = actual["positions_after"]["300502.SZ"]
        assert state["total_qty"] == expected["total_qty"]
        assert state["available_qty"] == expected["available_qty"]
        assert Decimal(str(state["avg_cost"])) == expected["avg_cost"].quantize(Decimal("0.00000001"))
        assert Decimal(str(actual["cash_after"])) == expected["cash"]
        assert Decimal(str(actual["total_assets"])) == expected["total_assets"]
    assert result.metadata["corporate_action_income"] == "100"


def test_all_required_fixed_scenarios_and_hash_versioning():
    scenarios = validate_fixed_scenarios(event())
    assert len(scenarios) == 12
    assert all(scenarios.values())
    assert corporate_action_lineage_hash(event()) == corporate_action_lineage_hash(event())
    assert corporate_action_lineage_hash(event()) != corporate_action_lineage_hash(event(cash_dividend_per_10=Decimal("11")))
