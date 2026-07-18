import hashlib
import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import FEATURE_STRATEGY, get_logger
from app.core.response import error, ok
from app.strategy.version_service import StrategyVersionError, StrategyVersionService

logger = get_logger(__name__, feature=FEATURE_STRATEGY)
router = APIRouter()
_service = StrategyVersionService()


def _principal_from_request(request: Request):
    from app.core.auth import get_request_principal

    return get_request_principal(request)


def _database_context():
    from app.db import get_db

    return get_db()


def build_strategy_runtime_status(items: list[dict[str, Any]]) -> dict[str, Any]:
    stable_payload = [
        {
            "type": item["type"],
            "enabled": item["enabled"],
            "params": item["params"],
            "requirement_profile": item["requirement_profile"],
            "required_fields": item["required_fields"],
            "config_status": item["config_status"],
            "revision": item["revision"],
            "version": item["version"],
            "config_hash": item["config_hash"],
            "catalog_hash": item["catalog_hash"],
        }
        for item in sorted(items, key=lambda value: value["type"])
    ]
    config_hash = hashlib.sha256(
        json.dumps(
            stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        "items": items,
        "total": len(items),
        "enabled_count": sum(1 for item in items if item["enabled"]),
        "catalog_version": "builtin-strategy-catalog-v1",
        "config_hash": config_hash,
        "source": "strategy.strategy_versions + strategy.strategy_version_heads",
        "source_version": "strategy-runtime-status-v2",
    }


class StrategyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=0)
    enabled: bool | None = None
    params: dict[str, Any] | None = None


class StrategyCreateRequest(BaseModel):
    """Compatibility submission for an immutable built-in strategy version."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="内置策略类型 dual_ma/bollinger/rsi/macd")
    expected_revision: int = Field(..., ge=0)
    enabled: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


def _raise_version_error(exc: StrategyVersionError) -> None:
    logger.warning("strategy_version_rejected", code=exc.code, detail=str(exc))
    error(str(exc), exc.code, exc.status_code, retryable=exc.retryable)


def _raise_database_error(exc: SQLAlchemyError) -> None:
    logger.error("strategy_version_database_unavailable", error_type=type(exc).__name__)
    error("策略版本控制面不可用", "STRATEGY_VERSION_UNAVAILABLE", 503, retryable=True)


@router.get("/list")
async def list_strategies():
    try:
        async with _database_context() as db:
            items = await _service.list_configurations(db)
    except StrategyVersionError as exc:
        _raise_version_error(exc)
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    logger.info("strategy_list", total=len(items))
    return ok({"items": items, "total": len(items)})


@router.get("/runtime-status")
async def get_strategy_runtime_status():
    """Return catalog metadata and the current governed configuration state."""
    try:
        async with _database_context() as db:
            items = await _service.list_configurations(db)
    except StrategyVersionError as exc:
        _raise_version_error(exc)
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    return ok(build_strategy_runtime_status(items))


@router.post("/create")
async def create_strategy(body: StrategyCreateRequest, request: Request):
    principal = _principal_from_request(request)
    logger.info(
        "strategy_version_submit",
        strategy_type=body.type,
        expected_revision=body.expected_revision,
        enabled=body.enabled,
        params_keys=list(body.params),
        principal_id=principal.principal_id,
    )
    try:
        async with _database_context() as db:
            item = await _service.submit(
                db,
                principal=principal,
                strategy_type=body.type,
                expected_revision=body.expected_revision,
                enabled=body.enabled,
                params=body.params,
            )
    except StrategyVersionError as exc:
        _raise_version_error(exc)
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    return ok(item, message="策略版本已提交，等待独立审批")


@router.post("/versions/{version_id}/approve")
async def approve_strategy_version(version_id: int, request: Request):
    principal = _principal_from_request(request)
    logger.info(
        "strategy_version_approve",
        version_id=version_id,
        principal_id=principal.principal_id,
    )
    try:
        async with _database_context() as db:
            item = await _service.approve(db, principal=principal, version_id=version_id)
    except StrategyVersionError as exc:
        _raise_version_error(exc)
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    return ok(item, message="策略版本已审批")


@router.get("/{strategy_type}")
async def get_strategy(strategy_type: str):
    logger.info("strategy_get", strategy_type=strategy_type)
    try:
        async with _database_context() as db:
            item = await _service.get_configuration(db, strategy_type=strategy_type)
    except StrategyVersionError as exc:
        _raise_version_error(exc)
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    return ok(item)


@router.post("/{strategy_type}/update")
async def update_strategy(
    strategy_type: str, body: StrategyUpdateRequest, request: Request
):
    principal = _principal_from_request(request)
    logger.info(
        "strategy_version_update",
        strategy_type=strategy_type,
        expected_revision=body.expected_revision,
        enabled=body.enabled,
        has_params=body.params is not None,
        principal_id=principal.principal_id,
    )
    try:
        async with _database_context() as db:
            item = await _service.submit(
                db,
                principal=principal,
                strategy_type=strategy_type,
                expected_revision=body.expected_revision,
                enabled=body.enabled,
                params=body.params,
            )
    except StrategyVersionError as exc:
        _raise_version_error(exc)
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    return ok(item, message="策略版本已提交，等待独立审批")
