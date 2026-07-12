"""回填历史 K 线数据。

用法:
  python -m scripts.backfill_kline --codes 000001,600519 --years 1
  python -m scripts.backfill_kline --universe hs300 --years 2
  python -m scripts.backfill_kline --codes 000001 --allow-synthetic
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 允许从 backend 根目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.data.kline_backfill import KlineBackfillService
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="K 线回填")
    parser.add_argument("--years", type=int, default=1)
    parser.add_argument("--universe", default="all", help="hs300|all|default")
    parser.add_argument("--codes", default="", help="逗号分隔代码，优先于 universe")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="远程失败时写入合成 K 线（仅演示）",
    )
    args = parser.parse_args()

    if args.codes.strip():
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        codes = await get_universe(args.universe)

    if not codes:
        print("股票池为空：请先 seed_stocks 或用 --codes 指定")
        sys.exit(1)

    limit = min(args.years * 250, 1000)
    svc = KlineBackfillService()
    try:
        stats = await svc.backfill_codes(
            codes,
            period="1d",
            limit=limit,
            concurrency=args.concurrency,
            allow_synthetic=args.allow_synthetic,
        )
        print(
            f"完成: success={stats['success']}/{stats['total']} "
            f"synthetic={stats['synthetic']} bars={stats['bars_written']}"
        )
        if stats["failed"]:
            print(f"失败: {stats['failed']}")
    finally:
        await svc.close()


if __name__ == "__main__":
    asyncio.run(main())
