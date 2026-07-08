from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.trade.base_trader import OrderRequest


class OrderManager:
    def __init__(
        self,
        db: AsyncSession,
        risk_checker: PreTradeRiskChecker,
        fuse_manager: FuseManager,
        traders: dict,
    ) -> None:
        self.db = db
        self.risk = risk_checker
        self.fuse = fuse_manager
        self.traders = traders

    async def create_order(self, request: OrderRequest, mode: str) -> dict:
        if mode == "live" and settings.TRADE_MODE != "live":
            return {
                "success": False,
                "message": "系统未开启实盘模式，请在.env中配置TRADE_MODE=live",
            }

        signal_id = request.signal_id or "manual"
        idempotency_key = f"{signal_id}:{request.stock_code}:{request.side}:{request.quantity}"

        existing = await self.db.execute(
            text(
                """
                SELECT id, status FROM trade.orders
                WHERE idempotency_key = :key AND mode = :mode
                """
            ),
            {"key": idempotency_key, "mode": mode},
        )
        row = existing.mappings().first()
        if row:
            return {
                "success": True,
                "order_id": str(row["id"]),
                "status": row["status"],
                "message": f"重复请求，返回已有订单 {row['id']}",
                "idempotent": True,
            }

        if await self.fuse.is_fused(mode):
            return {
                "success": False,
                "message": f"{mode}模式处于熔断状态，所有交易已暂停",
            }

        risk_report = await self.risk.check(
            {
                "stock_code": request.stock_code,
                "side": request.side,
                "quantity": request.quantity,
                "limit_price": request.limit_price,
                "signal_id": signal_id,
            },
            mode,
        )
        if not risk_report.passed:
            from app.ws.publisher import publish_alert

            await publish_alert(
                alert_type="risk_alert",
                level="WARNING",
                message=f"订单风控拦截: {', '.join(risk_report.blocked_by)}",
                detail={
                    "stock_code": request.stock_code,
                    "side": request.side,
                    "mode": mode,
                    "blocked_by": risk_report.blocked_by,
                },
            )
            return {
                "success": False,
                "message": f"风控拦截: {', '.join(risk_report.blocked_by)}",
                "risk_report": {
                    "blocked_by": risk_report.blocked_by,
                    "warnings": risk_report.warnings,
                    "checks": [
                        {
                            "rule_code": c.rule_code,
                            "passed": c.passed,
                            "severity": c.severity,
                            "message": c.message,
                        }
                        for c in risk_report.checks
                    ],
                },
            }

        trader = self.traders.get(mode)
        if not trader:
            return {"success": False, "message": f"不支持的交易模式: {mode}"}

        result = await trader.submit_order(request)
        success = result.status != "FAILED"
        if success:
            from app.ws.publisher import publish_portfolio_update

            await publish_portfolio_update(
                mode,
                {
                    "type": "order_update",
                    "order_id": result.order_id,
                    "stock_code": request.stock_code,
                    "side": request.side,
                    "status": result.status,
                    "filled_quantity": request.quantity,
                    "message": result.message,
                },
            )
        return {
            "success": success,
            "order_id": result.order_id,
            "status": result.status,
            "message": result.message,
            "warnings": risk_report.warnings,
        }