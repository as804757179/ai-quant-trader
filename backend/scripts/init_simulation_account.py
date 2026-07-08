"""初始化模拟账户"""

import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text

from app.db import get_db


async def init_simulation_account(cash: float, mode: str = "simulation") -> None:
    async with get_db() as db:
        existing = await db.execute(
            text(
                """
                SELECT id FROM trade.account_records
                WHERE mode = :mode
                LIMIT 1
                """
            ),
            {"mode": mode},
        )
        if existing.first():
            print(f"账户 {mode} 已存在，跳过初始化")
            return

        await db.execute(
            text(
                """
                INSERT INTO trade.account_records
                (mode, total_assets, cash, market_value, frozen_cash,
                 daily_pnl, total_pnl, position_ratio, data_type)
                VALUES
                (:mode, :cash, :cash, 0, 0, 0, 0, 0, 'init')
                """
            ),
            {"mode": mode, "cash": cash},
        )
    print(f"✅ {mode} 账户初始化完成，初始资金：¥{cash:,.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--mode", default="simulation")
    args = parser.parse_args()
    asyncio.run(init_simulation_account(args.cash, args.mode))