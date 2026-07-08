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
                result = await db.execute(
                    text(
                        """
                        SELECT p.*, s.name, s.sector
                        FROM trade.positions p
                        JOIN fundamental.stocks s ON p.stock_code = s.code
                        WHERE p.mode = :mode
                        ORDER BY p.market_value DESC NULLS LAST
                        """
                    ),
                    {"mode": mode},
                )
                rows = [dict(r._mapping) for r in result.fetchall()]

            for row in rows:
                quote = await svc.get_quote(row["stock_code"])
                if quote:
                    price = float(quote["price"])
                    market_value = price * row["total_qty"]
                    avg_cost = float(row["avg_cost"] or 0)
                    row["current_price"] = price
                    row["market_value"] = market_value
                    row["unrealized_pnl"] = (price - avg_cost) * row["total_qty"]
                    row["unrealized_pnl_pct"] = (
                        (price / avg_cost - 1) * 100 if avg_cost > 0 else 0
                    )
            return rows
        finally:
            await svc.close()