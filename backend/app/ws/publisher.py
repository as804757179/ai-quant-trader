from __future__ import annotations

from typing import Any

from app.data.cache import CacheManager


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
    await cache.publish(
        "channel:alerts",
        {
            "type": alert_type,
            "level": level,
            "message": message,
            "detail": detail or {},
        },
    )


async def publish_portfolio_update(mode: str, data: dict[str, Any]) -> None:
    cache = CacheManager()
    await cache.publish(f"channel:portfolio:{mode}", data)