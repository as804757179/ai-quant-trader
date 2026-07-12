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
    *,
    certified_calendar: list[date] | None = None,
    require_certified: bool = False,
) -> list[date]:
    if require_certified:
        if not certified_calendar:
            raise ValueError("certified trading calendar is required")
        days = sorted({day for day in certified_calendar if start <= day <= end})
        if not days:
            raise ValueError("certified trading calendar has no coverage")
        bar_dates = {
            trade_date
            for stock_bars in (bars_by_stock or {}).values()
            for trade_date in stock_bars
            if start <= trade_date <= end
        }
        if not bar_dates.issubset(set(days)):
            raise ValueError("Kline date is outside certified trading calendar")
        return days

    """从 K 线数据提取交易日；普通测试无数据时可使用显式工作日 fixture。"""
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
