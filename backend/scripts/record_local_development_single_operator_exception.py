"""Record the approved local-development single-operator governance exception."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Sequence

from sqlalchemy import text

from app.core.auth import Principal, ROLE_SCOPES
from app.db import get_db
from app.strategy.single_operator_exception import LocalDevelopmentSingleOperatorException


async def record(args: argparse.Namespace) -> dict:
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                SELECT principal_id, display_name, principal_type, role
                FROM auth.principals
                WHERE principal_id = CAST(:principal_id AS uuid)
                  AND is_active IS TRUE
                """
            ),
            {"principal_id": args.actor_principal_id},
        )
        row = result.mappings().first()
        if row is None:
            raise ValueError("单人治理例外主体不存在或未启用")
        principal = Principal(
            principal_id=str(row["principal_id"]),
            display_name=row["display_name"],
            principal_type=row["principal_type"],
            role=row["role"],
            scopes=ROLE_SCOPES[row["role"]],
            source="local_governance_command",
        )
        exception = LocalDevelopmentSingleOperatorException.create(
            principal=principal,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
        return await exception.record_authorization(db, principal=principal)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="登记本地开发单人策略治理例外")
    parser.add_argument("--actor-principal-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(record(args)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
