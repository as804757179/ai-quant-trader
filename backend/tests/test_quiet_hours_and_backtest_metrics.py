"""静默时段与回测 metrics。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.monitoring.metrics import metrics_response, record_backtest
from app.notify.quiet_hours import (
    is_in_quiet_hours,
    parse_quiet_window,
    should_suppress_notify,
)

TZ = ZoneInfo("Asia/Shanghai")


def test_parse_quiet_window() -> None:
    w = parse_quiet_window("23:00-08:00")
    assert w is not None
    assert w[0].hour == 23
    assert w[1].hour == 8
    assert parse_quiet_window("") is None


def test_quiet_hours_same_day() -> None:
    # 12:00-13:00
    noon = datetime(2024, 6, 1, 12, 30, tzinfo=TZ)
    assert is_in_quiet_hours("12:00-13:00", now=noon) is True
    morning = datetime(2024, 6, 1, 10, 0, tzinfo=TZ)
    assert is_in_quiet_hours("12:00-13:00", now=morning) is False


def test_quiet_hours_cross_midnight() -> None:
    late = datetime(2024, 6, 1, 23, 30, tzinfo=TZ)
    early = datetime(2024, 6, 2, 7, 0, tzinfo=TZ)
    mid = datetime(2024, 6, 1, 12, 0, tzinfo=TZ)
    assert is_in_quiet_hours("23:00-08:00", now=late) is True
    assert is_in_quiet_hours("23:00-08:00", now=early) is True
    assert is_in_quiet_hours("23:00-08:00", now=mid) is False


def test_suppress_bypass_critical() -> None:
    night = datetime(2024, 6, 1, 23, 30, tzinfo=TZ)
    assert (
        should_suppress_notify(
            "WARNING",
            "23:00-08:00",
            {"CRITICAL"},
            now=night,
        )
        is True
    )
    assert (
        should_suppress_notify(
            "CRITICAL",
            "23:00-08:00",
            {"CRITICAL"},
            now=night,
        )
        is False
    )


def test_record_backtest_metrics() -> None:
    record_backtest("done", 1.5)
    record_backtest("failed", 0.2)
    text = metrics_response()[0].decode()
    assert "quant_backtest_total" in text


def test_dingtalk_respects_quiet_hours() -> None:
    import asyncio
    from unittest.mock import patch

    from app.core import config as config_mod
    from app.notify import dingtalk

    async def _run() -> None:
        config_mod.settings.ENABLE_DINGTALK_NOTIFY = True
        config_mod.settings.DINGTALK_WEBHOOK = "https://example.com/hook"
        config_mod.settings.DINGTALK_ALERT_LEVELS = "WARNING,CRITICAL"
        config_mod.settings.DINGTALK_QUIET_HOURS = "00:00-23:59"
        config_mod.settings.DINGTALK_QUIET_BYPASS_LEVELS = "CRITICAL"

        # WARNING 在全天静默内被抑制
        out = await dingtalk.notify_dingtalk("t", "m", level="WARNING")
        assert out["reason"] == "quiet_hours"

        # CRITICAL 可 bypass
        with patch(
            "app.notify.dingtalk.httpx.AsyncClient"
        ) as Client, patch(
            "app.notify.dingtalk.CacheManager"
        ) as Cache:
            from unittest.mock import AsyncMock, MagicMock

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"errcode": 0}
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            Client.return_value = client
            cache = MagicMock()
            cache.get_raw = AsyncMock(return_value=None)
            cache.set_raw = AsyncMock()
            Cache.return_value = cache
            out2 = await dingtalk.notify_dingtalk("t", "m", level="CRITICAL")
            assert out2["sent"] is True

    asyncio.run(_run())
