"""Manually provision a hashed API credential without persisting its raw value."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import text

from app.core.auth import ROLE_SCOPES, _digest
from app.core.config import settings
from app.db import get_db


SERVICE_ROLES = frozenset({"service_worker", "auditor", "admin"})
PRINCIPAL_ONLY_HUMAN_ROLES = frozenset({"strategy_admin", "research_reviewer"})


def parse_scopes(raw_scopes: str | None, role: str) -> list[str]:
    allowed = ROLE_SCOPES[role]
    if not raw_scopes:
        return sorted(allowed)
    scopes = sorted({scope.strip() for scope in raw_scopes.split(",") if scope.strip()})
    if not scopes:
        raise ValueError("scopes 不能为空")
    unknown = set(scopes) - allowed
    if unknown:
        raise ValueError(f"scopes 超出角色 {role} 的显式权限：{', '.join(sorted(unknown))}")
    return scopes


def principal_only_request_hash(args: argparse.Namespace) -> str:
    payload = {
        "display_name": args.display_name,
        "role": args.role,
        "principal_type": args.principal_type,
        "metadata": json.loads(args.metadata_json),
        "reason": args.reason,
        "bootstrap_operator": args.bootstrap_operator,
        "owner_confirmed_by_user": args.owner_confirmed_by_user,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_principal_only_args(args: argparse.Namespace) -> None:
    if args.principal_type != "human" or args.role not in PRINCIPAL_ONLY_HUMAN_ROLES:
        allowed_roles = ", ".join(sorted(PRINCIPAL_ONLY_HUMAN_ROLES))
        raise ValueError(f"principal-only 仅允许 human {allowed_roles}")


async def provision_principal_only(args: argparse.Namespace) -> dict:
    if not args.bootstrap_operator or not args.owner_confirmed_by_user:
        raise ValueError("principal-only 需要已确认的 bootstrap_operator 和用户确认标记")
    metadata = json.loads(args.metadata_json)
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须为 JSON 对象")
    metadata["owner_confirmed_by_user"] = True
    request_hash = principal_only_request_hash(args)
    async with get_db() as db:
        existing_audit = await db.execute(text("""
            SELECT entity_id, after_data->>'request_hash' AS request_hash
            FROM audit.operation_logs
            WHERE operation = 'AUTH_PRINCIPAL_BOOTSTRAPPED'
              AND after_data->>'idempotency_key' = :idempotency_key
            ORDER BY id DESC LIMIT 1
        """), {"idempotency_key": args.idempotency_key})
        audit = existing_audit.mappings().first()
        if audit:
            if audit["request_hash"] != request_hash:
                raise ValueError("相同幂等键不能绑定不同创建请求")
            return {"principal_id": audit["entity_id"], "request_hash": request_hash, "idempotent": True}
        duplicate = await db.execute(text("""
            SELECT principal_id FROM auth.principals WHERE display_name = :display_name
            UNION ALL
            SELECT principal_id FROM auth.principals
            WHERE principal_type = 'human' AND role = :role AND is_active IS TRUE
        """), {"display_name": args.display_name, "role": args.role})
        if duplicate.mappings().first():
            raise ValueError(f"同名 principal 或 active human {args.role} 已存在")
        principal_id = str(uuid4())
        await db.execute(text("""
            INSERT INTO auth.principals (principal_id, display_name, principal_type, role, metadata)
            VALUES (CAST(:principal_id AS uuid), :display_name, :principal_type, :role, CAST(:metadata AS jsonb))
        """), {"principal_id": principal_id, "display_name": args.display_name,
                 "principal_type": args.principal_type, "role": args.role,
                 "metadata": json.dumps(metadata, sort_keys=True)})
        await db.execute(text("""
            INSERT INTO audit.operation_logs (operator, operation, entity_type, entity_id, after_data, result)
            VALUES (:operator, 'AUTH_PRINCIPAL_BOOTSTRAPPED', 'auth_principal', :entity_id,
                    CAST(:after_data AS jsonb), 'SUCCESS')
        """), {"operator": args.bootstrap_operator[:50], "entity_id": principal_id,
                 "after_data": json.dumps({"reason": args.reason, "idempotency_key": args.idempotency_key,
                                               "request_hash": request_hash, "metadata": metadata}, sort_keys=True)})
    return {"principal_id": principal_id, "request_hash": request_hash, "idempotent": False}


async def provision(args: argparse.Namespace) -> str:
    settings.validate_api_security_settings()
    if args.role not in ROLE_SCOPES:
        raise ValueError(f"未知角色：{args.role}")
    if args.principal_type == "human" and args.role == "service_worker":
        raise ValueError("service_worker 必须使用 service 主体")
    if args.principal_type == "service" and args.role not in SERVICE_ROLES:
        raise ValueError("service 主体仅允许 service_worker、auditor 或 admin 角色")

    scopes = parse_scopes(args.scopes, args.role)
    raw_token = f"aqp_{secrets.token_urlsafe(32)}"
    credential_id = str(uuid4())
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=args.expires_in_days)
        if args.expires_in_days
        else None
    )

    async with get_db() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO auth.principals (
                    principal_id, display_name, principal_type, role
                ) VALUES (
                    CAST(:principal_id AS uuid), :display_name, :principal_type, :role
                )
                ON CONFLICT (display_name) DO NOTHING
                RETURNING principal_id, principal_type, role
                """
            ),
            {
                "principal_id": str(uuid4()),
                "display_name": args.display_name,
                "principal_type": args.principal_type,
                "role": args.role,
            },
        )
        row = result.mappings().first()
        if row is None:
            existing = await db.execute(
                text(
                    """
                    SELECT principal_id, principal_type, role
                    FROM auth.principals
                    WHERE display_name = :display_name AND is_active IS TRUE
                    """
                ),
                {"display_name": args.display_name},
            )
            row = existing.mappings().first()
        if row is None:
            raise RuntimeError("主体创建或读取失败")
        if row["principal_type"] != args.principal_type or row["role"] != args.role:
            raise ValueError("同名主体的类型或角色不一致，拒绝追加凭据")

        await db.execute(
            text(
                """
                INSERT INTO auth.api_credentials (
                    credential_id, principal_id, token_prefix, token_digest, scopes,
                    expires_at
                ) VALUES (
                    CAST(:credential_id AS uuid), CAST(:principal_id AS uuid),
                    :token_prefix, :token_digest, :scopes, :expires_at
                )
                """
            ),
            {
                "credential_id": credential_id,
                "principal_id": str(row["principal_id"]),
                "token_prefix": raw_token[:16],
                "token_digest": _digest("credential", raw_token),
                "scopes": scopes,
                "expires_at": expires_at,
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO audit.operation_logs (
                    operator, operation, entity_type, entity_id, result
                ) VALUES (
                    :operator, 'AUTH_CREDENTIAL_PROVISIONED', 'auth_credential',
                    :entity_id, 'SUCCESS'
                )
                """
            ),
            {
                "operator": args.operator[:50],
                "entity_id": credential_id,
            },
        )
    return raw_token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建 API 主体及一次性显示的凭据")
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", required=True, choices=sorted(ROLE_SCOPES))
    parser.add_argument("--principal-type", required=True, choices=("human", "service"))
    parser.add_argument("--scopes", help="逗号分隔；默认使用该角色的全部显式 Scope")
    parser.add_argument("--expires-in-days", type=int, default=0)
    parser.add_argument("--operator", default="local_admin")
    parser.add_argument("--principal-only", action="store_true")
    parser.add_argument("--metadata-json", default="{}")
    parser.add_argument("--bootstrap-operator")
    parser.add_argument("--owner-confirmed-by-user", action="store_true")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--reason", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.expires_in_days < 0:
        raise ValueError("expires-in-days 不能为负数")
    if args.principal_only:
        validate_principal_only_args(args)
        if not args.idempotency_key or not 8 <= len(args.idempotency_key) <= 128:
            raise ValueError("principal-only 需要有效 idempotency_key")
        result = asyncio.run(provision_principal_only(args))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    token = asyncio.run(provision(args))
    print("主体凭据已创建。以下 Token 仅显示一次，请立即存入受控密钥管理：")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
