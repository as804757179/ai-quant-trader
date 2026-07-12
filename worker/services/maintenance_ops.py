"""日终快照、对账、K 线完整性检查等维护操作。"""

from __future__ import annotations

import os
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger(__name__)

_engine = None
_session_factory = None
MODES = ("simulation", "paper", "live")


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        database_url = os.getenv("DATABASE_URL", "")
        _engine = create_async_engine(database_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


async def take_eod_snapshot() -> dict[str, Any]:
    """将各 mode 最新账户状态再插入一条 snapshot 记录。"""
    factory = _get_session_factory()
    inserted = 0
    async with factory() as session:
        for mode in MODES:
            acc = await session.execute(
                text(
                    """
                    SELECT cash, market_value, total_assets, frozen_cash,
                           daily_pnl, total_pnl, total_pnl_pct, position_count, position_ratio
                    FROM trade.account_records
                    WHERE mode = :mode
                    ORDER BY record_time DESC
                    LIMIT 1
                    """
                ),
                {"mode": mode},
            )
            row = acc.mappings().first()
            if not row:
                continue
            # 用持仓重算市值
            mv = await session.execute(
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
            mv_row = mv.mappings().first()
            market_value = float(mv_row["mv"] or 0) if mv_row else 0.0
            position_count = int(mv_row["cnt"] or 0) if mv_row else 0
            cash = float(row["cash"] or 0)
            total_assets = cash + market_value
            position_ratio = market_value / total_assets if total_assets else 0.0

            await session.execute(
                text(
                    """
                    INSERT INTO trade.account_records
                    (mode, record_time, total_assets, cash, market_value, frozen_cash,
                     daily_pnl, total_pnl, total_pnl_pct, position_count, position_ratio, data_type)
                    VALUES
                    (:mode, NOW(), :total_assets, :cash, :market_value, :frozen_cash,
                     :daily_pnl, :total_pnl, :total_pnl_pct, :position_count, :position_ratio, 'eod')
                    """
                ),
                {
                    "mode": mode,
                    "total_assets": total_assets,
                    "cash": cash,
                    "market_value": market_value,
                    "frozen_cash": float(row["frozen_cash"] or 0),
                    "daily_pnl": float(row["daily_pnl"] or 0),
                    "total_pnl": float(row["total_pnl"] or 0),
                    "total_pnl_pct": float(row["total_pnl_pct"] or 0),
                    "position_count": position_count,
                    "position_ratio": position_ratio,
                },
            )
            inserted += 1
        await session.commit()
    logger.info("eod_snapshot_done", inserted=inserted)
    return {"status": "ok", "snapshots": inserted}


async def reconcile_accounts() -> dict[str, Any]:
    """本地账本一致性：cash + market_value 应 ≈ total_assets。"""
    factory = _get_session_factory()
    issues: list[dict[str, Any]] = []
    async with factory() as session:
        for mode in MODES:
            acc = await session.execute(
                text(
                    """
                    SELECT id, cash, market_value, total_assets
                    FROM trade.account_records
                    WHERE mode = :mode
                    ORDER BY record_time DESC
                    LIMIT 1
                    """
                ),
                {"mode": mode},
            )
            row = acc.mappings().first()
            if not row:
                continue
            pos = await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(market_value), 0) AS mv
                    FROM trade.positions WHERE mode = :mode AND total_qty > 0
                    """
                ),
                {"mode": mode},
            )
            pos_mv = float(pos.scalar() or 0)
            cash = float(row["cash"] or 0)
            recorded_mv = float(row["market_value"] or 0)
            total = float(row["total_assets"] or 0)
            expected = cash + pos_mv
            drift = abs(expected - total)
            mv_drift = abs(pos_mv - recorded_mv)
            severity = "OK"
            if drift > 1.0 or mv_drift > 1.0:
                severity = "CRITICAL" if max(drift, mv_drift) > 1000 else "WARNING"
                issues.append(
                    {
                        "mode": mode,
                        "severity": severity,
                        "cash": cash,
                        "position_market_value": pos_mv,
                        "recorded_market_value": recorded_mv,
                        "recorded_total_assets": total,
                        "expected_total_assets": expected,
                        "drift": round(drift, 2),
                        "market_value_drift": round(mv_drift, 2),
                    }
                )
                # 自动校正：以持仓汇总市值 + 现金重写 total_assets
                await session.execute(
                    text(
                        """
                        UPDATE trade.account_records
                        SET market_value = :mv,
                            total_assets = :total,
                            record_time = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"], "mv": pos_mv, "total": expected},
                )
        await session.commit()
    logger.info("reconcile_done", issue_count=len(issues))
    return {
        "status": "ok" if not any(i["severity"] == "CRITICAL" for i in issues) else "critical",
        "issues": issues,
        "issue_count": len(issues),
    }


async def check_kline_completeness(lookback_days: int = 5) -> dict[str, Any]:
    """检查最近交易日活跃股票是否有日 K。"""
    factory = _get_session_factory()
    async with factory() as session:
        stock_cnt = await session.execute(
            text("SELECT COUNT(*) FROM fundamental.stocks WHERE is_active = TRUE")
        )
        active = int(stock_cnt.scalar() or 0)
        kline_cnt = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT stock_code) FROM market.klines
                WHERE period = '1d'
                  AND time >= NOW() - (:days || ' days')::interval
                """
            ),
            {"days": lookback_days},
        )
        covered = int(kline_cnt.scalar() or 0)
    ratio = covered / active if active else 0.0
    status = "ok" if ratio >= 0.5 or active == 0 else "warning"
    result = {
        "status": status,
        "active_stocks": active,
        "stocks_with_recent_kline": covered,
        "coverage_ratio": round(ratio, 4),
        "lookback_days": lookback_days,
    }
    logger.info("kline_completeness_check", **result)
    return result


async def archive_daily_data() -> dict[str, Any]:
    """归档：过期信号标记 expired；清理过旧 risk 事件可选。"""
    factory = _get_session_factory()
    async with factory() as session:
        sig = await session.execute(
            text(
                """
                UPDATE ai.signals
                SET status = 'expired'
                WHERE status = 'active'
                  AND valid_until IS NOT NULL
                  AND valid_until < NOW()
                """
            )
        )
        expired = int(sig.rowcount or 0)
        await session.commit()
    logger.info("archive_daily_done", expired_signals=expired)
    return {"status": "ok", "expired_signals": expired}


async def reconcile_with_broker(mode: str | None = None) -> dict[str, Any]:
    """
    券商对账：优先调用 backend TradeService；
    失败时仅做本地账本一致性检查。
    """
    trade_mode = mode or os.getenv("TRADE_MODE", "simulation")
    if trade_mode == "simulation":
        local = await reconcile_accounts()
        return {
            "status": "ok",
            "broker_reconcile": "skipped",
            "local": local,
        }

    try:
        from app.services.trade_service import TradeService

        svc = TradeService()
        broker = await svc.reconcile_with_broker(
            "live" if trade_mode == "live" else "paper"
        )
        local = await reconcile_accounts()
        return {
            "status": broker.get("status", "ok"),
            "broker_reconcile": broker,
            "local": local,
        }
    except Exception as exc:
        logger.warning("broker_reconcile_fallback_local", error=str(exc))
        local = await reconcile_accounts()
        return {
            "status": "degraded",
            "broker_reconcile": {"error": str(exc)},
            "local": local,
        }
