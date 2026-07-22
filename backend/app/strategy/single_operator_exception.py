"""Local-development-only single-operator strategy governance exception."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
if TYPE_CHECKING:
    from app.core.auth import Principal


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _error(message: str, code: str, status_code: int = 400) -> Exception:
    from app.strategy.version_service import StrategyVersionError

    return StrategyVersionError(message, code, status_code)


@dataclass(frozen=True)
class LocalDevelopmentSingleOperatorException:
    actor_principal_id: str
    reason: str
    idempotency_key: str
    request_hash: str

    @classmethod
    def create(
        cls, *, principal: Principal, reason: str, idempotency_key: str
    ) -> "LocalDevelopmentSingleOperatorException":
        if principal.principal_type != "human" or principal.role != "strategy_admin":
            raise _error(
                "单人治理例外仅允许 human strategy_admin",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_ACTOR_INVALID",
                403,
            )
        if not reason.strip() or not 8 <= len(idempotency_key) <= 128:
            raise _error(
                "单人治理例外需要原因和有效幂等键",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_REQUEST_INVALID",
            )
        database_host = urlparse(settings.DATABASE_URL).hostname
        if (
            settings.APP_ENV.strip().lower() != "development"
            or database_host not in _LOOPBACK_HOSTS
        ):
            raise _error(
                "单人治理例外仅允许本地 development 回环数据库",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_NOT_LOCAL",
                403,
            )
        payload = {
            "actor_principal_id": principal.principal_id,
            "environment": "local_development",
            "reason": reason,
            "separation_of_duties": False,
            "single_operator_exception": True,
        }
        request_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            actor_principal_id=principal.principal_id,
            reason=reason,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    def audit_payload(self, **extra: Any) -> dict[str, Any]:
        return {
            "actor_principal_id": self.actor_principal_id,
            "environment": "local_development",
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
            "request_hash": self.request_hash,
            "separation_of_duties": False,
            "single_operator_exception": True,
            **extra,
        }

    async def assert_active_actor(
        self, db: AsyncSession, *, principal: Principal
    ) -> None:
        if principal.principal_id != self.actor_principal_id:
            raise _error(
                "单人治理例外 actor 不一致",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_ACTOR_INVALID",
                403,
            )
        result = await db.execute(
            text(
                """
                SELECT principal_id
                FROM auth.principals
                WHERE principal_id = CAST(:principal_id AS uuid)
                  AND principal_type = 'human'
                  AND role = 'strategy_admin'
                  AND is_active IS TRUE
                FOR UPDATE
                """
            ),
            {"principal_id": principal.principal_id},
        )
        if result.mappings().first() is None:
            raise _error(
                "单人治理例外 actor 不可用",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_ACTOR_INVALID",
                403,
            )

    async def record_authorization(
        self, db: AsyncSession, *, principal: Principal
    ) -> dict[str, Any]:
        await self.assert_active_actor(db, principal=principal)
        row = await self._authorization_row(db)
        if row is not None:
            if row["request_hash"] != self.request_hash:
                raise _error(
                    "相同幂等键不能绑定不同单人治理例外请求",
                    "STRATEGY_SINGLE_OPERATOR_EXCEPTION_IDEMPOTENCY_CONFLICT",
                    409,
                )
            return {"idempotent": True, **self.audit_payload()}
        payload = self.audit_payload(
            scope="strategy_version_submission_and_approval_only",
        )
        await db.execute(
            text(
                """
                INSERT INTO audit.operation_logs
                    (operator, operation, entity_type, entity_id, after_data, result)
                VALUES
                    (:operator, 'STRATEGY_SINGLE_OPERATOR_EXCEPTION_AUTHORIZED',
                     'strategy_governance_exception', :entity_id,
                     CAST(:after_data AS jsonb), 'SUCCESS')
                """
            ),
            {
                "operator": principal.display_name[:50],
                "entity_id": self.actor_principal_id,
                "after_data": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        )
        return {"idempotent": False, **payload}

    async def assert_authorized(self, db: AsyncSession) -> None:
        row = await self._authorization_row(db)
        if row is None:
            raise _error(
                "单人治理例外尚未登记审计授权",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_NOT_AUTHORIZED",
                403,
            )
        if row["request_hash"] != self.request_hash:
            raise _error(
                "单人治理例外审计请求不一致",
                "STRATEGY_SINGLE_OPERATOR_EXCEPTION_IDEMPOTENCY_CONFLICT",
                409,
            )

    async def _authorization_row(self, db: AsyncSession) -> Any:
        existing = await db.execute(
            text(
                """
                SELECT after_data->>'request_hash' AS request_hash
                FROM audit.operation_logs
                WHERE operation = 'STRATEGY_SINGLE_OPERATOR_EXCEPTION_AUTHORIZED'
                  AND after_data->>'idempotency_key' = :idempotency_key
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"idempotency_key": self.idempotency_key},
        )
        return existing.mappings().first()

    async def record_approval_use(
        self,
        db: AsyncSession,
        *,
        principal: Principal,
        strategy_id: int,
        version_id: int,
    ) -> None:
        payload = self.audit_payload(
            strategy_id=strategy_id,
            version_id=version_id,
        )
        await db.execute(
            text(
                """
                INSERT INTO audit.operation_logs
                    (operator, operation, entity_type, entity_id, after_data, result)
                VALUES
                    (:operator, 'STRATEGY_SINGLE_OPERATOR_APPROVAL_EXCEPTION_USED',
                     'strategy_version', :entity_id,
                     CAST(:after_data AS jsonb), 'SUCCESS')
                """
            ),
            {
                "operator": principal.display_name[:50],
                "entity_id": str(version_id),
                "after_data": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        )
