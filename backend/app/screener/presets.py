from __future__ import annotations

from typing import Any

PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "ai_momentum": {
        "id": "ai_momentum",
        "name": "AI动量",
        "description": "近期涨幅 + 成交量放大 + AI 信号偏多",
        "conditions": {
            "filters": [
                {"field": "change_pct", "op": "gte", "value": 2.0},
                {"field": "volume_ratio", "op": "gte", "value": 1.2},
                {"field": "ai_confidence", "op": "gte", "value": 0.6},
            ],
            "sort_by": "change_pct",
            "sort_order": "desc",
        },
    },
    "value_rebound": {
        "id": "value_rebound",
        "name": "低估回弹",
        "description": "低 PB + 近期超跌 + 资金净流入",
        "conditions": {
            "filters": [
                {"field": "pb_ratio", "op": "lte", "value": 2.5},
                {"field": "recent_return_5d", "op": "lte", "value": -3.0},
                {"field": "main_net_in_5d", "op": "gt", "value": 0},
            ],
            "sort_by": "main_net_in_5d",
            "sort_order": "desc",
        },
    },
    "sector_leader": {
        "id": "sector_leader",
        "name": "行业龙头",
        "description": "行业内成交额排名靠前 + 基本面较好",
        "conditions": {
            "preset_handler": "sector_leader",
            "filters": [
                {"field": "sector_rank_pct", "op": "lte", "value": 0.2},
                {"field": "roe", "op": "gte", "value": 8.0},
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