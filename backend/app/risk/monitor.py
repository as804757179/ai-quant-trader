from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RiskMonitor:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_portfolio_snapshot(self, mode: str) -> dict:
        account_result = await self.db.execute(
            text(
                """
                SELECT * FROM trade.account_records
                WHERE mode = :mode
                ORDER BY record_time DESC
                LIMIT 1
                """
            ),
            {"mode": mode},
        )
        account = account_result.mappings().first()

        positions_result = await self.db.execute(
            text(
                """
                SELECT p.*, s.sector
                FROM trade.positions p
                LEFT JOIN fundamental.stocks s ON p.stock_code = s.code
                WHERE p.mode = :mode
                """
            ),
            {"mode": mode},
        )
        positions = positions_result.mappings().all()

        peak_result = await self.db.execute(
            text(
                """
                SELECT MAX(total_assets) AS peak
                FROM trade.account_records
                WHERE mode = :mode
                """
            ),
            {"mode": mode},
        )
        peak_row = peak_result.mappings().first()

        total_assets = float(account["total_assets"]) if account else 0.0
        peak = float(peak_row["peak"]) if peak_row and peak_row["peak"] else total_assets
        drawdown = (total_assets - peak) / peak if peak > 0 else 0

        return {
            "total_assets": total_assets,
            "cash": float(account["cash"]) if account else 0.0,
            "total_market_value": float(account["market_value"]) if account else 0.0,
            "daily_pnl": float(account["daily_pnl"]) if account and account["daily_pnl"] else 0.0,
            "daily_pnl_pct": (
                float(account["daily_pnl"]) / total_assets if account and total_assets else 0.0
            ),
            "drawdown_from_peak": drawdown,
            "positions": {p["stock_code"]: dict(p) for p in positions},
        }