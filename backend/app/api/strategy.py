from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.logging import FEATURE_STRATEGY, get_logger
from app.core.response import error, ok
from app.strategy.config_store import StrategyConfigStore

logger = get_logger(__name__, feature=FEATURE_STRATEGY)
router = APIRouter()
_store = StrategyConfigStore()


class StrategyUpdateRequest(BaseModel):
    enabled: bool | None = None
    params: dict[str, Any] | None = None


class StrategyCreateRequest(BaseModel):
    """兼容旧接口：基于内置类型创建覆盖配置。"""

    type: str = Field(..., description="内置策略类型 dual_ma/bollinger/rsi/macd")
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("/list")
async def list_strategies():
    items = _store.list_strategies()
    logger.info("strategy_list", total=len(items))
    return ok({"items": items, "total": len(items)})


@router.get("/{strategy_type}")
async def get_strategy(strategy_type: str):
    logger.info("strategy_get", strategy_type=strategy_type)
    item = _store.get(strategy_type)
    if not item:
        logger.warning("strategy_not_found", strategy_type=strategy_type)
        error(f"策略不存在: {strategy_type}", "STRATEGY_NOT_FOUND", 404)
    return ok(item)


@router.post("/create")
async def create_strategy(body: StrategyCreateRequest):
    logger.info(
        "strategy_create_or_save",
        strategy_type=body.type,
        enabled=body.enabled,
        params_keys=list((body.params or {}).keys()),
    )
    try:
        item = _store.update(body.type, enabled=body.enabled, params=body.params or None)
    except ValueError as exc:
        logger.warning("strategy_create_invalid", strategy_type=body.type, error=str(exc))
        error(str(exc), "INVALID_STRATEGY", 400)
    logger.info("strategy_saved", strategy_type=body.type, enabled=item.get("enabled"))
    return ok(item, message="策略配置已保存")


@router.post("/{strategy_type}/update")
async def update_strategy(strategy_type: str, body: StrategyUpdateRequest):
    logger.info(
        "strategy_update",
        strategy_type=strategy_type,
        enabled=body.enabled,
        has_params=body.params is not None,
    )
    try:
        item = _store.update(
            strategy_type, enabled=body.enabled, params=body.params
        )
    except ValueError as exc:
        logger.warning("strategy_update_invalid", strategy_type=strategy_type, error=str(exc))
        error(str(exc), "INVALID_STRATEGY", 400)
    logger.info("strategy_updated", strategy_type=strategy_type, enabled=item.get("enabled"))
    return ok(item, message="策略已更新")
