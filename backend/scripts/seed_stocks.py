"""导入A股股票列表到 fundamental.stocks

优先从 a-stock-data 拉取全市场；失败则写入内置常用股票池。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from pathlib import Path

# Docker: /app；本机：backend 根目录
_backend_root = Path(__file__).resolve().parents[1]
for _p in (Path("/app"), _backend_root):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sqlalchemy import text

from app.data.client import DataClient
from app.db import get_db

FALLBACK: list[dict[str, Any]] = [
    {"code": "000001", "name": "平安银行", "market": "SZ", "board": "主板", "sector": "银行"},
    {"code": "000002", "name": "万科A", "market": "SZ", "board": "主板", "sector": "房地产"},
    {"code": "000063", "name": "中兴通讯", "market": "SZ", "board": "主板", "sector": "通信"},
    {"code": "000100", "name": "TCL科技", "market": "SZ", "board": "主板", "sector": "电子"},
    {"code": "000333", "name": "美的集团", "market": "SZ", "board": "主板", "sector": "家电"},
    {"code": "000651", "name": "格力电器", "market": "SZ", "board": "主板", "sector": "家电"},
    {"code": "000725", "name": "京东方A", "market": "SZ", "board": "主板", "sector": "电子"},
    {"code": "000858", "name": "五粮液", "market": "SZ", "board": "主板", "sector": "白酒"},
    {"code": "002230", "name": "科大讯飞", "market": "SZ", "board": "主板", "sector": "计算机"},
    {"code": "002415", "name": "海康威视", "market": "SZ", "board": "主板", "sector": "电子"},
    {"code": "002594", "name": "比亚迪", "market": "SZ", "board": "主板", "sector": "汽车"},
    {"code": "300059", "name": "东方财富", "market": "SZ", "board": "创业板", "sector": "证券"},
    {"code": "300750", "name": "宁德时代", "market": "SZ", "board": "创业板", "sector": "电池"},
    {"code": "300760", "name": "迈瑞医疗", "market": "SZ", "board": "创业板", "sector": "医药"},
    {"code": "600000", "name": "浦发银行", "market": "SH", "board": "主板", "sector": "银行"},
    {"code": "600030", "name": "中信证券", "market": "SH", "board": "主板", "sector": "证券"},
    {"code": "600036", "name": "招商银行", "market": "SH", "board": "主板", "sector": "银行"},
    {"code": "600050", "name": "中国联通", "market": "SH", "board": "主板", "sector": "通信"},
    {"code": "600276", "name": "恒瑞医药", "market": "SH", "board": "主板", "sector": "医药"},
    {"code": "600519", "name": "贵州茅台", "market": "SH", "board": "主板", "sector": "白酒"},
    {"code": "600809", "name": "山西汾酒", "market": "SH", "board": "主板", "sector": "白酒"},
    {"code": "600887", "name": "伊利股份", "market": "SH", "board": "主板", "sector": "乳业"},
    {"code": "600900", "name": "长江电力", "market": "SH", "board": "主板", "sector": "公用事业"},
    {"code": "601012", "name": "隆基绿能", "market": "SH", "board": "主板", "sector": "光伏"},
    {"code": "601088", "name": "中国神华", "market": "SH", "board": "主板", "sector": "煤炭"},
    {"code": "601166", "name": "兴业银行", "market": "SH", "board": "主板", "sector": "银行"},
    {"code": "601318", "name": "中国平安", "market": "SH", "board": "主板", "sector": "保险"},
    {"code": "601398", "name": "工商银行", "market": "SH", "board": "主板", "sector": "银行"},
    {"code": "601857", "name": "中国石油", "market": "SH", "board": "主板", "sector": "石油"},
    {"code": "601888", "name": "中国中免", "market": "SH", "board": "主板", "sector": "旅游"},
    {"code": "603259", "name": "药明康德", "market": "SH", "board": "主板", "sector": "医药"},
    {"code": "603501", "name": "韦尔股份", "market": "SH", "board": "主板", "sector": "半导体"},
    {"code": "688041", "name": "海光信息", "market": "SH", "board": "科创板", "sector": "半导体"},
    {"code": "688111", "name": "金山办公", "market": "SH", "board": "科创板", "sector": "计算机"},
    {"code": "688981", "name": "中芯国际", "market": "SH", "board": "科创板", "sector": "半导体"},
]


def _normalize_stock(raw: dict[str, Any]) -> dict[str, Any] | None:
    code = str(raw.get("code") or "").zfill(6)
    if not code.isdigit() or len(code) != 6:
        return None
    name = raw.get("name") or code
    market = raw.get("market") or ("SH" if code.startswith(("5", "6", "9")) else "SZ")
    total = raw.get("total_shares")
    flo = raw.get("float_shares")
    try:
        total = float(total) if total not in (None, "-", "") else None
    except (TypeError, ValueError):
        total = None
    try:
        flo = float(flo) if flo not in (None, "-", "") else None
    except (TypeError, ValueError):
        flo = None
    return {
        "code": code,
        "name": name,
        "market": market,
        "board": raw.get("board") or "",
        "sector": raw.get("sector") or "",
        "sub_sector": raw.get("sub_sector") or "",
        "total_shares": total,
        "float_shares": flo,
        "is_st": bool(raw.get("is_st")) or ("ST" in str(name).upper()),
        "is_active": True if raw.get("is_active") is None else bool(raw.get("is_active")),
    }


def _load_local_universe_cache() -> list[dict[str, Any]]:
    """读取 a-stock-data 本地全市场缓存（HTTP 不可用时的降级）。"""
    import json

    candidates = [
        _backend_root.parent / "a-stock-data" / "service" / "cache" / "a_share_universe.json",
        Path(__file__).resolve().parents[2] / "a-stock-data" / "service" / "cache" / "a_share_universe.json",
    ]
    for p in candidates:
        try:
            if not p.exists():
                continue
            payload = json.loads(p.read_text(encoding="utf-8"))
            items = payload.get("items") or []
            if isinstance(items, list) and items:
                print(f"📂 使用本地缓存 {p} 共 {len(items)} 条")
                return items
        except Exception as exc:
            print(f"⚠️ 读取缓存失败 {p}: {exc}")
    return []


async def seed_stocks(*, refresh_source: bool = False) -> None:
    client = DataClient()
    try:
        remote = (
            await client.refresh_stock_list()
            if refresh_source
            else await client.fetch_stock_list()
        )
    finally:
        await client.close()

    if refresh_source and not remote:
        raise RuntimeError("股票池刷新未获得完整上游快照")

    stocks: list[dict[str, Any]] = []
    if remote:
        for item in remote:
            n = _normalize_stock(item if isinstance(item, dict) else {})
            if n:
                stocks.append(n)

    # HTTP 失败或数量不足时，优先本地全市场缓存（约 5000+）
    if len(stocks) < 500:
        for item in _load_local_universe_cache():
            n = _normalize_stock(item if isinstance(item, dict) else {})
            if n:
                stocks.append(n)
        # 去重
        dedup: dict[str, dict[str, Any]] = {}
        for s in stocks:
            dedup[s["code"]] = s
        stocks = list(dedup.values())

    if len(stocks) < 30:
        print(f"⚠️ 远程/缓存股票列表不足({len(stocks)})，合并内置常用池")
        seen = {s["code"] for s in stocks}
        for item in FALLBACK:
            n = _normalize_stock(item)
            if n and n["code"] not in seen:
                stocks.append(n)
                seen.add(n["code"])

    if not stocks:
        print("❌ 无可用股票数据")
        sys.exit(1)

    upsert_sql = text(
        """
        INSERT INTO fundamental.stocks
        (code, name, market, board, sector, sub_sector,
         total_shares, float_shares, is_st, is_active, updated_at)
        VALUES
        (:code, :name, :market, :board, :sector, :sub_sector,
         :total_shares, :float_shares, :is_st, :is_active, NOW())
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            market = EXCLUDED.market,
            board = EXCLUDED.board,
            sector = EXCLUDED.sector,
            sub_sector = EXCLUDED.sub_sector,
            total_shares = COALESCE(EXCLUDED.total_shares, fundamental.stocks.total_shares),
            float_shares = COALESCE(EXCLUDED.float_shares, fundamental.stocks.float_shares),
            is_st = EXCLUDED.is_st,
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
        """
    )

    inserted = 0
    batch_size = 500
    async with get_db() as db:
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i : i + batch_size]
            await db.execute(upsert_sql, batch)
            inserted += len(batch)
            if inserted % 1000 == 0 or inserted == len(stocks):
                print(f"  … 已写入 {inserted}/{len(stocks)}", flush=True)
        total = await db.scalar(text("SELECT COUNT(*) FROM fundamental.stocks WHERE is_active = TRUE"))

    print(f"✅ 股票列表导入完成，处理 {inserted} 条，库内 active={total}")


if __name__ == "__main__":
    asyncio.run(seed_stocks())
