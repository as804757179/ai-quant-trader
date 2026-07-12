"""维护任务单元测试。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)

from services.maintenance_ops import check_kline_completeness, reconcile_accounts


def test_reconcile_detects_and_fixes_drift() -> None:
    async def _run() -> None:
        mock_session = AsyncMock()

        # mode simulation: account + position + update
        acc = MagicMock()
        acc.mappings.return_value.first.return_value = {
            "id": 1,
            "cash": 50_000,
            "market_value": 40_000,  # stale
            "total_assets": 100_000,  # wrong vs cash+pos
        }
        pos = MagicMock()
        pos.scalar.return_value = 50_000  # real mv
        # for other modes: None
        empty = MagicMock()
        empty.mappings.return_value.first.return_value = None

        calls = []

        async def execute(sql, params=None):
            s = str(sql)
            calls.append(s)
            if "FROM trade.account_records" in s and params and params.get("mode") == "simulation":
                return acc
            if "SUM(market_value)" in s and params and params.get("mode") == "simulation":
                return pos
            if "FROM trade.account_records" in s:
                return empty
            return MagicMock()

        mock_session.execute = execute
        mock_session.commit = AsyncMock()

        factory = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        factory.return_value = cm

        with patch("services.maintenance_ops._get_session_factory", return_value=factory):
            out = await reconcile_accounts()

        assert out["issue_count"] >= 1
        assert any("UPDATE trade.account_records" in c for c in calls)

    asyncio.run(_run())


def test_check_kline_completeness_ratio() -> None:
    async def _run() -> None:
        mock_session = AsyncMock()
        c1 = MagicMock()
        c1.scalar.return_value = 100
        c2 = MagicMock()
        c2.scalar.return_value = 80
        mock_session.execute = AsyncMock(side_effect=[c1, c2])

        factory = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        factory.return_value = cm

        with patch("services.maintenance_ops._get_session_factory", return_value=factory):
            out = await check_kline_completeness(5)

        assert out["status"] == "ok"
        assert out["coverage_ratio"] == 0.8

    asyncio.run(_run())
