"""Activate one immutable strategy version under the local single-operator exception."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from typing import Any, Sequence

from sqlalchemy import text

from app.core.auth import Principal, ROLE_SCOPES
from app.core.config import settings
from app.db import get_db
from app.strategy.single_operator_exception import LocalDevelopmentSingleOperatorException
from app.strategy.version_service import StrategyVersionError, StrategyVersionService


_LOCKS = (
    "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
    "CERTIFIED_SCREENER_OUTPUT_ENABLED",
    "TRADING_EXECUTION_ENABLED",
    "LIVE_TRADING_ENABLED",
    "AI_ORDER_ENABLED",
    "ALLOW_SCHEDULED_ORDER",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def activation_request_hash(
    *,
    actor_principal_id: str,
    strategy_id: int,
    source_version_id: int,
    source_params: dict[str, Any],
    config_hash: str,
    catalog_hash: str,
    reason: str,
) -> str:
    payload = {
        "actor_principal_id": actor_principal_id,
        "catalog_hash": catalog_hash,
        "config_hash": config_hash,
        "reason": reason,
        "source_params": source_params,
        "source_version_id": source_version_id,
        "strategy_id": strategy_id,
        "validity_policy": "90d_from_database_commit",
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_locks_closed() -> None:
    enabled = [name for name in _LOCKS if getattr(settings, name) is not False]
    if enabled:
        raise StrategyVersionError(
            f"发布或交易锁未关闭: {', '.join(enabled)}",
            "STRATEGY_LOCAL_ACTIVATION_LOCK_OPEN",
            409,
        )


def _require_single_update(result: Any, code: str) -> None:
    if getattr(result, "rowcount", None) != 1:
        raise StrategyVersionError("策略状态已变化，请刷新后重试", code, 409)


async def _load_actor(db: Any, actor_principal_id: str) -> Principal:
    result = await db.execute(
        text(
            """
            SELECT principal_id, display_name, principal_type, role
            FROM auth.principals
            WHERE principal_id = CAST(:principal_id AS uuid)
              AND is_active IS TRUE
            FOR UPDATE
            """
        ),
        {"principal_id": actor_principal_id},
    )
    row = result.mappings().first()
    if row is None:
        raise StrategyVersionError("策略治理主体不存在或未启用", "STRATEGY_ACTOR_INVALID", 403)
    return Principal(
        principal_id=str(row["principal_id"]),
        display_name=row["display_name"],
        principal_type=row["principal_type"],
        role=row["role"],
        scopes=ROLE_SCOPES[row["role"]],
        source="local_governance_command",
    )


async def activate(args: argparse.Namespace) -> dict[str, Any]:
    _require_locks_closed()
    service = StrategyVersionService()
    async with get_db() as db:
        actor = await _load_actor(db, args.actor_principal_id)
        exception = LocalDevelopmentSingleOperatorException.create(
            principal=actor,
            reason=args.exception_reason,
            idempotency_key=args.exception_idempotency_key,
        )
        await exception.assert_active_actor(db, principal=actor)
        await exception.assert_authorized(db)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:strategy_type))"),
            {"strategy_type": args.strategy_type},
        )
        source_result = await db.execute(
            text(
                """
                SELECT s.id AS strategy_id, s.strategy_type, s.is_active,
                       h.revision, h.active_version_id,
                       v.version_id, v.version_number, v.enabled, v.params,
                       v.config_hash, v.catalog_hash, a.status AS approval_status
                FROM strategy.strategies s
                JOIN strategy.strategy_version_heads h ON h.strategy_id = s.id
                JOIN strategy.strategy_versions v ON v.version_id = :source_version_id
                JOIN strategy.strategy_version_approvals a ON a.version_id = v.version_id
                WHERE s.id = :strategy_id AND v.strategy_id = s.id
                FOR UPDATE OF s, h, v, a
                """
            ),
            {
                "strategy_id": args.strategy_id,
                "source_version_id": args.source_version_id,
            },
        )
        source = source_result.mappings().first()
        if source is None or source["strategy_type"] != args.strategy_type:
            raise StrategyVersionError("策略或源版本不匹配", "STRATEGY_LOCAL_ACTIVATION_SOURCE_INVALID", 409)
        if source["approval_status"] != "approved" or source["enabled"] is not True:
            raise StrategyVersionError("源版本未审批或未启用", "STRATEGY_LOCAL_ACTIVATION_SOURCE_INVALID", 409)
        _, params = service._verified_config(
            strategy_type=args.strategy_type,
            enabled=source["enabled"],
            params=source["params"],
            catalog_hash=source["catalog_hash"],
            config_hash=source["config_hash"],
        )
        request_hash = activation_request_hash(
            actor_principal_id=actor.principal_id,
            strategy_id=args.strategy_id,
            source_version_id=args.source_version_id,
            source_params=params,
            config_hash=source["config_hash"],
            catalog_hash=source["catalog_hash"],
            reason=args.activation_reason,
        )
        existing = await db.execute(
            text(
                """
                SELECT after_data
                FROM audit.operation_logs
                WHERE operation = 'STRATEGY_LOCAL_SINGLE_OPERATOR_ACTIVATED'
                  AND after_data->>'idempotency_key' = :idempotency_key
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"idempotency_key": args.activation_idempotency_key},
        )
        prior = existing.mappings().first()
        if prior is not None:
            if prior["after_data"].get("request_hash") != request_hash:
                raise StrategyVersionError(
                    "相同幂等键不能绑定不同策略激活请求",
                    "STRATEGY_LOCAL_ACTIVATION_IDEMPOTENCY_CONFLICT",
                    409,
                )
            return {"idempotent": True, **prior["after_data"]}
        if source["is_active"] is not False or source["active_version_id"] is not None:
            raise StrategyVersionError("策略主体或 active head 已存在", "STRATEGY_LOCAL_ACTIVATION_CONFLICT", 409)
        if source["revision"] != 4 or source["version_number"] != 1:
            raise StrategyVersionError("策略 head 修订号不符合 v5 创建前置", "STRATEGY_LOCAL_ACTIVATION_CONFLICT", 409)
        submitted = await service.submit(
            db,
            principal=actor,
            strategy_type=args.strategy_type,
            expected_revision=source["revision"],
            enabled=True,
            params=params,
        )
        if (
            submitted["version"] != source["revision"] + 1
            or submitted["params"] != params
            or submitted["config_hash"] != source["config_hash"]
            or submitted["catalog_hash"] != source["catalog_hash"]
        ):
            raise StrategyVersionError("v5 不可变快照校验失败", "STRATEGY_LOCAL_ACTIVATION_SNAPSHOT_INVALID", 409)
        approved = await service.approve(
            db,
            principal=actor,
            version_id=submitted["version_id"],
            single_operator_exception=exception,
        )
        event_result = await db.execute(
            text(
                """
                WITH clock AS (
                    SELECT NOW() AS effective_at,
                           NOW() + INTERVAL '90 days' AS valid_until,
                           current_setting('TimeZone') AS database_timezone
                )
                INSERT INTO strategy.strategy_version_validity_events
                    (strategy_id, version_id, event_type, effective_at, valid_until,
                     reason, actor_principal_id, idempotency_key, request_hash)
                SELECT :strategy_id, :version_id, 'activated', clock.effective_at,
                       clock.valid_until, :reason, CAST(:actor_principal_id AS uuid),
                       :idempotency_key, :request_hash
                FROM clock
                RETURNING event_id, effective_at, valid_until,
                          current_setting('TimeZone') AS database_timezone
                """
            ),
            {
                "strategy_id": args.strategy_id,
                "version_id": submitted["version_id"],
                "reason": args.activation_reason,
                "actor_principal_id": actor.principal_id,
                "idempotency_key": args.activation_idempotency_key,
                "request_hash": request_hash,
            },
        )
        event = dict(event_result.mappings().first())
        subject_update = await db.execute(
            text(
                """
                UPDATE strategy.strategies
                SET is_active = TRUE
                WHERE id = :strategy_id AND is_active IS FALSE
                """
            ),
            {"strategy_id": args.strategy_id},
        )
        _require_single_update(subject_update, "STRATEGY_LOCAL_ACTIVATION_CONFLICT")
        head = await db.execute(
            text(
                """
                SELECT active_version_id
                FROM strategy.strategy_version_heads
                WHERE strategy_id = :strategy_id
                FOR UPDATE
                """
            ),
            {"strategy_id": args.strategy_id},
        )
        if head.mappings().first()["active_version_id"] != submitted["version_id"]:
            raise StrategyVersionError("active head 未指向 v5", "STRATEGY_LOCAL_ACTIVATION_HEAD_INVALID", 409)
        payload = {
            "actor_principal_id": actor.principal_id,
            "approval_version_event": "approved",
            "catalog_hash": submitted["catalog_hash"],
            "config_hash": submitted["config_hash"],
            "environment": "local_development",
            "event_id": str(event["event_id"]),
            "idempotency_key": args.activation_idempotency_key,
            "reason": args.activation_reason,
            "request_hash": request_hash,
            "separation_of_duties": False,
            "single_operator_exception": True,
            "source_version_id": args.source_version_id,
            "strategy_id": args.strategy_id,
            "strategy_type": args.strategy_type,
            "valid_until": event["valid_until"].isoformat(),
            "validity_policy": "90d_from_database_commit",
            "version_id": submitted["version_id"],
            "version_number": submitted["version"],
        }
        await db.execute(
            text(
                """
                INSERT INTO audit.operation_logs
                    (operator, operation, entity_type, entity_id, after_data, result)
                VALUES
                    (:operator, 'STRATEGY_LOCAL_SINGLE_OPERATOR_ACTIVATED',
                     'strategy_version', :entity_id, CAST(:after_data AS jsonb), 'SUCCESS')
                """
            ),
            {
                "operator": actor.display_name[:50],
                "entity_id": str(submitted["version_id"]),
                "after_data": _canonical_json(payload),
            },
        )
        return {
            "idempotent": False,
            "activation_event": {**event, "event_id": str(event["event_id"])},
            "approved_snapshot": approved,
            "submitted_snapshot": submitted,
            "workflow_audit": payload,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地单人治理例外下创建、审批并激活策略版本")
    parser.add_argument("--actor-principal-id", required=True)
    parser.add_argument("--strategy-id", required=True, type=int)
    parser.add_argument("--strategy-type", required=True)
    parser.add_argument("--source-version-id", required=True, type=int)
    parser.add_argument("--exception-reason", required=True)
    parser.add_argument("--exception-idempotency-key", required=True)
    parser.add_argument("--activation-reason", required=True)
    parser.add_argument("--activation-idempotency-key", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(activate(args)), ensure_ascii=False, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
