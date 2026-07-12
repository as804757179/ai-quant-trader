"""中国时区工具（Asia/Shanghai，UTC+8）。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def now_cn() -> datetime:
    """当前中国时间（带时区）。"""
    return datetime.now(CN_TZ)


def now_cn_iso() -> str:
    """ISO8601 字符串，含 +08:00。"""
    return now_cn().isoformat(timespec="seconds")


def today_cn() -> date:
    return now_cn().date()


def ensure_cn(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CN_TZ)
    return dt.astimezone(CN_TZ)


def to_cn_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_cn(dt).isoformat(timespec="seconds")
