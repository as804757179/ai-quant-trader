from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.backtest.service import BacktestService
from app.core.logging import FEATURE_BACKTEST, get_logger
from app.core.response import error, ok

logger = get_logger(__name__, feature=FEATURE_BACKTEST)
router = APIRouter()


class BacktestRunRequest(BaseModel):
    strategy_type: str = Field(..., description="dual_ma / bollinger / rsi / macd")
    stock_codes: list[str] = Field(..., min_length=1)
    start_date: date
    end_date: date
    initial_cash: float = Field(default=1_000_000, gt=0)
    params: dict[str, Any] | None = None
    name: str | None = None
    requirement_profile: str | None = None
    required_fields: list[str] | None = None
    auto_backfill: bool | None = Field(
        default=None, description="缺失 K 线时自动回填；默认读环境配置"
    )
    allow_synthetic: bool | None = Field(
        default=None, description="远程无数据时使用合成 K 线；默认读环境配置"
    )


@router.post("/run")
async def run_backtest(body: BacktestRunRequest):
    logger.info(
        "backtest_run_request",
        strategy_type=body.strategy_type,
        stock_codes=body.stock_codes,
        start_date=str(body.start_date),
        end_date=str(body.end_date),
        initial_cash=body.initial_cash,
        auto_backfill=body.auto_backfill,
        allow_synthetic=body.allow_synthetic,
    )
    svc = BacktestService()
    try:
        result = await svc.create_and_run(
            strategy_type=body.strategy_type,
            stock_codes=body.stock_codes,
            start_date=body.start_date,
            end_date=body.end_date,
            initial_cash=body.initial_cash,
            params=body.params,
            name=body.name,
            auto_backfill=body.auto_backfill,
            allow_synthetic=body.allow_synthetic,
            requirement_profile=body.requirement_profile,
            required_fields=body.required_fields,
        )
        msg = "回测完成"
        if result.get("data_meta", {}).get("synthetic_used"):
            msg = "回测完成（该回测结果不能作为投资依据。）"
        logger.info(
            "backtest_run_done",
            task_id=result.get("task_id"),
            strategy_type=body.strategy_type,
            synthetic_used=bool(result.get("data_meta", {}).get("synthetic_used")),
            metrics_keys=list((result.get("metrics") or {}).keys()),
        )
        return ok(result, message=msg)
    except ValueError as exc:
        logger.warning("backtest_run_invalid", error=str(exc))
        error(str(exc), "BACKTEST_INVALID", 400)
    except Exception as exc:
        logger.error("backtest_run_failed", error=str(exc), exc_info=True)
        error(f"回测失败: {exc}", "BACKTEST_FAILED", 500)


@router.get("/tasks")
async def list_backtest_tasks(limit: int = Query(20, ge=1, le=100)):
    logger.info("backtest_list_tasks", limit=limit)
    svc = BacktestService()
    try:
        items = await svc.list_tasks(limit=limit)
        return ok({"items": items, "total": len(items)})
    except Exception as exc:
        logger.error("backtest_list_failed", error=str(exc), exc_info=True)
        error(f"查询失败: {exc}", "BACKTEST_LIST_FAILED", 500)


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
