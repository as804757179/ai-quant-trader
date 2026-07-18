import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l2-risk-rule-snapshot-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["WS_REDIS_ENABLED"] = "false"

from app.api import risk as risk_api  # noqa: E402
from app.api import trade as trade_api  # noqa: E402
from app.core.auth import Principal  # noqa: E402
from app.risk.rule_snapshot import (  # noqa: E402
    RISK_RULE_SNAPSHOT_VERSION,
    load_persisted_risk_rule_snapshot,
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
        self.sql.append(str(statement))
        if "SET TRANSACTION" in str(statement):
            return _Result([])
        return _Result(self.results.pop(0))


@asynccontextmanager
async def _db_context(db):
    yield db


def _rule(code, updated_at):
    return {
        "rule_code": code,
        "rule_name": f"{code}-name",
        "rule_type": "position",
        "is_hard": True,
        "threshold": Decimal("0.1"),
        "action": "block",
        "is_enabled": True,
        "description": "test rule",
        "updated_at": updated_at,
        "updated_by": "risk-admin",
    }


class RiskRuleSnapshotTests(unittest.TestCase):
    def test_snapshot_is_stably_sorted_versioned_and_time_bounded(self):
        early = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
        latest = datetime(2026, 7, 17, 9, 30, tzinfo=UTC)
        first = run(
            load_persisted_risk_rule_snapshot(
                _Db([_rule("Z_RULE", early), _rule("A_RULE", latest)])
            )
        )
        second = run(
            load_persisted_risk_rule_snapshot(
                _Db([_rule("A_RULE", latest), _rule("Z_RULE", early)])
            )
        )

        self.assertEqual([item["rule_code"] for item in first["items"]], ["A_RULE", "Z_RULE"])
        self.assertEqual(first["rule_set_hash"], second["rule_set_hash"])
        self.assertEqual(first["rule_version"], RISK_RULE_SNAPSHOT_VERSION)
        self.assertEqual(first["source"], "risk.risk_rules")
        self.assertEqual(first["effective_at"], latest.isoformat())
        self.assertEqual(first["items"][0]["threshold"], "0.1")

    def test_risk_rules_endpoint_returns_the_persisted_snapshot(self):
        updated_at = datetime(2026, 7, 17, 9, 30, tzinfo=UTC)
        db = _Db([_rule("A_RULE", updated_at)])
        with patch.object(risk_api, "get_db", lambda: _db_context(db)):
            response = run(risk_api.list_risk_rules())

        self.assertEqual(response.data["enabled_count"], 1)
        self.assertEqual(response.data["effective_at"], updated_at.isoformat())
        self.assertEqual(response.data["source_version"], RISK_RULE_SNAPSHOT_VERSION)

    def test_execution_snapshot_reuses_the_same_rule_metadata(self):
        updated_at = datetime(2026, 7, 17, 9, 30, tzinfo=UTC)
        order_summary = {
            "total": 0,
            "failed": 0,
            "cancelled": 0,
            "open": 0,
            "unknown_caller": 0,
            "ai_source": 0,
            "scheduled_source": 0,
            "unapproved": 0,
            "latest_order_at": None,
        }
        approval_summary = {
            "total": 0,
            "requested": 0,
            "approved": 0,
            "consumed": 0,
            "expired": 0,
            "rejected": 0,
            "expired_unconsumed": 0,
            "policy_version_mismatch": 0,
            "latest_approval_at": None,
        }
        data_authorization_summary = {
            "latest_review_count": 0,
            "ready_fresh_count": 0,
            "stale_ready_count": 0,
            "review_required_count": 0,
            "rejected_count": 0,
            "invalid_field_count": 0,
            "latest_reviewed_at": None,
        }
        principal = Principal(
            principal_id="risk-rule-reader",
            display_name="Risk Rule Reader",
            principal_type="service",
            role="risk_admin",
            scopes=frozenset({"trade:read"}),
            source="test",
        )
        db = _Db(
            {"snapshot_at": updated_at},
            order_summary,
            [],
            approval_summary,
            data_authorization_summary,
            [_rule("A_RULE", updated_at)],
        )
        with patch.object(trade_api, "get_db", lambda: _db_context(db)), patch.object(
            trade_api, "get_request_principal", return_value=principal
        ):
            response = run(trade_api.execution_status(object(), days=30))

        rules = response.data["risk_rules"]
        self.assertEqual(rules["enabled_count"], 1)
        self.assertEqual(rules["effective_at"], updated_at.isoformat())
        self.assertEqual(rules["rule_version"], RISK_RULE_SNAPSHOT_VERSION)
        self.assertEqual(response.data["source_version"], "execution-safety-v4")


if __name__ == "__main__":
    unittest.main()
