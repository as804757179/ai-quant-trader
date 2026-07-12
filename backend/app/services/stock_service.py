import re
from unicodedata import normalize

from sqlalchemy import text

from app.data.service import DataService
from app.db import get_db


def _normalize_keyword(raw: str | None) -> str:
    """搜索词规范化：去空白、全角转半角、大写。"""
    if not raw:
        return ""
    s = normalize("NFKC", str(raw)).strip()
    s = re.sub(r"\s+", "", s)
    return s


def _fuzzy_name_pattern(kw: str) -> str | None:
    """中文/字母模糊：字符间插入 .* ，如 茅台 → 茅.*台，gzmt → g.*z.*m.*t。"""
    if len(kw) < 2:
        return None
    # 仅对「非纯数字」做字符级模糊，避免 600 匹配过多
    if kw.isdigit():
        return None
    parts = [re.escape(ch) for ch in kw if ch.strip()]
    if len(parts) < 2:
        return None
    return ".*".join(parts)


class StockService:
    async def get_stock_list(
        self,
        market: str | None = None,
        sector: str | None = None,
        board: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 100,
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

        order_sql = "code"
        kw = _normalize_keyword(keyword)
        if kw:
            # 名称去空白后匹配（兼容「万 科Ａ」等）
            name_norm = "regexp_replace(name, '\\s+', '', 'g')"
            # 全角兼容：PostgreSQL translate 对常见全角数字
            code_norm = "code"

            fuzzy_pat = _fuzzy_name_pattern(kw)
            # 条件：代码前缀/包含、名称包含、名称字符序模糊、板块/行业
            conds = [
                f"{code_norm} ILIKE :kw_like",
                f"{code_norm} LIKE :kw_prefix",
                f"name ILIKE :kw_like",
                f"{name_norm} ILIKE :kw_like",
                "sector ILIKE :kw_like",
                "board ILIKE :kw_like",
            ]
            params["kw_like"] = f"%{kw}%"
            params["kw_prefix"] = f"{kw}%"
            params["kw_exact"] = kw.upper() if kw.isdigit() or kw.isalnum() else kw
            params["kw_exact_raw"] = kw

            if fuzzy_pat:
                # ~* 不区分大小写正则；名称去空白后匹配
                conds.append(f"{name_norm} ~* :kw_fuzzy")
                conds.append("name ~* :kw_fuzzy")
                params["kw_fuzzy"] = fuzzy_pat

            filters.append("(" + " OR ".join(conds) + ")")

            # 相关度排序：精确代码 > 代码前缀 > 名称开头 > 名称包含 > 其它
            order_sql = f"""
                CASE
                    WHEN {code_norm} = :kw_exact_raw THEN 0
                    WHEN {code_norm} = :kw_exact THEN 0
                    WHEN {code_norm} LIKE :kw_prefix THEN 1
                    WHEN {name_norm} ILIKE :kw_starts THEN 2
                    WHEN name ILIKE :kw_starts THEN 2
                    WHEN {name_norm} ILIKE :kw_like THEN 3
                    WHEN name ILIKE :kw_like THEN 3
                    WHEN {code_norm} ILIKE :kw_like THEN 4
                    ELSE 5
                END ASC,
                code ASC
            """
            params["kw_starts"] = f"{kw}%"

        where_clause = " AND ".join(filters)
        offset = (page - 1) * page_size
        params.update({"limit": page_size, "offset": offset})

        # 单次查询：窗口函数同时拿 total，少一次往返
        async with get_db() as db:
            result = await db.execute(
                text(
                    f"""
                    SELECT code, name, market, board, sector, sub_sector,
                           list_date, is_st, is_active,
                           COUNT(*) OVER() AS _total
                    FROM fundamental.stocks
                    WHERE {where_clause}
                    ORDER BY {order_sql}
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            raw = result.fetchall()
            items = []
            total = 0
            for r in raw:
                m = dict(r._mapping)
                total = int(m.pop("_total", 0) or 0)
                if m.get("list_date"):
                    m["list_date"] = str(m["list_date"])
                items.append(m)
            if not items and page == 1:
                # 空页再确认 total（无匹配）
                count_result = await db.execute(
                    text(
                        f"SELECT COUNT(*) AS cnt FROM fundamental.stocks WHERE {where_clause}"
                    ),
                    params,
                )
                total = int(count_result.scalar() or 0)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "keyword": kw or None,
        }

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

    def __init__(self) -> None:
        # 复用进程级 HTTP 连接池（DataClient shared=True）
        self._data = DataService(shared_client=True)

    async def get_quote(self, code: str) -> dict | None:
        quote = await self._data.get_quote(code)
        if quote:
            # 拷贝，避免污染缓存对象
            out = dict(quote)
            out["stock_code"] = code
            return out
        return None

    async def get_kline(
        self, code: str, period: str, limit: int, adj: str
    ) -> list[dict]:
        return await self._data.get_kline(code, period, limit, adj)

    async def get_fund_flow(self, code: str, days: int) -> list[dict]:
        return await self._data.get_fund_flow(code, days)

    async def get_news(self, code: str, limit: int) -> list[dict]:
        return await self._data.get_news(code, limit)