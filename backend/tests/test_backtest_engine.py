from datetime import date

from app.backtest.engine import BacktestEngine
from app.backtest.schemas import BacktestConfig, BacktestSignal, DailyBar


def _bar(
    d: date,
    *,
    open_: float,
    close: float,
    prev_close: float | None = None,
    volume: int = 1_000_000,
    high: float | None = None,
    low: float | None = None,
    suspended: bool = False,
) -> DailyBar:
    return DailyBar(
        trade_date=d,
        open=open_,
        high=high or max(open_, close) * 1.01,
        low=low or min(open_, close) * 0.99,
        close=close,
        volume=0 if suspended else volume,
        prev_close=prev_close or open_,
        is_suspended=suspended,
    )


def _sample_bars() -> dict[str, dict[date, DailyBar]]:
    code = "000001"
    return {
        code: {
            date(2024, 1, 2): _bar(date(2024, 1, 2), open_=10.0, close=10.2, prev_close=9.8),
            date(2024, 1, 3): _bar(date(2024, 1, 3), open_=10.2, close=10.5, prev_close=10.2),
            date(2024, 1, 4): _bar(date(2024, 1, 4), open_=10.5, close=10.8, prev_close=10.5),
            date(2024, 1, 5): _bar(date(2024, 1, 5), open_=10.8, close=11.0, prev_close=10.8),
        }
    }


def test_backtest_buy_and_sell_with_t1() -> None:
    engine = BacktestEngine()
    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        universe=["000001"],
        initial_cash=100_000,
    )
    signals = [
        BacktestSignal("000001", "BUY", 100, date(2024, 1, 2)),
        BacktestSignal("000001", "SELL", 100, date(2024, 1, 3)),
    ]
    result = engine.run(config, _sample_bars(), signals=signals)

    filled = [t for t in result.trades if t.status == "FILLED"]
    assert len(filled) == 2
    assert filled[0].execution_date == date(2024, 1, 3)
    assert filled[1].execution_date == date(2024, 1, 4)
    assert result.filled_trades == 2
    assert result.equity_curve[-1].total_assets > config.initial_cash * 0.9


def test_backtest_limit_up_blocks_buy() -> None:
    engine = BacktestEngine()
    bars = {
        "000001": {
            date(2024, 1, 2): _bar(date(2024, 1, 2), open_=10.0, close=10.0, prev_close=9.0),
            date(2024, 1, 3): _bar(
                date(2024, 1, 3),
                open_=9.9,
                close=9.9,
                high=9.9,
                low=9.9,
                prev_close=9.0,
            ),
        }
    }
    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        universe=["000001"],
        initial_cash=100_000,
    )
    signals = [BacktestSignal("000001", "BUY", 100, date(2024, 1, 2))]
    result = engine.run(config, bars, signals=signals)

    assert result.failed_trades == 1
    assert result.trades[0].fail_reason == "LIMIT_UP"


def test_backtest_suspended_stock_skipped() -> None:
    engine = BacktestEngine()
    bars = {
        "000001": {
            date(2024, 1, 2): _bar(date(2024, 1, 2), open_=10.0, close=10.0, prev_close=10.0),
            date(2024, 1, 3): _bar(
                date(2024, 1, 3), open_=10.0, close=10.0, prev_close=10.0, suspended=True
            ),
        }
    }
    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        universe=["000001"],
        initial_cash=100_000,
    )
    signals = [BacktestSignal("000001", "BUY", 100, date(2024, 1, 2))]
    result = engine.run(config, bars, signals=signals)

    assert result.trades[0].fail_reason == "SUSPENDED"


def test_backtest_commission_and_slippage_applied() -> None:
    engine = BacktestEngine()
    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        universe=["000001"],
        initial_cash=100_000,
        slippage_rate=0.01,
        commission_rate=0.0003,
        min_commission=5.0,
    )
    signals = [BacktestSignal("000001", "BUY", 100, date(2024, 1, 2))]
    result = engine.run(config, _sample_bars(), signals=signals)

    trade = result.trades[0]
    assert trade.status == "FILLED"
    assert trade.commission >= 5.0
    assert trade.fill_price > 10.2  # open + slippage on execution day


def test_backtest_insufficient_cash() -> None:
    engine = BacktestEngine()
    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        universe=["000001"],
        initial_cash=500,
    )
    signals = [BacktestSignal("000001", "BUY", 100, date(2024, 1, 2))]
    result = engine.run(config, _sample_bars(), signals=signals)

    assert result.trades[0].fail_reason == "INSUFFICIENT_CASH"


def test_backtest_signal_generator_callback() -> None:
    engine = BacktestEngine()

    def _gen(day: date, positions, bars):
        if day == date(2024, 1, 2):
            return [BacktestSignal("000001", "BUY", 100, day)]
        return []

    config = BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 4),
        universe=["000001"],
        initial_cash=100_000,
    )
    result = engine.run(config, _sample_bars(), signal_generator=_gen)

    assert result.filled_trades == 1
    assert result.trades[0].signal_date == date(2024, 1, 2)


def test_bars_from_rows_helper() -> None:
    rows = [
        {
            "stock_code": "000001",
            "trade_date": "2024-01-02",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "volume": 1000,
            "prev_close": 9.9,
        }
    ]
    bars = BacktestEngine.bars_from_rows(rows)
    assert "000001" in bars
    assert date(2024, 1, 2) in bars["000001"]
    assert bars["000001"][date(2024, 1, 2)].close == 10.2