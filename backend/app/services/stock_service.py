from sqlalchemy import text

from app.data.service import DataService
from app.db import get_db


class StockService:
    async def get_stock_list(
        self,
        market: str | None = None,
        sector: str | None = None,
        board: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        filters = ["is_active = TRUE"]
        params: dict = {}
        if market:
            filters.append("market = :market")
            params["market"] = market
        if sector:
            filters.append("sector = :sector")
            params["sector"] = sector
        if board:
            filters.append("board = :board")
            params["board"] = board
        if keyword:
            filters.append("(code ILIKE :kw OR name ILIKE :kw)")
            params["kw"] = f"%{keyword}%"

        where_clause = " AND ".join(filters)
        offset = (page - 1) * page_size
        params.update({"limit": page_size, "offset": offset})

        async with get_db() as db:
            count_result = await db.execute(
                text(f"SELECT COUNT(*) AS cnt FROM fundamental.stocks WHERE {where_clause}"),
                params,
            )
            total = int(count_result.scalar() or 0)
            result = await db.execute(
                text(
                    f"""
                    SELECT code, name, market, board, sector, sub_sector,
                           list_date, is_st, is_active
                    FROM fundamental.stocks
                    WHERE {where_clause}
                    ORDER BY code
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            items = [dict(r._mapping) for r in result.fetchall()]
            for item in items:
                if item.get("list_date"):
                    item["list_date"] = str(item["list_date"])

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_profile(self, code: str) -> dict | None:
        async with get_db() as db:
            result = await db.execute(
                text("SELECT * FROM fundamental.stocks WHERE code = :code"),
                {"code": code},
            )
            row = result.mappings().first()
            if not row:
                return None
            data = dict(row)
            if data.get("list_date"):
                data["list_date"] = str(data["list_date"])
            return data

    async def get_quote(self, code: str) -> dict | None:
        svc = DataService()
        try:
            quote = await svc.get_quote(code)
            if quote:
                quote["stock_code"] = code
            return quote
        finally:
            await svc.close()

    async def get_kline(
        self, code: str, period: str, limit: int, adj: str
    ) -> list[dict]:
        svc = DataService()
        try:
            return await svc.get_kline(code, period, limit, adj)
        finally:
            await svc.close()

    async def get_fund_flow(self, code: str, days: int) -> list[dict]:
        svc = DataService()
        try:
            return await svc.get_fund_flow(code, days)
        finally:
            await svc.close()

    async def get_news(self, code: str, limit: int) -> list[dict]:
        svc = DataService()
        try:
            return await svc.get_news(code, limit)
        finally:
            await svc.close()