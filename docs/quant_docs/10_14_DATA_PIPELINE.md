# 10-14 — 数据层完整设计

---

## 1. DataService 完整实现

```python
# backend/app/data/service.py

import asyncio
from typing import Optional, List
from datetime import date, datetime
import structlog

from .client import DataClient
from .cache import CacheManager

logger = structlog.get_logger()

class DataService:
    """
    统一数据访问层
    职责：缓存优先 → 数据源回源 → 质量校验 → 返回
    所有方法保证：返回None代表数据不可用，不抛出异常
    """

    def __init__(self):
        self.client = DataClient()
        self.cache = CacheManager()

    async def get_quote(self, code: str) -> Optional[dict]:
        """实时报价（Redis缓存5秒）"""
        cache_key = f"quote:{code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            data = await self.client.fetch_quote(code)
            if data and self._validate_quote(data):
                await self.cache.set(cache_key, data, ttl=5)
                return data
        except Exception as e:
            logger.warning("get_quote_failed", code=code, error=str(e))

        return None

    async def get_kline(
        self,
        code: str,
        period: str = "1d",
        limit: int = 200,
        adj: str = "qfq"
    ) -> List[dict]:
        """
        K线数据（数据库优先，缺失时从a-stock-data补充）
        adj: qfq=前复权，hfq=后复权，none=不复权
        """
        cache_key = f"kline:{code}:{period}:{limit}:{adj}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # 先从TimescaleDB查
            from app.db import get_db
            async with get_db() as db:
                rows = await db.execute("""
                    SELECT time, open, high, low, close, volume, amount,
                           turnover_rate, adj_factor
                    FROM market.klines
                    WHERE stock_code = $1 AND period = $2
                    ORDER BY time DESC
                    LIMIT $3
                """, code, period, limit)
                data = [dict(r) for r in rows.fetchall()]

            if len(data) >= limit * 0.8:  # 数据库有足够数据
                data.reverse()  # 改为时间正序
                if adj == 'qfq':
                    data = self._apply_forward_adj(data)
                ttl = 300 if period == '1d' else 60 if '60' in period else 30
                await self.cache.set(cache_key, data, ttl=ttl)
                return data

            # 数据库不足，从数据源拉取
            data = await self.client.fetch_kline(code, period, limit)
            if data:
                await self._save_klines(code, period, data)  # 回写数据库
                if adj == 'qfq':
                    data = self._apply_forward_adj(data)
                await self.cache.set(cache_key, data, ttl=60)
                return data

        except Exception as e:
            logger.error("get_kline_failed", code=code, period=period, error=str(e))

        return []

    async def get_fund_flow(self, code: str, days: int = 10) -> List[dict]:
        """资金流向数据"""
        cache_key = f"fund_flow:{code}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            from app.db import get_db
            async with get_db() as db:
                rows = await db.execute("""
                    SELECT time, super_large_in, large_in, medium_in, small_in,
                           main_net_in, north_net_in
                    FROM market.fund_flows
                    WHERE stock_code = $1
                    ORDER BY time DESC
                    LIMIT $2
                """, code, days)
                data = [dict(r) for r in rows.fetchall()]

            if not data:
                data = await self.client.fetch_fund_flow(code, days)

            await self.cache.set(cache_key, data, ttl=60)
            return data
        except Exception as e:
            logger.warning("get_fund_flow_failed", code=code, error=str(e))
            return []

    async def get_news(self, code: str, limit: int = 20) -> List[dict]:
        """相关新闻"""
        cache_key = f"news:{code}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            from app.db import get_db
            async with get_db() as db:
                rows = await db.execute("""
                    SELECT title, publish_time, content_url, category
                    FROM fundamental.announcements
                    WHERE stock_code = $1
                    ORDER BY publish_time DESC
                    LIMIT $2
                """, code, limit)
                db_news = [dict(r) for r in rows.fetchall()]

            # 合并数据库已有和实时新闻
            fresh_news = await self.client.fetch_news(code, limit=10)
            all_news = (fresh_news or []) + db_news
            # 去重（按标题）
            seen = set()
            unique_news = []
            for n in all_news:
                key = n.get('title', '')
                if key not in seen:
                    seen.add(key)
                    unique_news.append(n)

            unique_news = unique_news[:limit]
            await self.cache.set(cache_key, unique_news, ttl=300)
            return unique_news
        except Exception as e:
            logger.warning("get_news_failed", code=code, error=str(e))
            return []

    async def get_latest_financial_report(self, code: str) -> Optional[dict]:
        """
        获取最新已发布财务报告
        关键：按 publish_date 查询，不是 report_date（防未来函数）
        """
        cache_key = f"financial:{code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            from app.db import get_db
            today = date.today()
            async with get_db() as db:
                row = await db.execute("""
                    SELECT *
                    FROM fundamental.financial_reports
                    WHERE stock_code = $1
                      AND publish_date <= $2    -- 只用已发布的报告
                    ORDER BY publish_date DESC
                    LIMIT 1
                """, code, today)
                data = dict(row.fetchone()) if row.rowcount else None

            if not data:
                data = await self.client.fetch_financial_report(code)
                if data:
                    await self._save_financial_report(code, data)

            if data:
                await self.cache.set(cache_key, data, ttl=3600)
            return data
        except Exception as e:
            logger.error("get_financial_report_failed", code=code, error=str(e))
            return None

    async def get_north_flow(self, code: str = None) -> dict:
        """北向资金（个股或全市场）"""
        cache_key = f"north_flow:{code or 'market'}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            data = await self.client.fetch_north_flow(code)
            if data:
                await self.cache.set(cache_key, data, ttl=60)
            return data or {}
        except Exception as e:
            logger.warning("get_north_flow_failed", code=code, error=str(e))
            return {}

    async def get_dragon_tiger(self, code: str) -> List[dict]:
        """龙虎榜（只在上榜后次日可查）"""
        cache_key = f"dragon_tiger:{code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            data = await self.client.fetch_dragon_tiger(code)
            if data:
                await self.cache.set(cache_key, data, ttl=3600)
            return data or []
        except Exception as e:
            return []

    async def get_full_context(self, code: str) -> dict:
        """
        获取AI分析所需的完整数据上下文
        并发获取所有数据，减少总等待时间
        """
        # 并发获取所有数据
        quote, kline_1d, kline_60m, fund_flow, news, financial, north, dragon = await asyncio.gather(
            self.get_quote(code),
            self.get_kline(code, '1d', 60),
            self.get_kline(code, '60min', 30),
            self.get_fund_flow(code, 5),
            self.get_news(code, 10),
            self.get_latest_financial_report(code),
            self.get_north_flow(code),
            self.get_dragon_tiger(code),
            return_exceptions=True  # 某项失败不影响其他
        )

        # 处理异常（某项数据失败时用None替代）
        def safe(val):
            return None if isinstance(val, Exception) else val

        quote = safe(quote) or {}
        kline_1d = safe(kline_1d) or []
        kline_60m = safe(kline_60m) or []
        fund_flow = safe(fund_flow) or []
        news = safe(news) or []
        financial = safe(financial) or {}
        north = safe(north) or {}
        dragon = safe(dragon) or []

        # 计算技术指标
        indicators = self._calculate_indicators(kline_1d) if kline_1d else {}

        # 获取股票基本信息
        stock_info = await self._get_stock_info(code)

        return {
            'code': code,
            'name': stock_info.get('name', code),
            'sector': stock_info.get('sector', ''),
            'board': stock_info.get('board', ''),
            'is_st': stock_info.get('is_st', False),

            # 价格数据
            'price': quote.get('price'),
            'prev_close': quote.get('prev_close'),
            'open': quote.get('open'),
            'high': quote.get('high'),
            'low': quote.get('low'),
            'volume': quote.get('volume'),
            'amount': quote.get('amount'),
            'daily_amount': quote.get('amount'),
            'change_pct': quote.get('change_pct'),
            'turnover_rate': quote.get('turnover_rate'),
            'volume_ratio': quote.get('volume_ratio'),

            # K线历史
            'kline_1d': kline_1d,
            'kline_60m': kline_60m,

            # 技术指标
            **indicators,

            # 基本面
            'financial_report': financial,

            # 资金/情绪
            'fund_flow': fund_flow[-1] if fund_flow else {},
            'news': news,
            'north_flow': north,
            'dragon_tiger': dragon,

            # 格式化字符串（供Prompt使用）
            'close_prices_str': ', '.join([f"{k['close']}" for k in kline_1d[-20:]]) if kline_1d else 'N/A',
            'price_changes_5d': self._calc_price_changes(kline_1d, 5),
            'price_3d_change': self._calc_price_change(kline_1d, 3),
            'price_5d_change': self._calc_price_change(kline_1d, 5),
            'market_cap_str': self._fmt_market_cap(stock_info.get('total_shares'), quote.get('price')),
        }

    def _calculate_indicators(self, klines: List[dict]) -> dict:
        """计算技术指标（只用已有的K线数据，不含当日未收盘数据）"""
        if len(klines) < 20:
            return {}

        import pandas as pd
        import numpy as np

        df = pd.DataFrame(klines)
        closes = df['close']
        volumes = df['volume']

        # 移动平均
        ma5 = closes.rolling(5).mean().iloc[-1]
        ma20 = closes.rolling(20).mean().iloc[-1]
        ma60 = closes.rolling(60).mean().iloc[-1] if len(closes) >= 60 else None

        # MACD
        ema12 = closes.ewm(span=12).mean()
        ema26 = closes.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        histogram = macd - signal

        # RSI
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - 100 / (1 + rs)

        # 布林带
        bb_mid = closes.rolling(20).mean()
        bb_std = closes.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        # 量比（当日量/近5日均量）
        volume_ma5 = volumes.rolling(5).mean()
        volume_ratio = (volumes.iloc[-1] / volume_ma5.iloc[-1]) if volume_ma5.iloc[-1] > 0 else 1.0

        return {
            'ma5': round(float(ma5), 3) if not pd.isna(ma5) else None,
            'ma20': round(float(ma20), 3) if not pd.isna(ma20) else None,
            'ma60': round(float(ma60), 3) if ma60 is not None and not pd.isna(ma60) else None,
            'macd': round(float(macd.iloc[-1]), 4) if not pd.isna(macd.iloc[-1]) else None,
            'macd_signal': round(float(signal.iloc[-1]), 4) if not pd.isna(signal.iloc[-1]) else None,
            'macd_histogram': round(float(histogram.iloc[-1]), 4) if not pd.isna(histogram.iloc[-1]) else None,
            'rsi14': round(float(rsi.iloc[-1]), 2) if not pd.isna(rsi.iloc[-1]) else None,
            'bb_upper': round(float(bb_upper.iloc[-1]), 3) if not pd.isna(bb_upper.iloc[-1]) else None,
            'bb_mid': round(float(bb_mid.iloc[-1]), 3) if not pd.isna(bb_mid.iloc[-1]) else None,
            'bb_lower': round(float(bb_lower.iloc[-1]), 3) if not pd.isna(bb_lower.iloc[-1]) else None,
            'volume_ratio': round(float(volume_ratio), 2),
            'avg_turnover_30d': self._calc_avg_turnover(klines, 30),
        }

    def _apply_forward_adj(self, klines: List[dict]) -> List[dict]:
        """前复权处理（用最新的复权因子调整历史价格）"""
        if not klines:
            return klines
        latest_factor = klines[-1].get('adj_factor', 1.0) or 1.0
        result = []
        for k in klines:
            factor = k.get('adj_factor', 1.0) or 1.0
            ratio = factor / latest_factor
            result.append({
                **k,
                'open':  round(k['open'] * ratio, 4),
                'high':  round(k['high'] * ratio, 4),
                'low':   round(k['low'] * ratio, 4),
                'close': round(k['close'] * ratio, 4),
            })
        return result

    def _validate_quote(self, data: dict) -> bool:
        """报价数据质量校验"""
        if not data:
            return False
        price = data.get('price', 0)
        if price <= 0:
            return False
        if data.get('high', 0) < data.get('low', 0):
            return False
        return True

    def _calc_price_change(self, klines: List[dict], days: int) -> Optional[float]:
        if len(klines) < days + 1:
            return None
        curr = klines[-1]['close']
        prev = klines[-days-1]['close']
        return round((curr / prev - 1) * 100, 2) if prev > 0 else None

    def _calc_price_changes(self, klines: List[dict], days: int) -> str:
        changes = []
        for i in range(min(days, len(klines) - 1)):
            curr = klines[-(i+1)]['close']
            prev = klines[-(i+2)]['close']
            pct = (curr / prev - 1) * 100 if prev > 0 else 0
            changes.append(f"{pct:+.2f}%")
        return ', '.join(reversed(changes)) if changes else 'N/A'

    def _calc_avg_turnover(self, klines: List[dict], days: int) -> Optional[float]:
        rates = [k.get('turnover_rate', 0) for k in klines[-days:] if k.get('turnover_rate')]
        return round(sum(rates) / len(rates), 2) if rates else None

    def _fmt_market_cap(self, total_shares, price) -> str:
        if not total_shares or not price:
            return 'N/A'
        cap = total_shares * price
        if cap >= 1e11:
            return f"{cap/1e12:.1f}万亿"
        if cap >= 1e8:
            return f"{cap/1e8:.0f}亿"
        return f"{cap/1e4:.0f}万"

    async def _get_stock_info(self, code: str) -> dict:
        from app.db import get_db
        async with get_db() as db:
            row = await db.execute("""
                SELECT code, name, sector, board, is_st, total_shares
                FROM fundamental.stocks WHERE code = $1
            """, code)
            r = row.fetchone()
            return dict(r) if r else {}

    async def _save_klines(self, code: str, period: str, klines: List[dict]):
        """批量保存K线到TimescaleDB（upsert）"""
        from app.db import get_db
        async with get_db() as db:
            for k in klines:
                await db.execute("""
                    INSERT INTO market.klines
                    (time, stock_code, period, open, high, low, close, volume, amount, turnover_rate)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (time, stock_code, period) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, volume=EXCLUDED.volume, amount=EXCLUDED.amount
                """, k['time'], code, period, k['open'], k['high'], k['low'],
                     k['close'], k['volume'], k['amount'], k.get('turnover_rate'))

    async def _save_financial_report(self, code: str, report: dict):
        """保存财务报告（含publish_date）"""
        from app.db import get_db
        async with get_db() as db:
            await db.execute("""
                INSERT INTO fundamental.financial_reports
                (stock_code, report_type, report_date, publish_date,
                 revenue, net_profit, roe, pe_ratio, pb_ratio, eps,
                 gross_margin, debt_ratio, oper_cashflow,
                 revenue_yoy, profit_yoy)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (stock_code, report_type, report_date) DO UPDATE SET
                    publish_date=EXCLUDED.publish_date,
                    revenue=EXCLUDED.revenue,
                    net_profit=EXCLUDED.net_profit,
                    roe=EXCLUDED.roe
            """, code,
                 report.get('report_type', 'annual'),
                 report.get('report_date'),
                 report.get('publish_date'),    # 关键：记录发布日期
                 report.get('revenue'),
                 report.get('net_profit'),
                 report.get('roe'),
                 report.get('pe_ratio'),
                 report.get('pb_ratio'),
                 report.get('eps'),
                 report.get('gross_margin'),
                 report.get('debt_ratio'),
                 report.get('oper_cashflow'),
                 report.get('revenue_yoy'),
                 report.get('profit_yoy'))
```

---

## 2. CacheManager

```python
# backend/app/data/cache.py

import json
import redis.asyncio as aioredis
from typing import Optional, Any
from app.core.config import settings

class CacheManager:
    """
    Redis缓存管理
    不同数据类型使用不同TTL策略
    """

    # TTL策略（秒）
    TTL_QUOTE = 5          # 实时报价：5秒
    TTL_KLINE_MIN = 30     # 分钟K线：30秒
    TTL_KLINE_DAILY = 300  # 日线K线：5分钟
    TTL_FUND_FLOW = 60     # 资金流向：1分钟
    TTL_NEWS = 300         # 新闻：5分钟
    TTL_FUNDAMENTAL = 3600 # 基本面：1小时
    TTL_SIGNAL = 300       # AI信号：5分钟

    def __init__(self):
        self._client = None

    async def _get_client(self):
        if self._client is None:
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                encoding='utf-8',
                decode_responses=True,
                max_connections=20,
            )
        return self._client

    async def get(self, key: str) -> Optional[Any]:
        client = await self._get_client()
        try:
            value = await client.get(key)
            if value:
                return json.loads(value)
        except Exception:
            pass
        return None

    async def set(self, key: str, value: Any, ttl: int = 60):
        client = await self._get_client()
        try:
            await client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            pass  # 缓存失败不影响主流程

    async def delete(self, key: str):
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception:
            pass

    async def delete_pattern(self, pattern: str):
        """批量删除匹配pattern的key（用于缓存失效）"""
        client = await self._get_client()
        try:
            keys = await client.keys(pattern)
            if keys:
                await client.delete(*keys)
        except Exception:
            pass

    async def publish(self, channel: str, data: dict):
        """发布消息到Redis Pub/Sub"""
        client = await self._get_client()
        try:
            await client.publish(channel, json.dumps(data, ensure_ascii=False, default=str))
        except Exception as e:
            pass

    async def set_lock(self, key: str, ttl: int = 10) -> bool:
        """分布式锁（防止并发重复任务）"""
        client = await self._get_client()
        try:
            return await client.set(f"lock:{key}", "1", ex=ttl, nx=True)
        except Exception:
            return False

    async def release_lock(self, key: str):
        await self.delete(f"lock:{key}")
```

---

## 3. DataClient（封装a-stock-data）

```python
# backend/app/data/client.py

import httpx
import asyncio
from typing import Optional, List
import structlog

logger = structlog.get_logger()

class DataClient:
    """
    封装 a-stock-data HTTP接口
    所有请求带超时和重试
    """

    BASE_URL = "http://a-stock-data:8080"   # Docker内网地址
    TIMEOUT = 10.0
    MAX_RETRIES = 3

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=self.TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20)
        )

    async def _request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        """带重试的HTTP请求"""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.warning("data_client_timeout", path=path, attempts=attempt+1)
                return None
            except httpx.HTTPStatusError as e:
                logger.error("data_client_http_error", path=path, status=e.response.status_code)
                return None
            except Exception as e:
                logger.error("data_client_error", path=path, error=str(e))
                return None

    async def fetch_quote(self, code: str) -> Optional[dict]:
        return await self._request("GET", f"/quote/{code}")

    async def fetch_kline(self, code: str, period: str, limit: int) -> Optional[List[dict]]:
        data = await self._request("GET", f"/kline/{code}", params={
            "period": period, "limit": limit
        })
        return data.get('data') if data else None

    async def fetch_fund_flow(self, code: str, days: int) -> Optional[List[dict]]:
        data = await self._request("GET", f"/fund-flow/{code}", params={"days": days})
        return data.get('data') if data else None

    async def fetch_news(self, code: str, limit: int = 20) -> Optional[List[dict]]:
        data = await self._request("GET", f"/news/{code}", params={"limit": limit})
        return data.get('data') if data else None

    async def fetch_financial_report(self, code: str) -> Optional[dict]:
        data = await self._request("GET", f"/financial/{code}")
        return data.get('data') if data else None

    async def fetch_north_flow(self, code: str = None) -> Optional[dict]:
        path = f"/north-flow/{code}" if code else "/north-flow"
        return await self._request("GET", path)

    async def fetch_dragon_tiger(self, code: str) -> Optional[List[dict]]:
        data = await self._request("GET", f"/dragon-tiger/{code}")
        return data.get('data') if data else None

    async def fetch_stock_list(self) -> Optional[List[dict]]:
        data = await self._request("GET", "/stock/list")
        return data.get('data') if data else None

    async def fetch_sector_flow(self) -> Optional[List[dict]]:
        data = await self._request("GET", "/sector/flow")
        return data.get('data') if data else None
```

---

## 4. 数据同步 Celery 任务

```python
# worker/tasks/market.py

from celery import shared_task
import structlog

logger = structlog.get_logger()

@shared_task(
    name='tasks.sync_realtime_quotes',
    queue='high',
    max_retries=3,
    default_retry_delay=1,
)
def sync_realtime_quotes():
    """
    每3秒：同步活跃股票实时行情到Redis，并推送WebSocket
    只同步：当前持仓 + 用户关注列表
    """
    from app.data.service import DataService
    from app.data.cache import CacheManager
    import asyncio

    async def _run():
        svc = DataService()
        cache = CacheManager()

        # 获取需要同步的股票（持仓+关注）
        active_codes = await _get_active_codes()

        for code in active_codes:
            try:
                quote = await svc.client.fetch_quote(code)
                if quote and svc._validate_quote(quote):
                    # 写入缓存
                    await cache.set(f"quote:{code}", quote, ttl=5)
                    # 推送WebSocket
                    await cache.publish(f"channel:quotes:{code}", {
                        'type': 'quote',
                        'code': code,
                        **quote
                    })
            except Exception as e:
                logger.warning("quote_sync_failed", code=code, error=str(e))

    asyncio.run(_run())


@shared_task(name='tasks.run_signal_scan', queue='normal')
def run_signal_scan():
    """
    每分钟：对关注列表 + 持仓股票运行AI信号扫描
    """
    import asyncio
    from app.data.service import DataService
    from app.ai.orchestrator import AgentOrchestrator
    from app.data.cache import CacheManager
    from app.core.config import settings

    async def _run():
        # 获取需要扫描的股票
        codes = await _get_scan_universe()
        if not codes:
            return

        svc = DataService()
        orchestrator = AgentOrchestrator()
        cache = CacheManager()

        for code in codes[:20]:  # 每分钟最多扫描20只（控制AI费用）
            try:
                # 避免重复分析（5分钟内已分析过的跳过）
                lock_key = f"scanning:{code}"
                if not await cache.set_lock(lock_key, ttl=300):
                    continue

                context = await svc.get_full_context(code)
                if not context.get('price'):
                    continue

                signal = await orchestrator.analyze(code, context)

                # 只推送有效信号（非HOLD或高置信度）
                if signal['action'] != 'HOLD' or signal['confidence'] > 0.75:
                    await cache.publish('channel:signals', {
                        'type': 'signal',
                        'stock_code': code,
                        'stock_name': context.get('name', code),
                        **signal
                    })

                    logger.info("signal_generated",
                               code=code, action=signal['action'],
                               confidence=signal['confidence'])

            except Exception as e:
                logger.error("signal_scan_failed", code=code, error=str(e))

    asyncio.run(_run())


@shared_task(name='tasks.archive_daily_data', queue='low')
def archive_daily_data():
    """
    每日15:30：归档当日数据（日K线/资金流/财报更新）
    """
    import asyncio
    from app.data.service import DataService

    async def _run():
        svc = DataService()
        from app.db import get_db
        async with get_db() as db:
            stocks = await db.execute(
                "SELECT code FROM fundamental.stocks WHERE is_active = TRUE"
            )
            codes = [r[0] for r in stocks.fetchall()]

        total = 0
        for i, code in enumerate(codes):
            try:
                # 回填今日日线
                kline = await svc.client.fetch_kline(code, '1d', 2)
                if kline:
                    await svc._save_klines(code, '1d', kline)
                    total += 1

                # 每100只股票暂停0.1秒（限速）
                if i % 100 == 0:
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.warning("archive_kline_failed", code=code, error=str(e))

        logger.info("daily_archive_done", total=total)

    asyncio.run(_run())


async def _get_active_codes() -> list:
    """获取需要实时同步行情的股票列表"""
    from app.db import get_db
    async with get_db() as db:
        # 当前持仓
        positions = await db.execute("""
            SELECT DISTINCT stock_code FROM trade.positions
            WHERE mode IN ('simulation', 'paper', 'live')
        """)
        codes = {r[0] for r in positions.fetchall()}

        # 今日有活跃信号的股票
        signals = await db.execute("""
            SELECT DISTINCT stock_code FROM ai.signals
            WHERE status = 'active' AND created_at > NOW() - INTERVAL '24 hours'
        """)
        codes |= {r[0] for r in signals.fetchall()}

    return list(codes)


async def _get_scan_universe() -> list:
    """获取AI信号扫描的股票池"""
    from app.db import get_db
    async with get_db() as db:
        # 持仓 + 关注列表 + 最近选股结果
        rows = await db.execute("""
            (SELECT stock_code as code FROM trade.positions WHERE mode != 'live')
            UNION
            (SELECT stock_code FROM strategy.watchlists WHERE is_active = TRUE)
            LIMIT 50
        """)
        return [r[0] for r in rows.fetchall()]
```
