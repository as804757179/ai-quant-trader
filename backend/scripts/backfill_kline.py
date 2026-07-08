"""回填历史K线数据"""

import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text

from app.data.service import DataService
from app.db import get_db


async def get_universe(universe: str) -> list[str]:
    async with get_db() as db:
        if universe == "hs300":
            result = await db.execute(
                text(
                    """
                    SELECT code FROM fundamental.stocks
                    WHERE market IN ('SH', 'SZ') AND is_active = TRUE
                    ORDER BY code
                    LIMIT 300
                    """
                )
            )
        elif universe == "all":
            result = await db.execute(
                text(
                    """
                    SELECT code FROM fundamental.stocks
                    WHERE is_active = TRUE
                    ORDER BY code
                    """
                )
            )
        else:
            result = await db.execute(
                text(
                    """
                    SELECT code FROM fundamental.stocks
                    WHERE is_active = TRUE
                    ORDER BY code
                    LIMIT 500
                    """
                )
            )
        return [row[0] for row in result.fetchall()]


async def backfill(years: int, universe: str) -> None:
    codes = await get_universe(universe)
    if not codes:
        print("❌ 股票池为空，请先运行 seed_stocks.py")
        sys.exit(1)

    limit = min(years * 250, 1000)
    svc = DataService()
    success = 0
    try:
        for idx, code in enumerate(codes, start=1):
            klines = await svc.get_kline(code, "1d", limit, adj="none")
            if klines:
                success += 1
            if idx % 50 == 0:
                print(f"进度: {idx}/{len(codes)}，成功 {success}")
        print(f"✅ K线回填完成：{success}/{len(codes)} 只股票写入数据")
    finally:
        await svc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=1)
    parser.add_argument("--universe", default="all")
    args = parser.parse_args()
    asyncio.run(backfill(args.years, args.universe))