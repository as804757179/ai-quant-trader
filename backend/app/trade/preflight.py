from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from app.core.logging import FEATURE_TRADE, get_logger
from app.risk.checker import CheckResult, PreTradeRiskChecker, RiskCheckReport
from app.risk.fuse import FuseManager
from app.trade.base_trader import OrderRequest
from app.trade.execution_gate import ExecutionGate

logger = get_logger(__name__, feature=FEATURE_TRADE)


@dataclass(frozen=True)
class OrderPreflightResult:
    stage: str
    report: RiskCheckReport

    @property
    def allowed(self) -> bool:
        return self.report.passed

    @property
    def reason(self) -> str | None:
        return self.report.blocked_by[0] if self.report.blocked_by else None


class OrderPreflight:
    """Run the shared, non-mutating checks before an order can proceed."""

    def __init__(
        self,
        risk_checker: PreTradeRiskChecker,
        fuse_manager: FuseManager,
        execution_gate: ExecutionGate | None = None,
    ) -> None:
        self.risk = risk_checker
        self.fuse = fuse_manager
        self.execution_gate = execution_gate or ExecutionGate()

    def check_execution_gate(self, request: OrderRequest, mode: str) -> OrderPreflightResult:
        try:
            decision = self.execution_gate.evaluate(request, mode)
        except Exception as exc:
            logger.warning(
                "trade_preflight_execution_gate_unavailable",
                mode=mode,
                stock_code=request.stock_code,
                error_type=type(exc).__name__,
            )
            return self._blocked(
                "execution_gate",
                "EXECUTION_GATE_UNAVAILABLE",
                "执行门禁状态不可验证，禁止继续执行",
            )
        if not decision.allowed:
            reason = decision.reason or "EXECUTION_GATE_REJECTED"
            return self._blocked(
                "execution_gate",
                reason,
                f"订单被执行安全门禁拒绝: {reason}",
            )
        return OrderPreflightResult("execution_gate", RiskCheckReport(passed=True))

    @staticmethod
    def check_input(request: OrderRequest) -> OrderPreflightResult:
        if request.side not in {"BUY", "SELL"}:
            return OrderPreflight._blocked(
                "input", "INVALID_SIDE", "订单方向必须是 BUY 或 SELL",
            )
        if request.order_type not in {"MARKET", "LIMIT"}:
            return OrderPreflight._blocked(
                "input", "INVALID_ORDER_TYPE", "订单类型必须是 MARKET 或 LIMIT",
            )
        if (
            isinstance(request.quantity, bool)
            or not isinstance(request.quantity, int)
            or request.quantity <= 0
        ):
            return OrderPreflight._blocked(
                "input", "INVALID_QUANTITY", "订单数量必须是正整数",
            )
        if request.side == "BUY":
            code = str(request.stock_code).zfill(6)
            if code.startswith("688") and request.quantity < 200:
                return OrderPreflight._blocked(
                    "input", "INVALID_QUANTITY", "科创板买入不少于 200 股",
                )
            if not code.startswith("688") and request.quantity % 100 != 0:
                return OrderPreflight._blocked(
                    "input", "INVALID_QUANTITY", "买入数量必须是 100 的整数倍",
                )
        if request.order_type == "LIMIT":
            if request.limit_price is None:
                return OrderPreflight._blocked(
                    "input", "MISSING_PRICE", "限价单必须提供 limit_price",
                )
            try:
                limit_price = float(request.limit_price)
            except (TypeError, ValueError):
                return OrderPreflight._blocked(
                    "input", "INVALID_PRICE", "限价必须是有限正数",
                )
            if (
                isinstance(request.limit_price, bool)
                or not math.isfinite(limit_price)
                or limit_price <= 0
            ):
                return OrderPreflight._blocked(
                    "input", "INVALID_PRICE", "限价必须是有限正数",
                )
        return OrderPreflightResult("input", RiskCheckReport(passed=True))

    async def check_fuse(self, mode: str) -> OrderPreflightResult:
        try:
            fused = await self.fuse.is_fused(mode)
        except Exception as exc:
            logger.warning(
                "trade_preflight_fuse_unavailable",
                mode=mode,
                error_type=type(exc).__name__,
            )
            return self._blocked(
                "fuse",
                "FUSE_STATE_UNAVAILABLE",
                "熔断状态不可验证，禁止继续执行",
            )
        if fused:
            return self._blocked(
                "fuse",
                "FUSE_BLOCKED",
                f"{mode} 模式处于熔断或熔断状态不可验证，禁止继续执行",
            )
        return OrderPreflightResult("fuse", RiskCheckReport(passed=True))

    async def check_risk(
        self,
        request: OrderRequest,
        mode: str,
        *,
        record_risk_events: bool,
    ) -> OrderPreflightResult:
        try:
            report = await self.risk.check(
                {
                    "stock_code": request.stock_code,
                    "side": request.side,
                    "quantity": request.quantity,
                    "limit_price": request.limit_price,
                    "signal_id": request.signal_id or "manual",
                },
                mode,
                record_events=record_risk_events,
            )
        except Exception as exc:
            logger.warning(
                "trade_preflight_risk_state_unavailable",
                mode=mode,
                stock_code=request.stock_code,
                error_type=type(exc).__name__,
            )
            return self._blocked(
                "risk",
                "RISK_STATE_UNAVAILABLE",
                "风控数据或状态不可验证，禁止继续执行",
            )
        return OrderPreflightResult("risk", report)

    async def check(
        self,
        request: OrderRequest,
        mode: str,
        *,
        record_risk_events: bool,
    ) -> OrderPreflightResult:
        input_result = self.check_input(request)
        if not input_result.allowed:
            return input_result

        gate = self.check_execution_gate(request, mode)
        if not gate.report.passed:
            return gate

        fuse = await self.check_fuse(mode)
        if not fuse.report.passed:
            return fuse

        return await self.check_risk(
            request,
            mode,
            record_risk_events=record_risk_events,
        )

    @staticmethod
    def _blocked(stage: str, code: str, message: str) -> OrderPreflightResult:
        return OrderPreflightResult(
            stage,
            RiskCheckReport(
                passed=False,
                blocked_by=[code],
                checks=[
                    CheckResult(
                        rule_code=code,
                        passed=False,
                        severity="BLOCK",
                        message=message,
                        actual_value=0,
                        threshold=0,
                    )
                ],
            ),
        )


def build_dry_run_order_request(
    order_request: Mapping[str, Any], mode: str
) -> OrderRequest:
    """Build an intentionally untrusted request for a non-executing pre-check."""
    return OrderRequest(
        stock_code=str(order_request.get("stock_code") or "").zfill(6),
        side=str(order_request.get("side") or "").upper(),
        order_type=str(order_request.get("order_type", "LIMIT")).upper(),
        quantity=order_request.get("quantity"),  # type: ignore[arg-type]
        limit_price=order_request.get("limit_price"),
        signal_id=order_request.get("signal_id"),
        trigger_source="manual_order",
        caller="risk_precheck",
        data_certification_status="unknown",
    )
