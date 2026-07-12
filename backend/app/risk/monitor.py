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

        cash = float(account["cash"]) if account else 0.0
        # 以持仓表实时汇总市值，避免增量更新漂移
        positions_mv = sum(float(p.get("market_value") or 0) for p in positions)
        # 优先用 cash + 持仓市值；无持仓时回退账户字段
        if account:
            total_assets = cash + positions_mv
            recorded_assets = float(account["total_assets"] or 0)
            # 若两边接近仍以实时为准；无现金无持仓时用记录值
            if total_assets <= 0 and recorded_assets > 0:
                total_assets = recorded_assets
        else:
            total_assets = 0.0

        peak = float(peak_row["peak"]) if peak_row and peak_row["peak"] else total_assets
        # 峰值至少不低于当前资产
        if peak < total_assets:
            peak = total_assets
        drawdown = (total_assets - peak) / peak if peak > 0 else 0

        daily_pnl = float(account["daily_pnl"]) if account and account["daily_pnl"] else 0.0

        return {
            "total_assets": total_assets,
            "cash": cash,
            "total_market_value": positions_mv,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": (daily_pnl / total_assets) if total_assets else 0.0,
            "drawdown_from_peak": drawdown,
            "positions": {p["stock_code"]: dict(p) for p in positions},
        }
