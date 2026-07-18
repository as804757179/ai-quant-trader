import asyncio
from datetime import date, datetime
from typing import Any

import structlog
from sqlalchemy import text

from app.data.cache import CacheManager
from app.data.certification import DataCertificationService
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.data.research_profiles import ResearchDataRequirementProfile
from app.data.client import DataClient, DataFetchResult
from app.db import get_db

logger = structlog.get_logger()

AI_CONTEXT_POLICY_VERSION = "ai-context-gate-v1"
_AI_CONTEXT_REQUIRED_SOURCES = (
    "quote",
    "kline_1d",
    "kline_60m",
    "fund_flow",
    "news",
    "financial_report",
    "rag",
)


class DataService:
    def __init__(self, *, shared_client: bool = True) -> None:
        self.client = DataClient(shared=shared_client)
        self.cache = CacheManager()
        self.certified_klines = CertifiedKlineRepository()

    async def close(self) -> None:
        await self.client.close()

    async def get_quote_result(self, code: str) -> DataFetchResult:
        code = str(code).zfill(6) if str(code).isdigit() else str(code)
        cache_key = f"quote:{code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return DataFetchResult(
                status="success",
                data=cached,
                provenance={
                    "source": "backend_memory_cache",
                    "quality_status": "observed",
                    "usage_status": "display_only",
                },
            )
        try:
            fetch_result = await self.client.fetch_quote_result(code)
            if not fetch_result.success:
                logger.warning(
                    "quote_remote_data_unavailable",
                    code=code,
                    status=fetch_result.status,
                    error_code=fetch_result.error_code,
                    retryable=fetch_result.retryable,
                    provenance=fetch_result.provenance,
                )
                return fetch_result
            if fetch_result.data and self._validate_quote(fetch_result.data):
                await self.cache.set(
                    cache_key, fetch_result.data, ttl=CacheManager.TTL_QUOTE
                )
                return fetch_result
            return DataFetchResult(
                status="validation_failed",
                error_code="QUOTE_VALIDATION_FAILED",
                provenance=fetch_result.provenance,
            )
        except Exception as exc:
            logger.warning("get_quote_failed", code=code, error=str(exc))
            return DataFetchResult(
                status="fetch_failed",
                error_code="QUOTE_SERVICE_FAILED",
                retryable=True,
                provenance={"source": "backend_data_service"},
            )

    async def get_quote(self, code: str) -> dict | None:
        result = await self.get_quote_result(code)
        return result.data if result.success and isinstance(result.data, dict) else None

    async def get_quotes_batch(self, codes: list[str]) -> dict[str, dict]:
        """批量取行情：L1/Redis 优先，缺口一次远程批量拉取。"""
        norm = []
        seen: set[str] = set()
        for c in codes:
            if not c:
                continue
            code = str(c).zfill(6) if str(c).isdigit() else str(c)
            if code not in seen:
                seen.add(code)
                norm.append(code)
        if not norm:
            return {}

        keys = [f"quote:{c}" for c in norm]
        cached_list = await self.cache.mget(keys)
        out: dict[str, dict] = {}
        missing: list[str] = []
        for code, cached in zip(norm, cached_list):
            if cached and self._validate_quote(cached):
                out[code] = cached
            else:
                missing.append(code)

        if missing:
            try:
                fetch_result = await self.client.fetch_quotes_batch_result(missing)
                remote = fetch_result.data if fetch_result.success else {}
                if not fetch_result.success:
                    logger.warning(
                        "quotes_batch_remote_data_unavailable",
                        status=fetch_result.status,
                        error_code=fetch_result.error_code,
                        retryable=fetch_result.retryable,
                        provenance=fetch_result.provenance,
                        n=len(missing),
                    )
            except Exception as exc:
                logger.warning("get_quotes_batch_failed", error=str(exc), n=len(missing))
                remote = {}
            for code in missing:
                data = remote.get(code)
                if data and self._validate_quote(data):
                    out[code] = data
                    await self.cache.set(f"quote:{code}", data, ttl=CacheManager.TTL_QUOTE)
        return out

    async def get_kline(
        self,
        code: str,
        period: str = "1d",
        limit: int = 200,
        adj: str = "qfq",
    ) -> list[dict]:
        if adj not in {"raw", "qfq"}:
            raise ValueError(f"unsupported kline adjustment: {adj}")
        code = str(code).zfill(6) if str(code).isdigit() else str(code)
        period = self._normalize_period(period)
        cache_key = f"kline:{code}:{period}:{limit}:{adj}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # 分钟线远程通常更快且更新；日线优先 DB
            prefer_remote = period.endswith("min")
            rows: list[dict] = []
            if not prefer_remote:
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

            # 日/周/月：库内有数据直接用；分钟线数据过少则继续拉远程
            use_db = bool(rows) and (
                period in ("1d", "1w", "1M") or len(rows) >= min(limit, 30)
            )
            if use_db:
                rows.reverse()
                for row in rows:
                    row["time"] = row["time"].isoformat() if row.get("time") else None
                    for num_key in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "adj_factor",
                        "turnover_rate",
                    ):
                        if row.get(num_key) is not None:
                            try:
                                row[num_key] = float(row[num_key])
                            except (TypeError, ValueError):
                                pass
                if adj == "qfq":
                    rows = self._apply_forward_adj(rows)
                ttl = (
                    CacheManager.TTL_KLINE_DAILY
                    if period in ("1d", "1w", "1M")
                    else CacheManager.TTL_KLINE_MIN
                )
                await self.cache.set(cache_key, rows, ttl=ttl)
                return rows

            fetch_result = await self.client.fetch_kline_result(code, period, limit)
            data = fetch_result.data if fetch_result.success else []
            if not fetch_result.success:
                logger.warning(
                    "kline_remote_data_unavailable",
                    code=code,
                    period=period,
                    status=fetch_result.status,
                    error_code=fetch_result.error_code,
                    retryable=fetch_result.retryable,
                    provenance=fetch_result.provenance,
                )
            if data:
                # 先返回再异步落库，避免串行 INSERT 拖慢首屏
                if period in ("1d", "1w", "1M"):
                    asyncio.create_task(self._save_klines_safe(code, period, data))
                if adj == "qfq":
                    data = self._apply_forward_adj(data)
                ttl = (
                    CacheManager.TTL_KLINE_DAILY
                    if period in ("1d", "1w", "1M")
                    else CacheManager.TTL_KLINE_MIN
                )
                await self.cache.set(cache_key, data, ttl=ttl)
                return data
        except Exception as exc:
            logger.error("get_kline_failed", code=code, period=period, error=str(exc))
        return []

    async def get_certified_kline(
        self,
        code: str,
        period: str,
        limit: int,
        adjustment: str,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | None,
    ) -> list[dict]:
        period = self._normalize_period(period)
        rows = await self.certified_klines.get_bars(
            [code], period=period, adjustment=adjustment
        )
        rows = rows[-limit:]
        if rows:
            await self.certified_klines.assert_dataset_ready(
                [code],
                period=period,
                adjustment=adjustment,
                research_use_scope=research_use_scope,
                requirement_profile=requirement_profile,
                required_fields=required_fields,
                start_date=rows[0]["trading_date"],
                end_date=rows[-1]["trading_date"],
            )
        for row in rows:
            row["time"] = datetime.combine(
                row["trading_date"], row["market_close_time"]
            ).isoformat()
            for key in ("open", "high", "low", "close", "volume", "amount", "turnover_rate"):
                if row.get(key) is not None:
                    row[key] = float(row[key])
        return rows

    @staticmethod
    def _normalize_period(period: str) -> str:
        p = (period or "1d").strip()
        aliases = {
            "day": "1d",
            "daily": "1d",
            "d": "1d",
            "week": "1w",
            "w": "1w",
            "month": "1M",
            "mon": "1M",
            "m": "1M",
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "60m": "60min",
            "1h": "60min",
            "120m": "60min",
        }
        return aliases.get(p.lower(), p)

    async def _save_klines_safe(self, code: str, period: str, klines: list[dict]) -> None:
        try:
            await self._save_klines(code, period, klines)
        except Exception as save_exc:
            logger.warning(
                "kline_save_failed", code=code, period=period, error=str(save_exc)
            )

    async def get_fund_flow_result(self, code: str, days: int = 10) -> DataFetchResult:
        cache_key = f"fund_flow:{code}:{days}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return DataFetchResult(
                status="success" if cached else "no_data",
                data=cached if cached else None,
                error_code=None if cached else "NO_DATA",
                provenance={
                    "source": "backend_memory_cache",
                    "quality_status": "observed",
                    "usage_status": "display_only",
                },
            )
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

            if data:
                await self.cache.set(cache_key, data, ttl=CacheManager.TTL_FUND_FLOW)
                return DataFetchResult(
                    status="success",
                    data=data,
                    provenance={
                        "source": "market.fund_flows",
                        "quality_status": "observed",
                        "usage_status": "display_only",
                    },
                )

            if not data:
                fetch_result = await self.client.fetch_fund_flow_result(code, days)
                if not fetch_result.success:
                    logger.warning(
                        "fund_flow_remote_data_unavailable",
                        code=code,
                        status=fetch_result.status,
                        error_code=fetch_result.error_code,
                        retryable=fetch_result.retryable,
                        provenance=fetch_result.provenance,
                    )
                    return fetch_result
                data = fetch_result.data
                if not data:
                    return DataFetchResult(
                        status="no_data",
                        error_code="NO_DATA",
                        provenance=fetch_result.provenance,
                    )
                await self.cache.set(cache_key, data, ttl=CacheManager.TTL_FUND_FLOW)
                return fetch_result
        except Exception as exc:
            logger.warning("get_fund_flow_failed", code=code, error=str(exc))
            return DataFetchResult(
                status="fetch_failed",
                error_code="FUND_FLOW_SERVICE_FAILED",
                retryable=True,
                provenance={"source": "backend_data_service"},
            )

    async def get_fund_flow(self, code: str, days: int = 10) -> list[dict]:
        result = await self.get_fund_flow_result(code, days)
        return result.data if result.success and isinstance(result.data, list) else []

    async def get_news_result(self, code: str, limit: int = 20) -> DataFetchResult:
        cache_key = f"news:{code}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return DataFetchResult(
                status="success" if cached else "no_data",
                data=cached if cached else None,
                error_code=None if cached else "NO_DATA",
                provenance={
                    "source": "backend_memory_cache",
                    "quality_status": "observed",
                    "usage_status": "display_only",
                    "content_scope": "announcement_compatibility_only",
                },
            )
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

            # 库内已有足够公告时跳过远程，减少超时等待
            if not db_news:
                return DataFetchResult(
                    status="no_data",
                    error_code="NO_DATA",
                    provenance={
                        "source": "fundamental.announcements",
                        "quality_status": "observed",
                        "usage_status": "display_only",
                        "content_scope": "announcement_compatibility_only",
                    },
                )
            await self.cache.set(cache_key, db_news, ttl=CacheManager.TTL_NEWS)
            return DataFetchResult(
                status="success",
                data=db_news,
                provenance={
                    "source": "fundamental.announcements",
                    "quality_status": "observed",
                    "usage_status": "display_only",
                    "content_scope": "announcement_compatibility_only",
                },
            )
        except Exception as exc:
            logger.warning("get_news_failed", code=code, error=str(exc))
            return DataFetchResult(
                status="fetch_failed",
                error_code="NEWS_STORAGE_FAILED",
                retryable=True,
                provenance={"source": "fundamental.announcements"},
            )

    async def get_news(self, code: str, limit: int = 20) -> list[dict]:
        result = await self.get_news_result(code, limit)
        return result.data if result.success and isinstance(result.data, list) else []

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
        latest_factor = float(klines[-1].get("adj_factor", 1.0) or 1.0)
        result = []
        for k in klines:
            factor = float(k.get("adj_factor", 1.0) or 1.0)
            ratio = factor / latest_factor if latest_factor else 1.0
            result.append(
                {
                    **k,
                    "open": round(float(k["open"]) * ratio, 4),
                    "high": round(float(k["high"]) * ratio, 4),
                    "low": round(float(k["low"]) * ratio, 4),
                    "close": round(float(k["close"]) * ratio, 4),
                    "volume": int(k.get("volume") or 0),
                    "amount": float(k.get("amount") or 0),
                }
            )
        return result

    async def _save_klines(self, code: str, period: str, klines: list[dict]) -> None:
        if not klines:
            return
        # 批量 executemany，避免逐行往返
        rows = []
        for k in klines:
            ts = k.get("time")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            rows.append(
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
                }
            )
        sql = text(
            """
            INSERT INTO market.klines
            (time, stock_code, period, open, high, low, close, volume, amount, turnover_rate)
            VALUES (:time, :code, :period, :open, :high, :low, :close, :volume, :amount, :turnover_rate)
            ON CONFLICT (time, stock_code, period) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume, amount = EXCLUDED.amount
            """
        )
        async with get_db() as db:
            provenance_rows = [{**k, "stock_code": code, "period": period} for k in klines]
            certification = DataCertificationService()
            batch_id, quality = await certification.create_batch(
                db, provenance_rows, provider="unknown", source="unknown", period=period,
            )
            await db.execute(sql, rows)
            await certification.record_provenance(
                db, provenance_rows, batch_id=batch_id, provider="unknown", source="unknown",
                quality=quality, is_synthetic=False,
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
            self.get_certified_kline(
                code,
                "1d",
                60,
                "raw",
                "raw_price_analysis",
                "OHLCV_RETURN_V1",
                list(ResearchDataRequirementProfile.get("OHLCV_RETURN_V1").required_fields),
            ),
            self.get_certified_kline(
                code,
                "60min",
                30,
                "raw",
                "raw_price_analysis",
                "OHLCV_RETURN_V1",
                list(ResearchDataRequirementProfile.get("OHLCV_RETURN_V1").required_fields),
            ),
            self.get_fund_flow(code, 5),
            self.get_news(code, 10),
            self.get_latest_financial_report(code),
            self.get_north_flow(code),
            self.get_dragon_tiger(code),
            return_exceptions=True,
        )

        source_values = {
            "quote": quote,
            "kline_1d": kline_1d,
            "kline_60m": kline_60m,
            "fund_flow": fund_flow,
            "news": news,
            "financial_report": financial,
            "rag": {"status": "not_research_authorized"},
        }
        analysis_context = self._build_analysis_context_gate(source_values)

        def _safe(val: Any, default: Any) -> Any:
            return default if isinstance(val, Exception) else val or default

        quote = _safe(quote, {})
        kline_1d = _safe(kline_1d, [])
        kline_60m = _safe(kline_60m, [])
        fund_flow = _safe(fund_flow, [])
        news = _safe(news, [])
        financial = _safe(financial, {})
        north = _safe(north, {})
        dragon = _safe(dragon, [])

        indicators = self._calculate_indicators(kline_1d) if kline_1d else {}
        historical_data_status = "certified" if kline_1d else "uncertified"
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
            "historical_data_status": historical_data_status,
            "historical_data_warning": (
                None if historical_data_status == "certified"
                else "当前历史数据未认证，仅可用于展示，不可用于交易判断。"
            ),
            **analysis_context,
        }

    @staticmethod
    def _build_analysis_context_gate(source_values: dict[str, Any]) -> dict[str, Any]:
        source_states: dict[str, str] = {}
        blockers: list[dict[str, str]] = []

        for source in _AI_CONTEXT_REQUIRED_SOURCES:
            value = source_values.get(source)
            if isinstance(value, Exception):
                status = "unavailable"
                reason = "关键数据源请求失败。"
            elif not value:
                status = "missing"
                reason = "关键数据源没有可用记录。"
            elif source in {"kline_1d", "kline_60m"}:
                status = "ready"
                reason = ""
            elif source in {"news", "financial_report", "rag"}:
                status = "not_research_authorized"
                reason = "研究证据尚未获得当前用途授权。"
            else:
                status = "provenance_unverified"
                reason = "关键数据缺少可验证的来源、抓取时点或使用资格。"

            source_states[source] = status
            if status != "ready":
                blockers.append({"source": source, "status": status, "reason": reason})

        return {
            "analysis_context_policy_version": AI_CONTEXT_POLICY_VERSION,
            "analysis_context_status": "ready" if not blockers else "blocked",
            "analysis_context_sources": source_states,
            "analysis_context_blockers": blockers,
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

        fetch_result = await self.client.fetch_financial_report_result(code)
        if not fetch_result.success:
            logger.warning(
                "financial_remote_data_unavailable",
                code=code,
                status=fetch_result.status,
                error_code=fetch_result.error_code,
                retryable=fetch_result.retryable,
                provenance=fetch_result.provenance,
            )
            return {}
        return fetch_result.data

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
