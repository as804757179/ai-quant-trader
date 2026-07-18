"""Server-side approval, intent, and outbox controls for order execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.core.config import settings
from app.data.kline_contract import KlineContract
from app.data.research_profiles import ResearchDataRequirementProfile


ORDER_ACTION = "trade.order.create"
OPERATION_ACTIONS = frozenset(
    {
        "trade.order.cancel",
        "risk.fuse.recover",
        "trade.simulation.release_t1",
        "trade.reconcile",
    }
)
EXECUTION_AUTHORIZATION_POLICY_VERSION = "execution-authorization-v3"
EXECUTION_REFERENCE_PROFILE = "EXECUTION_REFERENCE_V1"
EXECUTION_REFERENCE_SCOPE = "execution_reference"
INTENT_TTL_SECONDS = 900


class ExecutionAuthorizationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def canonical_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only execution-relevant fields in a stable, caller-independent form."""
    limit_price = payload.get("limit_price")
    return {
        "stock_code": str(payload["stock_code"]).zfill(6),
        "side": str(payload["side"]).upper(),
        "order_type": str(payload.get("order_type") or "LIMIT").upper(),
        "quantity": int(payload["quantity"]),
        "limit_price": round(float(limit_price), 2) if limit_price is not None else None,
        "signal_id": str(payload.get("signal_id") or ""),
        "mode": str(payload.get("mode") or "simulation").lower(),
        "order_reason": str(payload.get("order_reason") or ""),
    }


def order_payload_hash(payload: dict[str, Any]) -> str:
    canonical = canonical_order_payload(payload)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_operation_payload(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action_type not in OPERATION_ACTIONS:
        raise ExecutionAuthorizationError("UNSUPPORTED_APPROVAL_ACTION", "不支持的运维审批动作", 422)
    if not isinstance(payload, dict):
        raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "审批载荷格式无效", 422)

    def require_keys(*keys: str) -> None:
        if set(payload) != set(keys):
            raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "审批载荷字段不匹配", 422)

    def mode() -> str:
        value = str(payload.get("mode") or "").lower()
        if value not in {"simulation", "paper", "live"}:
            raise ExecutionAuthorizationError("INVALID_EXECUTION_MODE", "不支持的执行模式", 422)
        return value

    if action_type == "trade.order.cancel":
        require_keys("order_id", "mode")
        order_id = str(payload.get("order_id") or "").strip()
        if not order_id:
            raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "撤单审批缺少订单标识", 422)
        return {"order_id": order_id, "mode": mode()}
    if action_type == "risk.fuse.recover":
        require_keys("mode", "fuse_record_id", "note")
        fuse_record_id = payload.get("fuse_record_id")
        if isinstance(fuse_record_id, bool) or not isinstance(fuse_record_id, int) or fuse_record_id < 1:
            raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "熔断审批记录标识无效", 422)
        note = payload.get("note")
        if not isinstance(note, str):
            raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "熔断恢复说明无效", 422)
        return {
            "mode": mode(),
            "fuse_record_id": fuse_record_id,
            "note": note.strip(),
        }
    if action_type == "trade.simulation.release_t1":
        require_keys("mode", "force_all")
        force_all = payload.get("force_all")
        if mode() != "simulation" or not isinstance(force_all, bool):
            raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "T+1 运维审批载荷无效", 422)
        return {"mode": "simulation", "force_all": force_all}

    require_keys("mode")
    reconciliation_mode = mode()
    if reconciliation_mode not in {"paper", "live"}:
        raise ExecutionAuthorizationError("INVALID_APPROVAL_PAYLOAD", "对账审批仅支持 Paper 或 Live", 422)
    return {"mode": reconciliation_mode}


def operation_payload_hash(action_type: str, payload: dict[str, Any]) -> str:
    canonical = canonical_operation_payload(action_type, payload)
    encoded = json.dumps(
        {"action_type": action_type, "payload": canonical},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_human_principal(principal: Principal, action: str) -> None:
    if principal.is_anonymous:
        raise ExecutionAuthorizationError("UNAUTHORIZED", f"匿名主体不能{action}", 401)
    if principal.principal_type != "human":
        raise ExecutionAuthorizationError("HUMAN_PRINCIPAL_REQUIRED", f"{action}必须由人工主体执行", 403)


class ExecutionAuthorizationService:
    async def request_order_approval(
        self,
        db: AsyncSession,
        *,
        principal: Principal,
        payload: dict[str, Any],
        data_authorization_ref: str,
        expires_in_seconds: int,
    ) -> dict[str, Any]:
        _require_human_principal(principal, "请求执行审批")
        if not data_authorization_ref.strip():
            raise ExecutionAuthorizationError(
                "DATA_AUTHORIZATION_REQUIRED", "执行审批必须绑定数据授权引用", 422
            )
        if not 300 <= expires_in_seconds <= 3600:
            raise ExecutionAuthorizationError("INVALID_APPROVAL_TTL", "审批有效期必须为 5 至 60 分钟", 422)

        canonical = canonical_order_payload(payload)
        if canonical["mode"] not in {"simulation", "paper", "live"}:
            raise ExecutionAuthorizationError("INVALID_EXECUTION_MODE", "不支持的执行模式", 422)
        authorization_ref = data_authorization_ref.strip()
        if not await self._has_execution_data_authorization(
            db, authorization_ref, canonical["stock_code"]
        ):
            raise ExecutionAuthorizationError(
                "DATA_AUTHORIZATION_INVALID", "执行数据授权引用不可验证", 403
            )
        result = await db.execute(
            text(
                """
                INSERT INTO trade.execution_approvals (
                    action_type, mode, payload_hash, requester_principal_id,
                    data_authorization_ref, policy_version, status, expires_at
                ) VALUES (
                    :action_type, :mode, :payload_hash, :principal_id,
                    :data_authorization_ref, :policy_version, 'requested',
                    NOW() + (:ttl_seconds * INTERVAL '1 second')
                )
                RETURNING approval_id, status, expires_at
                """
            ),
            {
                "action_type": ORDER_ACTION,
                "mode": canonical["mode"],
                "payload_hash": order_payload_hash(canonical),
                "principal_id": principal.principal_id,
                "data_authorization_ref": authorization_ref,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
                "ttl_seconds": expires_in_seconds,
            },
        )
        row = result.mappings().one()
        await self._append_event(
            db,
            approval_id=str(row["approval_id"]),
            event_type="requested",
            actor_principal_id=principal.principal_id,
            event_payload={
                "action_type": ORDER_ACTION,
                "payload": canonical,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
            },
        )
        return {
            "approval_id": str(row["approval_id"]),
            "status": row["status"],
            "expires_at": row["expires_at"].isoformat(),
            "payload_hash": order_payload_hash(canonical),
        }

    async def request_operation_approval(
        self,
        db: AsyncSession,
        *,
        principal: Principal,
        action_type: str,
        payload: dict[str, Any],
        expires_in_seconds: int,
    ) -> dict[str, Any]:
        _require_human_principal(principal, "请求运维审批")
        if not 300 <= expires_in_seconds <= 3600:
            raise ExecutionAuthorizationError("INVALID_APPROVAL_TTL", "审批有效期必须为 5 至 60 分钟", 422)
        canonical = canonical_operation_payload(action_type, payload)
        result = await db.execute(
            text(
                """
                INSERT INTO trade.execution_approvals (
                    action_type, mode, payload_hash, requester_principal_id,
                    data_authorization_ref, policy_version, status, expires_at
                ) VALUES (
                    :action_type, :mode, :payload_hash, :principal_id,
                    NULL, :policy_version, 'requested', NOW() + (:ttl_seconds * INTERVAL '1 second')
                )
                RETURNING approval_id, status, expires_at
                """
            ),
            {
                "action_type": action_type,
                "mode": canonical["mode"],
                "payload_hash": operation_payload_hash(action_type, canonical),
                "principal_id": principal.principal_id,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
                "ttl_seconds": expires_in_seconds,
            },
        )
        row = result.mappings().one()
        await self._append_event(
            db,
            approval_id=str(row["approval_id"]),
            event_type="requested",
            actor_principal_id=principal.principal_id,
            event_payload={
                "action_type": action_type,
                "payload": canonical,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
            },
        )
        return {
            "approval_id": str(row["approval_id"]),
            "status": row["status"],
            "expires_at": row["expires_at"].isoformat(),
            "payload_hash": operation_payload_hash(action_type, canonical),
        }

    async def approve_order(
        self,
        db: AsyncSession,
        *,
        approval_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        _require_human_principal(principal, "审批执行请求")
        result = await db.execute(
            text(
                """
                UPDATE trade.execution_approvals
                SET status = 'approved', approver_principal_id = :principal_id, approved_at = NOW()
                WHERE approval_id = CAST(:approval_id AS uuid)
                  AND status = 'requested'
                  AND expires_at > NOW()
                  AND requester_principal_id <> CAST(:principal_id AS uuid)
                RETURNING approval_id, status, expires_at
                """
            ),
            {"approval_id": approval_id, "principal_id": principal.principal_id},
        )
        row = result.mappings().first()
        if not row:
            raise ExecutionAuthorizationError(
                "APPROVAL_NOT_APPROVABLE", "审批不存在、已过期、已处理或违反职责分离", 409
            )
        await self._append_event(
            db,
            approval_id=str(row["approval_id"]),
            event_type="approved",
            actor_principal_id=principal.principal_id,
            event_payload={},
        )
        return {
            "approval_id": str(row["approval_id"]),
            "status": row["status"],
            "expires_at": row["expires_at"].isoformat(),
        }

    async def create_order_intent(
        self,
        db: AsyncSession,
        *,
        principal: Principal,
        client_intent_key: str,
        payload: dict[str, Any],
    ) -> tuple[str, bool, str]:
        if principal.is_anonymous:
            raise ExecutionAuthorizationError("UNAUTHORIZED", "匿名主体不能创建订单意图", 401)
        canonical = canonical_order_payload(payload)
        digest = order_payload_hash(canonical)
        scope = {
            "principal_id": principal.principal_id,
            "client_intent_key": client_intent_key,
        }
        await db.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                    hashtext(CAST(:principal_id AS text)),
                    hashtext(:client_intent_key)
                )
                """
            ),
            scope,
        )
        existing = await db.execute(
            text(
                """
                SELECT intent_id, payload_hash, status, intent_generation,
                       expires_at > NOW() AS active
                FROM trade.order_intents
                WHERE principal_id = CAST(:principal_id AS uuid)
                  AND client_intent_key = :client_intent_key
                ORDER BY intent_generation DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            scope,
        )
        row = existing.mappings().first()
        if row and row["active"]:
            if row["payload_hash"] != digest:
                raise ExecutionAuthorizationError(
                    "IDEMPOTENCY_KEY_PAYLOAD_CONFLICT", "同一意图键不能绑定不同订单载荷", 409
                )
            return str(row["intent_id"]), True, str(row["status"])

        generation = int(row["intent_generation"]) + 1 if row else 1
        created = await db.execute(
            text(
                """
                INSERT INTO trade.order_intents (
                    principal_id, client_intent_key, intent_generation, payload_hash,
                    mode, status, expires_at
                ) VALUES (
                    CAST(:principal_id AS uuid), :client_intent_key, :intent_generation,
                    :payload_hash, :mode, 'pending', NOW() + INTERVAL '15 minutes'
                )
                RETURNING intent_id, status
                """
            ),
            {
                **scope,
                "intent_generation": generation,
                "payload_hash": digest,
                "mode": canonical["mode"],
            },
        )
        row = created.mappings().first()
        if not row:
            raise ExecutionAuthorizationError(
                "EXECUTION_INTENT_UNAVAILABLE", "订单意图无法持久化", 503
            )
        return str(row["intent_id"]), False, str(row["status"])

    async def mark_intent(self, db: AsyncSession, intent_id: str, status: str) -> None:
        await db.execute(
            text(
                """
                UPDATE trade.order_intents
                SET status = :status
                WHERE intent_id = CAST(:intent_id AS uuid)
                """
            ),
            {"intent_id": intent_id, "status": status},
        )

    async def consume_order_approval(
        self,
        db: AsyncSession,
        *,
        approval_id: str | None,
        principal: Principal,
        payload: dict[str, Any],
        intent_id: str,
    ) -> None:
        if not approval_id:
            raise ExecutionAuthorizationError("HUMAN_APPROVAL_REQUIRED", "缺少服务端执行审批", 403)
        _require_human_principal(principal, "消费执行审批")
        canonical = canonical_order_payload(payload)
        digest = order_payload_hash(canonical)
        approval = await db.execute(
            text(
                """
                SELECT action_type, mode, payload_hash, requester_principal_id,
                       approver_principal_id, data_authorization_ref, policy_version,
                       status, expires_at
                FROM trade.execution_approvals
                WHERE approval_id = CAST(:approval_id AS uuid)
                FOR UPDATE
                """
            ),
            {"approval_id": approval_id},
        )
        row = approval.mappings().first()
        if not row or row["status"] != "approved" or row["expires_at"] <= datetime.now(timezone.utc):
            raise ExecutionAuthorizationError("APPROVAL_INVALID", "执行审批不存在、已失效或不可使用", 403)
        if row["policy_version"] != EXECUTION_AUTHORIZATION_POLICY_VERSION:
            raise ExecutionAuthorizationError("APPROVAL_POLICY_VERSION_MISMATCH", "执行审批策略版本不匹配", 403)
        if (
            row["action_type"] != ORDER_ACTION
            or row["mode"] != canonical["mode"]
            or row["payload_hash"] != digest
            or str(row["requester_principal_id"]) != principal.principal_id
            or row["approver_principal_id"] == row["requester_principal_id"]
        ):
            raise ExecutionAuthorizationError("APPROVAL_BINDING_MISMATCH", "执行审批与当前订单不匹配", 403)
        if not await self._has_execution_data_authorization(
            db, str(row["data_authorization_ref"] or ""), canonical["stock_code"]
        ):
            raise ExecutionAuthorizationError("DATA_AUTHORIZATION_INVALID", "数据授权引用不可验证", 403)
        updated = await db.execute(
            text(
                """
                UPDATE trade.execution_approvals
                SET status = 'consumed', consumed_at = NOW()
                WHERE approval_id = CAST(:approval_id AS uuid)
                  AND status = 'approved' AND expires_at > NOW()
                RETURNING approval_id
                """
            ),
            {"approval_id": approval_id},
        )
        if not updated.mappings().first():
            raise ExecutionAuthorizationError("APPROVAL_ALREADY_CONSUMED", "执行审批已被消费", 409)
        await self._append_event(
            db,
            approval_id=approval_id,
            event_type="consumed",
            actor_principal_id=principal.principal_id,
            event_payload={
                "intent_id": intent_id,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
            },
        )

    async def consume_operation_approval(
        self,
        db: AsyncSession,
        *,
        approval_id: str | None,
        principal: Principal,
        action_type: str,
        payload: dict[str, Any],
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not approval_id:
            raise ExecutionAuthorizationError("HUMAN_APPROVAL_REQUIRED", "缺少服务端运维审批", 403)
        _require_human_principal(principal, "消费运维审批")
        canonical = canonical_operation_payload(action_type, payload)
        digest = operation_payload_hash(action_type, canonical)
        approval = await db.execute(
            text(
                """
                SELECT action_type, mode, payload_hash, requester_principal_id,
                       approver_principal_id, policy_version, status, expires_at
                FROM trade.execution_approvals
                WHERE approval_id = CAST(:approval_id AS uuid)
                FOR UPDATE
                """
            ),
            {"approval_id": approval_id},
        )
        row = approval.mappings().first()
        if not row or row["status"] != "approved" or row["expires_at"] <= datetime.now(timezone.utc):
            raise ExecutionAuthorizationError("APPROVAL_INVALID", "运维审批不存在、已失效或不可使用", 403)
        if row["policy_version"] != EXECUTION_AUTHORIZATION_POLICY_VERSION:
            raise ExecutionAuthorizationError("APPROVAL_POLICY_VERSION_MISMATCH", "运维审批策略版本不匹配", 403)
        if (
            row["action_type"] != action_type
            or row["mode"] != canonical["mode"]
            or row["payload_hash"] != digest
            or str(row["requester_principal_id"]) != principal.principal_id
            or row["approver_principal_id"] == row["requester_principal_id"]
        ):
            raise ExecutionAuthorizationError("APPROVAL_BINDING_MISMATCH", "运维审批与当前动作不匹配", 403)
        updated = await db.execute(
            text(
                """
                UPDATE trade.execution_approvals
                SET status = 'consumed', consumed_at = NOW()
                WHERE approval_id = CAST(:approval_id AS uuid)
                  AND status = 'approved' AND expires_at > NOW()
                RETURNING approval_id
                """
            ),
            {"approval_id": approval_id},
        )
        if not updated.mappings().first():
            raise ExecutionAuthorizationError("APPROVAL_ALREADY_CONSUMED", "运维审批已被消费", 409)
        await self._append_event(
            db,
            approval_id=approval_id,
            event_type="consumed",
            actor_principal_id=principal.principal_id,
            event_payload={
                "action_type": action_type,
                "payload": canonical,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
                **({"job_id": job_id} if job_id else {}),
            },
        )
        return {
            "approval_id": approval_id,
            "approver_principal_id": str(row["approver_principal_id"]),
            "payload": canonical,
        }

    async def verify_consumed_operation_approval(
        self,
        db: AsyncSession,
        *,
        approval_id: str,
        requester_principal_id: str,
        action_type: str,
        payload: dict[str, Any],
        job_id: str,
    ) -> None:
        canonical = canonical_operation_payload(action_type, payload)
        digest = operation_payload_hash(action_type, canonical)
        approval = await db.execute(
            text(
                """
                SELECT action_type, mode, payload_hash, requester_principal_id,
                       approver_principal_id, policy_version, status
                FROM trade.execution_approvals
                WHERE approval_id = CAST(:approval_id AS uuid)
                """
            ),
            {"approval_id": approval_id},
        )
        row = approval.mappings().first()
        if (
            not row
            or row["status"] != "consumed"
            or row["policy_version"] != EXECUTION_AUTHORIZATION_POLICY_VERSION
            or row["action_type"] != action_type
            or row["mode"] != canonical["mode"]
            or row["payload_hash"] != digest
            or str(row["requester_principal_id"]) != requester_principal_id
            or row["approver_principal_id"] == row["requester_principal_id"]
        ):
            raise ExecutionAuthorizationError(
                "APPROVAL_BINDING_MISMATCH", "运维审批与任务不匹配", 403
            )
        binding = await db.execute(
            text(
                """
                SELECT 1
                FROM trade.execution_approval_events
                WHERE approval_id = CAST(:approval_id AS uuid)
                  AND event_type = 'consumed'
                  AND event_payload ->> 'job_id' = :job_id
                LIMIT 1
                """
            ),
            {"approval_id": approval_id, "job_id": job_id},
        )
        if not binding.mappings().first():
            raise ExecutionAuthorizationError(
                "APPROVAL_JOB_BINDING_MISSING", "运维审批未绑定到任务", 403
            )

    async def prepare_broker_outbox(
        self, db: AsyncSession, *, intent_id: str, payload: dict[str, Any]
    ) -> str:
        result = await db.execute(
            text(
                """
                INSERT INTO trade.broker_outbox (intent_id, status, request_payload)
                VALUES (CAST(:intent_id AS uuid), 'pending', CAST(:request_payload AS jsonb))
                RETURNING outbox_id
                """
            ),
            {
                "intent_id": intent_id,
                "request_payload": json.dumps(canonical_order_payload(payload), ensure_ascii=False),
            },
        )
        return str(result.mappings().one()["outbox_id"])

    async def mark_outbox(
        self,
        db: AsyncSession,
        *,
        outbox_id: str,
        status: str,
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        await db.execute(
            text(
                """
                UPDATE trade.broker_outbox
                SET status = :status, response_payload = CAST(:response_payload AS jsonb), updated_at = NOW()
                WHERE outbox_id = CAST(:outbox_id AS uuid)
                """
            ),
            {
                "outbox_id": outbox_id,
                "status": status,
                "response_payload": json.dumps(response_payload or {}, ensure_ascii=False),
            },
        )

    async def _has_execution_data_authorization(
        self, db: AsyncSession, authorization_ref: str, stock_code: str
    ) -> bool:
        if not authorization_ref:
            return False
        try:
            symbol = KlineContract.canonical_symbol(stock_code)[0]
        except ValueError:
            return False
        profile = ResearchDataRequirementProfile.get(EXECUTION_REFERENCE_PROFILE)
        freshness_seconds = max(60, int(settings.DATA_CACHE_TTL_QUOTE) * 3)
        result = await db.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM market.research_readiness_reviews review
                    WHERE review.review_id = :authorization_ref
                      AND review.stock_code = :stock_code
                      AND review.readiness_status = 'ready'
                      AND review.research_use_scope = :research_use_scope
                      AND review.requirement_profile = :requirement_profile
                      AND review.validated_fields @> CAST(:required_fields AS jsonb)
                      AND COALESCE(review.unresolved_fields, '[]'::jsonb) = '[]'::jsonb
                      AND COALESCE(review.rejected_fields, '[]'::jsonb) = '[]'::jsonb
                      AND review.reviewed_at >= NOW()
                          - make_interval(secs => :freshness_seconds)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM market.research_readiness_reviews newer
                          WHERE newer.stock_code = review.stock_code
                            AND newer.research_use_scope = review.research_use_scope
                            AND newer.requirement_profile = review.requirement_profile
                            AND (
                                newer.reviewed_at > review.reviewed_at
                                OR (
                                    newer.reviewed_at = review.reviewed_at
                                    AND newer.review_id > review.review_id
                                )
                            )
                      )
                ) AS valid
                """
            ),
            {
                "authorization_ref": authorization_ref,
                "stock_code": symbol,
                "research_use_scope": EXECUTION_REFERENCE_SCOPE,
                "requirement_profile": profile.name,
                "required_fields": json.dumps(list(profile.required_fields)),
                "freshness_seconds": freshness_seconds,
            },
        )
        return bool(result.mappings().one()["valid"])

    async def _append_event(
        self,
        db: AsyncSession,
        *,
        approval_id: str,
        event_type: str,
        actor_principal_id: str,
        event_payload: dict[str, Any],
    ) -> None:
        await db.execute(
            text(
                """
                INSERT INTO trade.execution_approval_events (
                    approval_id, event_type, actor_principal_id, event_payload
                ) VALUES (
                    CAST(:approval_id AS uuid), :event_type, CAST(:actor_principal_id AS uuid),
                    CAST(:event_payload AS jsonb)
                )
                """
            ),
            {
                "approval_id": approval_id,
                "event_type": event_type,
                "actor_principal_id": actor_principal_id,
                "event_payload": json.dumps(event_payload, ensure_ascii=False),
            },
        )
