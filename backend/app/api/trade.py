from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text

from app.core.auth import Principal, get_request_principal
from app.core.config import settings
from app.core.response import error, ok
from app.schemas.trade import (
    ExecutionApprovalRequest,
    OperationApprovalRequest,
    OrderCancelRequest,
    OrderCreateRequest,
)
from app.services.trade_service import TradeService
from app.db import get_db
from app.jobs.dispatch import OperationJobDispatchError
from app.jobs.operations import OperationJobService
from app.jobs.service import AsyncJobError
from app.risk.rule_snapshot import load_persisted_risk_rule_snapshot
from app.trade.execution_authorization import (
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    EXECUTION_REFERENCE_PROFILE,
    EXECUTION_REFERENCE_SCOPE,
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
)

router = APIRouter()


_RELEASE_LOCKS = (
    ("CERTIFIED_BACKTEST_EXECUTION_ENABLED", "可信回测发布", "未开放公共回测执行"),
    ("CERTIFIED_SCREENER_OUTPUT_ENABLED", "真实选股输出", "未开放候选发布"),
    ("TRADING_EXECUTION_ENABLED", "交易执行", "执行门禁关闭"),
    ("LIVE_TRADING_ENABLED", "实盘交易", "Live 安全锁关闭"),
    ("AI_ORDER_ENABLED", "AI 下单", "AI 仅可分析和推荐"),
    ("ALLOW_SCHEDULED_ORDER", "定时任务下单", "定时任务不得自动产生订单"),
)
_EXECUTION_STATUS_SOURCE_VERSION = "execution-safety-v4"
_EXECUTION_STATUS_SNAPSHOT_VERSION = "execution-safety-snapshot-v1"


def build_execution_status() -> dict:
    release_locks = [
        {
            "key": key,
            "label": label,
            "enabled": bool(getattr(settings, key)),
            "reason": "已由当前环境显式开启" if getattr(settings, key) else reason,
        }
        for key, label, reason in _RELEASE_LOCKS
    ]
    return {
        "mode": settings.TRADE_MODE,
        "release_locks": release_locks,
        "all_release_locks_closed": not any(item["enabled"] for item in release_locks),
        "paper_trading_enabled": settings.PAPER_TRADING_ENABLED,
        "require_human_approval": settings.REQUIRE_HUMAN_APPROVAL,
        "ai_direct_order_allowed": False,
        "source_version": _EXECUTION_STATUS_SOURCE_VERSION,
    }


def _serialize_execution_identity(principal: Principal) -> dict:
    return {
        "authenticated": not principal.is_anonymous,
        "principal_type": principal.principal_type,
        "role": principal.role,
        "scopes": sorted(principal.scopes),
    }


def _serialize_timestamp(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def get_trade_service() -> TradeService:
    return TradeService()


@router.post("/order")
async def create_order(
    request: OrderCreateRequest,
    http_request: Request,
    svc: TradeService = Depends(get_trade_service),
):
    code = str(request.stock_code).zfill(6)
    # 科创板买入 ≥200 且可为 1 股递增；其它板买入须 100 整数倍（卖出零股由撮合层校验）
    if request.side == "BUY":
        if code.startswith("688"):
            if request.quantity < 200:
                error("科创板买入不少于 200 股", "INVALID_QUANTITY")
        elif request.quantity % 100 != 0:
            error("买入数量必须是 100 的整数倍（1 手）", "INVALID_QUANTITY")
    elif request.quantity % 100 != 0 and request.quantity > 0:
        # 卖出非整手：允许（清仓零股），撮合层再校验可卖
        pass
    if request.order_type == "LIMIT":
        if request.limit_price is None:
            error("限价单必须提供 limit_price", "MISSING_PRICE")
        else:
            # 统一到分，避免浮点导致「最小变动单位」误拒
            request.limit_price = round(float(request.limit_price) + 1e-8, 2)

    result = await svc.create_manual_order(
        request.model_dump(), get_request_principal(http_request)
    )
    if not result.get("success"):
        error(
            result.get("message", "订单被拒绝"),
            result.get("error_code", "ORDER_REJECTED"),
            int(result.get("status_code", 403)),
        )
    return ok(result)


@router.post("/approvals")
async def request_execution_approval(
    body: ExecutionApprovalRequest | OperationApprovalRequest,
    request: Request,
):
    principal = get_request_principal(request)
    service = ExecutionAuthorizationService()
    try:
        async with get_db() as db:
            if isinstance(body, OperationApprovalRequest):
                result = await service.request_operation_approval(
                    db,
                    principal=principal,
                    action_type=body.action_type,
                    payload=body.payload,
                    expires_in_seconds=body.expires_in_seconds,
                )
            else:
                payload = body.model_dump(exclude={"data_authorization_ref", "expires_in_seconds"})
                result = await service.request_order_approval(
                    db,
                    principal=principal,
                    payload=payload,
                    data_authorization_ref=body.data_authorization_ref,
                    expires_in_seconds=body.expires_in_seconds,
                )
    except ExecutionAuthorizationError as exc:
        error(exc.message, exc.code, exc.status_code)
    return ok(result, message="执行审批请求已创建")


@router.post("/approvals/{approval_id}/approve")
async def approve_execution_request(approval_id: str, request: Request):
    principal = get_request_principal(request)
    service = ExecutionAuthorizationService()
    try:
        async with get_db() as db:
            result = await service.approve_order(
                db, approval_id=approval_id, principal=principal
            )
    except ExecutionAuthorizationError as exc:
        error(exc.message, exc.code, exc.status_code)
    return ok(result, message="执行审批已确认")


@router.post("/simulation/release-t1")
async def simulation_release_t1(
    request: Request,
    force_all: bool = Query(
        False,
        description="true=模拟跳到下一交易日，全部可卖；false=仅释放非当日买入",
    ),
    execution_authorization_id: str = Query(..., min_length=1, max_length=100),
):
    """模拟盘：释放 T+1 可卖数量（学习辅助，非实盘）。"""
    from app.data.service import DataService
    from app.trade.account_ledger import release_t1_available_qty
    from app.trade.simulation_trader import SimulationTrader

    principal = get_request_principal(request)
    authorization_payload = {"mode": "simulation", "force_all": force_all}
    try:
        async with get_db() as db:
            approval = await ExecutionAuthorizationService().consume_operation_approval(
                db,
                approval_id=execution_authorization_id,
                principal=principal,
                action_type="trade.simulation.release_t1",
                payload=authorization_payload,
            )
    except ExecutionAuthorizationError as exc:
        error(exc.message, exc.code, exc.status_code)

    approved_payload = approval["payload"]
    data = DataService()
    try:
        async with get_db() as db:
            if approved_payload["force_all"]:
                out = await release_t1_available_qty(db, "simulation")
                out["force_all"] = True
            else:
                trader = SimulationTrader(db, data)
                out = await trader._maybe_release_t1()
                out["force_all"] = False
        return ok(
            out,
            message=(
                f"已释放可卖 {out.get('released_rows', 0)} 条持仓"
                + (
                    "（模拟下一交易日，含当日买入）"
                    if approved_payload["force_all"]
                    else "（仅非当日买入）"
                )
            ),
        )
    finally:
        await data.close()


@router.post("/order/cancel")
async def cancel_order(
    body: OrderCancelRequest,
    request: Request,
    svc: TradeService = Depends(get_trade_service),
):
    principal = get_request_principal(request)
    try:
        async with get_db() as db:
            approval = await ExecutionAuthorizationService().consume_operation_approval(
                db,
                approval_id=body.execution_authorization_id,
                principal=principal,
                action_type="trade.order.cancel",
                payload={"order_id": str(body.order_id), "mode": body.mode},
            )
    except ExecutionAuthorizationError as exc:
        error(exc.message, exc.code, exc.status_code)
    approved_payload = approval["payload"]
    result = await svc.cancel_order(approved_payload["order_id"], approved_payload["mode"])
    if not result.get("success"):
        error(
            result.get("message", "撤单被拒绝"),
            result.get("error_code", "ORDER_CANCEL_REJECTED"),
            int(result.get("status_code", 409)),
        )
    return ok(result)


@router.get("/orders")
async def list_orders(
    mode: str = Query("simulation"),
    status: str | None = Query(None),
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    svc: TradeService = Depends(get_trade_service),
):
    return ok(await svc.list_orders(mode, status, days, page, page_size))


@router.get("/orders/{order_id}")
async def get_order(order_id: UUID, svc: TradeService = Depends(get_trade_service)):
    data = await svc.get_order(str(order_id))
    if not data:
        error("订单不存在", "ORDER_NOT_FOUND", 404)
    return ok(data)


@router.post("/orders/sync", status_code=202)
async def sync_open_orders(
    request: Request,
    response: Response,
    mode: str = Query("paper", pattern="^(paper|live)$"),
):
    """创建券商批量同步 Job；HTTP 请求不连接券商。"""
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)
    try:
        job, created = await OperationJobService().submit(
            job_type="trade.orders_sync",
            principal=get_request_principal(request),
            idempotency_key=idempotency_key,
            payload={"mode": mode},
        )
    except OperationJobDispatchError:
        error("订单同步任务未能投递到 Worker", "OPERATION_JOB_DISPATCH_UNAVAILABLE", 503)
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
    location = f"/api/v1/jobs/{job['job_id']}"
    response.headers["Location"] = location
    return ok(
        {"job": job, "location": location, "idempotent_replay": not created},
        message="订单同步 Job 已受理",
    )


@router.post("/orders/{order_id}/sync")
async def sync_one_order(
    order_id: UUID,
    mode: str = Query("paper", pattern="^(paper|live|simulation)$"),
    svc: TradeService = Depends(get_trade_service),
):
    return ok(await svc.sync_order(str(order_id), mode))


@router.get("/mode")
async def get_trade_mode(svc: TradeService = Depends(get_trade_service)):
    return ok(await svc.get_current_mode())


@router.get("/broker-status")
async def broker_status(svc: TradeService = Depends(get_trade_service)):
    """QMT / Mock 环境探测（不强制连接）。"""
    return ok(await svc.get_broker_status())


@router.get("/execution-status")
async def execution_status(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """只读返回当前执行安全配置，不触发订单或券商连接。"""
    principal = get_request_principal(request)
    snapshot = build_execution_status()
    freshness_seconds = max(60, int(settings.DATA_CACHE_TTL_QUOTE) * 3)
    async with get_db() as db:
        await db.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        snapshot_time_result = await db.execute(text("SELECT NOW() AS snapshot_at"))
        snapshot_at = _serialize_timestamp(
            snapshot_time_result.mappings().one()["snapshot_at"]
        )
        order_result = await db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'FAILED') AS failed,
                       COUNT(*) FILTER (WHERE status = 'CANCELLED') AS cancelled,
                       COUNT(*) FILTER (WHERE status IN ('PENDING','SUBMITTED','PARTIAL'))
                           AS open,
                       COUNT(*) FILTER (WHERE COALESCE(caller, '') IN ('', 'unknown'))
                           AS unknown_caller,
                       COUNT(*) FILTER (
                           WHERE LOWER(COALESCE(order_source, '')) IN
                               ('ai','ai_recommendation','ai_signal')
                              OR LOWER(COALESCE(caller, '')) LIKE 'ai%'
                       ) AS ai_source,
                       COUNT(*) FILTER (
                           WHERE LOWER(COALESCE(order_source, '')) IN
                              ('scheduled_order','scheduled_rule')
                              OR created_from_task IS TRUE
                       ) AS scheduled_source,
                       COUNT(*) FILTER (
                           WHERE COALESCE(approval_status, '') <> 'approved'
                       ) AS unapproved,
                       MAX(created_at) AS latest_order_at
                FROM trade.orders
                WHERE created_at >= NOW() - make_interval(days => :days)
                """
            ),
            {"days": int(days)},
        )
        order_row = dict(order_result.mappings().one())
        rejection_result = await db.execute(
            text(
                """
                SELECT COALESCE(NULLIF(reject_reason, ''), '未记录') AS reason,
                       COUNT(*) AS count
                FROM trade.orders
                WHERE created_at >= NOW() - make_interval(days => :days)
                  AND status = 'FAILED'
                GROUP BY COALESCE(NULLIF(reject_reason, ''), '未记录')
                ORDER BY count DESC, reason
                LIMIT 10
                """
            ),
            {"days": int(days)},
        )
        rejection_reasons = [
            {"reason": row["reason"], "count": int(row["count"] or 0)}
            for row in rejection_result.mappings().all()
        ]
        approval_result = await db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'requested') AS requested,
                       COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                       COUNT(*) FILTER (WHERE status = 'consumed') AS consumed,
                       COUNT(*) FILTER (WHERE status = 'expired') AS expired,
                       COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                       COUNT(*) FILTER (
                           WHERE status IN ('requested', 'approved') AND expires_at <= NOW()
                       ) AS expired_unconsumed,
                       COUNT(*) FILTER (
                           WHERE policy_version <> :policy_version
                       ) AS policy_version_mismatch,
                       MAX(created_at) AS latest_approval_at
                FROM trade.execution_approvals
                WHERE created_at >= NOW() - make_interval(days => :days)
                """
            ),
            {
                "days": int(days),
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
            },
        )
        approval_row = dict(approval_result.mappings().one())
        data_authorization_result = await db.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (stock_code)
                           stock_code, review_id, readiness_status, reviewed_at,
                           unresolved_fields, rejected_fields
                    FROM market.research_readiness_reviews
                    WHERE research_use_scope = :research_use_scope
                      AND requirement_profile = :requirement_profile
                    ORDER BY stock_code, reviewed_at DESC, review_id DESC
                )
                SELECT COUNT(*) AS latest_review_count,
                       COUNT(*) FILTER (
                           WHERE readiness_status = 'ready'
                             AND COALESCE(jsonb_array_length(unresolved_fields), 0) = 0
                             AND COALESCE(jsonb_array_length(rejected_fields), 0) = 0
                             AND reviewed_at >= NOW()
                                 - make_interval(secs => :freshness_seconds)
                       ) AS ready_fresh_count,
                       COUNT(*) FILTER (
                           WHERE readiness_status = 'ready'
                             AND reviewed_at < NOW()
                                 - make_interval(secs => :freshness_seconds)
                       ) AS stale_ready_count,
                       COUNT(*) FILTER (
                           WHERE readiness_status = 'review_required'
                       ) AS review_required_count,
                       COUNT(*) FILTER (
                           WHERE readiness_status = 'rejected'
                       ) AS rejected_count,
                       COUNT(*) FILTER (
                           WHERE COALESCE(jsonb_array_length(unresolved_fields), 0) > 0
                              OR COALESCE(jsonb_array_length(rejected_fields), 0) > 0
                       ) AS invalid_field_count,
                       MAX(reviewed_at) AS latest_reviewed_at
                FROM latest
                """
            ),
            {
                "research_use_scope": EXECUTION_REFERENCE_SCOPE,
                "requirement_profile": EXECUTION_REFERENCE_PROFILE,
                "freshness_seconds": freshness_seconds,
            },
        )
        data_authorization_row = dict(data_authorization_result.mappings().one())
        risk_rule_snapshot = await load_persisted_risk_rule_snapshot(db)

    snapshot["snapshot_version"] = _EXECUTION_STATUS_SNAPSHOT_VERSION
    snapshot["snapshot_at"] = snapshot_at
    snapshot["identity"] = _serialize_execution_identity(principal)
    snapshot["window_days"] = days
    snapshot["order_audit"] = {
        "total": int(order_row["total"] or 0),
        "failed": int(order_row["failed"] or 0),
        "cancelled": int(order_row["cancelled"] or 0),
        "open": int(order_row["open"] or 0),
        "unknown_caller": int(order_row["unknown_caller"] or 0),
        "ai_source": int(order_row["ai_source"] or 0),
        "scheduled_source": int(order_row["scheduled_source"] or 0),
        "unapproved": int(order_row["unapproved"] or 0),
        "latest_order_at": (
            order_row["latest_order_at"].isoformat()
            if order_row.get("latest_order_at")
            else None
        ),
        "rejection_reasons": rejection_reasons,
    }
    snapshot["approval_policy"] = {
        "required": settings.REQUIRE_HUMAN_APPROVAL,
        "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
        "independent_approver_required": True,
    }
    snapshot["approval_audit"] = {
        "total": int(approval_row["total"] or 0),
        "requested": int(approval_row["requested"] or 0),
        "approved": int(approval_row["approved"] or 0),
        "consumed": int(approval_row["consumed"] or 0),
        "expired": int(approval_row["expired"] or 0),
        "rejected": int(approval_row["rejected"] or 0),
        "expired_unconsumed": int(approval_row["expired_unconsumed"] or 0),
        "policy_version_mismatch": int(
            approval_row["policy_version_mismatch"] or 0
        ),
        "latest_approval_at": _serialize_timestamp(
            approval_row.get("latest_approval_at")
        ),
    }
    snapshot["data_authorization_policy"] = {
        "required_for_order_approval": True,
        "server_review_reference_required": True,
        "profile": EXECUTION_REFERENCE_PROFILE,
        "scope": EXECUTION_REFERENCE_SCOPE,
        "freshness_seconds": freshness_seconds,
    }
    snapshot["data_authorization_audit"] = {
        "latest_review_count": int(data_authorization_row["latest_review_count"] or 0),
        "ready_fresh_count": int(data_authorization_row["ready_fresh_count"] or 0),
        "stale_ready_count": int(data_authorization_row["stale_ready_count"] or 0),
        "review_required_count": int(
            data_authorization_row["review_required_count"] or 0
        ),
        "rejected_count": int(data_authorization_row["rejected_count"] or 0),
        "invalid_field_count": int(data_authorization_row["invalid_field_count"] or 0),
        "latest_reviewed_at": _serialize_timestamp(
            data_authorization_row.get("latest_reviewed_at")
        ),
    }
    snapshot["risk_rules"] = risk_rule_snapshot
    snapshot["source"] = (
        "runtime settings + request principal + trade.orders + "
        "trade.execution_approvals + market.research_readiness_reviews + "
        "risk.risk_rules"
    )
    snapshot["source_version"] = _EXECUTION_STATUS_SOURCE_VERSION
    return ok(snapshot)


@router.post("/reconcile", status_code=202)
async def reconcile_broker(
    request: Request,
    response: Response,
    mode: str = Query("paper", pattern="^(paper|live)$"),
    execution_authorization_id: str = Query(..., min_length=1, max_length=100),
):
    """创建受审批保护的券商对账 Job。"""
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)
    principal = get_request_principal(request)
    try:
        job, created = await OperationJobService().submit_reconcile(
            principal=principal,
            idempotency_key=idempotency_key,
            mode=mode,
            approval_id=execution_authorization_id,
        )
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
    location = f"/api/v1/jobs/{job['job_id']}"
    response.headers["Location"] = location
    return ok(
        {"job": job, "location": location, "idempotent_replay": not created},
        message="券商对账 Job 已受理",
    )
