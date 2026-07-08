from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.backtest.engine import BacktestEngine
from app.backtest.lookahead_checker import LookaheadChecker, LookaheadError
from app.backtest.schemas import BacktestConfig, BacktestSignal, DailyBar

GOOD_STRATEGY = """
def generate_signal(df):
    prev = df[df['date'] < today].tail(20)
    ma20 = prev['close'].mean()
    return 'BUY' if ma20 > 0 else 'HOLD'
"""

BAD_SHIFT_STRATEGY = """
import pandas as pd
def generate_signal(df):
    df['future'] = df['close'].shift(-5)
    return 'BUY'
"""

BAD_REPORT_DATE_STRATEGY = """
def get_roe(stock_code, date):
    return db.query('''
        SELECT roe FROM financial_reports
        WHERE stock_code = %s AND report_date <= %s
        ORDER BY report_date DESC LIMIT 1
    ''', [stock_code, date])
"""

WARNING_ILOC_STRATEGY = """
def generate_signal(df):
    last_close = df.iloc[-1]['close']
    return 'BUY' if last_close > 10 else 'HOLD'
"""


def test_clean_strategy_passes() -> None:
    checker = LookaheadChecker()
    with patch.object(checker, "_check_financial_data_db", AsyncMock(return_value=[])):
        result = checker.check(GOOD_STRATEGY, financial_data_used=False)

    assert result.passed is True
    assert result.error_count == 0


def test_negative_shift_detected_and_blocks() -> None:
    checker = LookaheadChecker()
    with patch.object(checker, "_check_financial_data_db", AsyncMock(return_value=[])):
        result = checker.check(BAD_SHIFT_STRATEGY, financial_data_used=False)

    assert result.passed is False
    assert result.error_count >= 1
    assert any("shift" in i["message"].lower() for i in result.issues)


def test_report_date_usage_detected() -> None:
    checker = LookaheadChecker()
    with patch.object(checker, "_check_financial_data_db", AsyncMock(return_value=[])):
        result = checker.check(BAD_REPORT_DATE_STRATEGY, financial_data_used=True)

    assert result.passed is False
    assert result.error_count >= 1
    assert any("report_date" in i["message"].lower() for i in result.issues)


def test_iloc_negative_index_warning_only() -> None:
    checker = LookaheadChecker()
    with patch.object(checker, "_check_financial_data_db", AsyncMock(return_value=[])):
        result = checker.check(WARNING_ILOC_STRATEGY, financial_data_used=False)

    assert result.passed is True
    assert result.warning_count >= 1


def test_financial_db_issues_block() -> None:
    from app.backtest.lookahead_checker import LookaheadIssue

    checker = LookaheadChecker()
    mock_issues = [
        LookaheadIssue(
            severity="ERROR",
            location="financial_reports:000001:2024-03-31",
            message="财务记录 publish_date 缺失或早于 report_date",
            suggestion="补齐 publish_date",
        )
    ]
    with patch.object(checker, "_check_financial_data_db", AsyncMock(return_value=mock_issues)):
        result = checker.check(GOOD_STRATEGY, financial_data_used=True)

    assert result.passed is False
    assert result.error_count >= 1


def test_backtest_engine_blocks_on_lookahead_error() -> None:
    engine = BacktestEngine()
    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        universe=["000001"],
        initial_cash=100_000,
    )
    bars = {
        "000001": {
            date(2024, 1, 2): DailyBar(
                date(2024, 1, 2), 10, 10.5, 9.8, 10.2, volume=1000, prev_close=10.0
            ),
            date(2024, 1, 3): DailyBar(
                date(2024, 1, 3), 10.2, 10.5, 10.0, 10.4, volume=1000, prev_close=10.2
            ),
        }
    }

    with pytest.raises(LookaheadError) as exc_info:
        engine.run(
            config,
            bars,
            signals=[BacktestSignal("000001", "BUY", 100, date(2024, 1, 2))],
            strategy_code=BAD_SHIFT_STRATEGY,
            financial_data_used=False,
        )

    assert exc_info.value.result.error_count >= 1