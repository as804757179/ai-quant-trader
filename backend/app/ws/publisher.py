from __future__ import annotations

import json
from app.core.timeutil import now_cn_iso
from typing import Any

from app.data.cache import CacheManager

ALERTS_HISTORY_KEY = "alerts:history"
ALERTS_HISTORY_MAX = 100


async def publish_signal(data: dict[str, Any]) -> None:
    cache = CacheManager()
    await cache.publish("channel:signals", data)


async def publish_alert(
    alert_type: str,
    level: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> None:
    cache = CacheManager()
    payload = {
        "type": alert_type,
        "level": level.upper() if level else "INFO",
        "message": message,
        "detail": detail or {},
        "ts": now_cn_iso(),
    }
    await cache.publish("channel:alerts", payload)
    # 最近告警历史（Redis List）
    try:
        client = await cache._get_client()
        await client.lpush(
            ALERTS_HISTORY_KEY,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
        await client.ltrim(ALERTS_HISTORY_KEY, 0, ALERTS_HISTORY_MAX - 1)
    except Exception:
        pass

    try:
        from app.monitoring.metrics import record_alert

        record_alert(payload["level"], alert_type or "unknown")
    except Exception:
        pass

    # 按配置级别转发钉钉
    try:
        from app.core.config import settings
        from app.notify.dingtalk import notify_dingtalk

        if payload["level"] in settings.dingtalk_levels():
            await notify_dingtalk(
                title=alert_type or "alert",
                text=message,
                level=payload["level"],
            )
    except Exception:
        pass


async def get_recent_alerts(
    limit: int = 50,
    *,
    level: str | None = None,
    alert_type: str | None = None,
) -> list[dict[str, Any]]:
    cache = CacheManager()
    # 多取再过滤
    fetch_n = max(1, min(limit * 3 if (level or alert_type) else limit, ALERTS_HISTORY_MAX))
    try:
        client = await cache._get_client()
        raw = await client.lrange(ALERTS_HISTORY_KEY, 0, fetch_n - 1)
        items: list[dict[str, Any]] = []
        level_u = level.upper() if level else None
        for item in raw or []:
            try:
                obj = json.loads(item)
            except json.JSONDecodeError:
                continue
            if level_u and str(obj.get("level", "")).upper() != level_u:
                continue
            if alert_type and obj.get("type") != alert_type:
                continue
            items.append(obj)
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []


async def summarize_alerts(limit: int = 100) -> dict[str, Any]:
    items = await get_recent_alerts(limit=limit)
    by_level: dict[str, int] = {}
    for it in items:
        lv = str(it.get("level") or "INFO").upper()
        by_level[lv] = by_level.get(lv, 0) + 1
    return {
        "total": len(items),
        "by_level": by_level,
        "critical": by_level.get("CRITICAL", 0),
        "error": by_level.get("ERROR", 0),
        "warning": by_level.get("WARNING", 0),
        "info": by_level.get("INFO", 0),
        "latest": items[0] if items else None,
    }


async def publish_portfolio_update(mode: str, data: dict[str, Any]) -> None:
    cache = CacheManager()
    await cache.publish(f"channel:portfolio:{mode}", data)
