"""Versioned canonical row hashes for certified K-line lineage."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

HASH_POLICY_VERSION = "certified-kline-row-v1"
HASH_FIELDS = ("stock_code", "period", "trading_date", "adjustment", "open", "high", "low", "close", "volume", "amount", "provider", "source", "batch_id", "raw_hash")


def _value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return value


def certified_kline_row_hash(row: dict[str, Any]) -> str:
    payload = {field: _value(row.get(field)) for field in HASH_FIELDS}
    payload["hash_policy_version"] = HASH_POLICY_VERSION
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
