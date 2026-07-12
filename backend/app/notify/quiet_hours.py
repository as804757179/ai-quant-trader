"""通知静默时段判断（Asia/Shanghai）。"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def parse_hhmm(s: str) -> time | None:
    s = (s or "").strip()
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        return time(int(h), int(m))
    except ValueError:
        return None


def parse_quiet_window(spec: str) -> tuple[time, time] | None:
    """
    解析 "23:00-08:00" 或 "12:00-13:30"。
    返回 (start, end)；跨日时 start > end（按分钟比较）。
    """
    spec = (spec or "").strip()
    if not spec or "-" not in spec:
        return None
    left, right = spec.split("-", 1)
    start = parse_hhmm(left)
    end = parse_hhmm(right)
    if not start or not end:
        return None
    return start, end


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def is_in_quiet_hours(
    quiet_spec: str,
    *,
    now: datetime | None = None,
) -> bool:
    """当前是否处于静默时段。"""
    window = parse_quiet_window(quiet_spec)
    if not window:
        return False
    start, end = window
    if now is None:
        now = datetime.now(TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    cur = _to_minutes(now.timetz().replace(tzinfo=None))
    s = _to_minutes(start)
    e = _to_minutes(end)
    if s == e:
        return False
    if s < e:
        # 同日窗口 09:00-15:00
        return s <= cur < e
    # 跨日 23:00-08:00
    return cur >= s or cur < e


def should_suppress_notify(
    level: str,
    quiet_spec: str,
    bypass_levels: set[str],
    *,
    now: datetime | None = None,
) -> bool:
    """静默时段内且级别不在 bypass 则抑制。"""
    if not is_in_quiet_hours(quiet_spec, now=now):
        return False
    return (level or "INFO").upper() not in bypass_levels
