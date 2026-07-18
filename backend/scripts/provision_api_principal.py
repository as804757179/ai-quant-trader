"""Manually provision a hashed API credential without persisting its raw value."""

from __future__ import annotations

import argparse
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import text

from app.core.auth import ROLE_SCOPES, _digest
from app.core.config import settings
from app.db import get_db


SERVICE_ROLES = frozenset({"service_worker", "auditor", "admin"})


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.expires_in_days < 0:
        raise ValueError("expires-in-days 不能为负数")
    token = asyncio.run(provision(args))
    print("主体凭据已创建。以下 Token 仅显示一次，请立即存入受控密钥管理：")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
