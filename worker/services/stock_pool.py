from __future__ import annotations

import os

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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


async def get_active_stock_codes(limit: int = 100) -> list[str]:
    """从 fundamental.stocks 获取活跃股票池。"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                SELECT code FROM fundamental.stocks
                WHERE is_active = TRUE
                ORDER BY code
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        codes = [row[0] for row in result.fetchall()]
    logger.debug("active_stock_pool_loaded", count=len(codes), limit=limit)
    return codes
