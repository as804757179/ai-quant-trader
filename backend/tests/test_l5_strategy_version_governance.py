import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError


os.environ.setdefault("SECRET_KEY", "l5-strategy-version-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.api.strategy import StrategyCreateRequest, StrategyUpdateRequest
from app.backtest.service import BacktestService, BacktestStrategyDisabled
from app.core.auth import Principal, ROLE_SCOPES, route_access
from app.core.config import settings
from app.strategy.single_operator_exception import LocalDevelopmentSingleOperatorException
from app.strategy.version_service import StrategyVersionError, StrategyVersionService


def run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, rows=None, *, rowcount=None):
        self.rows = [] if rows is None else rows
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        if isinstance(self.rows, list):
            return self.rows[0] if self.rows else None
        return self.rows

    def all(self):
        if isinstance(self.rows, list):
            return self.rows
        return [] if self.rows is None else [self.rows]


class _MemoryStrategyDb:
    def __init__(self):
        self.next_strategy_id = 1
        self.next_version_id = 1
        self.subjects: dict[int, dict] = {}
        self.subject_by_type: dict[str, int] = {}
        self.heads: dict[int, dict] = {}
        self.versions: dict[int, dict] = {}
        self.approvals: dict[int, dict] = {}
        self.events: list[dict] = []
        self.audit_logs: list[dict] = []

    def _version_for(self, strategy_id, version_number):
        for version in self.versions.values():
            if (
                version["strategy_id"] == strategy_id
                and version["version_number"] == version_number
            ):
                return version
        return None

    def _state_rows(self):
        rows = []
        for strategy_id, head in self.heads.items():
            subject = self.subjects[strategy_id]
            active = self.versions.get(head["active_version_id"])
            latest = self._version_for(strategy_id, head["revision"])
            active_approval = self.approvals.get(active["version_id"]) if active else None
            latest_approval = self.approvals.get(latest["version_id"]) if latest else None
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_type": subject["strategy_type"],
                    "revision": head["revision"],
                    "active_version_id": head["active_version_id"],
                    "effective_version_id": active["version_id"] if active else None,
                    "effective_version": active["version_number"] if active else None,
                    "effective_enabled": active["enabled"] if active else None,
                    "effective_params": active["params"] if active else None,
                    "effective_catalog_hash": active["catalog_hash"] if active else None,
                    "effective_config_hash": active["config_hash"] if active else None,
                    "effective_approval_status": active_approval["status"] if active_approval else None,
                    "latest_version_id": latest["version_id"] if latest else None,
                    "latest_version": latest["version_number"] if latest else None,
                    "latest_enabled": latest["enabled"] if latest else None,
                    "latest_params": latest["params"] if latest else None,
                    "latest_catalog_hash": latest["catalog_hash"] if latest else None,
                    "latest_config_hash": latest["config_hash"] if latest else None,
                    "latest_approval_status": latest_approval["status"] if latest_approval else None,
                }
            )
        return sorted(rows, key=lambda row: (row["strategy_type"], -row["revision"]))

    async def execute(self, statement, params=None):
        sql = str(statement)
        values = dict(params or {})
        if "pg_advisory_xact_lock" in sql:
            return _Result()
        if "FROM auth.principals" in sql:
            return _Result({"principal_id": values["principal_id"]})
        if "FROM audit.operation_logs" in sql:
            matched = [
                log for log in self.audit_logs
                if log["operation"] == "STRATEGY_SINGLE_OPERATOR_EXCEPTION_AUTHORIZED"
                and log["after_data"]["idempotency_key"] == values["idempotency_key"]
            ]
            return _Result([] if not matched else [{"request_hash": matched[-1]["after_data"]["request_hash"]}])
        if "INSERT INTO audit.operation_logs" in sql:
            self.audit_logs.append(
                {
                    "operation": (
                        "STRATEGY_SINGLE_OPERATOR_EXCEPTION_AUTHORIZED"
                        if "AUTHORIZED" in sql
                        else "STRATEGY_SINGLE_OPERATOR_APPROVAL_EXCEPTION_USED"
                    ),
                    "after_data": json.loads(values["after_data"]),
                }
            )
            return _Result(rowcount=1)
        if "FROM strategy.strategy_version_heads AS h" in sql:
            return _Result(self._state_rows())
        if "FROM strategy.strategies" in sql and "WHERE strategy_type = :strategy_type" in sql:
            strategy_id = self.subject_by_type.get(values["strategy_type"])
            return _Result([] if strategy_id is None else [{"id": strategy_id}])
        if "INSERT INTO strategy.strategies" in sql:
            strategy_id = self.next_strategy_id
            self.next_strategy_id += 1
            self.subjects[strategy_id] = {
                "id": strategy_id,
                "strategy_type": values["strategy_type"],
                "name": values["name"],
            }
            self.subject_by_type[values["strategy_type"]] = strategy_id
            return _Result({"id": strategy_id})
        if "FROM strategy.strategy_version_heads" in sql and "FOR UPDATE" in sql:
            head = self.heads.get(values["strategy_id"])
            return _Result([] if head is None else [dict(head)])
        if "INSERT INTO strategy.strategy_version_heads" in sql:
            self.heads[values["strategy_id"]] = {
                "strategy_id": values["strategy_id"],
                "revision": 0,
                "active_version_id": None,
            }
            return _Result(rowcount=1)
        if "WHERE strategy_id = :strategy_id AND version_id = :version_id" in sql:
            version = self.versions.get(values["version_id"])
            if version is None or version["strategy_id"] != values["strategy_id"]:
                return _Result([])
            return _Result([dict(version)])
        if "INSERT INTO strategy.strategy_versions" in sql:
            version_id = self.next_version_id
            self.next_version_id += 1
            self.versions[version_id] = {
                "version_id": version_id,
                "strategy_id": values["strategy_id"],
                "version_number": values["version_number"],
                "enabled": values["enabled"],
                "params": json.loads(values["params"]),
                "catalog_hash": values["catalog_hash"],
                "config_hash": values["config_hash"],
                "requester_principal_id": values["principal_id"],
            }
            return _Result({"version_id": version_id}, rowcount=1)
        if "INSERT INTO strategy.strategy_version_approvals" in sql:
            self.approvals[values["version_id"]] = {"status": "pending"}
            return _Result(rowcount=1)
        if "INSERT INTO strategy.strategy_version_events" in sql:
            self.events.append(
                {
                    "version_id": values["version_id"],
                    "event_type": values["event_type"],
                    "actor_principal_id": values["actor_principal_id"],
                    "payload": json.loads(values["payload"]),
                }
            )
            return _Result(rowcount=1)
        if "UPDATE strategy.strategy_version_heads" in sql and "SET revision" in sql:
            head = self.heads[values["strategy_id"]]
            if head["revision"] != values["expected_revision"]:
                return _Result(rowcount=0)
            head["revision"] = values["revision"]
            head["active_version_id"] = None
            return _Result(rowcount=1)
        if "WHERE v.version_id = :version_id" in sql:
            version = self.versions.get(values["version_id"])
            if version is None:
                return _Result([])
            head = self.heads[version["strategy_id"]]
            subject = self.subjects[version["strategy_id"]]
            return _Result(
                {
                    "strategy_id": version["strategy_id"],
                    "strategy_type": subject["strategy_type"],
                    "revision": head["revision"],
                    "active_version_id": head["active_version_id"],
                    **version,
                    "approval_status": self.approvals[version["version_id"]]["status"],
                }
            )
        if "UPDATE strategy.strategy_version_approvals" in sql:
            approval = self.approvals[values["version_id"]]
            if approval["status"] != "pending":
                return _Result(rowcount=0)
            approval["status"] = "approved"
            approval["approver_principal_id"] = values["principal_id"]
            return _Result(rowcount=1)
        if "UPDATE strategy.strategy_version_heads" in sql and "SET active_version_id" in sql:
            head = self.heads[values["strategy_id"]]
            if head["revision"] != values["revision"] or head["active_version_id"] is not None:
                return _Result(rowcount=0)
            head["active_version_id"] = values["version_id"]
            return _Result(rowcount=1)
        raise AssertionError(f"未处理的 SQL: {sql}")


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


def principal(role, *, principal_id=None, principal_type="human"):
    return Principal(
        principal_id=principal_id or str(uuid4()),
        display_name=f"strategy-{role}",
        principal_type=principal_type,
        role=role,
        scopes=ROLE_SCOPES[role],
        source="credential",
        credential_id=str(uuid4()),
    )


class StrategyVersionGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.db = _MemoryStrategyDb()
        self.service = StrategyVersionService()
        self.submitter = principal("strategy_admin")
        self.approver = principal("risk_admin")

    def test_submission_requires_revision_and_disables_until_approved(self):
        submitted = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=0,
                enabled=True,
                params={"fast_period": 8},
            )
        )

        self.assertEqual(submitted["config_status"], "pending_approval")
        self.assertFalse(submitted["enabled"])
        self.assertEqual(self.db.heads[1]["revision"], 1)
        self.assertIsNone(self.db.heads[1]["active_version_id"])
        with self.assertRaises(StrategyVersionError) as blocked:
            run(self.service.resolve_enabled_snapshot(self.db, strategy_type="dual_ma"))
        self.assertEqual(blocked.exception.code, "STRATEGY_NOT_APPROVED_ENABLED")
        with self.assertRaises(StrategyVersionError) as conflict:
            run(
                self.service.submit(
                    self.db,
                    principal=self.submitter,
                    strategy_type="dual_ma",
                    expected_revision=0,
                    enabled=True,
                    params={},
                )
            )
        self.assertEqual(conflict.exception.code, "STRATEGY_REVISION_CONFLICT")

    def test_approval_is_independent_and_only_current_version_can_activate(self):
        first = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=0,
                enabled=True,
                params={},
            )
        )
        same_person_risk_admin = principal(
            "risk_admin", principal_id=self.submitter.principal_id
        )
        with self.assertRaises(StrategyVersionError) as same_person:
            run(
                self.service.approve(
                    self.db,
                    principal=same_person_risk_admin,
                    version_id=first["version_id"],
                )
            )
        self.assertEqual(same_person.exception.code, "STRATEGY_APPROVAL_SEPARATION")

        approved = run(
            self.service.approve(
                self.db,
                principal=self.approver,
                version_id=first["version_id"],
            )
        )
        self.assertTrue(approved["enabled"])
        self.assertEqual(self.db.heads[1]["active_version_id"], first["version_id"])

        second = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=1,
                enabled=None,
                params={"fast_period": 8},
            )
        )
        self.assertIsNone(self.db.heads[1]["active_version_id"])
        third = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=2,
                enabled=True,
                params={"fast_period": 9},
            )
        )
        with self.assertRaises(StrategyVersionError) as stale:
            run(
                self.service.approve(
                    self.db,
                    principal=self.approver,
                    version_id=second["version_id"],
                )
            )
        self.assertEqual(stale.exception.code, "STRATEGY_VERSION_STALE")
        run(
            self.service.approve(
                self.db,
                principal=self.approver,
                version_id=third["version_id"],
            )
        )
        snapshot = run(
            self.service.resolve_enabled_snapshot(self.db, strategy_type="dual_ma")
        )
        self.assertEqual(snapshot["version_id"], third["version_id"])
        self.assertEqual(snapshot["params"]["fast_period"], 9)
        self.assertEqual([event["event_type"] for event in self.db.events], [
            "submitted",
            "approved",
            "submitted",
            "submitted",
            "approved",
        ])

    def test_local_development_single_operator_exception_is_audited_and_scoped(self):
        submitted = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=0,
                enabled=True,
                params={},
            )
        )
        with patch.object(settings, "APP_ENV", "development"), patch.object(
            settings,
            "DATABASE_URL",
            "postgresql+asyncpg://test:test@127.0.0.1/test",
        ):
            exception = LocalDevelopmentSingleOperatorException.create(
                principal=self.submitter,
                reason="local development single-owner governance",
                idempotency_key="local-single-operator-0001",
            )
            authorization = run(
                exception.record_authorization(self.db, principal=self.submitter)
            )
            self.assertFalse(authorization["idempotent"])
            self.assertTrue(authorization["single_operator_exception"])
            self.assertFalse(authorization["separation_of_duties"])
            self.assertEqual(authorization["environment"], "local_development")
            self.assertTrue(
                run(exception.record_authorization(self.db, principal=self.submitter))["idempotent"]
            )
            run(exception.assert_authorized(self.db))
            approved = run(
                self.service.approve(
                    self.db,
                    principal=self.submitter,
                    version_id=submitted["version_id"],
                    single_operator_exception=exception,
                )
            )
        self.assertEqual(approved["version_id"], submitted["version_id"])
        self.assertEqual(self.db.heads[1]["active_version_id"], submitted["version_id"])
        self.assertEqual(len(self.db.audit_logs), 2)
        self.assertFalse(self.db.audit_logs[-1]["after_data"]["separation_of_duties"])
        self.assertNotIn("INSERT INTO auth.principals", "\n".join(str(item) for item in self.db.audit_logs))

    def test_single_operator_exception_rejects_nonlocal_environment(self):
        for app_env, database_url in (
            ("production", "postgresql+asyncpg://test:test@127.0.0.1/test"),
            ("development", "postgresql+asyncpg://test:test@shared-db/test"),
        ):
            with patch.object(settings, "APP_ENV", app_env), patch.object(
                settings, "DATABASE_URL", database_url
            ):
                with self.assertRaises(StrategyVersionError) as rejected:
                    LocalDevelopmentSingleOperatorException.create(
                        principal=self.submitter,
                        reason="local development single-owner governance",
                        idempotency_key="local-single-operator-0002",
                    )
            self.assertEqual(
                rejected.exception.code, "STRATEGY_SINGLE_OPERATOR_EXCEPTION_NOT_LOCAL"
            )

    def test_tampered_version_hash_fails_closed_before_approval(self):
        submitted = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=0,
                enabled=True,
                params={},
            )
        )
        self.db.versions[submitted["version_id"]]["config_hash"] = "0" * 64

        with self.assertRaises(StrategyVersionError) as rejected:
            run(
                self.service.approve(
                    self.db,
                    principal=self.approver,
                    version_id=submitted["version_id"],
                )
            )

        self.assertEqual(rejected.exception.code, "STRATEGY_VERSION_HASH_MISMATCH")
        self.assertIsNone(self.db.heads[1]["active_version_id"])

    def test_backtest_uses_and_rechecks_the_approved_snapshot(self):
        submitted = run(
            self.service.submit(
                self.db,
                principal=self.submitter,
                strategy_type="dual_ma",
                expected_revision=0,
                enabled=True,
                params={},
            )
        )
        run(
            self.service.approve(
                self.db,
                principal=self.approver,
                version_id=submitted["version_id"],
            )
        )
        backtest = BacktestService()
        with patch(
            "app.backtest.service.get_db",
            side_effect=lambda: _DbContext(self.db),
        ):
            snapshot = run(
                backtest.resolve_enabled_strategy_snapshot(
                    strategy_type="dual_ma", params={"fast_period": 5}
                )
            )
            self.assertEqual(snapshot["version_id"], submitted["version_id"])
            with self.assertRaises(BacktestStrategyDisabled) as override:
                run(
                    backtest.resolve_enabled_strategy_snapshot(
                        strategy_type="dual_ma", params={"fast_period": 8}
                    )
                )
            self.assertEqual(override.exception.code, "BACKTEST_STRATEGY_CONFIG_MISMATCH")
            run(
                self.service.submit(
                    self.db,
                    principal=self.submitter,
                    strategy_type="dual_ma",
                    expected_revision=1,
                    enabled=True,
                    params={"fast_period": 8},
                )
            )
            with self.assertRaises(BacktestStrategyDisabled) as stale:
                run(backtest.verify_strategy_snapshot(snapshot))
        self.assertEqual(stale.exception.code, "BACKTEST_STRATEGY_DISABLED")

    def test_models_and_route_scope_require_governed_submission(self):
        with self.assertRaises(ValidationError):
            StrategyCreateRequest.model_validate({"type": "dual_ma", "enabled": True})
        with self.assertRaises(ValidationError):
            StrategyUpdateRequest.model_validate({"enabled": True})
        self.assertEqual(
            route_access("POST", "/api/v1/strategy/versions/7/approve").scope,
            "strategy:approve",
        )
        self.assertIn("strategy:approve", ROLE_SCOPES["risk_admin"])
        self.assertNotIn("strategy:approve", ROLE_SCOPES["strategy_admin"])

    def test_runtime_paths_no_longer_use_local_json_configuration(self):
        api_source = (
            REPO_ROOT / "backend" / "app" / "api" / "strategy.py"
        ).read_text(encoding="utf-8")
        migration_source = (
            REPO_ROOT
            / "backend"
            / "alembic"
            / "versions"
            / "028_strategy_version_governance.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("StrategyConfigStore", api_source)
        for fragment in (
            "strategy.strategy_versions",
            "strategy.strategy_version_heads",
            "strategy.strategy_version_approvals",
            "strategy.strategy_version_events",
            "strategy_versions_append_only",
            "raise RuntimeError",
        ):
            self.assertIn(fragment, migration_source)


if __name__ == "__main__":
    unittest.main()
