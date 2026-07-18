"""Stable read-only snapshots for persisted risk rules."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


RISK_RULE_SNAPSHOT_VERSION = "risk-rule-snapshot-v1"


def _iso_timestamp(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def load_persisted_risk_rule_snapshot(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT rule_code, rule_name, rule_type, is_hard, threshold,
                   action, is_enabled, description, updated_at, updated_by
            FROM risk.risk_rules
            WHERE is_enabled = TRUE
            ORDER BY rule_code
            """
        )
    )
    items: list[dict[str, Any]] = []
    effective_at: datetime | None = None
    for row in result.mappings().all():
        updated_at = row["updated_at"]
        if isinstance(updated_at, datetime) and (
            effective_at is None or updated_at > effective_at
        ):
            effective_at = updated_at
        items.append(
            {
                "rule_code": row["rule_code"],
                "rule_name": row["rule_name"],
                "rule_type": row["rule_type"],
                "is_hard": bool(row["is_hard"]),
                "threshold": str(row["threshold"]),
                "action": row["action"],
                "is_enabled": bool(row["is_enabled"]),
                "description": row["description"],
                "updated_at": _iso_timestamp(updated_at),
                "updated_by": row["updated_by"],
            }
        )
    items.sort(key=lambda item: item["rule_code"])
    encoded = json.dumps(
        items,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "items": items,
        "enabled_count": len(items),
        "rule_set_hash": hashlib.sha256(encoded).hexdigest(),
        "rule_version": RISK_RULE_SNAPSHOT_VERSION,
        "effective_at": _iso_timestamp(effective_at),
        "source": "risk.risk_rules",
        "source_version": RISK_RULE_SNAPSHOT_VERSION,
    }
