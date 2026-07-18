from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.backtest.jobs import BacktestJobService
from app.backtest.service import BacktestService, BacktestStrategyDisabled
from app.core.auth import get_request_principal
from app.core.logging import FEATURE_BACKTEST, get_logger
from app.core.response import error, ok
from app.jobs.service import AsyncJobError

logger = get_logger(__name__, feature=FEATURE_BACKTEST)
router = APIRouter()


class BacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_type: str = Field(..., description="dual_ma / bollinger / rsi / macd")
    strategy_code: str = Field(..., min_length=1, description="声明的内置策略版本，例如 builtin:dual_ma:v1")
    stock_codes: list[str] = Field(..., min_length=1, max_length=200)
    start_date: date
    end_date: date
    initial_cash: float = Field(default=1_000_000, gt=0)
    params: dict[str, Any] | None = None
    name: str | None = None
    requirement_profile: str = Field(..., min_length=1)
    required_fields: list[str] = Field(..., min_length=1)
    auto_backfill: bool | None = Field(
        default=False, description="可信回测不允许请求内回填；仅为拒绝旧调用方保留"
    )
    allow_synthetic: bool | None = Field(
        default=False, description="可信回测不允许 Synthetic K 线；仅为拒绝旧调用方保留"
    )


@router.post("/run", status_code=202)
async def run_backtest(
    body: BacktestRunRequest, request: Request, response: Response
):
    """只创建可审计 Job；HTTP 请求绝不执行回测。"""
    logger.info(
        "backtest_run_request",
        strategy_type=body.strategy_type,
        strategy_code=body.strategy_code,
        stock_codes=body.stock_codes,
        start_date=str(body.start_date),
        end_date=str(body.end_date),
        initial_cash=body.initial_cash,
    )
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)

    svc = BacktestJobService()
    try:
        job, created = await svc.enqueue(
            principal=get_request_principal(request),
            idempotency_key=idempotency_key,
            payload=body.model_dump(mode="json"),
        )
        location = f"/api/v1/backtest/jobs/{job['job_id']}"
        response.headers["Location"] = location
        logger.info(
            "backtest_job_accepted",
            job_id=job["job_id"],
            strategy_type=body.strategy_type,
            created=created,
            status=job["status"],
        )
        return ok(
            {
                "job": job,
                "location": location,
                "idempotent_replay": not created,
            },
            message=(
                "回测 Job 已记录，但可信回测执行锁关闭，任务不会执行"
                if job["status"] == "blocked"
                else "回测 Job 已受理"
            ),
        )
    except BacktestStrategyDisabled as exc:
        logger.warning("backtest_run_strategy_disabled", error_code=exc.code)
        error(str(exc), exc.code, 422)
    except ValueError as exc:
        logger.warning("backtest_run_invalid", error=str(exc))
        error(str(exc), "BACKTEST_INVALID", 422)
    except AsyncJobError as exc:
        logger.warning("backtest_job_rejected", error_code=exc.code)
        error(str(exc), exc.code, exc.status_code)


@router.get("/jobs/{job_id}")
async def get_backtest_job(job_id: UUID, request: Request):
    svc = BacktestJobService()
    try:
        return ok(await svc.get_status(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)


@router.get("/jobs/{job_id}/result")
async def get_backtest_job_result(job_id: UUID, request: Request):
    svc = BacktestJobService()
    try:
        return ok(await svc.get_result(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
    except ValueError as exc:
        error("任务结果不可用", "JOB_RESULT_UNAVAILABLE", 409)


@router.post("/jobs/{job_id}/cancel")
async def cancel_backtest_job(job_id: UUID, request: Request):
    svc = BacktestJobService()
    try:
        return ok(await svc.cancel(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)


@router.post("/jobs/{job_id}/execute")
async def execute_backtest_job(job_id: UUID, request: Request):
    """受控 Worker/本地执行入口，不接受人类会话或匿名请求。"""
    svc = BacktestJobService()
    try:
        return ok(await svc.execute(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)


@router.get("/tasks")
async def list_backtest_tasks(
    limit: int | None = Query(None, ge=1, le=100, description="兼容旧客户端"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
):
    resolved_page_size = page_size or limit or 20
    logger.info(
        "backtest_list_tasks",
        page=page,
        page_size=resolved_page_size,
    )
    svc = BacktestService()
    try:
        return ok(
            await svc.list_tasks(
                page=page,
                page_size=resolved_page_size,
            )
        )
    except Exception as exc:
        logger.error("backtest_list_failed", error=str(exc), exc_info=True)
        error(f"查询失败: {exc}", "BACKTEST_LIST_FAILED", 500)


@router.get("/validation-summary")
async def get_backtest_validation_summary():
    """只读返回持久化回测证据及明确缺失的运行时血缘。"""
    svc = BacktestService()
    try:
        return ok(await svc.get_validation_summary())
    except Exception as exc:
        logger.error("backtest_validation_summary_failed", error=str(exc), exc_info=True)
        error(f"查询失败: {exc}", "BACKTEST_VALIDATION_SUMMARY_FAILED", 500)


@router.get("/{task_id}/status")
async def get_backtest_status(task_id: int):
    logger.info("backtest_status_query", task_id=task_id)
    svc = BacktestService()
    try:
        return ok(await svc.get_status(task_id))
    except ValueError as exc:
        logger.warning("backtest_status_not_found", task_id=task_id)
        error(str(exc), "TASK_NOT_FOUND", 404)
    except Exception as exc:
        logger.error("backtest_status_failed", task_id=task_id, error=str(exc), exc_info=True)
        error(f"查询失败: {exc}", "BACKTEST_STATUS_FAILED", 500)
