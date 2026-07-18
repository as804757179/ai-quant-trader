from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text

from app.core.auth import get_request_principal
from app.core.config import settings
from app.core.logging import FEATURE_AI, get_logger
from app.core.response import APIResponse, error, ok
from app.db import get_db
from app.jobs.dispatch import OperationJobDispatchError
from app.jobs.operations import OperationJobService
from app.jobs.service import AsyncJobError
from app.services.ai_service import AIService

logger = get_logger(__name__, feature=FEATURE_AI)

router = APIRouter()


def get_ai_service() -> AIService:
    return AIService()


@router.get(
    "/signals",
    response_model=APIResponse,
    summary="信号列表",
    description="分页查询 AI 信号，支持按 action、置信度、风险等级筛选。",
)
async def list_signals(
    action: str | None = Query(None, description="BUY/SELL/HOLD"),
    min_confidence: float = Query(0.0, ge=0, le=1),
    risk_level: str | None = Query(None, description="LOW/MEDIUM/HIGH/EXTREME"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    svc: AIService = Depends(get_ai_service),
):
    try:
        result = await svc.list_signals(
            action=action,
            min_confidence=min_confidence,
            risk_level=risk_level,
            page=page,
            page_size=page_size,
        )
        return ok(result.model_dump())
    finally:
        await svc.close()


@router.get(
    "/audit-summary",
    response_model=APIResponse,
    summary="AI 只读审计汇总",
)
async def get_ai_audit_summary(days: int = Query(30, ge=1, le=365)):
    """统计 AI 调用和 AI 来源订单，不触发分析或交易。"""
    params = {"days": int(days)}
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM ai.signals
                   WHERE created_at >= NOW() - make_interval(days => :days)) AS signal_count,
                  (SELECT COUNT(*) FROM ai.signals
                   WHERE created_at >= NOW() - make_interval(days => :days)
                     AND action='HOLD') AS hold_count,
                  (SELECT COUNT(*) FROM ai.signals
                   WHERE created_at >= NOW() - make_interval(days => :days)
                     AND COALESCE(raw_agent_output->>'historical_data_status','unknown')
                         = 'certified') AS certified_signal_count,
                  (SELECT COUNT(*) FROM ai.signals
                   WHERE created_at >= NOW() - make_interval(days => :days)
                     AND COALESCE(raw_agent_output->>'historical_data_status','unknown')
                         IN ('uncertified','synthetic')) AS blocked_data_signal_count,
                  (SELECT COUNT(*) FROM ai.signals
                   WHERE created_at >= NOW() - make_interval(days => :days)
                     AND COALESCE(raw_agent_output->>'historical_data_status','unknown')
                         = 'unknown') AS unknown_data_signal_count,
                  (SELECT COUNT(*) FROM ai.agent_logs
                   WHERE created_at >= NOW() - make_interval(days => :days)) AS agent_call_count,
                  (SELECT COUNT(*) FROM ai.agent_logs
                   WHERE created_at >= NOW() - make_interval(days => :days)
                     AND status <> 'success') AS agent_failure_count,
                  (SELECT COUNT(*) FROM trade.orders
                   WHERE created_at >= NOW() - make_interval(days => :days)
                     AND (LOWER(COALESCE(order_source,'')) IN
                          ('ai','ai_recommendation','ai_signal')
                       OR LOWER(COALESCE(caller,'')) LIKE 'ai%'))
                    AS ai_order_count,
                  (SELECT MAX(created_at) FROM ai.agent_logs
                   WHERE created_at >= NOW() - make_interval(days => :days)) AS latest_call_at,
                  (SELECT MAX(created_at) FROM ai.signals
                   WHERE created_at >= NOW() - make_interval(days => :days)) AS latest_signal_at
                """
            ),
            params,
        )
        row = dict(result.mappings().one())
        usage_result = await db.execute(
            text(
                """
                SELECT agent_name, COALESCE(model_used, 'not_recorded') AS model_used,
                       COALESCE(status, 'not_recorded') AS status,
                       COUNT(*) AS count,
                       ROUND(AVG(COALESCE(latency_ms, 0))) AS average_latency_ms
                FROM ai.agent_logs
                WHERE created_at >= NOW() - make_interval(days => :days)
                GROUP BY agent_name, COALESCE(model_used, 'not_recorded'),
                         COALESCE(status, 'not_recorded')
                ORDER BY count DESC, agent_name, model_used
                """
            ),
            params,
        )
        agent_usage = [
            {
                "agent_name": item["agent_name"],
                "model_used": item["model_used"],
                "status": item["status"],
                "count": int(item["count"] or 0),
                "average_latency_ms": int(item["average_latency_ms"] or 0),
            }
            for item in usage_result.mappings().all()
        ]

    configured_models = [
        name for name, configured in settings.validate_ai_keys().items() if configured
    ]
    latest_call_at = row.get("latest_call_at")
    latest_signal_at = row.get("latest_signal_at")
    ai_order_count = int(row.get("ai_order_count") or 0)
    return ok(
        {
            "window_days": days,
            "signal_count": int(row.get("signal_count") or 0),
            "hold_count": int(row.get("hold_count") or 0),
            "data_status_counts": {
                "certified": int(row.get("certified_signal_count") or 0),
                "blocked": int(row.get("blocked_data_signal_count") or 0),
                "unknown": int(row.get("unknown_data_signal_count") or 0),
            },
            "agent_call_count": int(row.get("agent_call_count") or 0),
            "agent_failure_count": int(row.get("agent_failure_count") or 0),
            "ai_order_count": ai_order_count,
            "order_created": ai_order_count > 0,
            "unauthorized_attempt_count": None,
            "unauthorized_attempt_status": "not_recorded",
            "configured_models": configured_models,
            "agent_usage": agent_usage,
            "latest_call_at": latest_call_at.isoformat() if latest_call_at else None,
            "latest_signal_at": (
                latest_signal_at.isoformat() if latest_signal_at else None
            ),
            "ai_order_enabled": settings.AI_ORDER_ENABLED,
            "ai_direct_order_allowed": False,
            "scheduled_order_enabled": settings.ALLOW_SCHEDULED_ORDER,
            "source": "ai.signals + ai.agent_logs + trade.orders",
            "source_version": "ai-audit-v2",
        }
    )


@router.post(
    "/{code}/analyze",
    response_model=APIResponse,
    status_code=202,
    summary="触发完整 AI 分析",
    description="创建 AI 分析 Job；HTTP 请求不直接运行 Agent 或写入信号。",
)
async def analyze_stock(
    code: str,
    request: Request,
    response: Response,
    force_refresh: bool = Query(False, description="强制重新分析（忽略缓存）"),
    strategy_id: int | None = Query(None, description="关联策略 ID"),
):
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)
    try:
        job, created = await OperationJobService().submit(
            job_type="ai.analyze",
            principal=get_request_principal(request),
            idempotency_key=idempotency_key,
            payload={
                "code": code,
                "force_refresh": force_refresh,
                "strategy_id": strategy_id,
            },
        )
    except OperationJobDispatchError:
        error("AI 分析任务未能投递到 Worker", "OPERATION_JOB_DISPATCH_UNAVAILABLE", 503)
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
    location = f"/api/v1/jobs/{job['job_id']}"
    response.headers["Location"] = location
    logger.info(
        "ai_analyze_accepted",
        stock_code=code,
        job_id=job["job_id"],
        created=created,
        force_refresh=force_refresh,
        strategy_id=strategy_id,
    )
    return ok(
        {"job": job, "location": location, "idempotent_replay": not created},
        message="AI 分析 Job 已受理",
    )


@router.get(
    "/{code}/latest-signal",
    response_model=APIResponse,
    summary="最新有效信号",
)
async def get_latest_signal(code: str, svc: AIService = Depends(get_ai_service)):
    try:
        cached = await svc.get_current_valid_signal(code)
        if not cached:
            return ok(None, message="暂无有效信号")
        return ok(cached.model_dump())
    finally:
        await svc.close()


@router.get(
    "/{code}/signal-history",
    response_model=APIResponse,
    summary="历史信号记录",
    description="查询指定股票的历史信号（含执行结果）。",
)
async def get_signal_history(
    code: str,
    days: int = Query(30, ge=1, le=365),
    svc: AIService = Depends(get_ai_service),
):
    try:
        result = await svc.get_signal_history(code, days=days)
        return ok(result.model_dump())
    except AnalysisError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "success": False,
                "message": exc.message,
                "error_code": "AI_QUERY_FAILED",
            },
        ) from exc
    finally:
        await svc.close()
