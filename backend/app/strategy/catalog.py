"""内置策略元数据。"""

from __future__ import annotations

from typing import Any

OHLCV_RETURN_FIELDS = [
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjustment",
    "trading_calendar",
    "corporate_action_status",
]

STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "dual_ma": {
        "type": "dual_ma",
        "requirement_profile": "OHLCV_RETURN_V1",
        "required_fields": OHLCV_RETURN_FIELDS,
        "name": "双均线交叉",
        "description": "快线上穿慢线买入，下穿卖出；适合趋势行情。",
        "scenario": "趋势跟踪",
        "default_params": {
            "fast_period": 5,
            "slow_period": 20,
            "position_pct": 0.2,
        },
        "param_schema": {
            "fast_period": {"type": "int", "min": 2, "max": 60},
            "slow_period": {"type": "int", "min": 5, "max": 250},
            "position_pct": {"type": "float", "min": 0.05, "max": 1.0},
        },
    },
    "bollinger": {
        "type": "bollinger",
        "requirement_profile": "OHLCV_RETURN_V1",
        "required_fields": OHLCV_RETURN_FIELDS,
        "name": "布林带均值回归",
        "description": "跌破下轨买入，突破上轨卖出。",
        "scenario": "震荡市",
        "default_params": {
            "period": 20,
            "std_mult": 2.0,
            "position_pct": 0.2,
        },
        "param_schema": {
            "period": {"type": "int", "min": 5, "max": 120},
            "std_mult": {"type": "float", "min": 1.0, "max": 3.5},
            "position_pct": {"type": "float", "min": 0.05, "max": 1.0},
        },
    },
    "rsi": {
        "type": "rsi",
        "requirement_profile": "OHLCV_RETURN_V1",
        "required_fields": OHLCV_RETURN_FIELDS,
        "name": "RSI 超买超卖",
        "description": "RSI 低于超卖线买入，高于超买线卖出。",
        "scenario": "短线反转",
        "default_params": {
            "period": 14,
            "oversold": 30,
            "overbought": 70,
            "position_pct": 0.2,
        },
        "param_schema": {
            "period": {"type": "int", "min": 5, "max": 30},
            "oversold": {"type": "float", "min": 10, "max": 40},
            "overbought": {"type": "float", "min": 60, "max": 90},
            "position_pct": {"type": "float", "min": 0.05, "max": 1.0},
        },
    },
    "macd": {
        "type": "macd",
        "requirement_profile": "OHLCV_RETURN_V1",
        "required_fields": OHLCV_RETURN_FIELDS,
        "name": "MACD 金叉死叉",
        "description": "DIF 上穿 DEA 买入，下穿卖出。",
        "scenario": "趋势确认",
        "default_params": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "position_pct": 0.2,
        },
        "param_schema": {
            "fast_period": {"type": "int", "min": 5, "max": 30},
            "slow_period": {"type": "int", "min": 10, "max": 60},
            "signal_period": {"type": "int", "min": 3, "max": 20},
            "position_pct": {"type": "float", "min": 0.05, "max": 1.0},
        },
    },
}


def list_strategy_types() -> list[str]:
    return list(STRATEGY_CATALOG.keys())


def get_strategy_meta(strategy_type: str) -> dict[str, Any] | None:
    return STRATEGY_CATALOG.get(strategy_type)
