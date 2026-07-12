"""钉钉机器人 Webhook 通知。"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import FEATURE_NOTIFY, get_logger
from app.data.cache import CacheManager

logger = get_logger(__name__, feature=FEATURE_NOTIFY)

# 同内容冷却秒数，避免刷屏
DEFAULT_COOLDOWN = 300


async def notify_dingtalk(
    title: str,
    text: str,
    *,
    level: str = "INFO",
    cooldown_seconds: int | None = None,
) -> dict[str, Any]:
    """
    发送钉钉 markdown 消息。
    需 ENABLE_DINGTALK_NOTIFY=true 且配置 DINGTALK_WEBHOOK。
    """
    if not settings.ENABLE_DINGTALK_NOTIFY:
        return {"sent": False, "reason": "disabled"}
    webhook = (settings.DINGTALK_WEBHOOK or "").strip()
    if not webhook:
        return {"sent": False, "reason": "no_webhook"}

    level_u = (level or "INFO").upper()
    allowed = settings.dingtalk_levels()
    if level_u not in allowed:
        return {"sent": False, "reason": "level_filtered", "level": level_u}

    from app.notify.quiet_hours import should_suppress_notify

    if should_suppress_notify(
        level_u,
        settings.DINGTALK_QUIET_HOURS,
        settings.dingtalk_quiet_bypass_levels(),
    ):
        return {"sent": False, "reason": "quiet_hours", "level": level_u}

    cooldown = (
        cooldown_seconds
        if cooldown_seconds is not None
        else int(getattr(settings, "DINGTALK_COOLDOWN_SECONDS", DEFAULT_COOLDOWN) or DEFAULT_COOLDOWN)
    )
    key_raw = f"{level_u}:{title}:{text[:120]}"
    cool_key = "dingtalk:cd:" + hashlib.md5(key_raw.encode()).hexdigest()

    cache = CacheManager()
    try:
        existing = await cache.get_raw(cool_key)
        if existing:
            return {"sent": False, "reason": "cooldown"}
    except Exception:
        pass

    body = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"[{level_u}] {title}"[:64],
            "text": (
                f"### [{level_u}] {title}\n\n"
                f"{text}\n\n"
                f"> AI Quant Trader Pro · {time.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        },
    }
    if level_u in ("CRITICAL", "ERROR"):
        body["at"] = {"isAtAll": True}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook, json=body)
            ok = resp.status_code == 200
            data = {}
            try:
                data = resp.json()
            except Exception:
                data = {"status_code": resp.status_code}
            if ok and data.get("errcode", 0) == 0:
                try:
                    await cache.set_raw(cool_key, "1", ttl=cooldown)
                except Exception:
                    pass
                logger.info("dingtalk_sent", level=level_u, title=title)
                try:
                    from app.monitoring.metrics import record_dingtalk

                    record_dingtalk(True)
                except Exception:
                    pass
                return {"sent": True, "response": data}
            logger.warning("dingtalk_failed", status=resp.status_code, body=data)
            try:
                from app.monitoring.metrics import record_dingtalk

                record_dingtalk(False)
            except Exception:
                pass
            return {"sent": False, "reason": "api_error", "response": data}
    except Exception as exc:
        logger.warning("dingtalk_error", error=str(exc))
        try:
            from app.monitoring.metrics import record_dingtalk

            record_dingtalk(False)
        except Exception:
            pass
        return {"sent": False, "reason": str(exc)}
