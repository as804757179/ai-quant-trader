from __future__ import annotations

from typing import Any

# 预设尽量依赖 stocks + klines 可算出的因子，避免无财务/AI 数据时永远空结果
PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "all_active": {
        "id": "all_active",
        "name": "全部（有行情/K线优先）",
        "description": "不过滤条件，返回股票池全部（按成交额排序）",
        "conditions": {
            "filters": [],
            "sort_by": "amount",
            "sort_order": "desc",
        },
    },
    "ai_momentum": {
        "id": "ai_momentum",
        "name": "动量偏强",
        "description": "日涨跌幅≥0 且量比≥0.8",
        "conditions": {
            "filters": [
                {"field": "change_pct", "op": "gte", "value": 0.0},
                {"field": "volume_ratio", "op": "gte", "value": 0.8},
            ],
            "sort_by": "change_pct",
            "sort_order": "desc",
        },
    },
    "value_rebound": {
        "id": "value_rebound",
        "name": "近端回调",
        "description": "近 5 日收益相对偏低（便于找超跌）",
        "conditions": {
            "filters": [
                {"field": "recent_return_5d", "op": "lte", "value": 5.0},
            ],
            "sort_by": "recent_return_5d",
            "sort_order": "asc",
        },
    },
    "sector_leader": {
        "id": "sector_leader",
        "name": "行业龙头",
        "description": "行业内成交额排名前 50%",
        "conditions": {
            "preset_handler": "sector_leader",
            "filters": [
                {"field": "sector_rank_pct", "op": "lte", "value": 0.5},
            ],
            "sort_by": "amount",
            "sort_order": "desc",
        },
    },
}


def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
        }
        for p in PRESET_DEFINITIONS.values()
    ]


def get_preset_conditions(preset_id: str) -> dict[str, Any] | None:
    preset = PRESET_DEFINITIONS.get(preset_id)
    if not preset:
        return None
    return dict(preset["conditions"])
