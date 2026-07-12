from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import text

from app.data.cache import CacheManager
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.data.research_readiness import ResearchReadinessService
from app.data.research_profiles import ResearchDataRequirementProfile
from app.core.config import settings
from app.db import get_db
from app.screener.factors import FactorLibrary
from app.screener.presets import PRESET_DEFINITIONS, get_preset_conditions

logger = structlog.get_logger(__name__)

CACHE_TTL = 3600
SCREENER_REQUIREMENT_PROFILE = "AMOUNT_FACTOR_V1"
SCREENER_REQUIRED_FIELDS = list(
    ResearchDataRequirementProfile.get(SCREENER_REQUIREMENT_PROFILE).required_fields
)

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

    def __init__(
        self,
        cache: CacheManager | None = None,
        release_enabled: bool | None = None,
        kline_repository: CertifiedKlineRepository | None = None,
    ) -> None:
        self.cache = cache or CacheManager()
        self.kline_repository = kline_repository or CertifiedKlineRepository()
        self.factors = FactorLibrary()
        self.release_enabled = (
            settings.CERTIFIED_SCREENER_OUTPUT_ENABLED
            if release_enabled is None
            else release_enabled
        )

    async def screen(self, conditions: dict[str, Any], limit: int = 50) -> dict[str, Any]:
        if not self.release_enabled:
            return self._release_blocked_payload(limit, conditions=conditions)
        cache_key = self._cache_key("screen_certified_v2", {"conditions": conditions, "limit": limit})
        cached = await self._get_cache(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached

        universe = await self._load_universe(
            requirement_profile=SCREENER_REQUIREMENT_PROFILE,
            required_fields=SCREENER_REQUIRED_FIELDS,
        )
        if conditions.get("preset_handler") == "sector_leader":
            universe = self._enrich_sector_rank(universe)

        results = self._filter_and_sort(universe, conditions, limit)
        payload = {
            "items": results,
            "total": len(results),
            "universe_size": len(universe),
            "limit": limit,
            "conditions": conditions,
            "from_cache": False,
            "data_certification": "certified_only",
            "note": (
                f"股票池 {len(universe)} 只，筛选后 {len(results)} 只"
                if universe
                else "无已认证历史数据，已排除 unknown/synthetic K 线"
            ),
        }
        await self._set_cache(cache_key, payload)
        return payload

    async def screen_preset(self, preset_id: str, limit: int = 50) -> dict[str, Any]:
        conditions = get_preset_conditions(preset_id)
        if not conditions:
            raise ValueError(f"未知预设条件: {preset_id}")
        if not self.release_enabled:
            payload = self._release_blocked_payload(limit, conditions=conditions)
            payload["preset_id"] = preset_id
            payload["preset_name"] = PRESET_DEFINITIONS[preset_id]["name"]
            return payload

        cache_key = self._cache_key("preset_certified_v2", {"preset_id": preset_id, "limit": limit})
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
        if not self.release_enabled:
            payload = self._release_blocked_payload(limit)
            payload["theme"] = theme
            return payload

        cache_key = self._cache_key("theme_certified_v2", {"theme": theme, "limit": limit})
        cached = await self._get_cache(cache_key)
        if cached:
            cached["from_cache"] = True
            return cached

        sectors, keywords = self._resolve_theme(theme)
        theme_codes = await self._find_theme_stock_codes(keywords)
        universe = await self._load_universe(
            requirement_profile=SCREENER_REQUIREMENT_PROFILE,
            required_fields=SCREENER_REQUIRED_FIELDS,
        )
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

    @staticmethod
    def _release_blocked_payload(
        limit: int,
        *,
        conditions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "universe_size": 0,
            "limit": limit,
            "conditions": conditions or {},
            "from_cache": False,
            "data_certification": "certified_only",
            "release_status": "blocked",
            "blocked_reason": "CERTIFIED_SCREENER_OUTPUT_DISABLED",
            "note": "Sprint06 仅允许 certified 数据可用性检查，真实候选股输出仍关闭。",
        }

    async def _load_legacy_universe_disabled(self) -> list[dict[str, Any]]:
        """加载选股宇宙。

        兼容标准 PostgreSQL（不依赖 Timescale first/last），
        并以 stocks + klines 为主；财务/资金流/行情表缺失时自动降级。
        """
        raise RuntimeError("legacy K-line screener path is permanently disabled")
        async with get_db() as db:
            # 探测可选表
            optional = await db.execute(
                text(
                    """
                    SELECT table_schema || '.' || table_name AS fq
                    FROM information_schema.tables
                    WHERE (table_schema, table_name) IN (
                        ('fundamental', 'financial_reports'),
                        ('market', 'fund_flows'),
                        ('market', 'quotes')
                    )
                    """
                )
            )
            present = {r[0] for r in optional.fetchall()}
            has_fin = "fundamental.financial_reports" in present
            has_fund = "market.fund_flows" in present
            has_quotes = "market.quotes" in present

            fin_cte = (
                """
                latest_fin AS (
                    SELECT DISTINCT ON (stock_code)
                        stock_code, pb_ratio, roe, pe_ratio
                    FROM fundamental.financial_reports
                    ORDER BY stock_code, report_date DESC
                )
                """
                if has_fin
                else """
                latest_fin AS (
                    SELECT
                        NULL::varchar AS stock_code,
                        NULL::numeric AS pb_ratio,
                        NULL::numeric AS roe,
                        NULL::numeric AS pe_ratio
                    WHERE FALSE
                )
                """
            )
            fund_cte = (
                """
                fund_5d AS (
                    SELECT stock_code,
                           COALESCE(SUM(main_net_in), 0)::float AS main_net_in_5d
                    FROM market.fund_flows
                    WHERE time >= NOW() - INTERVAL '5 days'
                    GROUP BY stock_code
                )
                """
                if has_fund
                else """
                fund_5d AS (
                    SELECT NULL::varchar AS stock_code,
                           NULL::float AS main_net_in_5d
                    WHERE FALSE
                )
                """
            )
            quote_cte = (
                """
                latest_quote AS (
                    SELECT DISTINCT ON (stock_code)
                        stock_code, price, change_pct,
                        volume AS quote_volume,
                        amount AS quote_amount, prev_close
                    FROM market.quotes
                    ORDER BY stock_code, time DESC
                )
                """
                if has_quotes
                else """
                latest_quote AS (
                    SELECT
                        NULL::varchar AS stock_code,
                        NULL::numeric AS price,
                        NULL::numeric AS change_pct,
                        NULL::numeric AS quote_volume,
                        NULL::numeric AS quote_amount,
                        NULL::numeric AS prev_close
                    WHERE FALSE
                )
                """
            )

            sql = f"""
                    WITH certified_klines AS (
                        SELECT k.*
                        FROM market.klines k
                        JOIN market.kline_provenance p
                          ON (p.time, p.stock_code, p.period) = (k.time, k.stock_code, k.period)
                        WHERE {CERTIFIED_FILTER}
                    ),
                    k_ranked AS (
                        SELECT
                            stock_code,
                            close,
                            volume,
                            amount,
                            turnover_rate,
                            time,
                            LAG(close) OVER (
                                PARTITION BY stock_code ORDER BY time
                            ) AS prev_close,
                            ROW_NUMBER() OVER (
                                PARTITION BY stock_code ORDER BY time DESC
                            ) AS rn
                        FROM certified_klines
                        WHERE period = '1d'
                    ),
                    latest_kline AS (
                        SELECT
                            stock_code,
                            close,
                            volume,
                            amount,
                            turnover_rate,
                            time,
                            prev_close,
                            CASE
                                WHEN prev_close IS NOT NULL AND prev_close > 0
                                THEN (close - prev_close) / prev_close * 100
                                ELSE NULL
                            END AS kline_change_pct
                        FROM k_ranked
                        WHERE rn = 1
                    ),
                    avg_volume AS (
                        SELECT stock_code, AVG(volume)::float AS avg_volume
                        FROM certified_klines
                        WHERE period = '1d'
                          AND time >= NOW() - INTERVAL '20 days'
                        GROUP BY stock_code
                    ),
                    return_5d AS (
                        SELECT
                            a.stock_code,
                            CASE
                                WHEN b.close IS NOT NULL AND b.close > 0
                                THEN (a.close / b.close - 1) * 100
                                ELSE NULL
                            END AS recent_return_5d
                        FROM (
                            SELECT DISTINCT ON (stock_code)
                                stock_code, close
                            FROM certified_klines
                            WHERE period = '1d'
                              AND time >= NOW() - INTERVAL '10 days'
                            ORDER BY stock_code, time DESC
                        ) a
                        JOIN (
                            SELECT DISTINCT ON (stock_code)
                                stock_code, close
                            FROM certified_klines
                            WHERE period = '1d'
                              AND time >= NOW() - INTERVAL '10 days'
                            ORDER BY stock_code, time ASC
                        ) b ON a.stock_code = b.stock_code
                    ),
                    {fin_cte},
                    {fund_cte},
                    latest_signal AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code,
                            action AS ai_action,
                            confidence AS ai_confidence
                        FROM ai.signals
                        WHERE status = 'active'
                          AND (valid_until IS NULL OR valid_until > NOW())
                        ORDER BY stock_code, signal_time DESC
                    ),
                    {quote_cte}
                    SELECT
                        s.code,
                        s.name,
                        s.sector,
                        s.market,
                        s.board,
                        s.total_shares,
                        COALESCE(q.price, lk.close) AS price,
                        COALESCE(
                            q.change_pct,
                            lk.kline_change_pct,
                            CASE
                                WHEN q.prev_close > 0
                                THEN (q.price - q.prev_close) / q.prev_close * 100
                                ELSE NULL
                            END
                        ) AS change_pct,
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
                    WHERE s.is_active = TRUE
                      AND COALESCE(s.is_st, FALSE) = FALSE
                      AND lk.stock_code IS NOT NULL
                    ORDER BY s.code
                    """
            result = await db.execute(text(sql))
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

    async def _load_universe(
        self,
        *,
        requirement_profile: str | None,
        required_fields: list[str] | None,
    ) -> list[dict[str, Any]]:
        symbols = await self.kline_repository.get_certified_universe(
            period="1d", adjustment="raw"
        )
        if not symbols:
            return []
        bars = await self.kline_repository.get_bars(
            symbols, period="1d", adjustment="raw"
        )
        if not bars:
            return []
        start_date = min(row["trading_date"] for row in bars)
        end_date = max(row["trading_date"] for row in bars)
        ready_symbols = await ResearchReadinessService().get_ready_codes(
            symbols,
            period="1d",
            adjustment="raw",
            research_use_scope="return_backtest",
            requirement_profile=requirement_profile,
            required_fields=required_fields,
            start_date=start_date,
            end_date=end_date,
        )
        if not ready_symbols:
            return []
        ready_set = set(ready_symbols)
        bars = [row for row in bars if row["stock_code"] in ready_set]
        symbols = ready_symbols
        codes = [symbol.split(".", 1)[0] for symbol in symbols]
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT code, name, sector, market, board, total_shares
                    FROM fundamental.stocks
                    WHERE code=ANY(:codes) AND is_active=TRUE
                      AND COALESCE(is_st, FALSE)=FALSE
                    """
                ),
                {"codes": codes},
            )
            metadata = {row["code"]: dict(row) for row in result.mappings().all()}

        by_code: dict[str, list[dict[str, Any]]] = {}
        for bar in bars:
            by_code.setdefault(bar["stock_code"].split(".", 1)[0], []).append(bar)

        universe: list[dict[str, Any]] = []
        for code, items in by_code.items():
            meta = metadata.get(code)
            if not meta:
                continue
            items.sort(key=lambda row: row["trading_date"])
            latest = items[-1]
            previous = items[-2] if len(items) > 1 else None
            close = float(latest["close"])
            prev_close = float(previous["close"]) if previous else None
            volumes = [float(row["volume"]) for row in items[-20:]]
            avg_volume = sum(volumes) / len(volumes)
            first_5d = items[-5] if len(items) >= 5 else items[0]
            first_close = float(first_5d["close"])
            universe.append(
                {
                    **meta,
                    "price": close,
                    "change_pct": (
                        (close / prev_close - 1) * 100 if prev_close else None
                    ),
                    "volume": float(latest["volume"]),
                    "amount": float(latest["amount"]),
                    "turnover_rate": (
                        float(latest["turnover_rate"])
                        if latest.get("turnover_rate") is not None
                        else None
                    ),
                    "volume_ratio": self.factors.volume_ratio(
                        float(latest["volume"]), avg_volume
                    ),
                    "market_cap": self.factors.market_cap(close, meta.get("total_shares")),
                    "recent_return_5d": (close / first_close - 1) * 100,
                    "pb_ratio": None,
                    "roe": None,
                    "pe_ratio": None,
                    "main_net_in_5d": None,
                    "ai_action": None,
                    "ai_confidence": None,
                }
            )
        return universe

    async def _find_theme_stock_codes(self, keywords: list[str]) -> set[str]:
        if not keywords:
            return set()

        async with get_db() as db:
            # 公告表可能不存在（精简库）
            exists = await db.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='fundamental' AND table_name='announcements'
                    """
                )
            )
            if not exists.scalar():
                return set()

            # asyncpg 对 ANY(:list) 支持不稳定，改为 OR 拼接
            clauses = []
            params: dict[str, Any] = {}
            for i, kw in enumerate(keywords[:12]):
                key = f"p{i}"
                params[key] = f"%{kw}%"
                clauses.append(
                    f"(title ILIKE :{key} OR COALESCE(content_text, '') ILIKE :{key})"
                )
            if not clauses:
                return set()
            ann = await db.execute(
                text(
                    f"""
                    SELECT DISTINCT stock_code
                    FROM fundamental.announcements
                    WHERE stock_code IS NOT NULL
                      AND ({' OR '.join(clauses)})
                    LIMIT 200
                    """
                ),
                params,
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
