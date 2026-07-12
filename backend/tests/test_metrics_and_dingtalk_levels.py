"""Prometheus 指标与钉钉级别过滤。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("WS_REDIS_ENABLED", "false")

from app.core import config as config_mod
from app.monitoring import metrics
from app.notify import dingtalk


def test_metrics_record_and_export() -> None:
    metrics.record_alert("CRITICAL", "fuse_activated")
    metrics.record_order("paper", "FILLED")
    metrics.set_fuse_active("simulation", True)
    metrics.record_dingtalk(True)
    metrics.set_ws_connections(3)
    body, ctype = metrics.metrics_response()
    text = body.decode("utf-8")
    assert "quant_alerts_total" in text
    assert "quant_risk_fuse_active" in text
    assert "quant_ws_connections" in text
    assert "text/plain" in ctype or "openmetrics" in ctype or "prometheus" in ctype


def test_dingtalk_level_filter() -> None:
    async def _run() -> None:
        config_mod.settings.ENABLE_DINGTALK_NOTIFY = True
        config_mod.settings.DINGTALK_WEBHOOK = "https://example.com/hook"
        config_mod.settings.DINGTALK_ALERT_LEVELS = "CRITICAL"

        out = await dingtalk.notify_dingtalk("t", "m", level="WARNING")
        assert out["sent"] is False
        assert out["reason"] == "level_filtered"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errcode": 0}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        cache = MagicMock()
        cache.get_raw = AsyncMock(return_value=None)
        cache.set_raw = AsyncMock()

        with (
            patch("app.notify.dingtalk.httpx.AsyncClient", return_value=mock_client),
            patch("app.notify.dingtalk.CacheManager", return_value=cache),
        ):
            out2 = await dingtalk.notify_dingtalk("t", "m", level="CRITICAL")
        assert out2["sent"] is True

    asyncio.run(_run())


def test_settings_dingtalk_levels() -> None:
    config_mod.settings.DINGTALK_ALERT_LEVELS = "CRITICAL, warning ,INFO"
    levels = config_mod.settings.dingtalk_levels()
    assert levels == {"CRITICAL", "WARNING", "INFO"}


def test_metrics_endpoint() -> None:
    async def _run() -> None:
        import httpx
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/metrics")
            assert r.status_code == 200
            assert "quant_" in r.text or "python_" in r.text or len(r.content) > 0

    asyncio.run(_run())
