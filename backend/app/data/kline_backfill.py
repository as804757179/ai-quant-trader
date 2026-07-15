"""K 线回填：外部数据源 → DB，支持合成数据兜底。"""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.config import settings
from app.core.logging import FEATURE_STOCK, get_logger
from app.data.certification import DataCertificationService
from app.core.timeutil import today_cn
from app.data.client import DataClient
from app.db import get_db

logger = get_logger(__name__, feature=FEATURE_STOCK)
CN_TZ = ZoneInfo("Asia/Shanghai")


def _seed_from_code(code: str) -> int:
    h = hashlib.md5(code.encode()).hexdigest()
    return int(h[:8], 16)


def generate_synthetic_klines(
    code: str,
    start_date: date,
    end_date: date,
    *,
    start_price: float | None = None,
) -> list[dict[str, Any]]:
    """
    生成可复现的伪日 K（跳过周末），用于本地无数据源时的端到端回测演示。
    不用于真实交易决策。
    """
    if end_date < start_date:
        return []
    seed = _seed_from_code(code)
    price = start_price or (5.0 + (seed % 5000) / 100.0)  # 5~55
    rows: list[dict[str, Any]] = []
    d = start_date
    i = 0
    while d <= end_date:
        if d.weekday() < 5:  # Mon-Fri
            # 确定性伪随机游走 + 慢趋势
            wave = math.sin((i + seed % 17) / 8.0) * 0.02
            drift = 0.0008 if (seed + i) % 40 > 15 else -0.0003
            ret = wave + drift + (((seed >> (i % 8)) & 7) - 3) * 0.0015
            open_p = price
            close_p = max(0.5, price * (1 + ret))
            high_p = max(open_p, close_p) * (1 + 0.005 + (i % 3) * 0.001)
            low_p = min(open_p, close_p) * (1 - 0.005 - (i % 2) * 0.001)
            vol = 1_000_000 + (seed % 1000) * 1000 + i * 5000
            amount = vol * (open_p + close_p) / 2
            # A 股日 K 收盘按中国时间 15:00
            ts = datetime(d.year, d.month, d.day, 15, 0, tzinfo=CN_TZ)
            rows.append(
                {
                    "time": ts.isoformat(),
                    "open": round(open_p, 4),
                    "high": round(high_p, 4),
                    "low": round(low_p, 4),
                    "close": round(close_p, 4),
                    "volume": int(vol),
                    "amount": round(amount, 2),
                    "turnover_rate": round(0.5 + (i % 10) * 0.1, 2),
                    "adj_factor": 1.0,
                    "_synthetic": True,
                }
            )
            price = close_p
            i += 1
        d += timedelta(days=1)
    return rows


def estimate_limit_for_range(start_date: date, end_date: date) -> int:
    days = max((end_date - start_date).days + 30, 30)
    # 交易日近似
    return min(max(int(days * 0.75), 60), 1000)


class KlineBackfillService:
    def __init__(self, client: DataClient | None = None) -> None:
        self.client = client or DataClient()
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.close()

    async def backfill_codes(
        self,
        codes: list[str],
        *,
        period: str = "1d",
        limit: int = 250,
        concurrency: int = 5,
        allow_synthetic: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "kline_backfill_start",
            codes_count=len(codes),
            period=period,
            limit=limit,
            concurrency=concurrency,
            allow_synthetic=allow_synthetic,
            start_date=str(start_date) if start_date else None,
            end_date=str(end_date) if end_date else None,
        )
        sem = asyncio.Semaphore(max(1, concurrency))
        stats = {
            "total": len(codes),
            "success": 0,
            "failed": 0,
            "synthetic": 0,
            "bars_written": 0,
            "details": [],
        }

        async def _one(code: str) -> None:
            async with sem:
                try:
                    n, source = await self.backfill_one(
                        code,
                        period=period,
                        limit=limit,
                        allow_synthetic=allow_synthetic,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if n > 0:
                        stats["success"] += 1
                        stats["bars_written"] += n
                        if source == "synthetic":
                            stats["synthetic"] += 1
                        stats["details"].append(
                            {"code": code, "bars": n, "source": source}
                        )
                    else:
                        stats["failed"] += 1
                        stats["details"].append(
                            {"code": code, "bars": 0, "source": "none"}
                        )
                except Exception as exc:
                    logger.warning("backfill_one_failed", code=code, error=str(exc))
                    stats["failed"] += 1
                    stats["details"].append(
                        {"code": code, "bars": 0, "source": "error", "error": str(exc)}
                    )

        await asyncio.gather(*[_one(c) for c in codes])
        logger.info(
            "kline_backfill_done",
            total=stats["total"],
            success=stats["success"],
            synthetic=stats["synthetic"],
            bars=stats["bars_written"],
        )
        return stats

    async def backfill_one(
        self,
        code: str,
        *,
        period: str = "1d",
        limit: int = 250,
        allow_synthetic: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[int, str]:
        data = await self.client.fetch_kline(code, period, limit)
        source = "remote"
        if allow_synthetic and not settings.SYNTHETIC_KLINE_SMOKE_TEST:
            raise ValueError(
                "Synthetic Kline 仅允许在 SYNTHETIC_KLINE_SMOKE_TEST=true 的 Smoke Test 环境中使用"
            )
        if not data and allow_synthetic and period == "1d":
            sd = start_date or (today_cn() - timedelta(days=int(limit * 1.5)))
            ed = end_date or today_cn()
            data = generate_synthetic_klines(code, sd, ed)
            source = "synthetic"
        if not data:
            return 0, "none"
        provider = "synthetic" if source == "synthetic" else "unknown"
        written = await self.save_klines(
            code, period, data, provider=provider, source=source, is_synthetic=source == "synthetic"
        )
        return written, source

    async def save_klines(
        self, code: str, period: str, klines: list[dict[str, Any]], *,
        provider: str = "unknown", source: str = "unknown", is_synthetic: bool = False,
    ) -> int:
        written = 0
        async with get_db() as db:
            rows_for_provenance = [{**k, "stock_code": code, "period": period} for k in klines]
            certification = DataCertificationService()
            batch_id, quality = await certification.create_batch(
                db, rows_for_provenance, provider=provider, source=source, period=period,
                is_synthetic=is_synthetic,
            )
            for k in klines:
                ts = k.get("time")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if ts is None:
                    continue
                await db.execute(
                    text(
                        """
                        INSERT INTO market.klines
                        (time, stock_code, period, open, high, low, close, volume,
                         amount, turnover_rate, adj_factor)
                        VALUES
                        (:time, :code, :period, :open, :high, :low, :close, :volume,
                         :amount, :turnover_rate, :adj_factor)
                        ON CONFLICT (time, stock_code, period) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            amount = EXCLUDED.amount,
                            turnover_rate = COALESCE(EXCLUDED.turnover_rate, market.klines.turnover_rate),
                            adj_factor = COALESCE(EXCLUDED.adj_factor, market.klines.adj_factor)
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
                        "adj_factor": k.get("adj_factor", 1.0),
                    },
                )
                written += 1
            await certification.record_provenance(
                db, rows_for_provenance, batch_id=batch_id, provider=provider, source=source,
                quality=quality, is_synthetic=is_synthetic,
            )
        return written

    async def ensure_range(
        self,
        codes: list[str],
        start_date: date,
        end_date: date,
        *,
        allow_synthetic: bool = False,
    ) -> dict[str, Any]:
        """确保区间内有日 K；不足则回填。"""
        missing: list[str] = []
        async with get_db() as db:
            for code in codes:
                result = await db.execute(
                    text(
                        """
                        SELECT COUNT(*) AS cnt FROM market.klines
                        WHERE stock_code = :code AND period = '1d'
                          AND time::date >= :start_date
                          AND time::date <= :end_date
                        """
                    ),
                    {
                        "code": code,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
                cnt = int(result.scalar() or 0)
                expected = estimate_limit_for_range(start_date, end_date) * 0.3
                if cnt < expected:
                    missing.append(code)

        if not missing:
            return {"backfilled": False, "missing": [], "stats": None}

        limit = estimate_limit_for_range(start_date, end_date)
        stats = await self.backfill_codes(
            missing,
            period="1d",
            limit=limit,
            allow_synthetic=allow_synthetic,
            start_date=start_date,
            end_date=end_date,
        )
        return {"backfilled": True, "missing": missing, "stats": stats}
