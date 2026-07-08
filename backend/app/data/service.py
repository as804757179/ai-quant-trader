import asyncio
from datetime import date, datetime
from typing import Any

import structlog
from sqlalchemy import text

from app.data.cache import CacheManager
from app.data.client import DataClient
from app.db import get_db

logger = structlog.get_logger()


class DataService:
    def __init__(self) -> None:
        self.client = DataClient()
        self.cache = CacheManager()

    async def close(self) -> None:
        await self.client.close()

    async def get_quote(self, code: str) -> dict | None:
        cache_key = f"quote:{code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            data = await self.client.fetch_quote(code)
            if data and self._validate_quote(data):
                await self.cache.set(cache_key, data, ttl=CacheManager.TTL_QUOTE)
                return data
        except Exception as exc:
            logger.warning("get_quote_failed", code=code, error=str(exc))
        return None

    async def get_kline(
        self,
        code: str,
        period: str = "1d",
        limit: int = 200,
        adj: str = "qfq",
    ) -> list[dict]:
        cache_key = f"kline:{code}:{period}:{limit}:{adj}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT time, open, high, low, close, volume, amount,
                               turnover_rate, adj_factor
                        FROM market.klines
                        WHERE stock_code = :code AND period = :period
                        ORDER BY time DESC
                        LIMIT :limit
                        """
                    ),
                    {"code": code, "period": period, "limit": limit},
                )
                rows = [dict(r._mapping) for r in result.fetchall()]

            if len(rows) >= limit * 0.8:
                rows.reverse()
                for row in rows:
                    row["time"] = row["time"].isoformat() if row.get("time") else None
                if adj == "qfq":
                    rows = self._apply_forward_adj(rows)
                ttl = (
                    CacheManager.TTL_KLINE_DAILY
                    if period == "1d"
                    else CacheManager.TTL_KLINE_MIN
                )
                await self.cache.set(cache_key, rows, ttl=ttl)
                return rows

            data = await self.client.fetch_kline(code, period, limit)
            if data:
                await self._save_klines(code, period, data)
                if adj == "qfq":
                    data = self._apply_forward_adj(data)
                await self.cache.set(cache_key, data, ttl=60)
                return data
        except Exception as exc:
            logger.error("get_kline_failed", code=code, period=period, error=str(exc))
        return []

    async def get_fund_flow(self, code: str, days: int = 10) -> list[dict]:
        cache_key = f"fund_flow:{code}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT time, super_large_in, large_in, medium_in, small_in,
                               main_net_in, north_net_in
                        FROM market.fund_flows
                        WHERE stock_code = :code
                        ORDER BY time DESC
                        LIMIT :days
                        """
                    ),
                    {"code": code, "days": days},
                )
                data = [dict(r._mapping) for r in result.fetchall()]
                for row in data:
                    if row.get("time"):
                        row["time"] = row["time"].isoformat()

            if not data:
                data = await self.client.fetch_fund_flow(code, days) or []

            await self.cache.set(cache_key, data, ttl=CacheManager.TTL_FUND_FLOW)
            return data
        except Exception as exc:
            logger.warning("get_fund_flow_failed", code=code, error=str(exc))
            return []

    async def get_news(self, code: str, limit: int = 20) -> list[dict]:
        cache_key = f"news:{code}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT title, publish_time, content_url, category
                        FROM fundamental.announcements
                        WHERE stock_code = :code
                        ORDER BY publish_time DESC
                        LIMIT :limit
                        """
                    ),
                    {"code": code, "limit": limit},
                )
                db_news = [dict(r._mapping) for r in result.fetchall()]
                for row in db_news:
                    if row.get("publish_time"):
                        row["publish_time"] = row["publish_time"].isoformat()

            fresh_news = await self.client.fetch_news(code, limit=10) or []
            seen: set[str] = set()
            unique_news: list[dict] = []
            for item in fresh_news + db_news:
                key = item.get("title", "")
                if key and key not in seen:
                    seen.add(key)
                    unique_news.append(item)
            unique_news = unique_news[:limit]
            await self.cache.set(cache_key, unique_news, ttl=CacheManager.TTL_NEWS)
            return unique_news
        except Exception as exc:
            logger.warning("get_news_failed", code=code, error=str(exc))
            return []

    def _validate_quote(self, data: dict) -> bool:
        if not data:
            return False
        price = data.get("price", 0)
        if price <= 0:
            return False
        high = data.get("high", 0)
        low = data.get("low", 0)
        if high and low and high < low:
            return False
        return True

    def _apply_forward_adj(self, klines: list[dict]) -> list[dict]:
        if not klines:
            return klines
        latest_factor = klines[-1].get("adj_factor", 1.0) or 1.0
        result = []
        for k in klines:
            factor = k.get("adj_factor", 1.0) or 1.0
            ratio = factor / latest_factor if latest_factor else 1.0
            result.append(
                {
                    **k,
                    "open": round(float(k["open"]) * ratio, 4),
                    "high": round(float(k["high"]) * ratio, 4),
                    "low": round(float(k["low"]) * ratio, 4),
                    "close": round(float(k["close"]) * ratio, 4),
                }
            )
        return result

    async def _save_klines(self, code: str, period: str, klines: list[dict]) -> None:
        async with get_db() as db:
            for k in klines:
                ts = k.get("time")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                await db.execute(
                    text(
                        """
                        INSERT INTO market.klines
                        (time, stock_code, period, open, high, low, close, volume, amount, turnover_rate)
                        VALUES (:time, :code, :period, :open, :high, :low, :close, :volume, :amount, :turnover_rate)
                        ON CONFLICT (time, stock_code, period) DO UPDATE SET
                            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                            close = EXCLUDED.close, volume = EXCLUDED.volume, amount = EXCLUDED.amount
                        """
                    ),
                    {
                        "time": ts,
                        "code": code,
                        "period": period,
                        "open": k["open"],
                        "high": k["high"],
                        "low": k["low"],
                        "close": k["close"],
                        "volume": k.get("volume", 0),
                        "amount": k.get("amount", 0),
                        "turnover_rate": k.get("turnover_rate"),
                    },
                )

    async def get_full_context(self, code: str) -> dict[str, Any]:
        """获取 AI 分析所需的完整数据上下文（并发拉取）。"""
        (
            quote,
            kline_1d,
            kline_60m,
            fund_flow,
            news,
            financial,
            north,
            dragon,
        ) = await asyncio.gather(
            self.get_quote(code),
            self.get_kline(code, "1d", 60),
            self.get_kline(code, "60min", 30),
            self.get_fund_flow(code, 5),
            self.get_news(code, 10),
            self.get_latest_financial_report(code),
            self.get_north_flow(code),
            self.get_dragon_tiger(code),
            return_exceptions=True,
        )

        def _safe(val: Any) -> Any:
            return None if isinstance(val, Exception) else val

        quote = _safe(quote) or {}
        kline_1d = _safe(kline_1d) or []
        kline_60m = _safe(kline_60m) or []
        fund_flow = _safe(fund_flow) or []
        news = _safe(news) or []
        financial = _safe(financial) or {}
        north = _safe(north) or {}
        dragon = _safe(dragon) or []

        indicators = self._calculate_indicators(kline_1d) if kline_1d else {}
        stock_info = await self._get_stock_info(code)
        data_quality_score = self._calc_data_quality_score(quote, kline_1d, financial)

        today_kline = {}
        if kline_1d:
            last = kline_1d[-1]
            today_kline = {
                "open": last.get("open"),
                "high": last.get("high"),
                "low": last.get("low"),
                "close": last.get("close"),
            }

        return {
            "code": code,
            "name": stock_info.get("name", code),
            "sector": stock_info.get("sector", ""),
            "board": stock_info.get("board", ""),
            "is_st": stock_info.get("is_st", False),
            "price": quote.get("price"),
            "prev_close": quote.get("prev_close"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "volume": quote.get("volume"),
            "amount": quote.get("amount"),
            "daily_amount": quote.get("amount"),
            "change_pct": quote.get("change_pct"),
            "turnover_rate": quote.get("turnover_rate"),
            "volume_ratio": quote.get("volume_ratio")
            or indicators.get("volume_ratio"),
            "kline_1d": kline_1d,
            "kline_60m": kline_60m,
            "today_kline": today_kline,
            **indicators,
            "financial_report": financial,
            "fund_flow": fund_flow[-1] if fund_flow else {},
            "news": news,
            "north_flow": north,
            "dragon_tiger": dragon,
            "close_prices_str": ", ".join(
                f"{k['close']}" for k in kline_1d[-20:]
            )
            if kline_1d
            else "N/A",
            "price_changes_5d": self._calc_price_changes(kline_1d, 5),
            "price_3d_change": self._calc_price_change(kline_1d, 3),
            "price_5d_change": self._calc_price_change(kline_1d, 5),
            "market_cap_str": self._fmt_market_cap(
                stock_info.get("total_shares"), quote.get("price")
            ),
            "data_quality_score": data_quality_score,
        }

    async def get_latest_financial_report(self, code: str) -> dict[str, Any]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT report_type, report_date, publish_date, revenue, net_profit,
                               roe, pe_ratio, pb_ratio, eps, gross_margin, debt_ratio,
                               oper_cashflow, revenue_yoy, profit_yoy
                        FROM fundamental.financial_reports
                        WHERE stock_code = :code
                        ORDER BY report_date DESC
                        LIMIT 1
                        """
                    ),
                    {"code": code},
                )
                row = result.mappings().first()
                if row:
                    data = dict(row)
                    for key in ("report_date", "publish_date"):
                        if data.get(key):
                            data[key] = str(data[key])
                    return data
        except Exception as exc:
            logger.warning("get_financial_report_db_failed", code=code, error=str(exc))

        report = await self.client.fetch_financial_report(code)
        return report or {}

    async def get_north_flow(self, code: str) -> dict[str, Any]:
        flows = await self.get_fund_flow(code, 5)
        if not flows:
            return {"today": None, "five_day": None}
        today_val = flows[0].get("north_net_in")
        five_day = sum(float(f.get("north_net_in") or 0) for f in flows[:5])
        return {"today": today_val, "five_day": five_day}

    async def get_dragon_tiger(self, code: str) -> list[dict[str, Any]]:
        return []

    async def _get_stock_info(self, code: str) -> dict[str, Any]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT code, name, sector, board, is_st, total_shares
                        FROM fundamental.stocks
                        WHERE code = :code
                        """
                    ),
                    {"code": code},
                )
                row = result.mappings().first()
                return dict(row) if row else {}
        except Exception as exc:
            logger.warning("get_stock_info_failed", code=code, error=str(exc))
            return {}

    def _calculate_indicators(self, klines: list[dict]) -> dict[str, Any]:
        if len(klines) < 20:
            return {}
        import pandas as pd

        df = pd.DataFrame(klines)
        closes = df["close"]
        volumes = df["volume"]

        ma5 = closes.rolling(5).mean().iloc[-1]
        ma20 = closes.rolling(20).mean().iloc[-1]
        ma60 = closes.rolling(60).mean().iloc[-1] if len(closes) >= 60 else None

        ema12 = closes.ewm(span=12).mean()
        ema26 = closes.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        histogram = macd - signal

        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - 100 / (1 + rs)

        bb_mid = closes.rolling(20).mean()
        bb_std = closes.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        volume_ma5 = volumes.rolling(5).mean()
        volume_ratio = (
            volumes.iloc[-1] / volume_ma5.iloc[-1]
            if volume_ma5.iloc[-1] > 0
            else 1.0
        )

        return {
            "ma5": round(float(ma5), 3) if not pd.isna(ma5) else None,
            "ma20": round(float(ma20), 3) if not pd.isna(ma20) else None,
            "ma60": round(float(ma60), 3)
            if ma60 is not None and not pd.isna(ma60)
            else None,
            "macd": round(float(macd.iloc[-1]), 4)
            if not pd.isna(macd.iloc[-1])
            else None,
            "macd_signal": round(float(signal.iloc[-1]), 4)
            if not pd.isna(signal.iloc[-1])
            else None,
            "macd_histogram": round(float(histogram.iloc[-1]), 4)
            if not pd.isna(histogram.iloc[-1])
            else None,
            "rsi14": round(float(rsi.iloc[-1]), 2)
            if not pd.isna(rsi.iloc[-1])
            else None,
            "bb_upper": round(float(bb_upper.iloc[-1]), 3)
            if not pd.isna(bb_upper.iloc[-1])
            else None,
            "bb_mid": round(float(bb_mid.iloc[-1]), 3)
            if not pd.isna(bb_mid.iloc[-1])
            else None,
            "bb_lower": round(float(bb_lower.iloc[-1]), 3)
            if not pd.isna(bb_lower.iloc[-1])
            else None,
            "volume_ratio": round(float(volume_ratio), 2),
            "avg_turnover_30d": self._calc_avg_turnover(klines, 30),
        }

    def _calc_price_change(self, klines: list[dict], days: int) -> float | None:
        if len(klines) < days + 1:
            return None
        curr = klines[-1]["close"]
        prev = klines[-days - 1]["close"]
        return round((curr / prev - 1) * 100, 2) if prev > 0 else None

    def _calc_price_changes(self, klines: list[dict], days: int) -> str:
        changes: list[str] = []
        for i in range(min(days, len(klines) - 1)):
            curr = klines[-(i + 1)]["close"]
            prev = klines[-(i + 2)]["close"]
            pct = (curr / prev - 1) * 100 if prev > 0 else 0
            changes.append(f"{pct:+.2f}%")
        return ", ".join(reversed(changes)) if changes else "N/A"

    def _calc_avg_turnover(self, klines: list[dict], days: int) -> float | None:
        rates = [
            k.get("turnover_rate", 0)
            for k in klines[-days:]
            if k.get("turnover_rate")
        ]
        return round(sum(rates) / len(rates), 2) if rates else None

    def _fmt_market_cap(self, total_shares: Any, price: Any) -> str:
        if not total_shares or not price:
            return "N/A"
        cap = float(total_shares) * float(price)
        if cap >= 1e11:
            return f"{cap / 1e12:.1f}万亿"
        if cap >= 1e8:
            return f"{cap / 1e8:.0f}亿"
        return f"{cap / 1e4:.0f}万"

    def _calc_data_quality_score(
        self, quote: dict, kline_1d: list[dict], financial: dict
    ) -> float:
        score = 100.0
        if not quote or not quote.get("price"):
            score -= 30
        if len(kline_1d) < 20:
            score -= 20
        if not financial:
            score -= 10
        return max(0.0, round(score, 2))

    async def save_fund_flows(self, code: str, flows: list[dict]) -> None:
        async with get_db() as db:
            for flow in flows:
                ts = flow.get("time")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                await db.execute(
                    text(
                        """
                        INSERT INTO market.fund_flows
                        (time, stock_code, super_large_in, large_in, medium_in, small_in, main_net_in)
                        VALUES (:time, :code, :super_large_in, :large_in, :medium_in, :small_in, :main_net_in)
                        ON CONFLICT (time, stock_code) DO UPDATE SET
                            super_large_in = EXCLUDED.super_large_in,
                            large_in = EXCLUDED.large_in,
                            medium_in = EXCLUDED.medium_in,
                            small_in = EXCLUDED.small_in,
                            main_net_in = EXCLUDED.main_net_in
                        """
                    ),
                    {
                        "time": ts,
                        "code": code,
                        "super_large_in": flow.get("super_large_in"),
                        "large_in": flow.get("large_in"),
                        "medium_in": flow.get("medium_in"),
                        "small_in": flow.get("small_in"),
                        "main_net_in": flow.get("main_net_in"),
                    },
                )