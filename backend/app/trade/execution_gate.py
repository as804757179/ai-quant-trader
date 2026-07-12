from __future__ import annotations

from dataclasses import dataclass
import os

from app.core.config import settings
from app.trade.base_trader import OrderRequest


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    reason: str | None = None


class ExecutionGate:
    """Central, fail-closed permission check before every order submission."""

    _MANUAL_SOURCES = {"manual_order", "manual_api"}
    _AI_SOURCES = {"ai", "ai_recommendation", "ai_signal"}
    _SCHEDULED_SOURCES = {"scheduled_order", "scheduled_rule"}

    def evaluate(self, request: OrderRequest, mode: str) -> ExecutionDecision:
        source = (request.trigger_source or "").strip().lower()
        if not source or source == "unknown":
            return ExecutionDecision(False, "UNKNOWN_CALLER")
        if source in self._AI_SOURCES:
            return ExecutionDecision(False, "AI_ORDER_DISABLED")
        if source in self._SCHEDULED_SOURCES:
            if not settings.ALLOW_SCHEDULED_ORDER:
                return ExecutionDecision(False, "SCHEDULED_ORDER_DISABLED")
            if settings.AI_ORDER_ENABLED:
                return ExecutionDecision(False, "AI_ORDER_DISABLED")
            if settings.REQUIRE_HUMAN_APPROVAL:
                return ExecutionDecision(False, "HUMAN_APPROVAL_REQUIRED")
        if source not in self._MANUAL_SOURCES | self._SCHEDULED_SOURCES:
            return ExecutionDecision(False, "UNKNOWN_CALLER")
        if not settings.TRADING_EXECUTION_ENABLED:
            return ExecutionDecision(False, "TRADING_EXECUTION_DISABLED")
        if mode == "paper" and not settings.PAPER_TRADING_ENABLED:
            return ExecutionDecision(False, "PAPER_TRADING_DISABLED")
        if mode == "live" and not settings.LIVE_TRADING_ENABLED:
            return ExecutionDecision(False, "LIVE_TRADING_DISABLED")
        if mode == "live" and os.getenv("QMT_FORCE_MOCK", "").lower() in {"1", "true", "yes"}:
            return ExecutionDecision(False, "LIVE_TRADING_DISABLED")
        if request.data_certification_status in {"unknown", "uncertified", "synthetic"}:
            return ExecutionDecision(False, "UNCERTIFIED_DATASET")
        if settings.REQUIRE_HUMAN_APPROVAL and not request.approval_id:
            return ExecutionDecision(False, "HUMAN_APPROVAL_REQUIRED")
        return ExecutionDecision(True)
