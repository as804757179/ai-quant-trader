import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l2-execution-snapshot-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["WS_REDIS_ENABLED"] = "false"

from app.api import trade as trade_api  # noqa: E402
from app.core.auth import Principal  # noqa: E402
from app.trade.execution_authorization import (  # noqa: E402
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    EXECUTION_REFERENCE_PROFILE,
    EXECUTION_REFERENCE_SCOPE,
)


def run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows if isinstance(self.rows, list) else []

    def one(self):
        if not isinstance(self.rows, dict):
            raise AssertionError("expected one mapping row")
        return self.rows


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    async def execute(self, statement, _params=None):
        statement_text = str(statement)
        self.sql.append(statement_text)
        if "SET TRANSACTION" in statement_text:
            return _Result([])
        return _Result(self.results.pop(0))


@asynccontextmanager
async def _db_context(db):
    yield db


class ExecutionSnapshotTests(unittest.TestCase):
    def test_execution_status_is_read_only_repeatable_and_caller_scoped(self):
        snapshot_at = datetime(2026, 7, 17, 10, 15, tzinfo=UTC)
        order_summary = {
            "total": 7,
            "failed": 1,
            "cancelled": 1,
            "open": 2,
            "unknown_caller": 0,
            "ai_source": 0,
            "scheduled_source": 0,
            "unapproved": 0,
            "latest_order_at": snapshot_at,
        }
        approval_summary = {
            "total": 5,
            "requested": 1,
            "approved": 1,
            "consumed": 2,
            "expired": 1,
            "rejected": 0,
            "expired_unconsumed": 1,
            "policy_version_mismatch": 1,
            "latest_approval_at": snapshot_at,
        }
        data_authorization_summary = {
            "latest_review_count": 4,
            "ready_fresh_count": 1,
            "stale_ready_count": 1,
            "review_required_count": 1,
            "rejected_count": 1,
            "invalid_field_count": 2,
            "latest_reviewed_at": snapshot_at,
        }
        risk_rule = {
            "rule_code": "MAX_POSITION",
            "rule_name": "Max position",
            "rule_type": "position",
            "is_hard": True,
            "threshold": Decimal("0.1"),
            "action": "block",
            "is_enabled": True,
            "description": "test rule",
            "updated_at": snapshot_at,
            "updated_by": "risk-admin",
        }
        principal = Principal(
            principal_id="current-caller-only",
            display_name="Current Caller",
            principal_type="service",
            role="risk_admin",
            scopes=frozenset({"trade:read", "risk:read"}),
            source="test",
        )
        db = _Db(
            {"snapshot_at": snapshot_at},
            order_summary,
            [{"reason": "风险拒绝", "count": 1}],
            approval_summary,
            data_authorization_summary,
            [risk_rule],
        )

        with patch.object(trade_api, "get_db", lambda: _db_context(db)), patch.object(
            trade_api, "get_request_principal", return_value=principal
        ):
            response = run(trade_api.execution_status(object(), days=30))

        payload = response.data
        self.assertEqual(payload["snapshot_version"], "execution-safety-snapshot-v1")
        self.assertEqual(payload["snapshot_at"], snapshot_at.isoformat())
        self.assertEqual(payload["source_version"], "execution-safety-v4")
        self.assertEqual(
            payload["identity"],
            {
                "authenticated": True,
                "principal_type": "service",
                "role": "risk_admin",
                "scopes": ["risk:read", "trade:read"],
            },
        )
        self.assertEqual(
            payload["approval_policy"]["policy_version"],
            EXECUTION_AUTHORIZATION_POLICY_VERSION,
        )
        self.assertTrue(payload["approval_policy"]["independent_approver_required"])
        self.assertEqual(payload["approval_audit"]["policy_version_mismatch"], 1)
        self.assertEqual(
            payload["data_authorization_policy"]["profile"],
            EXECUTION_REFERENCE_PROFILE,
        )
        self.assertEqual(
            payload["data_authorization_policy"]["scope"],
            EXECUTION_REFERENCE_SCOPE,
        )
        self.assertEqual(payload["data_authorization_audit"]["ready_fresh_count"], 1)
        self.assertEqual(payload["risk_rules"]["enabled_count"], 1)
        self.assertEqual(
            db.sql[0].strip(),
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        )
        self.assertNotIn("broker", " ".join(db.sql).lower())
        self.assertFalse(
            any(
                f" {statement.upper()} ".find(f" {verb} ") >= 0
                for statement in db.sql
                for verb in ("INSERT", "UPDATE", "DELETE", "CALL")
            )
        )


if __name__ == "__main__":
    unittest.main()
