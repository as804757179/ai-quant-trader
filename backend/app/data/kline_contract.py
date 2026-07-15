from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class KlineContract:
    PERIOD = "1d"
    MARKET_CLOSE_TIME = time(15, 0)
    TIMEZONE = "Asia/Shanghai"
    PRICE_CURRENCY = "CNY"
    VOLUME_UNIT = "share"
    AMOUNT_UNIT = "CNY"
    ADJUSTMENT = "raw"
    NORMALIZER_VERSION = "sprint07-kline-contract-v1"
    SCHEMA_VERSION = "certified-kline-v1"

    @classmethod
    def canonical_symbol(cls, code: str) -> tuple[str, str]:
        raw = str(code).strip().upper()
        base, dot, exchange = raw.partition(".")
        base = base.zfill(6)
        if not dot:
            exchange = "SH" if base.startswith(("5", "6", "9")) else "SZ"
        if len(base) != 6 or not base.isdigit() or exchange not in {"SH", "SZ"}:
            raise ValueError(f"invalid A-share symbol: {code}")
        return f"{base}.{exchange}", exchange

    @staticmethod
    def volume_to_shares(value: Any, source_unit: str) -> int:
        if source_unit == "share":
            return int(float(value))
        if source_unit == "lot":
            return int(float(value) * 100)
        raise ValueError(f"unsupported volume unit: {source_unit}")

    @staticmethod
    def amount_to_cny(value: Any, source_unit: str) -> float:
        if source_unit == "CNY":
            return float(value)
        if source_unit == "ten_thousand_CNY":
            return float(value) * 10_000
        raise ValueError(f"unsupported amount unit: {source_unit}")

    @classmethod
    def normalize_sohu_row(cls, code: str, fields: list[str]) -> dict[str, Any]:
        if len(fields) < 10:
            raise ValueError("incomplete Sohu daily row")
        symbol, exchange = cls.canonical_symbol(code)
        trading_date = date.fromisoformat(str(fields[0]))
        return {
            "stock_code": symbol,
            "exchange": exchange,
            "period": cls.PERIOD,
            "trading_date": trading_date,
            "time": datetime.combine(trading_date, cls.MARKET_CLOSE_TIME, tzinfo=CN_TZ),
            "market_close_time": cls.MARKET_CLOSE_TIME,
            "timezone": cls.TIMEZONE,
            "open": float(fields[1]),
            "close": float(fields[2]),
            "high": float(fields[6]),
            "low": float(fields[5]),
            "volume": cls.volume_to_shares(fields[7], "lot"),
            "amount": cls.amount_to_cny(fields[8], "ten_thousand_CNY"),
            "turnover_rate": float(str(fields[9]).rstrip("%")),
            "adjustment": cls.ADJUSTMENT,
            "price_currency": cls.PRICE_CURRENCY,
            "volume_unit": cls.VOLUME_UNIT,
            "amount_unit": cls.AMOUNT_UNIT,
            "normalizer_version": cls.NORMALIZER_VERSION,
            "schema_version": cls.SCHEMA_VERSION,
        }
