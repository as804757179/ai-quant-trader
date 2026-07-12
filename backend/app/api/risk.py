from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.logging import FEATURE_RISK, get_logger
from app.core.response import error, ok
from app.data.cache import CacheManager
from app.db import get_db
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.schemas.trade import OrderCreateRequest

logger = get_logger(__name__, feature=FEATURE_RISK)
router = APIRouter()


class FuseRecoverRequest(BaseModel):
    mode: str = Field(default="simulation")
    approved_by: str = Field(..., min_length=1)
    note: str = Field(default="")


class FuseActivateRequest(BaseModel):
    mode: str = Field(default="simulation")
    reason: str = Field(..., min_length=1)


@router.get("/rules")
async def list_risk_rules():
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                SELECT rule_code, rule_name, rule_type, is_hard, threshold,
                       action, is_enabled, description
                FROM risk.risk_rules
                WHERE is_enabled = TRUE
                ORDER BY id
                """
            )
        )
        items = [dict(r._mapping) for r in result.fetchall()]
    return ok({"items": items})


@router.get("/fuse-status")
async def get_fuse_status(mode: str = Query("simulation")):
    logger.info("risk_fuse_status_query", mode=mode)
    cache = CacheManager()
    async with get_db() as db:
        fuse = FuseManager(db, cache)
        is_active = await fuse.is_fused(mode)
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
        history = []
        for r in hist.mappings().all():
            item = dict(r)
            for k in ("triggered_at", "recovered_at"):
                if item.get(k):
                    item[k] = item[k].isoformat()
            history.append(item)
    return ok({"mode": mode, "is_active": is_active, "history": history})


@router.get("/exposure")
async def get_risk_exposure(mode: str = Query("simulation")):
    """仓位暴露与回撤快照。"""
    async with get_db() as db:
        monitor = RiskMonitor(db)
        snap = await monitor.get_portfolio_snapshot(mode)
    positions = []
    for code, pos in snap["positions"].items():
        mv = float(pos.get("market_value") or 0)
        ratio = mv / snap["total_assets"] if snap["total_assets"] else 0
        positions.append(
            {
                "stock_code": code,
                "name": pos.get("name"),
                "sector": pos.get("sector"),
                "market_value": mv,
                "ratio": round(ratio, 4),
                "total_qty": pos.get("total_qty"),
                "unrealized_pnl": float(pos.get("unrealized_pnl") or 0),
            }
        )
    positions.sort(key=lambda x: x["market_value"], reverse=True)
    return ok(
        {
            "mode": mode,
            "total_assets": snap["total_assets"],
            "cash": snap["cash"],
            "total_market_value": snap["total_market_value"],
            "position_ratio": (
                snap["total_market_value"] / snap["total_assets"]
                if snap["total_assets"]
                else 0
            ),
            "daily_pnl_pct": snap["daily_pnl_pct"],
            "drawdown_from_peak": snap["drawdown_from_peak"],
            "positions": positions,
        }
    )


@router.post("/fuse/activate")
async def activate_fuse(body: FuseActivateRequest):
    logger.warning(
        "risk_fuse_activate_request",
        mode=body.mode,
        reason=body.reason,
    )
    cache = CacheManager()
    async with get_db() as db:
        monitor = RiskMonitor(db)
        portfolio = await monitor.get_portfolio_snapshot(body.mode)
        fuse = FuseManager(db, cache)
        await fuse.activate(body.mode, body.reason, portfolio)
    logger.critical("risk_fuse_activated", mode=body.mode, reason=body.reason)
    return ok({"mode": body.mode, "is_active": True}, message="熔断已触发")


@router.post("/fuse/recover")
async def recover_fuse(body: FuseRecoverRequest):
    logger.warning(
        "risk_fuse_recover_request",
        mode=body.mode,
        approved_by=body.approved_by,
        note=body.note,
    )
    cache = CacheManager()
    async with get_db() as db:
        fuse = FuseManager(db, cache)
        if not await fuse.is_fused(body.mode):
            logger.info("risk_fuse_recover_noop", mode=body.mode)
            return ok({"mode": body.mode, "is_active": False}, message="当前未熔断")
        await fuse.recover(body.mode, body.approved_by, body.note)
    logger.info(
        "risk_fuse_recovered",
        mode=body.mode,
        approved_by=body.approved_by,
    )
    return ok({"mode": body.mode, "is_active": False}, message="熔断已解除")


@router.get("/alerts")
async def list_recent_alerts(
    limit: int = Query(50, ge=1, le=100),
    level: str | None = Query(None, description="INFO/WARNING/ERROR/CRITICAL"),
    alert_type: str | None = Query(None, description="告警类型过滤"),
):
    """最近告警（Redis 历史，进程重启后可能为空）。"""
    from app.ws.publisher import get_recent_alerts

    items = await get_recent_alerts(limit=limit, level=level, alert_type=alert_type)
    return ok({"items": items, "total": len(items), "level": level, "type": alert_type})


@router.get("/alerts/summary")
async def alerts_summary(limit: int = Query(100, ge=1, le=100)):
    """告警计数汇总（仪表盘用）。"""
    from app.ws.publisher import summarize_alerts

    return ok(await summarize_alerts(limit=limit))


@router.post("/pre-check")
async def pre_check_trade(request: OrderCreateRequest):
    """交易前风控检查（供 Worker run_signal_scan 调用）。"""
    logger.info(
        "risk_precheck_start",
        mode=request.mode,
        stock_code=request.stock_code,
        side=request.side,
        quantity=request.quantity,
    )
    if request.quantity % 100 != 0:
        error("买入数量必须是100的整数倍", "INVALID_QUANTITY")
    if request.order_type == "LIMIT" and request.limit_price is None:
        error("限价单必须提供limit_price", "MISSING_PRICE")

    async with get_db() as db:
        checker = PreTradeRiskChecker(db, RiskMonitor(db))
        report = await checker.check(
            {
                "stock_code": request.stock_code,
                "side": request.side,
                "quantity": request.quantity,
                "limit_price": request.limit_price,
                "signal_id": request.signal_id,
            },
            request.mode,
        )

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
    from app.ws.publisher import summarize_alerts

    cache = CacheManager()
    async with get_db() as db:
        monitor = RiskMonitor(db)
        snap = await monitor.get_portfolio_snapshot(mode)
        fuse = FuseManager(db, cache)
        is_fused = await fuse.is_fused(mode)

    alerts = await summarize_alerts(100)
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
                    if snap["total_assets"]
                    else 0
                ),
            },
            "fuse": {"is_active": is_fused},
            "alerts": alerts,
        }
    )