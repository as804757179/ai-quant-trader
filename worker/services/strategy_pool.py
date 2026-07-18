from __future__ import annotations

import os
from typing import Any

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


async def get_active_strategies() -> list[dict[str, Any]]:
    """只返回配置可证明的活跃策略。"""
    factory = _get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT s.id, s.name, s.strategy_type, s.trade_mode, s.universe,
                           v.version_id AS config_version_id,
                           v.version_number AS config_version,
                           v.params, v.config_hash, v.catalog_hash
                    FROM strategy.strategies AS s
                    JOIN strategy.strategy_version_heads AS h ON h.strategy_id = s.id
                    JOIN strategy.strategy_versions AS v
                        ON v.version_id = h.active_version_id
                        AND v.version_number = h.revision
                        AND v.enabled = TRUE
                    JOIN strategy.strategy_version_approvals AS a
                        ON a.version_id = v.version_id AND a.status = 'approved'
                    ORDER BY s.id
                    """
                )
            )
            rows = []
            for raw_row in result.mappings().all():
                row = dict(raw_row)
                row["config"] = {
                    "enabled": True,
                    "params": row.pop("params", None),
                    "version_id": row.pop("config_version_id", None),
                    "version": row.pop("config_version", None),
                    "config_hash": row.pop("config_hash", None),
                    "catalog_hash": row.pop("catalog_hash", None),
                }
                rows.append(row)
            strategies = [row for row in rows if _is_verified_strategy(row)]
            if strategies:
                logger.debug("active_strategies_loaded", count=len(strategies))
                return strategies
            logger.warning("active_strategies_unverified_or_empty", row_count=len(rows))
    except Exception as exc:
        logger.warning("strategy_table_unavailable", error=str(exc))

    return []


def _is_verified_strategy(strategy: dict[str, Any]) -> bool:
    strategy_id = strategy.get("id")
    config = strategy.get("config")
    config_hash = config.get("config_hash") if isinstance(config, dict) else None
    catalog_hash = config.get("catalog_hash") if isinstance(config, dict) else None
    return (
        type(strategy_id) is int
        and strategy_id > 0
        and isinstance(strategy.get("name"), str)
        and bool(strategy["name"].strip())
        and isinstance(strategy.get("strategy_type"), str)
        and bool(strategy["strategy_type"].strip())
        and strategy.get("trade_mode") in {"simulation", "paper", "live"}
        and isinstance(config, dict)
        and config.get("enabled") is True
        and isinstance(config.get("params"), dict)
        and bool(config["params"])
        and type(config.get("version_id")) is int
        and config["version_id"] > 0
        and type(config.get("version")) is int
        and config["version"] >= 1
        and isinstance(config_hash, str)
        and len(config_hash) == 64
        and all(char in "0123456789abcdef" for char in config_hash)
        and isinstance(catalog_hash, str)
        and len(catalog_hash) == 64
        and all(char in "0123456789abcdef" for char in catalog_hash)
    )


async def get_strategy_stock_codes(
    strategy_id: int | None,
    *,
    limit: int = 20,
) -> list[str]:
    """只返回可证明归属该策略的活跃关注股票。"""
    if type(strategy_id) is not int or strategy_id <= 0:
        logger.warning("strategy_pool_unverified", strategy_id=strategy_id)
        return []

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
            if codes and all(isinstance(code, str) and code.strip() for code in codes):
                logger.debug("strategy_watchlist_loaded", strategy_id=strategy_id, count=len(codes))
                return codes
            logger.warning("strategy_watchlist_unverified_or_empty", strategy_id=strategy_id)
    except Exception as exc:
        logger.warning(
            "watchlist_unavailable",
            strategy_id=strategy_id,
            error=str(exc),
        )

    return []


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
