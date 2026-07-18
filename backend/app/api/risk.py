from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.auth import get_request_principal
from app.core.logging import FEATURE_RISK, get_logger
from app.core.response import error, ok
from app.data.cache import CacheManager
from app.db import get_db
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.risk.alerts import list_persisted_risk_alerts, summarize_persisted_risk_alerts
from app.risk.rule_snapshot import load_persisted_risk_rule_snapshot
from app.schemas.trade import PreTradeCheckRequest
from app.trade.execution_authorization import (
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
)
from app.trade.preflight import OrderPreflight, build_dry_run_order_request

logger = get_logger(__name__, feature=FEATURE_RISK)
router = APIRouter()


class FuseRecoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
    fuse_record_id: int = Field(..., ge=1)
    execution_authorization_id: str = Field(..., min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class FuseActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
    reason: str = Field(..., min_length=1, max_length=200)


@router.get("/rules")
async def list_risk_rules():
    async with get_db() as db:
        snapshot = await load_persisted_risk_rule_snapshot(db)
    return ok(snapshot)


@router.get("/fuse-status")
async def get_fuse_status(mode: str = Query("simulation")):
    logger.info("risk_fuse_status_query", mode=mode)
    cache = CacheManager()
    async with get_db() as db:
        fuse = FuseManager(db, cache)
        state = await fuse.get_state(mode)
        history = []
        history_status = "unavailable" if state["reason"] == "db_unavailable" else "available"
        if history_status == "available":
            try:
                hist = await db.execute(
                    text(
                        """
                        SELECT id, mode, fuse_reason, triggered_at, is_active,
                               recovery_approved_by, recovered_at
                        FROM risk.fuse_records
                        WHERE mode = :mode
                        ORDER BY id DESC
                        LIMIT 5
                        """
                    ),
                    {"mode": mode},
                )
                for r in hist.mappings().all():
                    item = dict(r)
                    for k in ("triggered_at", "recovered_at"):
                        if item.get(k):
                            item[k] = item[k].isoformat()
                    history.append(item)
            except Exception as exc:
                history_status = "unavailable"
                logger.warning(
                    "risk_fuse_history_unavailable",
                    mode=mode,
                    error_type=type(exc).__name__,
                )
    return ok({**state, "history": history, "history_status": history_status})


@router.get("/exposure")
async def get_risk_exposure(mode: str = Query("simulation")):
    """仓位暴露与回撤快照。"""
    async with get_db() as db:
        monitor = RiskMonitor(db)
        snap = await monitor.get_portfolio_snapshot(mode)
    positions = []
    for code, pos in snap["positions"].items():
        market_value = pos.get("market_value")
        ratio = (
            market_value / snap["total_assets"]
            if market_value is not None
            and snap["total_assets"] is not None
            and snap["total_assets"] > 0
            else None
        )
        positions.append(
            {
                "stock_code": code,
                "name": pos.get("name"),
                "sector": pos.get("sector"),
                "current_price": pos.get("current_price"),
                "market_value": market_value,
                "ratio": round(ratio, 4) if ratio is not None else None,
                "total_qty": pos.get("total_qty"),
                "unrealized_pnl": pos.get("unrealized_pnl"),
                "valuation_status": pos.get("valuation_status"),
                "valuation_freshness": pos.get("valuation_freshness"),
                "valuation_as_of": pos.get("valuation_as_of"),
                "valuation_age_seconds": pos.get("valuation_age_seconds"),
                "valuation_source": pos.get("valuation_source"),
            }
        )
    positions.sort(
        key=lambda item: (
            item["market_value"] is None,
            -(item["market_value"] or 0),
        )
    )
    return ok(
        {
            "mode": mode,
            "total_assets": snap["total_assets"],
            "cash": snap["cash"],
            "total_market_value": snap["total_market_value"],
            "position_ratio": (
                snap["total_market_value"] / snap["total_assets"]
                if snap["total_market_value"] is not None
                and snap["total_assets"] is not None
                and snap["total_assets"] > 0
                else None
            ),
            "daily_pnl_pct": snap["daily_pnl_pct"],
            "drawdown_from_peak": snap["drawdown_from_peak"],
            "positions": positions,
            "account_snapshot_time": snap["account_snapshot_time"],
            "account_snapshot_age_seconds": snap["account_snapshot_age_seconds"],
            "account_snapshot_freshness": snap["account_snapshot_freshness"],
            "valuation_status": snap["valuation_status"],
            "valuation_stale": snap["valuation_stale"],
            "valuation_freshness": snap["valuation_freshness"],
            "valuation_as_of": snap["valuation_as_of"],
            "valuation_age_seconds": snap["valuation_age_seconds"],
            "valuation_unavailable_positions": snap[
                "valuation_unavailable_positions"
            ],
            "valuation_source": snap["valuation_source"],
            "source": snap["source"],
            "source_version": snap["source_version"],
        }
    )


@router.post("/fuse/activate")
async def activate_fuse(body: FuseActivateRequest, request: Request):
    principal = get_request_principal(request)
    logger.warning(
        "risk_fuse_activate_request",
        mode=body.mode,
        reason=body.reason,
        principal_id=principal.principal_id,
    )
    cache = CacheManager()
    async with get_db() as db:
        monitor = RiskMonitor(db)
        portfolio = await monitor.get_portfolio_snapshot(body.mode)
        fuse = FuseManager(db, cache)
        await fuse.activate(
            body.mode,
            body.reason,
            portfolio,
            activated_by=principal.principal_id,
        )
    logger.critical(
        "risk_fuse_activated",
        mode=body.mode,
        reason=body.reason,
        principal_id=principal.principal_id,
    )
    return ok({"mode": body.mode, "is_active": True}, message="熔断已触发")


@router.post("/fuse/recover")
async def recover_fuse(body: FuseRecoverRequest, request: Request):
    principal = get_request_principal(request)
    logger.warning(
        "risk_fuse_recover_request",
        mode=body.mode,
        fuse_record_id=body.fuse_record_id,
        principal_id=principal.principal_id,
    )
    cache = CacheManager()
    async with get_db() as db:
        fuse = FuseManager(db, cache)
        if not await fuse.is_fused(body.mode):
            logger.info("risk_fuse_recover_noop", mode=body.mode)
            return ok({"mode": body.mode, "is_active": False}, message="当前未熔断")
    try:
        async with get_db() as db:
            approval = await ExecutionAuthorizationService().consume_operation_approval(
                db,
                approval_id=body.execution_authorization_id,
                principal=principal,
                action_type="risk.fuse.recover",
                payload={
                    "mode": body.mode,
                    "fuse_record_id": body.fuse_record_id,
                    "note": body.note,
                },
            )
    except ExecutionAuthorizationError as exc:
        error(exc.message, exc.code, exc.status_code)

    approved_payload = approval["payload"]
    async with get_db() as db:
        fuse = FuseManager(db, cache)
        recovered = await fuse.recover(
            approved_payload["mode"],
            approved_payload["fuse_record_id"],
            approval["approver_principal_id"],
            approved_payload["note"],
        )
    if not recovered:
        error("熔断记录已变化，需重新发起审批", "FUSE_RECORD_CHANGED", 409)
    logger.info(
        "risk_fuse_recovered",
        mode=body.mode,
        fuse_record_id=body.fuse_record_id,
        approved_by=approval["approver_principal_id"],
    )
    return ok({"mode": body.mode, "is_active": False}, message="熔断已解除")


@router.get("/alerts")
async def list_recent_alerts(
    limit: int | None = Query(None, ge=1, le=100, description="兼容旧客户端"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    level: str | None = Query(None, description="INFO/WARNING/ERROR/CRITICAL"),
    alert_type: str | None = Query(None, description="告警类型过滤"),
):
    """持久化风险告警，按创建时间和 ID 稳定分页。"""
    effective_page_size = page_size or limit or 50
    async with get_db() as db:
        result = await list_persisted_risk_alerts(
            db,
            page=page,
            page_size=effective_page_size,
            level=level,
            alert_type=alert_type,
        )
    return ok(result)


@router.get("/alerts/summary")
async def alerts_summary(limit: int = Query(100, ge=1, le=100)):
    """持久化风险告警计数汇总（仪表盘用）。"""
    async with get_db() as db:
        result = await summarize_persisted_risk_alerts(db, limit=limit)
    return ok(result)


@router.post("/pre-check")
async def pre_check_trade(request: PreTradeCheckRequest):
    """交易前风控检查（供 Worker run_signal_scan 调用）。"""
    logger.info(
        "risk_precheck_start",
        mode=request.mode,
        stock_code=request.stock_code,
        side=request.side,
        quantity=request.quantity,
    )
    dry_run_order = build_dry_run_order_request(request.model_dump(), request.mode)
    input_result = OrderPreflight.check_input(dry_run_order)
    if not input_result.allowed:
        error(
            input_result.report.checks[0].message,
            input_result.reason or "ORDER_INPUT_REJECTED",
        )

    cache = CacheManager()
    async with get_db() as db:
        checker = PreTradeRiskChecker(db, RiskMonitor(db))
        preflight = OrderPreflight(checker, FuseManager(db, cache))
        result = await preflight.check(
            dry_run_order,
            request.mode,
            record_risk_events=False,
        )
        report = result.report

    logger.info(
        "risk_precheck_done",
        mode=request.mode,
        stock_code=request.stock_code,
        passed=report.passed,
        blocked_by=report.blocked_by,
        warnings=report.warnings,
    )
    return ok(
        {
            "passed": report.passed,
            "blocked_by": report.blocked_by,
            "warnings": report.warnings,
            "checks": [
                {
                    "rule_code": c.rule_code,
                    "passed": c.passed,
                    "severity": c.severity,
                    "message": c.message,
                }
                for c in report.checks
            ],
        }
    )


@router.post("/alerts/test-dingtalk")
async def test_dingtalk_notify(
    level: str = Query("CRITICAL"),
    message: str = Query("钉钉测试消息 from AI Quant Trader Pro"),
):
    """手动测试钉钉推送（受 DINGTALK_ALERT_LEVELS 过滤）。"""
    from app.core.config import settings
    from app.notify.dingtalk import notify_dingtalk

    logger.info("risk_dingtalk_test", level=level, message=message[:120])
    result = await notify_dingtalk(
        title="manual_test",
        text=message,
        level=level,
        cooldown_seconds=10,
    )
    logger.info("risk_dingtalk_test_result", **{k: result.get(k) for k in result})
    return ok(
        {
            **result,
            "enabled": settings.ENABLE_DINGTALK_NOTIFY,
            "levels": sorted(settings.dingtalk_levels()),
            "webhook_configured": bool(settings.DINGTALK_WEBHOOK),
        }
    )


@router.get("/dashboard")
async def risk_dashboard(mode: str = Query("simulation")):
    """仪表盘聚合：资产暴露 + 熔断 + 告警摘要。"""
    cache = CacheManager()
    async with get_db() as db:
        monitor = RiskMonitor(db)
        snap = await monitor.get_portfolio_snapshot(mode)
        fuse = FuseManager(db, cache)
        fuse_state = await fuse.get_state(mode)
        alerts = await summarize_persisted_risk_alerts(db, limit=100)
    return ok(
        {
            "mode": mode,
            "portfolio": {
                "total_assets": snap["total_assets"],
                "cash": snap["cash"],
                "market_value": snap["total_market_value"],
                "daily_pnl": snap["daily_pnl"],
                "daily_pnl_pct": snap["daily_pnl_pct"],
                "drawdown_from_peak": snap["drawdown_from_peak"],
                "position_count": len(snap["positions"]),
                "position_ratio": (
                    snap["total_market_value"] / snap["total_assets"]
                    if snap["total_market_value"] is not None
                    and snap["total_assets"] is not None
                    and snap["total_assets"] > 0
                    else None
                ),
                "account_snapshot_time": snap["account_snapshot_time"],
                "account_snapshot_age_seconds": snap["account_snapshot_age_seconds"],
                "account_snapshot_freshness": snap["account_snapshot_freshness"],
                "valuation_status": snap["valuation_status"],
                "valuation_stale": snap["valuation_stale"],
                "valuation_freshness": snap["valuation_freshness"],
                "valuation_as_of": snap["valuation_as_of"],
                "valuation_age_seconds": snap["valuation_age_seconds"],
                "valuation_unavailable_positions": snap[
                    "valuation_unavailable_positions"
                ],
                "valuation_source": snap["valuation_source"],
                "source": snap["source"],
                "source_version": snap["source_version"],
            },
            "fuse": fuse_state,
            "alerts": alerts,
        }
    )
