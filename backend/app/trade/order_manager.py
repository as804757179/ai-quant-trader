from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import FEATURE_TRADE, get_logger
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.trade.base_trader import OrderRequest
from app.trade.execution_authorization import (
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
)
from app.trade.execution_gate import ExecutionGate
from app.trade.idempotency import build_idempotency_key
from app.trade.preflight import OrderPreflight

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
        self.preflight = OrderPreflight(risk_checker, fuse_manager, self.execution_gate)
        self.execution_authorization = ExecutionAuthorizationService()

    async def _reject_intent(
        self,
        request: OrderRequest,
        *,
        error_code: str,
        message: str,
        status_code: int = 403,
        **extra: object,
    ) -> dict:
        if request.intent_id:
            try:
                await self.execution_authorization.mark_intent(
                    self.db, request.intent_id, "rejected"
                )
            except Exception:
                return {
                    "success": False,
                    "error_code": "EXECUTION_AUDIT_UNAVAILABLE",
                    "message": "订单拒绝审计无法持久化，禁止继续执行",
                    "status_code": 503,
                }
        return {
            "success": False,
            "error_code": error_code,
            "message": message,
            "status_code": status_code,
            **extra,
        }

    async def _find_by_idempotency(self, key: str, mode: str) -> dict | None:
        existing = await self.db.execute(
            text(
                """
                SELECT id, status, filled_quantity FROM trade.orders
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
            "filled_quantity": int(row["filled_quantity"] or 0),
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
        input_result = self.preflight.check_input(request)
        if not input_result.allowed:
            logger.warning(
                "trade_order_input_rejected",
                mode=mode,
                stock_code=request.stock_code,
                rejection_reason=input_result.reason,
            )
            return {
                "success": False,
                "error_code": "ORDER_INPUT_REJECTED",
                "status_code": 422,
                "rejection_reason": input_result.reason,
                "message": f"订单输入校验失败: {input_result.reason}",
            }
        if not request.principal or not request.principal_id or not request.client_intent_key:
            return {
                "success": False,
                "error_code": "EXECUTION_PRINCIPAL_REQUIRED",
                "message": "订单必须绑定已认证主体和客户端意图键",
                "status_code": 401,
            }
        authorization_payload = {
            "stock_code": request.stock_code,
            "side": request.side,
            "order_type": request.order_type,
            "quantity": request.quantity,
            "limit_price": request.limit_price,
            "signal_id": request.signal_id,
            "mode": mode,
            "order_reason": request.order_reason,
        }
        try:
            intent_id, idempotent, intent_status = (
                await self.execution_authorization.create_order_intent(
                    self.db,
                    principal=request.principal,
                    client_intent_key=request.client_intent_key,
                    payload=authorization_payload,
                )
            )
        except ExecutionAuthorizationError as exc:
            return {
                "success": False,
                "error_code": exc.code,
                "message": exc.message,
                "status_code": exc.status_code,
            }
        except Exception:
            return {
                "success": False,
                "error_code": "EXECUTION_INTENT_UNAVAILABLE",
                "message": "订单意图无法持久化，禁止继续执行",
                "status_code": 503,
            }
        request.intent_id = intent_id
        if idempotent:
            return {
                "success": True,
                "idempotent": True,
                "intent_id": intent_id,
                "status": intent_status,
                "message": "重复意图键，返回已有订单意图状态",
            }
        decision = self.preflight.check_execution_gate(request, mode)
        if not decision.allowed:
            logger.warning(
                "trade_order_execution_gate_rejected",
                mode=mode,
                stock_code=request.stock_code,
                rejection_reason=decision.reason,
                caller=request.caller,
            )
            await self.execution_authorization.mark_intent(
                self.db, request.intent_id, "rejected"
            )
            return {
                "success": False,
                "error_code": "ORDER_REJECTED_BY_EXECUTION_GATE",
                "status_code": 403,
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
            await self.execution_authorization.mark_intent(
                self.db, request.intent_id, "rejected"
            )
            guard["status_code"] = 403
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
            principal_id=request.principal_id,
            client_intent_key=request.client_intent_key,
            intent_id=request.intent_id,
        )
        request.idempotency_key = idempotency_key

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

        fuse_result = await self.preflight.check_fuse(mode)
        if not fuse_result.allowed:
            logger.warning(
                "trade_order_fuse_blocked",
                mode=mode,
                stock_code=request.stock_code,
                side=request.side,
            )
            await self.execution_authorization.mark_intent(
                self.db, request.intent_id, "rejected"
            )
            return {
                "success": False,
                "error_code": "FUSE_BLOCKED",
                "status_code": 503,
                "message": f"{mode}模式处于熔断状态，所有交易已暂停",
            }

        risk_result = await self.preflight.check_risk(
            request,
            mode,
            record_risk_events=True,
        )
        risk_report = risk_result.report
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
            await self.execution_authorization.mark_intent(
                self.db, request.intent_id, "rejected"
            )
            return {
                "success": False,
                "error_code": "RISK_CHECK_REJECTED",
                "status_code": 403,
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

        try:
            await self.execution_authorization.consume_order_approval(
                self.db,
                approval_id=request.approval_id,
                principal=request.principal,
                payload=authorization_payload,
                intent_id=request.intent_id,
            )
        except ExecutionAuthorizationError as exc:
            return await self._reject_intent(
                request,
                error_code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
            )
        except Exception:
            return await self._reject_intent(
                request,
                error_code="EXECUTION_AUTHORIZATION_UNAVAILABLE",
                message="执行审批无法验证，禁止继续执行",
                status_code=503,
            )

        outbox_id: str | None = None
        if mode in {"paper", "live"}:
            try:
                outbox_id = await self.execution_authorization.prepare_broker_outbox(
                    self.db, intent_id=request.intent_id, payload=authorization_payload
                )
                await self.db.commit()
            except Exception:
                return await self._reject_intent(
                    request,
                    error_code="BROKER_OUTBOX_UNAVAILABLE",
                    message="券商调用前的订单意图无法持久化，禁止继续执行",
                    status_code=503,
                )

        trader = self.traders.get(mode)
        if not trader:
            logger.error("trade_order_unsupported_mode", mode=mode)
            await self.execution_authorization.mark_intent(
                self.db, request.intent_id, "rejected"
            )
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
        if outbox_id:
            await self.execution_authorization.mark_outbox(
                self.db,
                outbox_id=outbox_id,
                status="sent" if success else "uncertain",
                response_payload={
                    "order_id": result.order_id,
                    "broker_order_id": getattr(result, "broker_order_id", None),
                    "status": result.status,
                    "filled_quantity": result.filled_quantity,
                },
            )
        await self.execution_authorization.mark_intent(
            self.db,
            request.intent_id,
            "submitted" if success else ("uncertain" if outbox_id else "rejected"),
        )
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
                    "filled_quantity": result.filled_quantity,
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
            "filled_quantity": result.filled_quantity,
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
        current_status = order["status"]
        if ok:
            latest = await self.db.execute(
                text("SELECT status FROM trade.orders WHERE id = :id"),
                {"id": order_id},
            )
            latest_row = latest.mappings().first()
            if latest_row:
                current_status = latest_row["status"]
        cancel_effective = current_status == "CANCELLED"
        cancel_pending = bool(
            ok and current_status in ("PENDING", "SUBMITTED", "PARTIAL")
        )
        logger.info(
            "trade_order_cancel_done",
            order_id=order_id,
            mode=mode,
            success=ok,
            status=current_status,
            cancel_effective=cancel_effective,
            cancel_pending=cancel_pending,
        )
        return {
            "success": ok,
            "order_id": order_id,
            "status": current_status,
            "cancel_effective": cancel_effective,
            "cancel_pending": cancel_pending,
            "message": (
                "撤单成功"
                if cancel_effective
                else "撤单请求已提交，等待券商确认"
                if cancel_pending
                else f"撤单请求未生效，订单当前状态 {current_status}"
                if ok
                else "撤单失败（可能已成交或券商拒绝）"
            ),
        }
