from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.logging import FEATURE_AI, get_logger
from app.core.response import APIResponse, ok
from app.schemas.ai import AnalyzeResponseData
from app.services.ai_service import AIService, AnalysisError

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


@router.post(
    "/{code}/analyze",
    response_model=APIResponse,
    summary="触发完整 AI 分析",
    description="并发运行 4 个 LLM Agent + 风控评估，聚合生成交易信号并落库。",
)
async def analyze_stock(
    code: str,
    force_refresh: bool = Query(False, description="强制重新分析（忽略缓存）"),
    strategy_id: int | None = Query(None, description="关联策略 ID"),
    svc: AIService = Depends(get_ai_service),
):
    logger.info(
        "api_analyze_request",
        stock_code=code,
        force_refresh=force_refresh,
        strategy_id=strategy_id,
    )
    try:
        result: AnalyzeResponseData = await svc.analyze(
            code,
            force_refresh=force_refresh,
            strategy_id=strategy_id,
        )
        message = "返回缓存信号" if result.from_cache else "分析完成"
        return ok(result.model_dump(), message=message)
    except AnalysisError as exc:
        logger.warning(
            "api_analyze_failed",
            stock_code=code,
            error=exc.message,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "success": False,
                "message": exc.message,
                "error_code": "AI_ANALYSIS_FAILED",
            },
        ) from exc
    except Exception as exc:
        logger.error(
            "api_analyze_error",
            stock_code=code,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "message": "AI 分析服务暂时不可用",
                "error_code": "AI_SERVICE_UNAVAILABLE",
            },
        ) from exc
    finally:
        await svc.close()


@router.get(
    "/{code}/latest-signal",
    response_model=APIResponse,
    summary="最新有效信号",
)
async def get_latest_signal(code: str, svc: AIService = Depends(get_ai_service)):
    try:
        cached = await svc.get_valid_signal(code)
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