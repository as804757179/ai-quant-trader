from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from app.db import AsyncSessionLocal


class TrustedTradingCalendar:
    VERSION = "official-calendar-gate-v1"

    async def get_days(
        self, exchanges: list[str], start_date: date, end_date: date
    ) -> tuple[list[date], list[dict[str, str]]]:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT exchange, trading_date, is_trading_day, source,
                               source_reference, status, timezone
                        FROM market.trading_calendar
                        WHERE exchange = ANY(:exchanges)
                          AND trading_date BETWEEN :start_date AND :end_date
                        ORDER BY exchange, trading_date
                        """
                    ),
                    {
                        "exchanges": sorted(set(exchanges)),
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
            ).mappings().all()
        expected_dates: list[date] = []
        current = start_date
        while current <= end_date:
            expected_dates.append(current)
            current += timedelta(days=1)
        by_exchange: dict[str, dict[date, dict]] = {}
        for row in rows:
            by_exchange.setdefault(row["exchange"], {})[row["trading_date"]] = dict(row)
        open_sets: list[set[date]] = []
        lineage: list[dict[str, str]] = []
        for exchange in sorted(set(exchanges)):
            calendar = by_exchange.get(exchange, {})
            if set(calendar) != set(expected_dates):
                raise ValueError(f"certified trading calendar has incomplete coverage: {exchange}")
            if any(
                row["status"] != "confirmed"
                or row["source"] not in {"sse", "szse"}
                or row["timezone"] != "Asia/Shanghai"
                or not row["source_reference"]
                for row in calendar.values()
            ):
                raise ValueError(f"trading calendar is not certified: {exchange}")
            open_sets.append({day for day, row in calendar.items() if row["is_trading_day"]})
            first = calendar[expected_dates[0]]
            lineage.append(
                {
                    "exchange": exchange,
                    "source": first["source"],
                    "source_reference": first["source_reference"],
                    "calendar_version": self.VERSION,
                }
            )
        if not open_sets or any(days != open_sets[0] for days in open_sets[1:]):
            raise ValueError("SH/SZ certified trading calendars disagree")
        return sorted(open_sets[0]), lineage
