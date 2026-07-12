"""账本工具与 T+1 释放单元测试。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.trade.account_ledger import (
    compute_total_assets,
    recompute_account_assets,
    release_t1_available_qty,
)


def test_compute_total_assets() -> None:
    assert compute_total_assets(100_000, 50_000) == 150_000
    assert compute_total_assets(0, 0) == 0
    assert compute_total_assets(10.5, 20.25) == 30.75


def test_recompute_account_assets_updates_totals() -> None:
    async def _run() -> None:
        db = AsyncMock()

        # 1) SELECT account
        acc_result = MagicMock()
        acc_result.mappings.return_value.first.return_value = {
            "id": 1,
            "cash": 80_000.0,
            "daily_pnl": 0,
            "total_pnl": 0,
        }

        # 2) SUM positions
        sum_result = MagicMock()
        sum_result.mappings.return_value.first.return_value = {
            "mv": 20_000.0,
            "cnt": 2,
        }

        # 3) UPDATE
        update_result = MagicMock()

        db.execute = AsyncMock(side_effect=[acc_result, sum_result, update_result])

        out = await recompute_account_assets(db, "simulation")
        assert out["updated"] is True
        assert out["total_assets"] == 100_000.0
        assert out["market_value"] == 20_000.0
        assert out["cash"] == 80_000.0
        assert db.execute.await_count == 3

        # UPDATE 参数校验
        update_call = db.execute.await_args_list[2]
        params = update_call.args[1]
        assert params["total_assets"] == 100_000.0
        assert params["market_value"] == 20_000.0
        assert params["position_count"] == 2

    asyncio.run(_run())


def test_recompute_no_account() -> None:
    async def _run() -> None:
        db = AsyncMock()
        acc_result = MagicMock()
        acc_result.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=acc_result)
        out = await recompute_account_assets(db, "simulation")
        assert out["updated"] is False

    asyncio.run(_run())


def test_release_t1_available_qty() -> None:
    async def _run() -> None:
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 3
        db.execute = AsyncMock(return_value=result)
        out = await release_t1_available_qty(db, "simulation")
        assert out["released_rows"] == 3
        assert out["mode"] == "simulation"
        sql = str(db.execute.await_args.args[0])
        assert "available_qty = total_qty" in sql

    asyncio.run(_run())
