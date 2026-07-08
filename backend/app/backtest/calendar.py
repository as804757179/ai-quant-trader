from __future__ import annotations

from datetime import date, timedelta

from app.backtest.schemas import DailyBar


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def next_trading_day(current: date, trading_days: list[date]) -> date | None:
    for d in trading_days:
        if d > current:
            return d
    return None


def build_trading_days(
    start: date,
    end: date,
    bars_by_stock: dict[str, dict[date, DailyBar]] | None = None,
) -> list[date]:
    """从 K 线数据提取交易日；无数据时回退为工作日。"""
    if bars_by_stock:
        dates: set[date] = set()
        for stock_bars in bars_by_stock.values():
            for trade_date in stock_bars:
                if start <= trade_date <= end:
                    dates.add(trade_date)
        if dates:
            return sorted(dates)

    days: list[date] = []
    current = start
    while current <= end:
        if is_weekday(current):
            days.append(current)
        current += timedelta(days=1)
    return days