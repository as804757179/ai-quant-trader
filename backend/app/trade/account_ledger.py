"""账户/持仓账本工具：总资产重算、T+1 可卖释放。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def compute_total_assets(cash: float, market_value: float) -> float:
    """总资产 = 现金 + 持仓市值。"""
    return float(cash) + float(market_value)


async def sum_positions_market_value(db: AsyncSession, mode: str) -> tuple[float, int]:
    """汇总某模式下持仓市值与持仓只数。"""
    result = await db.execute(
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
    row = result.mappings().first()
    if not row:
        return 0.0, 0
    return float(row["mv"] or 0), int(row["cnt"] or 0)


async def recompute_account_assets(db: AsyncSession, mode: str) -> dict:
    """
    以最新 account_records 的 cash 为准，用持仓表重算 market_value / total_assets。

    避免买卖后只做增量更新导致 total_assets 漂移。
    """
    acc = await db.execute(
        text(
            """
            SELECT id, cash, daily_pnl, total_pnl
            FROM trade.account_records
            WHERE mode = :mode
            ORDER BY record_time DESC
            LIMIT 1
            """
        ),
        {"mode": mode},
    )
    account = acc.mappings().first()
    if not account:
        return {"updated": False, "mode": mode, "reason": "no_account"}

    cash = float(account["cash"] or 0)
    market_value, position_count = await sum_positions_market_value(db, mode)
    total_assets = compute_total_assets(cash, market_value)
    position_ratio = (market_value / total_assets) if total_assets > 0 else 0.0

    await db.execute(
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
    return {
        "updated": True,
        "mode": mode,
        "cash": cash,
        "market_value": market_value,
        "total_assets": total_assets,
        "position_count": position_count,
    }


async def release_t1_available_qty(
    db: AsyncSession, mode: str | None = None
) -> dict:
    """
    T+1：将 available_qty 同步为 total_qty（当日买入次日可卖）。

    mode 为 None 时处理全部模式。
    """
    if mode:
        result = await db.execute(
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
        result = await db.execute(
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
    return {"released_rows": int(result.rowcount or 0), "mode": mode or "all"}
