from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import FEATURE_TRADE, get_logger
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.trade.base_trader import OrderRequest
from app.trade.execution_gate import ExecutionGate
from app.trade.idempotency import build_idempotency_key

logger = get_logger(__name__, feature=FEATURE_TRADE)


class OrderManager:
    def __init__(
        self,
        db: AsyncSession,
        risk_checker: PreTradeRiskChecker,
        fuse_manager: FuseManager,
        traders: dict,
        execution_gate: ExecutionGate | None = None,
    ) -> None:
        self.db = db
        self.risk = risk_checker
        self.fuse = fuse_manager
        self.traders = traders
        self.execution_gate = execution_gate or ExecutionGate()

    async def _find_by_idempotency(self, key: str, mode: str) -> dict | None:
        existing = await self.db.execute(
            text(
                """
                SELECT id, status FROM trade.orders
                WHERE idempotency_key = :key AND mode = :mode
                """
            ),
            {"key": key, "mode": mode},
        )
        row = existing.mappings().first()
        if not row:
            return None
        return {
            "success": True,
            "order_id": str(row["id"]),
            "status": row["status"],
            "message": f"重复请求，返回已有订单 {row['id']}",
            "idempotent": True,
        }

    def _check_live_guards(
        self, request: OrderRequest, mode: str, live_confirm: str | None
    ) -> dict | None:
        """实盘安全闸：系统开关、二次确认、单笔金额。"""
        if mode != "live":
            return None

        if settings.TRADE_MODE != "live":
            return {
                "success": False,
                "message": "系统未开启实盘模式，请在.env中配置TRADE_MODE=live",
                "error_code": "LIVE_DISABLED",
            }

        token = (settings.LIVE_CONFIRM_TOKEN or "").strip()
        if not token:
            return {
                "success": False,
                "message": "未配置 LIVE_CONFIRM_TOKEN，拒绝实盘下单",
                "error_code": "LIVE_CONFIRM_NOT_CONFIGURED",
            }
        if not live_confirm or live_confirm != token:
            return {
                "success": False,
                "message": "实盘二次确认失败：请提供正确的 live_confirm",
                "error_code": "LIVE_CONFIRM_REQUIRED",
            }

        max_val = float(getattr(settings, "LIVE_MAX_ORDER_VALUE", 0) or 0)
        if max_val > 0 and request.limit_price and request.quantity:
            order_value = float(request.limit_price) * int(request.quantity)
            if order_value > max_val:
                return {
                    "success": False,
                    "message": f"单笔金额¥{order_value:.2f}超过实盘上限¥{max_val:.2f}",
                    "error_code": "LIVE_ORDER_VALUE_EXCEEDED",
                }
        return None

    async def create_order(
        self,
        request: OrderRequest,
        mode: str,
        *,
        live_confirm: str | None = None,
    ) -> dict:
        logger.info(
            "trade_order_submit_start",
            mode=mode,
            stock_code=request.stock_code,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            limit_price=request.limit_price,
            signal_id=request.signal_id or "manual",
            trigger_source=getattr(request, "trigger_source", None),
        )
        decision = self.execution_gate.evaluate(request, mode)
        if not decision.allowed:
            logger.warning(
                "trade_order_execution_gate_rejected",
                mode=mode,
                stock_code=request.stock_code,
                rejection_reason=decision.reason,
                caller=request.caller,
            )
            return {
                "success": False,
                "error_code": "ORDER_REJECTED_BY_EXECUTION_GATE",
                "rejection_reason": decision.reason,
                "message": f"订单被执行安全闸拒绝: {decision.reason}",
            }

        guard = self._check_live_guards(request, mode, live_confirm)
        if guard:
            logger.warning(
                "trade_order_live_guard_rejected",
                mode=mode,
                stock_code=request.stock_code,
                error_code=guard.get("error_code"),
                message=guard.get("message"),
            )
            return guard

        signal_id = request.signal_id or "manual"
        idempotency_key = build_idempotency_key(
            mode=mode,
            signal_id=signal_id,
            stock_code=request.stock_code,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )

        hit = await self._find_by_idempotency(idempotency_key, mode)
        if hit:
            logger.info(
                "trade_order_idempotent_hit",
                mode=mode,
                order_id=hit.get("order_id"),
                status=hit.get("status"),
                stock_code=request.stock_code,
            )
            return hit

        if await self.fuse.is_fused(mode):
            logger.warning(
                "trade_order_fuse_blocked",
                mode=mode,
                stock_code=request.stock_code,
                side=request.side,
            )
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

            logger.warning(
                "trade_order_risk_blocked",
                mode=mode,
                stock_code=request.stock_code,
                side=request.side,
                blocked_by=risk_report.blocked_by,
                warnings=risk_report.warnings,
            )
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

        request.risk_check_id = getattr(risk_report, "check_id", None) or "pretrade_risk_check"

        trader = self.traders.get(mode)
        if not trader:
            logger.error("trade_order_unsupported_mode", mode=mode)
            return {"success": False, "message": f"不支持的交易模式: {mode}"}

        try:
            result = await trader.submit_order(request)
        except IntegrityError:
            await self.db.rollback()
            hit = await self._find_by_idempotency(idempotency_key, mode)
            if hit:
                logger.info(
                    "trade_order_idempotent_after_conflict",
                    mode=mode,
                    order_id=hit.get("order_id"),
                )
                return hit
            logger.error(
                "trade_order_integrity_conflict",
                mode=mode,
                stock_code=request.stock_code,
            )
            return {
                "success": False,
                "message": "订单写入冲突，请重试",
                "idempotent": False,
            }

        success = result.status != "FAILED"
        try:
            from app.monitoring.metrics import record_order

            record_order(mode, result.status)
        except Exception:
            pass
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
        logger.info(
            "trade_order_submit_done",
            mode=mode,
            success=success,
            order_id=result.order_id,
            status=result.status,
            stock_code=request.stock_code,
            side=request.side,
            message=result.message,
            broker_order_id=getattr(result, "broker_order_id", None),
        )
        return {
            "success": success,
            "order_id": result.order_id,
            "status": result.status,
            "message": result.message,
            "broker_order_id": getattr(result, "broker_order_id", None),
            "warnings": risk_report.warnings,
        }

    async def cancel_order(self, order_id: str, mode: str) -> dict:
        # 熔断时仍允许撤单，便于减仓/取消挂单
        logger.info("trade_order_cancel_start", order_id=order_id, mode=mode)
        trader = self.traders.get(mode)
        if not trader:
            return {"success": False, "message": f"不支持的交易模式: {mode}"}

        # 校验订单归属 mode
        row = await self.db.execute(
            text("SELECT id, status, mode FROM trade.orders WHERE id = :id"),
            {"id": order_id},
        )
        order = row.mappings().first()
        if not order:
            logger.warning("trade_order_cancel_not_found", order_id=order_id, mode=mode)
            return {"success": False, "message": "订单不存在"}
        if order["mode"] != mode:
            logger.warning(
                "trade_order_cancel_mode_mismatch",
                order_id=order_id,
                mode=mode,
                order_mode=order["mode"],
            )
            return {"success": False, "message": "订单模式不匹配"}
        if order["status"] in ("FILLED", "CANCELLED", "FAILED"):
            logger.info(
                "trade_order_cancel_invalid_status",
                order_id=order_id,
                status=order["status"],
            )
            return {
                "success": False,
                "message": f"订单状态 {order['status']} 不可撤",
            }

        ok = await trader.cancel_order(order_id)
        logger.info(
            "trade_order_cancel_done",
            order_id=order_id,
            mode=mode,
            success=ok,
        )
        return {
            "success": ok,
            "order_id": order_id,
            "message": "撤单成功" if ok else "撤单失败（可能已成交或券商拒绝）",
        }
