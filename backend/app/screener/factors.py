from __future__ import annotations

from typing import Any


class FactorLibrary:
    """基础因子库 — 成交量、涨跌幅、换手率、市值、行业等。"""

    NUMERIC_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "between"}
    SET_OPS = {"in", "not_in"}
    STRING_OPS = {"eq", "ne", "contains", "in", "not_in"}

    @staticmethod
    def volume_ratio(current_volume: float, avg_volume: float) -> float | None:
        if avg_volume <= 0:
            return None
        return current_volume / avg_volume

    @staticmethod
    def change_pct(price: float, prev_close: float) -> float | None:
        if prev_close <= 0:
            return None
        return (price - prev_close) / prev_close * 100

    @staticmethod
    def market_cap(price: float, total_shares: int | float | None) -> float | None:
        if not total_shares or price <= 0:
            return None
        return float(price) * float(total_shares)

    @staticmethod
    def turnover_rate(value: float | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def sector_match(stock_sector: str | None, sectors: list[str]) -> bool:
        if not stock_sector or not sectors:
            return False
        normalized = stock_sector.strip().lower()
        return any(s.strip().lower() in normalized or normalized in s.strip().lower() for s in sectors)

    @classmethod
    def apply_condition(cls, stock: dict[str, Any], condition: dict[str, Any]) -> bool:
        field = condition.get("field")
        op = str(condition.get("op", "eq")).lower()
        expected = condition.get("value")
        actual = stock.get(field)

        if actual is None:
            return False

        if op in cls.SET_OPS:
            values = expected if isinstance(expected, list) else [expected]
            normalized = [str(v).upper() if field == "ai_action" else v for v in values]
            if field == "ai_action":
                actual_cmp = str(actual).upper()
            elif field == "sector":
                actual_cmp = str(actual)
                return cls.sector_match(actual_cmp, [str(v) for v in values]) if op == "in" else not cls.sector_match(
                    actual_cmp, [str(v) for v in values]
                )
            else:
                actual_cmp = actual
            if op == "in":
                return actual_cmp in normalized
            return actual_cmp not in normalized

        if op == "contains":
            return str(expected).lower() in str(actual).lower()

        if op == "between":
            if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                return False
            low, high = expected
            return float(low) <= float(actual) <= float(high)

        actual_num = float(actual)
        expected_num = float(expected)
        if op == "eq":
            return actual_num == expected_num
        if op == "ne":
            return actual_num != expected_num
        if op == "gt":
            return actual_num > expected_num
        if op == "gte":
            return actual_num >= expected_num
        if op == "lt":
            return actual_num < expected_num
        if op == "lte":
            return actual_num <= expected_num
        return False

    @classmethod
    def apply_filters(cls, stock: dict[str, Any], filters: list[dict[str, Any]]) -> bool:
        return all(cls.apply_condition(stock, cond) for cond in filters)

    @staticmethod
    def sort_key(stock: dict[str, Any], field: str) -> float:
        value = stock.get(field)
        if value is None:
            return float("-inf")
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("-inf")