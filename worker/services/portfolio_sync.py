"""持仓市值同步 + 账户总资产重算 + T+1 可卖释放。"""

from __future__ import annotations

import os
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.cache import CacheManager

logger = structlog.get_logger(__name__)

_engine = None
_session_factory = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        database_url = os.getenv("DATABASE_URL", "")
        _engine = create_async_engine(database_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


class PortfolioSyncService:
    """从 Redis 行情刷新持仓市值，并重算 account_records.total_assets。"""

    MODES = ("simulation", "paper", "live")

    def __init__(self, cache: CacheManager | None = None) -> None:
        self.cache = cache or CacheManager()
        self._owns_cache = cache is None

    async def close(self) -> None:
        if self._owns_cache:
            await self.cache.close()

    async def sync_all(self) -> dict[str, Any]:
        factory = _get_session_factory()
        stats: dict[str, Any] = {
            "modes": [],
            "positions_updated": 0,
            "accounts_updated": 0,
        }
        async with factory() as session:
            for mode in self.MODES:
                mode_stats = await self._sync_mode(session, mode)
                stats["modes"].append(mode_stats)
                stats["positions_updated"] += mode_stats.get("positions_updated", 0)
                if mode_stats.get("account_updated"):
                    stats["accounts_updated"] += 1
            await session.commit()
        logger.info("portfolio_sync_done", **stats)
        return stats

    async def release_available_quantity(self, mode: str | None = None) -> dict[str, Any]:
        """T+1：available_qty = total_qty。"""
        factory = _get_session_factory()
        async with factory() as session:
            if mode:
                result = await session.execute(
                    text(
                        """
                        UPDATE trade.positions
                        SET available_qty = total_qty,
                            updated_at = NOW()
                        WHERE mode = :mode
                          AND total_qty > 0
                          AND available_qty < total_qty
                        """
                    ),
                    {"mode": mode},
                )
            else:
                result = await session.execute(
                    text(
                        """
                        UPDATE trade.positions
                        SET available_qty = total_qty,
                            updated_at = NOW()
                        WHERE total_qty > 0
                          AND available_qty < total_qty
                        """
                    )
                )
            released = int(result.rowcount or 0)
            await session.commit()
        logger.info("t1_available_released", released_rows=released, mode=mode or "all")
        return {"released_rows": released, "mode": mode or "all", "status": "ok"}

    async def _sync_mode(self, session: AsyncSession, mode: str) -> dict[str, Any]:
        positions = await session.execute(
            text(
                """
                SELECT stock_code, total_qty, avg_cost
                FROM trade.positions
                WHERE mode = :mode AND total_qty > 0
                """
            ),
            {"mode": mode},
        )
        rows = list(positions.mappings().all())
        updated = 0
        for row in rows:
            code = row["stock_code"]
            quote = await self.cache.get(f"quote:{code}")
            if not quote or not quote.get("price"):
                continue
            price = float(quote["price"])
            qty = int(row["total_qty"])
            avg_cost = float(row["avg_cost"] or 0)
            market_value = price * qty
            unrealized_pnl = (price - avg_cost) * qty
            unrealized_pnl_pct = ((price / avg_cost - 1) * 100) if avg_cost > 0 else 0.0
            await session.execute(
                text(
                    """
                    UPDATE trade.positions
                    SET current_price = :price,
                        market_value = :market_value,
                        unrealized_pnl = :unrealized_pnl,
                        unrealized_pnl_pct = :unrealized_pnl_pct,
                        updated_at = NOW()
                    WHERE stock_code = :code AND mode = :mode
                    """
                ),
                {
                    "price": price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "code": code,
                    "mode": mode,
                },
            )
            updated += 1

        account_updated = await self._recompute_account(session, mode)
        return {
            "mode": mode,
            "positions_updated": updated,
            "position_count": len(rows),
            "account_updated": account_updated,
        }

    async def _recompute_account(self, session: AsyncSession, mode: str) -> bool:
        acc = await session.execute(
            text(
                """
                SELECT id, cash FROM trade.account_records
                WHERE mode = :mode
                ORDER BY record_time DESC
                LIMIT 1
                """
            ),
            {"mode": mode},
        )
        account = acc.mappings().first()
        if not account:
            return False

        mv_row = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(market_value), 0) AS mv,
                       COUNT(*)::int AS cnt
                FROM trade.positions
                WHERE mode = :mode AND total_qty > 0
                """
            ),
            {"mode": mode},
        )
        mv_data = mv_row.mappings().first()
        market_value = float(mv_data["mv"] or 0) if mv_data else 0.0
        position_count = int(mv_data["cnt"] or 0) if mv_data else 0
        cash = float(account["cash"] or 0)
        total_assets = cash + market_value
        position_ratio = (market_value / total_assets) if total_assets > 0 else 0.0

        await session.execute(
            text(
                """
                UPDATE trade.account_records
                SET market_value = :market_value,
                    total_assets = :total_assets,
                    position_count = :position_count,
                    position_ratio = :position_ratio,
                    record_time = NOW()
                WHERE id = :id
                """
            ),
            {
                "id": account["id"],
                "market_value": market_value,
                "total_assets": total_assets,
                "position_count": position_count,
                "position_ratio": position_ratio,
            },
        )
        return True
