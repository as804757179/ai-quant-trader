from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import text

from app.data.cache import CacheManager
from app.db import get_db
from app.screener.factors import FactorLibrary
from app.screener.presets import PRESET_DEFINITIONS, get_preset_conditions

logger = structlog.get_logger(__name__)

CACHE_TTL = 3600

THEME_MAP: dict[str, dict[str, list[str]]] = {
    "ai": {
        "sectors": ["电子", "计算机", "通信", "半导体"],
        "keywords": ["AI", "人工智能", "芯片", "算力", "GPU", "大模型", "智能"],
    },
    "新能源": {
        "sectors": ["电力设备", "汽车", "有色金属"],
        "keywords": ["新能源", "光伏", "锂电", "储能", "风电", "电动车", "电池"],
    },
    "医药": {
        "sectors": ["医药生物"],
        "keywords": ["医药", "创新药", "生物", "医疗", "制药"],
    },
    "消费": {
        "sectors": ["食品饮料", "家用电器", "商贸零售"],
        "keywords": ["消费", "白酒", "零售", "品牌"],
    },
}


class ScreenerEngine:
    """选股条件引擎 — 因子过滤、预设条件、主题选股。"""

    def __init__(self, cache: CacheManager | None = None) -> None:
        self.cache = cache or CacheManager()
        self.factors = FactorLibrary()

    async def screen(self, conditions: dict[str, Any], limit: int = 50) -> dict[str, Any]:
        cache_key = self._cache_key("screen", {"conditions": conditions, "limit": limit})
        cached = await self._get_cache(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached

        universe = await self._load_universe()
        if conditions.get("preset_handler") == "sector_leader":
            universe = self._enrich_sector_rank(universe)

        results = self._filter_and_sort(universe, conditions, limit)
        payload = {
            "items": results,
            "total": len(results),
            "limit": limit,
            "conditions": conditions,
            "from_cache": False,
        }
        await self._set_cache(cache_key, payload)
        return payload

    async def screen_preset(self, preset_id: str, limit: int = 50) -> dict[str, Any]:
        conditions = get_preset_conditions(preset_id)
        if not conditions:
            raise ValueError(f"未知预设条件: {preset_id}")

        cache_key = self._cache_key("preset", {"preset_id": preset_id, "limit": limit})
        cached = await self._get_cache(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached

        result = await self.screen(conditions, limit=limit)
        preset = PRESET_DEFINITIONS[preset_id]
        result["preset_id"] = preset_id
        result["preset_name"] = preset["name"]
        await self._set_cache(cache_key, result)
        return result

    async def screen_by_theme(self, theme: str, limit: int = 50) -> dict[str, Any]:
        theme = theme.strip()
        if not theme:
            raise ValueError("主题词不能为空")

        cache_key = self._cache_key("theme", {"theme": theme, "limit": limit})
        cached = await self._get_cache(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached

        sectors, keywords = self._resolve_theme(theme)
        theme_codes = await self._find_theme_stock_codes(keywords)
        universe = await self._load_universe()
        matched = []
        theme_lower = theme.lower()

        for stock in universe:
            code = stock["code"]
            name = stock.get("name", "")
            sector = stock.get("sector", "")
            if code in theme_codes:
                stock["theme_match"] = "news"
                matched.append(stock)
                continue
            if self.factors.sector_match(sector, sectors):
                stock["theme_match"] = "sector"
                matched.append(stock)
                continue
            if any(kw.lower() in name.lower() or kw.lower() in theme_lower for kw in keywords):
                stock["theme_match"] = "name"
                matched.append(stock)

        sort_field = "change_pct"
        matched.sort(key=lambda s: self.factors.sort_key(s, sort_field), reverse=True)
        items = matched[:limit]
        payload = {
            "items": items,
            "total": len(items),
            "limit": limit,
            "theme": theme,
            "resolved_sectors": sectors,
            "resolved_keywords": keywords,
            "from_cache": False,
        }
        await self._set_cache(cache_key, payload)
        logger.info("screener_theme_done", theme=theme, matched=len(items))
        return payload

    async def _load_universe(self) -> list[dict[str, Any]]:
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    WITH latest_kline AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code, close, volume, amount, turnover_rate, time
                        FROM market.klines
                        WHERE period = '1d'
                        ORDER BY stock_code, time DESC
                    ),
                    avg_volume AS (
                        SELECT stock_code, AVG(volume)::float AS avg_volume
                        FROM market.klines
                        WHERE period = '1d'
                          AND time >= NOW() - INTERVAL '20 days'
                        GROUP BY stock_code
                    ),
                    return_5d AS (
                        SELECT stock_code,
                               (last(close, time) / first(close, time) - 1) * 100 AS recent_return_5d
                        FROM market.klines
                        WHERE period = '1d'
                          AND time >= NOW() - INTERVAL '7 days'
                        GROUP BY stock_code
                    ),
                    latest_fin AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code, pb_ratio, roe, pe_ratio
                        FROM fundamental.financial_reports
                        ORDER BY stock_code, report_date DESC
                    ),
                    fund_5d AS (
                        SELECT stock_code, COALESCE(SUM(main_net_in), 0)::float AS main_net_in_5d
                        FROM market.fund_flows
                        WHERE time >= NOW() - INTERVAL '5 days'
                        GROUP BY stock_code
                    ),
                    latest_signal AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code, action AS ai_action, confidence AS ai_confidence
                        FROM ai.signals
                        WHERE status = 'active'
                          AND (valid_until IS NULL OR valid_until > NOW())
                        ORDER BY stock_code, signal_time DESC
                    ),
                    latest_quote AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code, price, change_pct, volume AS quote_volume,
                            amount AS quote_amount, prev_close
                        FROM market.quotes
                        ORDER BY stock_code, time DESC
                    )
                    SELECT
                        s.code,
                        s.name,
                        s.sector,
                        s.market,
                        s.board,
                        s.total_shares,
                        COALESCE(q.price, lk.close) AS price,
                        COALESCE(q.change_pct, CASE
                            WHEN q.prev_close > 0 THEN (q.price - q.prev_close) / q.prev_close * 100
                            ELSE NULL
                        END) AS change_pct,
                        COALESCE(q.quote_volume, lk.volume) AS volume,
                        COALESCE(q.quote_amount, lk.amount) AS amount,
                        lk.turnover_rate,
                        av.avg_volume,
                        r5.recent_return_5d,
                        lf.pb_ratio,
                        lf.roe,
                        lf.pe_ratio,
                        ff.main_net_in_5d,
                        ls.ai_action,
                        ls.ai_confidence
                    FROM fundamental.stocks s
                    LEFT JOIN latest_kline lk ON s.code = lk.stock_code
                    LEFT JOIN avg_volume av ON s.code = av.stock_code
                    LEFT JOIN return_5d r5 ON s.code = r5.stock_code
                    LEFT JOIN latest_fin lf ON s.code = lf.stock_code
                    LEFT JOIN fund_5d ff ON s.code = ff.stock_code
                    LEFT JOIN latest_signal ls ON s.code = ls.stock_code
                    LEFT JOIN latest_quote q ON s.code = q.stock_code
                    WHERE s.is_active = TRUE AND s.is_st = FALSE
                    ORDER BY s.code
                    """
                )
            )
            rows = [dict(r) for r in result.mappings().all()]

        universe: list[dict[str, Any]] = []
        for row in rows:
            price = float(row.get("price") or 0)
            volume = float(row.get("volume") or 0)
            avg_volume = float(row.get("avg_volume") or 0)
            volume_ratio = self.factors.volume_ratio(volume, avg_volume)
            market_cap = self.factors.market_cap(price, row.get("total_shares"))

            universe.append(
                {
                    "code": row["code"],
                    "name": row.get("name"),
                    "sector": row.get("sector"),
                    "market": row.get("market"),
                    "board": row.get("board"),
                    "price": price or None,
                    "change_pct": float(row["change_pct"]) if row.get("change_pct") is not None else None,
                    "volume": volume or None,
                    "amount": float(row["amount"]) if row.get("amount") is not None else None,
                    "turnover_rate": float(row["turnover_rate"])
                    if row.get("turnover_rate") is not None
                    else None,
                    "volume_ratio": volume_ratio,
                    "market_cap": market_cap,
                    "recent_return_5d": float(row["recent_return_5d"])
                    if row.get("recent_return_5d") is not None
                    else None,
                    "pb_ratio": float(row["pb_ratio"]) if row.get("pb_ratio") is not None else None,
                    "roe": float(row["roe"]) if row.get("roe") is not None else None,
                    "pe_ratio": float(row["pe_ratio"]) if row.get("pe_ratio") is not None else None,
                    "main_net_in_5d": float(row["main_net_in_5d"])
                    if row.get("main_net_in_5d") is not None
                    else None,
                    "ai_action": row.get("ai_action"),
                    "ai_confidence": float(row["ai_confidence"])
                    if row.get("ai_confidence") is not None
                    else None,
                }
            )
        return universe

    async def _find_theme_stock_codes(self, keywords: list[str]) -> set[str]:
        if not keywords:
            return set()

        patterns = [f"%{kw}%" for kw in keywords]
        async with get_db() as db:
            ann = await db.execute(
                text(
                    """
                    SELECT DISTINCT stock_code
                    FROM fundamental.announcements
                    WHERE stock_code IS NOT NULL
                      AND (title ILIKE ANY(:patterns) OR COALESCE(content_text, '') ILIKE ANY(:patterns))
                    LIMIT 200
                    """
                ),
                {"patterns": patterns},
            )
            codes = {r[0] for r in ann.fetchall() if r[0]}

        return codes

    def _filter_and_sort(
        self,
        universe: list[dict[str, Any]],
        conditions: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        filters = conditions.get("filters", [])
        matched = [s for s in universe if self.factors.apply_filters(s, filters)]

        sort_by = conditions.get("sort_by", "change_pct")
        reverse = str(conditions.get("sort_order", "desc")).lower() != "asc"
        matched.sort(key=lambda s: self.factors.sort_key(s, sort_by), reverse=reverse)
        return matched[:limit]

    @staticmethod
    def _enrich_sector_rank(universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_sector: dict[str, list[dict[str, Any]]] = {}
        for stock in universe:
            sector = stock.get("sector") or "未知"
            by_sector.setdefault(sector, []).append(stock)

        enriched: list[dict[str, Any]] = []
        for sector_stocks in by_sector.values():
            sector_stocks.sort(
                key=lambda s: float(s.get("amount") or s.get("market_cap") or 0),
                reverse=True,
            )
            total = len(sector_stocks)
            for idx, stock in enumerate(sector_stocks):
                stock = dict(stock)
                stock["sector_rank_pct"] = (idx + 1) / total if total else 1.0
                enriched.append(stock)
        return enriched

    def _resolve_theme(self, theme: str) -> tuple[list[str], list[str]]:
        theme_lower = theme.lower().replace(" ", "")
        sectors: list[str] = []
        keywords: list[str] = [theme]

        for key, cfg in THEME_MAP.items():
            if key in theme or key.lower() in theme_lower:
                sectors.extend(cfg["sectors"])
                keywords.extend(cfg["keywords"])

        for cfg in THEME_MAP.values():
            for kw in cfg["keywords"]:
                if kw.lower() in theme_lower:
                    sectors.extend(cfg["sectors"])
                    keywords.append(kw)

        sectors = list(dict.fromkeys(sectors))
        keywords = list(dict.fromkeys(keywords))
        return sectors, keywords

    def _cache_key(self, kind: str, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()[:16]
        return f"screener:{kind}:{digest}"

    async def _get_cache(self, key: str) -> dict[str, Any] | None:
        data = await self.cache.get(key)
        return data if isinstance(data, dict) else None

    async def _set_cache(self, key: str, payload: dict[str, Any]) -> None:
        await self.cache.set(key, payload, ttl=CACHE_TTL)