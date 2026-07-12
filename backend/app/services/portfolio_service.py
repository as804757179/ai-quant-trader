import asyncio

from sqlalchemy import text

from app.core.config import settings
from app.data.service import DataService
from app.db import get_db
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.data.cache import CacheManager


class PortfolioService:
    async def get_summary(self, mode: str | None = None) -> dict:
        mode = mode or settings.TRADE_MODE
        cache = CacheManager()

        async with get_db() as db:
            monitor = RiskMonitor(db)
            snapshot = await monitor.get_portfolio_snapshot(mode)
            fuse_mgr = FuseManager(db, cache)
            is_fused = await fuse_mgr.is_fused(mode)

        return {
            "mode": mode,
            "total_assets": snapshot["total_assets"],
            "cash": snapshot["cash"],
            "market_value": snapshot["total_market_value"],
            "daily_pnl": snapshot["daily_pnl"],
            "daily_pnl_pct": snapshot["daily_pnl_pct"],
            "drawdown_from_peak": snapshot["drawdown_from_peak"],
            "position_count": len(snapshot["positions"]),
            "is_fused": is_fused,
        }

    async def get_positions(self, mode: str | None = None) -> list[dict]:
        mode = mode or settings.TRADE_MODE
        svc = DataService()
        try:
            async with get_db() as db:
                # 模拟盘：查询前按 A 股 T+1 释放「非当日买入」可卖
                if mode == "simulation":
                    try:
                        from app.trade.simulation_trader import SimulationTrader

                        trader = SimulationTrader(db, svc)
                        await trader._maybe_release_t1()
                    except Exception:
                        pass
                result = await db.execute(
                    text(
                        """
                        SELECT p.*, s.name, s.sector
                        FROM trade.positions p
                        LEFT JOIN fundamental.stocks s ON p.stock_code = s.code
                        WHERE p.mode = :mode
                        ORDER BY p.market_value DESC NULLS LAST
                        """
                    ),
                    {"mode": mode},
                )
                rows = [dict(r._mapping) for r in result.fetchall()]

            # 批量行情，避免 N 次串行 HTTP
            codes = [str(r.get("stock_code") or "") for r in rows if r.get("stock_code")]
            quotes: dict[str, dict] = {}
            if codes:
                try:
                    quotes = await svc.get_quotes_batch(codes)
                except Exception:
                    quotes = {}

            async def _fallback_kline_price(code: str) -> float | None:
                try:
                    klines = await svc.get_kline(code, "1d", 2, "qfq")
                    if klines:
                        return float(klines[-1]["close"])
                except Exception:
                    return None
                return None

            need_kline = []
            for row in rows:
                code = str(row.get("stock_code") or "")
                qty = int(row.get("total_qty") or 0)
                avg_cost = float(row.get("avg_cost") or 0)
                price = None
                price_source = "avg_cost"
                quote = quotes.get(code)
                if quote and float(quote.get("price") or 0) > 0:
                    price = float(quote["price"])
                    price_source = "quote"
                else:
                    need_kline.append(code)
                row["_price"] = price
                row["_price_source"] = price_source
                row["_avg_cost"] = avg_cost
                row["_qty"] = qty

            # 缺口用 K 线并发补齐
            kline_codes = list(dict.fromkeys(need_kline))
            kline_prices: dict[str, float] = {}
            if kline_codes:
                results = await asyncio.gather(
                    *[_fallback_kline_price(c) for c in kline_codes],
                    return_exceptions=True,
                )
                for c, p in zip(kline_codes, results):
                    if isinstance(p, (int, float)) and p > 0:
                        kline_prices[c] = float(p)

            for row in rows:
                code = str(row.get("stock_code") or "")
                qty = int(row.pop("_qty", 0) or 0)
                avg_cost = float(row.pop("_avg_cost", 0) or 0)
                price = row.pop("_price", None)
                price_source = row.pop("_price_source", "avg_cost")
                if price is None or price <= 0:
                    if code in kline_prices:
                        price = kline_prices[code]
                        price_source = "kline"
                    else:
                        price = avg_cost if avg_cost > 0 else 0.0
                        price_source = "avg_cost"
                market_value = price * qty
                row["current_price"] = price
                row["price_source"] = price_source
                row["market_value"] = market_value
                row["unrealized_pnl"] = (price - avg_cost) * qty if qty else 0
                row["unrealized_pnl_pct"] = (
                    (price / avg_cost - 1) * 100 if avg_cost > 0 else 0
                )
                # 序列化 Decimal
                for k, v in list(row.items()):
                    if hasattr(v, "as_tuple"):  # Decimal
                        row[k] = float(v)
            return rows
        finally:
            await svc.close()