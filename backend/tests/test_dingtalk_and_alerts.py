"""钉钉通知与告警汇总。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.core import config as config_mod
from app.notify import dingtalk
from app.ws import publisher


def test_dingtalk_disabled() -> None:
    async def _run() -> None:
        config_mod.settings.ENABLE_DINGTALK_NOTIFY = False
        out = await dingtalk.notify_dingtalk("t", "m", level="CRITICAL")
        assert out["sent"] is False
        assert out["reason"] == "disabled"

    asyncio.run(_run())


def test_dingtalk_sends_when_enabled() -> None:
    async def _run() -> None:
        config_mod.settings.ENABLE_DINGTALK_NOTIFY = True
        config_mod.settings.DINGTALK_ALERT_LEVELS = "CRITICAL,ERROR"
        config_mod.settings.DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=x"

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
            out = await dingtalk.notify_dingtalk("fuse", "熔断触发", level="CRITICAL")

        assert out["sent"] is True
        mock_client.post.assert_awaited()
        body = mock_client.post.await_args.kwargs.get("json") or mock_client.post.await_args[1].get(
            "json"
        )
        if body is None:
            body = mock_client.post.await_args.args[1] if len(mock_client.post.await_args.args) > 1 else mock_client.post.await_args.kwargs["json"]
        # 验证 at all
        posted = mock_client.post.await_args.kwargs["json"]
        assert posted["at"]["isAtAll"] is True

    asyncio.run(_run())


def test_dingtalk_cooldown() -> None:
    async def _run() -> None:
        config_mod.settings.ENABLE_DINGTALK_NOTIFY = True
        config_mod.settings.DINGTALK_WEBHOOK = "https://example.com/hook"
        config_mod.settings.DINGTALK_ALERT_LEVELS = "CRITICAL,ERROR"

        cache = MagicMock()
        cache.get_raw = AsyncMock(return_value="1")
        with patch("app.notify.dingtalk.CacheManager", return_value=cache):
            out = await dingtalk.notify_dingtalk("t", "m", level="ERROR")
        assert out["sent"] is False
        assert out["reason"] == "cooldown"

    asyncio.run(_run())


def test_summarize_alerts() -> None:
    async def _run() -> None:
        with patch(
            "app.ws.publisher.get_recent_alerts",
            new_callable=AsyncMock,
            return_value=[
                {"level": "CRITICAL", "message": "a"},
                {"level": "WARNING", "message": "b"},
                {"level": "WARNING", "message": "c"},
                {"level": "INFO", "message": "d"},
            ],
        ):
            s = await publisher.summarize_alerts(50)
        assert s["total"] == 4
        assert s["critical"] == 1
        assert s["warning"] == 2
        assert s["latest"]["message"] == "a"

    asyncio.run(_run())


def test_publish_alert_triggers_dingtalk_for_critical() -> None:
    async def _run() -> None:
        config_mod.settings.DINGTALK_ALERT_LEVELS = "CRITICAL,ERROR"
        cache = MagicMock()
        cache.publish = AsyncMock()
        client = AsyncMock()
        client.lpush = AsyncMock()
        client.ltrim = AsyncMock()
        cache._get_client = AsyncMock(return_value=client)

        with (
            patch("app.ws.publisher.CacheManager", return_value=cache),
            patch(
                "app.notify.dingtalk.notify_dingtalk",
                new_callable=AsyncMock,
            ) as ding,
        ):
            await publisher.publish_alert("fuse_activated", "CRITICAL", "熔断", {})
            ding.assert_awaited()

            ding.reset_mock()
            await publisher.publish_alert("order_filled", "INFO", "成交", {})
            ding.assert_not_awaited()

    asyncio.run(_run())
