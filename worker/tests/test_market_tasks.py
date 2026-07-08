import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", os.environ["REDIS_URL"])
os.environ.setdefault("CELERY_RESULT_BACKEND", os.environ["REDIS_URL"])
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)

from services.quote_sync import QuoteSyncService


def test_sync_one_writes_redis_and_publishes() -> None:
    async def _run() -> None:
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock()
        mock_cache.publish = AsyncMock()
        mock_cache.close = AsyncMock()

        mock_client = MagicMock()
        mock_client.fetch_quote = AsyncMock(
            return_value={
                "price": 10.5,
                "high": 10.8,
                "low": 10.2,
                "prev_close": 10.0,
            }
        )
        mock_client.close = AsyncMock()

        service = QuoteSyncService(
            data_client=mock_client,
            cache=mock_cache,
            concurrency=1,
        )
        ok = await service._sync_one("000001", asyncio.Semaphore(1))
        assert ok is True
        mock_cache.set.assert_awaited_once()
        call_args = mock_cache.set.await_args
        assert call_args.args[0] == "quote:000001"
        assert call_args.args[1]["price"] == 10.5
        assert mock_cache.publish.await_count == 2

    asyncio.run(_run())


def test_sync_one_invalid_quote_returns_false() -> None:
    async def _run() -> None:
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock()
        mock_cache.publish = AsyncMock()

        mock_client = MagicMock()
        mock_client.fetch_quote = AsyncMock(return_value={"price": 0})
        mock_client.close = AsyncMock()

        service = QuoteSyncService(data_client=mock_client, cache=mock_cache)
        ok = await service._sync_one("000001", asyncio.Semaphore(1))
        assert ok is False
        mock_cache.set.assert_not_awaited()

    asyncio.run(_run())


def test_sync_all_partial_failure() -> None:
    async def _run() -> None:
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock()
        mock_cache.publish = AsyncMock()
        mock_cache.close = AsyncMock()

        async def _fetch(code: str) -> dict | None:
            if code == "000002":
                raise RuntimeError("network error")
            return {"price": 11.0, "high": 11.5, "low": 10.8}

        mock_client = MagicMock()
        mock_client.fetch_quote = AsyncMock(side_effect=_fetch)
        mock_client.close = AsyncMock()

        service = QuoteSyncService(
            data_client=mock_client,
            cache=mock_cache,
            concurrency=2,
        )
        with patch(
            "services.quote_sync.get_active_stock_codes",
            AsyncMock(return_value=["000001", "000002", "000003"]),
        ):
            result = await service.sync_all()

        assert result["total"] == 3
        assert result["synced"] == 2
        assert result["failed"] == 1

    asyncio.run(_run())


def test_sync_realtime_quotes_task_runs() -> None:
    from celery_app import app

    with patch(
        "asyncio.run",
        return_value={"synced": 5, "failed": 0, "total": 5, "latency_ms": 100},
    ):
        task = app.tasks["tasks.sync_realtime_quotes"]
        result = task.run()

    assert result["status"] == "ok"
    assert result["synced"] == 5
    assert result["task"] == "sync_realtime_quotes"


def test_validate_quote_rejects_bad_data() -> None:
    from services.data_client import validate_quote

    assert validate_quote(None) is False
    assert validate_quote({"price": -1}) is False
    assert validate_quote({"price": 10, "high": 9, "low": 11}) is False
    assert validate_quote({"price": 10.5, "high": 11, "low": 10}) is True