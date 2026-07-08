"""导入A股股票列表到 fundamental.stocks"""

import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text

from app.data.client import DataClient
from app.db import get_db


async def seed_stocks() -> None:
    client = DataClient()
    stocks = await client.fetch_stock_list()
    await client.close()
    if not stocks:
        print("❌ 未能从 a-stock-data 获取股票列表")
        sys.exit(1)

    inserted = 0
    async with get_db() as db:
        for stock in stocks:
            await db.execute(
                text(
                    """
                    INSERT INTO fundamental.stocks
                    (code, name, market, board, sector, sub_sector,
                     total_shares, float_shares, is_st, is_active)
                    VALUES
                    (:code, :name, :market, :board, :sector, :sub_sector,
                     :total_shares, :float_shares, :is_st, :is_active)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        market = EXCLUDED.market,
                        board = EXCLUDED.board,
                        sector = EXCLUDED.sector,
                        sub_sector = EXCLUDED.sub_sector,
                        total_shares = EXCLUDED.total_shares,
                        float_shares = EXCLUDED.float_shares,
                        is_st = EXCLUDED.is_st,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """
                ),
                stock,
            )
            inserted += 1

    print(f"✅ 股票列表导入完成，共处理 {inserted} 只股票")


if __name__ == "__main__":
    asyncio.run(seed_stocks())