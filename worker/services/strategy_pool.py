from __future__ import annotations

import os
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from services.stock_pool import get_active_stock_codes

logger = structlog.get_logger(__name__)

_engine = None
_session_factory = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        database_url = os.getenv("DATABASE_URL", "")
        _engine = create_async_engine(database_url, poolclass=NullPool)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


async def get_active_strategies() -> list[dict[str, Any]]:
    """从 strategy.strategies 获取活跃策略；表不存在时回退默认策略。"""
    factory = _get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, name, strategy_type, trade_mode, universe, config
                    FROM strategy.strategies
                    WHERE is_active = TRUE
                    ORDER BY id
                    """
                )
            )
            rows = [dict(r) for r in result.mappings().all()]
            if rows:
                logger.debug("active_strategies_loaded", count=len(rows))
                return rows
    except Exception as exc:
        logger.warning("strategy_table_unavailable", error=str(exc))

    trade_mode = os.getenv("TRADE_MODE", "simulation")
    logger.info("strategy_fallback_default_pool", trade_mode=trade_mode)
    return [
        {
            "id": 0,
            "name": "default_active_pool",
            "strategy_type": "default",
            "trade_mode": trade_mode,
            "universe": "active",
            "config": {},
        }
    ]


async def get_strategy_stock_codes(
    strategy_id: int | None,
    *,
    limit: int = 20,
) -> list[str]:
    """获取策略关注股票池；无关注池时回退全市场活跃股。"""
    if not strategy_id:
        return await get_active_stock_codes(limit=limit)

    factory = _get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT w.stock_code
                    FROM strategy.watchlists w
                    JOIN fundamental.stocks s ON w.stock_code = s.code
                    WHERE w.strategy_id = :strategy_id
                      AND w.is_active = TRUE
                      AND s.is_active = TRUE
                    ORDER BY w.stock_code
                    LIMIT :limit
                    """
                ),
                {"strategy_id": strategy_id, "limit": limit},
            )
            codes = [row[0] for row in result.fetchall()]
            if codes:
                return codes
    except Exception as exc:
        logger.warning(
            "watchlist_unavailable",
            strategy_id=strategy_id,
            error=str(exc),
        )

    return await get_active_stock_codes(limit=limit)


async def has_valid_signal(stock_code: str) -> bool:
    """检查是否存在未过期的有效信号。"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                SELECT 1
                FROM ai.signals
                WHERE stock_code = :code
                  AND status = 'active'
                  AND (valid_until IS NULL OR valid_until > NOW())
                LIMIT 1
                """
            ),
            {"code": stock_code},
        )
        return result.scalar() is not None


async def get_available_sell_quantity(stock_code: str, mode: str) -> int:
    """查询可卖数量（用于 SELL 信号下单）。"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                SELECT available_qty
                FROM trade.positions
                WHERE stock_code = :code AND mode = :mode
                """
            ),
            {"code": stock_code, "mode": mode},
        )
        row = result.mappings().first()
        return int(row["available_qty"]) if row and row["available_qty"] else 0
