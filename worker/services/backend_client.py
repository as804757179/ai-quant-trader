from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import structlog

logger = structlog.get_logger(__name__)

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000")
SIGNAL_MIN_CONFIDENCE = float(os.getenv("SIGNAL_MIN_CONFIDENCE", "0.65"))
WORKER_API_CREDENTIAL_ENV = "WORKER_API_CREDENTIAL"
_WORKER_API_CREDENTIAL_MIN_LENGTH = 32
_WORKER_API_CREDENTIAL_FORBIDDEN_MARKERS = ("replace-with-", "changeme", "change_me", "123456", "test")


def _worker_api_credential_configured(credential: str) -> bool:
    normalized = credential.strip().lower()
    return (
        len(credential) >= _WORKER_API_CREDENTIAL_MIN_LENGTH
        and not any(marker in normalized for marker in _WORKER_API_CREDENTIAL_FORBIDDEN_MARKERS)
    )


def worker_api_headers() -> dict[str, str]:
    credential = os.getenv(WORKER_API_CREDENTIAL_ENV, "").strip()
    if not credential:
        raise RuntimeError("worker_api_credential_missing")
    if not _worker_api_credential_configured(credential):
        raise RuntimeError("worker_api_credential_invalid")
    return {"Authorization": f"Bearer {credential}"}


@dataclass
class RiskCheckResult:
    passed: bool
    blocked_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class AIAnalyzer(Protocol):
    async def analyze(
        self,
        code: str,
        *,
        force_refresh: bool = False,
        strategy_id: int | None = None,
    ) -> dict[str, Any]: ...


class RiskChecker(Protocol):
    async def check_before_trade(self, order_request: dict, mode: str) -> RiskCheckResult: ...


class TradeSubmitter(Protocol):
    async def submit_order(self, order_payload: dict) -> dict[str, Any]: ...


class HttpBackendClient(AIAnalyzer, RiskChecker, TradeSubmitter):
    """通过 Backend API 调用 AIService / 风控 / 交易。"""

    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or API_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def analyze(
        self,
        code: str,
        *,
        force_refresh: bool = False,
        strategy_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"force_refresh": force_refresh}
        if strategy_id is not None and strategy_id > 0:
            params["strategy_id"] = strategy_id

        response = await self._client.post(
            f"/api/v1/ai/{code}/analyze",
            params=params,
            headers=worker_api_headers(),
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise RuntimeError(body.get("message", "AI analyze failed"))
        return body["data"]

    async def check_before_trade(self, order_request: dict, mode: str) -> RiskCheckResult:
        payload = {
            "stock_code": order_request["stock_code"],
            "side": order_request["side"],
            "order_type": order_request.get("order_type", "LIMIT"),
            "quantity": order_request["quantity"],
            "limit_price": order_request.get("limit_price"),
            "signal_id": order_request.get("signal_id"),
            "mode": mode,
        }
        response = await self._client.post(
            "/api/v1/risk/pre-check",
            json=payload,
            headers=worker_api_headers(),
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise RuntimeError(body.get("message", "Risk pre-check failed"))
        data = body["data"]
        return RiskCheckResult(
            passed=bool(data.get("passed")),
            blocked_by=list(data.get("blocked_by") or []),
            warnings=list(data.get("warnings") or []),
        )

    async def submit_order(self, order_payload: dict) -> dict[str, Any]:
        raise RuntimeError("worker_order_submission_disabled: worker cannot submit orders")


class DirectBackendClient(AIAnalyzer, RiskChecker, TradeSubmitter):
    """Docker 内直接导入 backend 模块（需 PYTHONPATH 含 /backend）。"""

    async def close(self) -> None:
        pass

    async def analyze(
        self,
        code: str,
        *,
        force_refresh: bool = False,
        strategy_id: int | None = None,
    ) -> dict[str, Any]:
        from app.services.ai_service import AIService

        svc = AIService()
        try:
            result = await svc.analyze(
                code,
                force_refresh=force_refresh,
                strategy_id=strategy_id if strategy_id and strategy_id > 0 else None,
            )
            return result.model_dump()
        finally:
            await svc.close()

    async def check_before_trade(self, order_request: dict, mode: str) -> RiskCheckResult:
        from app.data.cache import CacheManager
        from app.db import get_db
        from app.risk.checker import PreTradeRiskChecker
        from app.risk.fuse import FuseManager
        from app.risk.monitor import RiskMonitor
        from app.trade.preflight import OrderPreflight, build_dry_run_order_request

        async with get_db() as db:
            checker = PreTradeRiskChecker(db, RiskMonitor(db))
            preflight = OrderPreflight(checker, FuseManager(db, CacheManager()))
            result = await preflight.check(
                build_dry_run_order_request(order_request, mode),
                mode,
                record_risk_events=False,
            )
            report = result.report
        return RiskCheckResult(
            passed=report.passed,
            blocked_by=list(report.blocked_by),
            warnings=list(report.warnings),
        )

    async def submit_order(self, order_payload: dict) -> dict[str, Any]:
        raise RuntimeError("worker_order_submission_disabled: worker cannot submit orders")


def create_backend_client() -> HttpBackendClient | DirectBackendClient:
    """按环境选择 HTTP 或直接导入 backend。"""
    mode = os.getenv("WORKER_BACKEND_MODE", "http").lower()
    if mode == "direct":
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise RuntimeError("worker_direct_backend_mode_forbidden_in_production")
        return DirectBackendClient()
    if mode != "http":
        raise RuntimeError("worker_backend_mode_invalid")
    worker_api_headers()
    return HttpBackendClient()
