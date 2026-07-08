from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.core.response import error, ok
from app.data.cache import CacheManager
from app.db import get_db
from app.risk.checker import PreTradeRiskChecker
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.schemas.trade import OrderCreateRequest

router = APIRouter()


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
    cache = CacheManager()
    async with get_db() as db:
        fuse = FuseManager(db, cache)
        is_active = await fuse.is_fused(mode)
    return ok({"mode": mode, "is_active": is_active})


@router.post("/pre-check")
async def pre_check_trade(request: OrderCreateRequest):
    """交易前风控检查（供 Worker run_signal_scan 调用）。"""
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