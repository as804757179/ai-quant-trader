import asyncio
import os
import sys
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from pydantic import ValidationError


os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "l4-async-job-contract-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.api import backtest  # noqa: E402
from app.backtest.jobs import BacktestJobService, BacktestWorkerForbidden  # noqa: E402
from app.backtest.service import BacktestService, BacktestStrategyDisabled  # noqa: E402
from app.core.auth import Principal, ROLE_SCOPES, route_access  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.response import register_exception_handlers  # noqa: E402
from app.jobs.service import AsyncJobStore, canonical_input_hash  # noqa: E402
from app.strategy.catalog import OHLCV_RETURN_FIELDS  # noqa: E402


VALID_PAYLOAD = {
    "strategy_type": "dual_ma",
    "strategy_code": "builtin:dual_ma:v1",
    "stock_codes": ["300308.SZ"],
    "start_date": "2026-06-01",
    "end_date": "2026-06-30",
    "initial_cash": 1_000_000,
    "params": None,
    "name": None,
    "requirement_profile": "OHLCV_RETURN_V1",
    "required_fields": OHLCV_RETURN_FIELDS,
    "auto_backfill": False,
    "allow_synthetic": False,
}

STRATEGY_SNAPSHOT = {
    "strategy_type": "dual_ma",
    "strategy_id": 7,
    "version_id": 11,
    "version": 2,
    "revision": 2,
    "params": {"fast_period": 5, "slow_period": 20, "position_pct": 0.2},
    "config_hash": "a" * 64,
    "catalog_hash": "b" * 64,
}


def principal(*, role: str = "strategy_admin", principal_type: str = "human") -> Principal:
    scopes = ROLE_SCOPES[role]
    return Principal(
        principal_id=str(uuid4()),
        display_name="l4-contract",
        principal_type=principal_type,
        role=role,
        scopes=scopes,
        source="credential",
        credential_id=str(uuid4()),
    )


def send(app: FastAPI, method: str, path: str, **kwargs):
    async def _send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_send())


class _FakeBacktestService:
    validate_submission_input = staticmethod(BacktestService.validate_submission_input)

    async def resolve_enabled_strategy_snapshot(self, *, strategy_type, params):
        if params == {"fast_period": 60}:
            raise BacktestStrategyDisabled(
                "策略参数 fast_period 不能覆盖已审批版本",
                "BACKTEST_STRATEGY_CONFIG_MISMATCH",
            )
        return dict(STRATEGY_SNAPSHOT)

    async def verify_strategy_snapshot(self, strategy_config_snapshot):
        if strategy_config_snapshot != STRATEGY_SNAPSHOT:
            raise BacktestStrategyDisabled("策略快照不可用")
        return dict(STRATEGY_SNAPSHOT)


class _DisabledBacktestService(_FakeBacktestService):
    async def resolve_enabled_strategy_snapshot(self, *, strategy_type, params):
        raise BacktestStrategyDisabled("策略未处于已审批启用状态")


class _FakeStore:
    def __init__(self):
        self.kwargs = None

    async def enqueue(self, **kwargs):
        self.kwargs = kwargs
        return (
            {
                "job_id": str(uuid4()),
                "job_type": kwargs["job_type"],
                "status": kwargs["initial_status"],
                "progress": 0,
                "input_hash": canonical_input_hash(kwargs["input_payload"]),
                "result_ref": None,
                "error_code": kwargs["initial_error_code"],
                "retry": {"count": 0, "max_retries": 2, "next_retry_at": None},
                "created_at": None,
                "started_at": None,
                "finished_at": None,
                "cancel_requested_at": None,
            },
            True,
        )


class _FakeApiJobService:
    async def enqueue(self, **kwargs):
        self.kwargs = kwargs
        return (
            {
                "job_id": "2cfb98c0-5a7a-4c4b-8cf2-4c689dfa14f6",
                "job_type": "backtest.run",
                "status": "queued",
                "progress": 0,
                "input_hash": "a" * 64,
                "result_ref": None,
                "error_code": None,
                "retry": {"count": 0, "max_retries": 2, "next_retry_at": None},
                "created_at": None,
                "started_at": None,
                "finished_at": None,
                "cancel_requested_at": None,
            },
            True,
        )


class _ExecutionStore:
    def __init__(self):
        self.calls = []

    async def claim(self, job_id, worker):
        self.calls.append(("claim", job_id, worker.principal_id))
        return {
            "input_payload": {
                **VALID_PAYLOAD,
                "strategy_config_snapshot": dict(STRATEGY_SNAPSHOT),
            }
        }

    async def get(self, job_id, worker):
        self.calls.append(("get", job_id))
        return {"job_id": job_id, "status": "cancelled"}

    async def mark_blocked(self, job_id, *, error_code):
        self.calls.append(("blocked", job_id, error_code))
        return {"job_id": job_id, "status": "blocked", "error_code": error_code}

    async def update_progress(self, job_id, progress):
        self.calls.append(("progress", job_id, progress))
        return {"job_id": job_id, "progress": progress}

    async def mark_succeeded(self, job_id, *, result_ref):
        self.calls.append(("succeeded", job_id, result_ref))
        return {"job_id": job_id, "status": "succeeded", "result_ref": result_ref}

    async def mark_failure(self, job_id, *, error_code, retryable):
        self.calls.append(("failed", job_id, error_code, retryable))
        return {"job_id": job_id, "status": "failed", "error_code": error_code}


class _RuntimeBacktestService:
    def __init__(self):
        self.called = False
        self.verified = False

    async def verify_strategy_snapshot(self, strategy_config_snapshot):
        if strategy_config_snapshot != STRATEGY_SNAPSHOT:
            raise BacktestStrategyDisabled("策略快照不可用")
        self.verified = True
        return dict(STRATEGY_SNAPSHOT)

    async def create_and_run(self, **payload):
        self.called = True
        return {"task_id": 42, "payload": payload}


class _DisabledRuntimeBacktestService(_RuntimeBacktestService):
    async def verify_strategy_snapshot(self, strategy_config_snapshot):
        raise BacktestStrategyDisabled("策略未处于已审批启用状态")


class _MappingResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value if isinstance(self.value, dict) else None

    def all(self):
        return self.value if isinstance(self.value, list) else []

    def scalar(self):
        return self.value


class _SequenceDb:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        self.params.append(params or {})
        return _MappingResult(self.results.pop(0))


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class _FinishedJobStore:
    async def get(self, _job_id, _principal):
        return {
            "job_id": "2cfb98c0-5a7a-4c4b-8cf2-4c689dfa14f6",
            "status": "succeeded",
            "result_ref": "backtest.tasks:42",
        }


class _ResultReader:
    def __init__(self):
        self.task_id = None

    async def get_result(self, task_id):
        self.task_id = task_id
        return {"task_id": task_id, "metrics": {"total_return": 0.1}}


class _FakeTaskListService:
    def __init__(self):
        self.kwargs = None

    async def list_tasks(self, **kwargs):
        self.kwargs = kwargs
        return {
            "items": [],
            "total": 3,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "has_more": True,
            "source": "backtest.tasks",
            "source_version": "backtest-task-list-v2",
        }


class L4AsyncJobContracts(unittest.TestCase):
    def test_input_hash_is_canonical(self):
        self.assertEqual(
            canonical_input_hash({"b": [2, 1], "a": {"x": 1}}),
            canonical_input_hash({"a": {"x": 1}, "b": [2, 1]}),
        )

    def test_run_endpoint_returns_202_location_and_job_reference(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(backtest.router, prefix="/api/v1/backtest")
        fake = _FakeApiJobService()
        with patch("app.api.backtest.BacktestJobService", return_value=fake), patch(
            "app.api.backtest.get_request_principal", return_value=principal()
        ):
            response = send(
                app,
                "POST",
                "/api/v1/backtest/run",
                headers={"Idempotency-Key": "backtest-job-key-0001"},
                json=VALID_PAYLOAD,
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.headers["location"],
            "/api/v1/backtest/jobs/2cfb98c0-5a7a-4c4b-8cf2-4c689dfa14f6",
        )
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["job"]["job_type"], "backtest.run")
        self.assertFalse(body["data"]["idempotent_replay"])
        self.assertEqual(fake.kwargs["payload"]["strategy_code"], "builtin:dual_ma:v1")

    def test_enqueue_is_blocked_when_release_lock_is_closed(self):
        store = _FakeStore()
        service = BacktestJobService(store=store, backtest_service=_FakeBacktestService())
        with patch.object(settings, "CERTIFIED_BACKTEST_EXECUTION_ENABLED", False):
            job, created = asyncio.run(
                service.enqueue(
                    principal=principal(),
                    idempotency_key="backtest-job-key-0002",
                    payload=dict(VALID_PAYLOAD),
                )
            )
        self.assertTrue(created)
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["error_code"], "CERTIFIED_BACKTEST_EXECUTION_DISABLED")
        self.assertEqual(store.kwargs["initial_status"], "blocked")
        self.assertEqual(
            store.kwargs["input_payload"]["strategy_config_snapshot"], STRATEGY_SNAPSHOT
        )

    def test_disabled_strategy_is_rejected_before_job_creation(self):
        store = _FakeStore()
        service = BacktestJobService(
            store=store,
            backtest_service=_DisabledBacktestService(),
        )
        with self.assertRaises(BacktestStrategyDisabled):
            asyncio.run(
                service.enqueue(
                    principal=principal(),
                    idempotency_key="backtest-job-key-disabled",
                    payload=dict(VALID_PAYLOAD),
                )
            )
        self.assertIsNone(store.kwargs)

    def test_enqueue_rejects_override_of_approved_strategy_params(self):
        store = _FakeStore()
        service = BacktestJobService(store=store, backtest_service=_FakeBacktestService())
        with self.assertRaisesRegex(ValueError, "fast_period"):
            asyncio.run(
                service.enqueue(
                    principal=principal(),
                    idempotency_key="backtest-job-key-invalid-params",
                    payload={**VALID_PAYLOAD, "params": {"fast_period": 60}},
                )
            )
        self.assertIsNone(store.kwargs)

    def test_human_cannot_execute_job(self):
        service = BacktestJobService(store=_FakeStore(), backtest_service=_FakeBacktestService())
        with self.assertRaises(BacktestWorkerForbidden):
            asyncio.run(service.execute(str(uuid4()), principal()))

    def test_worker_execution_rechecks_release_lock_before_backtest(self):
        store = _ExecutionStore()
        runtime = _RuntimeBacktestService()
        worker = principal(role="service_worker", principal_type="service")
        service = BacktestJobService(store=store, backtest_service=runtime)
        with patch.object(settings, "CERTIFIED_BACKTEST_EXECUTION_ENABLED", False):
            result = asyncio.run(service.execute(str(uuid4()), worker))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(runtime.called)
        self.assertEqual(store.calls[-1][0], "blocked")

    def test_worker_execution_uses_persisted_payload_and_result_reference(self):
        store = _ExecutionStore()
        runtime = _RuntimeBacktestService()
        worker = principal(role="service_worker", principal_type="service")
        service = BacktestJobService(store=store, backtest_service=runtime)
        with patch.object(settings, "CERTIFIED_BACKTEST_EXECUTION_ENABLED", True):
            result = asyncio.run(service.execute(str(uuid4()), worker))
        self.assertTrue(runtime.called)
        self.assertTrue(runtime.verified)
        self.assertEqual(result["result_ref"], "backtest.tasks:42")
        self.assertIn(("progress", result["job_id"], 10), store.calls)

    def test_worker_execution_rechecks_strategy_enabled_state(self):
        store = _ExecutionStore()
        worker = principal(role="service_worker", principal_type="service")
        service = BacktestJobService(
            store=store,
            backtest_service=_DisabledRuntimeBacktestService(),
        )
        with patch.object(settings, "CERTIFIED_BACKTEST_EXECUTION_ENABLED", True):
            result = asyncio.run(service.execute(str(uuid4()), worker))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "BACKTEST_STRATEGY_DISABLED")

    def test_cancel_recovery_finishes_the_active_attempt(self):
        job_id = str(uuid4())
        db = _SequenceDb(
            {"job_id": job_id, "status": "cancel_requested"},
            None,
            None,
        )
        worker = principal(role="service_worker", principal_type="service")
        with patch("app.jobs.service.get_db", return_value=_DbContext(db)):
            claimed = asyncio.run(AsyncJobStore().claim(job_id, worker))

        self.assertIsNone(claimed)
        self.assertIn("SET status = 'cancelled'", db.sql[1])
        self.assertIn("UPDATE audit.async_job_attempts", db.sql[2])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT INTO BACKTEST", "DELETE")
            )
        )

    def test_task_status_and_result_are_separate(self):
        created_at = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
        status_row = {
            "id": 42,
            "name": "回测任务",
            "status": "done",
            "progress": 100,
            "error_msg": None,
            "result_available": True,
            "start_date": date(2026, 6, 1),
            "end_date": date(2026, 6, 30),
            "universe": "300308.SZ",
            "initial_cash": 1_000_000,
            "created_at": created_at,
            "finished_at": created_at,
        }
        db = _SequenceDb(status_row)
        with patch("app.backtest.service.get_db", return_value=_DbContext(db)):
            status = asyncio.run(BacktestService().get_status(42))

        self.assertTrue(status["result_available"])
        self.assertNotIn("metrics", status)
        self.assertNotIn("equity_curve", status)
        self.assertNotIn("trades", status)
        self.assertIn("EXISTS", db.sql[0])

        reader = _ResultReader()
        service = BacktestJobService(
            store=_FinishedJobStore(), backtest_service=reader
        )
        result = asyncio.run(service.get_result(str(uuid4()), principal()))
        self.assertEqual(reader.task_id, 42)
        self.assertEqual(result["result"]["task_id"], 42)

    def test_task_list_uses_real_total_and_server_pagination(self):
        created_at = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
        db = _SequenceDb(
            3,
            [
                {
                    "id": 12,
                    "name": "回测任务",
                    "status": "done",
                    "progress": 100,
                    "start_date": date(2026, 6, 1),
                    "end_date": date(2026, 6, 30),
                    "universe": "300308.SZ",
                    "created_at": created_at,
                    "finished_at": created_at,
                    "error_msg": None,
                }
            ],
        )
        with patch("app.backtest.service.get_db", return_value=_DbContext(db)):
            payload = asyncio.run(BacktestService().list_tasks(page=2, page_size=1))

        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 1)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["items"][0]["task_id"], 12)
        self.assertEqual(db.params[1]["offset"], 1)
        self.assertIn("COUNT(*) AS total", db.sql[0])
        self.assertIn("ORDER BY created_at DESC, id DESC", db.sql[1])
        self.assertIn("LIMIT :limit OFFSET :offset", db.sql[1])

    def test_task_list_route_prefers_page_size_and_keeps_limit_compatibility(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(backtest.router, prefix="/api/v1/backtest")
        fake = _FakeTaskListService()
        with patch("app.api.backtest.BacktestService", return_value=fake):
            response = send(
                app,
                "GET",
                "/api/v1/backtest/tasks?limit=5&page=2&page_size=1",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.kwargs, {"page": 2, "page_size": 1})
        self.assertEqual(response.json()["data"]["total"], 3)

    def test_backtest_request_forbids_unknown_top_level_fields(self):
        with self.assertRaises(ValidationError):
            backtest.BacktestRunRequest.model_validate(
                {**VALID_PAYLOAD, "unexpected": True}
            )

    def test_execute_and_cancel_have_distinct_declared_scopes(self):
        self.assertEqual(
            route_access("POST", "/api/v1/backtest/jobs/abc/execute").scope,
            "backtest:execute",
        )
        self.assertEqual(
            route_access("POST", "/api/v1/backtest/jobs/abc/cancel").scope,
            "backtest:run",
        )
        self.assertIn("backtest:execute", ROLE_SCOPES["service_worker"])
        self.assertNotIn("backtest:execute", ROLE_SCOPES["strategy_admin"])

    def test_trusted_submission_rejects_synthetic_or_auto_backfill(self):
        with self.assertRaisesRegex(ValueError, "自动回填"):
            BacktestService.validate_submission_input(
                **{**VALID_PAYLOAD, "auto_backfill": True}
            )
        with self.assertRaisesRegex(ValueError, "Synthetic"):
            BacktestService.validate_submission_input(
                **{**VALID_PAYLOAD, "allow_synthetic": True}
            )
        with self.assertRaisesRegex(ValueError, "strategy_code"):
            BacktestService.validate_submission_input(
                **{**VALID_PAYLOAD, "strategy_code": "unverified:dual_ma"}
            )

    def test_route_does_not_execute_backtest_inline(self):
        source = (REPO_ROOT / "backend" / "app" / "api" / "backtest.py").read_text(
            encoding="utf-8"
        )
        run_section = source[source.index("async def run_backtest") : source.index('@router.get("/jobs/{job_id}")')]
        self.assertIn("svc.enqueue", run_section)
        self.assertNotIn("create_and_run", run_section)
        self.assertIn("status_code=202", source)
        self.assertIn('response.headers["Location"]', run_section)

    def test_migration_persists_required_job_audit_state(self):
        source = (
            REPO_ROOT
            / "backend"
            / "alembic"
            / "versions"
            / "027_async_job_backtest_governance.py"
        ).read_text(encoding="utf-8")
        for fragment in (
            'revision = "027"',
            'down_revision = "026"',
            "audit.async_jobs",
            "input_hash CHAR(64)",
            "result_ref VARCHAR(256)",
            "error_code VARCHAR(96)",
            "retry_count INTEGER",
            "audit.async_job_attempts",
            "UNIQUE (requester_principal_id, idempotency_key)",
            "raise RuntimeError",
        ):
            self.assertIn(fragment, source)

    def test_backtest_execution_forces_trusted_inputs_and_persists_lineage(self):
        source = (REPO_ROOT / "backend" / "app" / "backtest" / "service.py").read_text(
            encoding="utf-8"
        )
        for fragment in (
            "trusted_mode=True",
            "TrustedTradingCalendar().get_days",
            "_load_trusted_security_statuses",
            "_load_pit_corporate_actions",
            "strategy_code=source",
            "financial_data_used=False",
            '"trusted_lineage"',
            "strategy_config_snapshot",
        ):
            self.assertIn(fragment, source)
        self.assertNotIn("StrategyConfigStore", source)


if __name__ == "__main__":
    unittest.main()
