from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_LEVEL_BY_ACTION = {
    "critical": "CRITICAL",
    "block": "ERROR",
    "error": "ERROR",
    "warn": "WARNING",
    "warning": "WARNING",
    "alert": "WARNING",
    "info": "INFO",
}
_ACTIONS_BY_LEVEL = {
    "CRITICAL": ("critical",),
    "ERROR": ("block", "error"),
    "WARNING": ("warn", "warning", "alert"),
    "INFO": ("info",),
}


def _detail(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _serialize_event(row: dict[str, Any]) -> dict[str, Any]:
    detail = _detail(row.get("detail"))
    action_taken = str(row.get("action_taken") or "info").lower()
    created_at = row.get("created_at")
    return {
        "id": str(row["id"]),
        "level": _LEVEL_BY_ACTION.get(action_taken, "INFO"),
        "alert_type": row["rule_code"],
        "type": row["rule_code"],
        "message": detail.get("message") or f"风险规则触发：{row['rule_code']}",
        "detail": detail,
        "action_taken": action_taken,
        "trigger_value": _optional_float(row.get("trigger_value")),
        "threshold": _optional_float(row.get("threshold")),
        "is_resolved": bool(row.get("is_resolved")),
        "resolved_at": row["resolved_at"].isoformat()
        if row.get("resolved_at")
        else None,
        "resolved_by": row.get("resolved_by"),
        "created_at": created_at.isoformat() if created_at else None,
    }


async def list_persisted_risk_alerts(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    level: str | None = None,
    alert_type: str | None = None,
) -> dict[str, Any]:
    filters: list[str] = []
    params: dict[str, Any] = {}
    normalized_level = level.upper() if level else None
    if normalized_level:
        actions = _ACTIONS_BY_LEVEL.get(normalized_level)
        if actions is None:
            filters.append("FALSE")
        else:
            action_values = ", ".join(f"'{action}'" for action in actions)
            filters.append(f"LOWER(action_taken) IN ({action_values})")
    if alert_type:
        filters.append("rule_code = :alert_type")
        params["alert_type"] = alert_type

    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    count_result = await db.execute(
        text(f"SELECT COUNT(*) AS total FROM risk.risk_events{where}"),
        params,
    )
    count_row = count_result.mappings().first()
    total = int(count_row["total"]) if count_row else 0

    query_params = {
        **params,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    result = await db.execute(
        text(
            f"""
            SELECT id, rule_code, trigger_value, threshold, action_taken, detail,
                   is_resolved, resolved_at, resolved_by, created_at
            FROM risk.risk_events{where}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        query_params,
    )
    items = [_serialize_event(dict(row)) for row in result.mappings().all()]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "level": normalized_level,
        "type": alert_type,
        "source": "risk.risk_events",
        "source_version": "risk-alerts-v1",
    }


async def summarize_persisted_risk_alerts(
    db: AsyncSession,
    *,
    limit: int,
) -> dict[str, Any]:
    window = await list_persisted_risk_alerts(db, page=1, page_size=limit)
    by_level: dict[str, int] = {}
    for item in window["items"]:
        item_level = item["level"]
        by_level[item_level] = by_level.get(item_level, 0) + 1
    return {
        "total": len(window["items"]),
        "available_total": window["total"],
        "by_level": by_level,
        "critical": by_level.get("CRITICAL", 0),
        "error": by_level.get("ERROR", 0),
        "warning": by_level.get("WARNING", 0),
        "info": by_level.get("INFO", 0),
        "latest": window["items"][0] if window["items"] else None,
        "items": window["items"],
        "source": window["source"],
        "source_version": window["source_version"],
    }
