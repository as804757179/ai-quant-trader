"""Portfolio sync / T+1 释放任务逻辑测试。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", os.environ["REDIS_URL"])
os.environ.setdefault("CELERY_RESULT_BACKEND", os.environ["REDIS_URL"])
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)

from services.portfolio_sync import PortfolioSyncService


def test_release_available_quantity_sql() -> None:
    async def _run() -> None:
        mock_session = AsyncMock()
        result = MagicMock()
        result.rowcount = 5
        mock_session.execute = AsyncMock(return_value=result)
        mock_session.commit = AsyncMock()

        # async with factory() as session
        factory = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        factory.return_value = cm

        with patch("services.portfolio_sync._get_session_factory", return_value=factory):
            svc = PortfolioSyncService(cache=MagicMock())
            out = await svc.release_available_quantity("simulation")
        assert out["released_rows"] == 5
        assert out["status"] == "ok"
        sql = str(mock_session.execute.await_args.args[0])
        assert "available_qty = total_qty" in sql

    asyncio.run(_run())


def test_recompute_account_math() -> None:
    async def _run() -> None:
        mock_session = AsyncMock()
        acc = MagicMock()
        acc.mappings.return_value.first.return_value = {"id": 9, "cash": 70_000}
        mv = MagicMock()
        mv.mappings.return_value.first.return_value = {"mv": 30_000, "cnt": 1}
        mock_session.execute = AsyncMock(side_effect=[acc, mv, MagicMock()])

        svc = PortfolioSyncService(cache=MagicMock())
        ok = await svc._recompute_account(mock_session, "simulation")
        assert ok is True
        update_params = mock_session.execute.await_args_list[2].args[1]
        assert update_params["total_assets"] == 100_000
        assert update_params["market_value"] == 30_000

    asyncio.run(_run())
